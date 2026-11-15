"""ALIG-SEC-001: yonetim ve rapor erisim guvenligi denetimi. Negatif testler: erisimin OLMAMASI gereken her yol sinanir.

Kapsam: rapor belirteci firmalar arasi ve yasam suresi (tarama/server.py), yonetim uclarinin oturumsuz erisime kapaliligi
ve CSV disa aktarma (yonetim/server.py), rapor HTML kacisi (tarama/rapor.py; musteri, portal ve yonetim gorunumu),
TOTP tekrar kullanimi ve oturum kodunun ozetle saklanmasi (yonetim/guvenlik.py, yonetim/depo.py), TOTP kurtarma
(yonetim/kullanici.py) ve bulgularin belgelerde kayitli olmasi."""
import contextlib
import hashlib
import html
import inspect
import io
import re
import os
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import depo, portal_depo, rapor, yukleme  # noqa: E402
from tarama import server as tserver  # noqa: E402
from yonetim import depo as ydepo  # noqa: E402
from yonetim import guvenlik, kullanici, server  # noqa: E402
import test_portal  # noqa: E402
import test_tarama  # noqa: E402
import test_yonetim  # noqa: E402

PAROLA = test_yonetim.PAROLA
GECMIS = "2000-01-01T00:00:00Z"
ZQ = 'ZQ"><svg onload=alert(1)>\'</code><script>alert(2)</script>&amp;ZQ'   # tirnak, etiket ve varlik kacislari bir arada (65 karakter)


def belirtec(yol):
    return yol.split("/")[2]


def zehirli_belge():
    """Her metin kolonunda ZQ bulunan, tum PostgreSQL denetimlerini iceren belge (yukleme denetimini atlayan kayit gibi)."""
    b = test_tarama.temiz_belge()
    for cid, kolonlar in yukleme.TURLER.items():
        satir = {k: (ZQ if t == "metin" else True if t == "mantik" else 0.5 if t == "sayi" else 1) for k, t in kolonlar.items()}
        b["kontroller"][cid] = {"durum": "ok", "satirlar": [satir]}
    b["kontroller"]["pg_kapsam"]["satirlar"][0]["veritabani_sayisi"] = 3
    b["kontroller"]["pg_kapsam"]["atlanan"] = [{"veritabani": ZQ, "neden": "yetki"}]
    return b


def kacis_denetle(tc, sayfa, ad=""):
    """ZQ'dan etiket ya da oznitelik kirilimi olusmamis olmali."""
    for yasak in ("<svg", "<script", "<img src=x", 'ZQ"', "onload=alert(1)>", "</code><script"):
        tc.assertNotIn(yasak, sayfa, "%s: ham %r" % (ad, yasak))


class RaporBelirteciTests(test_tarama._SunucuTaban):
    """/rapor/<belirtec>/ ucu: belirtec yalniz kendi raporunu acar, sure ve silme sonrasi hicbir uc veri vermez."""

    def iki_firma(self):
        self.la = self.yukle(test_tarama.farkli_belge(1), eposta="a@firma-a.com.tr", sirket="Firma A").getheader("Location")
        self.lb = self.yukle(test_tarama.farkli_belge(2), eposta="b@firma-b.com.tr", sirket="Firma B").getheader("Location")
        self.ta, self.tb = belirtec(self.la), belirtec(self.lb)
        self.assertNotEqual(self.ta, self.tb)

    def yalniz_a(self, yol):
        r, g = self.get(yol)
        g = g.decode("utf-8", "replace")
        self.assertNotIn("12:00:02Z", g, yol)   # B'nin tarama zamani
        return r, g

    def test_firma_belirteci_yalniz_kendi_raporunu_acar(self):
        self.iki_firma()
        ra, ga = self.get(self.la)
        rb, gb = self.get(self.lb)
        self.assertEqual((ra.status, rb.status), (200, 200))
        self.assertIn("12:00:01Z", ga.decode())
        self.assertNotIn("12:00:02Z", ga.decode())
        self.assertIn("12:00:02Z", gb.decode())
        self.assertNotIn("12:00:01Z", gb.decode())
        for g_ in (ga.decode(), gb.decode()):
            self.assertNotIn("Firma A", g_)   # rapor firma adini tasimaz
            self.assertNotIn("Firma B", g_)
        # silme formu yalniz kendi belirtecine isaret eder
        self.assertIn("/rapor/%s/sil" % self.ta, ga.decode())
        self.assertNotIn(self.tb, ga.decode())

    def test_bozulmus_belirteclerle_hicbir_rapor_acilmaz(self):
        self.iki_firma()
        alfabe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for i in range(43):   # her konumda tek karakter degisimi
            ters = alfabe[(alfabe.index(self.ta[i]) + 1) % len(alfabe)]
            kotu = self.ta[:i] + ters + self.ta[i + 1:]
            self.assertEqual(self.get("/rapor/%s/" % kotu)[0].status, 404, "konum %d" % i)
        for kotu in (self.ta[:42], self.ta + "A", self.ta.swapcase(), self.ta.lower() if self.ta.lower() != self.ta else self.ta.upper(),
                     "A" * 43, "", "0" * 43, self.ta[::-1]):
            self.assertEqual(self.get("/rapor/%s/" % kotu)[0].status, 404, kotu)
        for yol in ("/rapor/%s/../%s/" % (self.ta, self.tb), "/rapor/%s/%s/" % (self.ta, self.tb),
                    "/rapor/%s%%2f%s/" % (self.ta, self.tb), "/rapor/%s%%00/" % self.tb, "/rapor/%s/..%%2f%s/" % (self.ta, self.tb),
                    "/rapor/%s/sil/" % self.tb, "/rapor/%s/dogrula/" % self.tb):
            r, g = self.get(yol)
            self.assertEqual(r.status, 404, yol)
            self.assertNotIn(b"12:00:0", g, yol)

    def test_sorgu_parametresi_baska_raporu_getirmez(self):
        self.iki_firma()
        for yol in (self.la + "?token=%s" % self.tb, self.la + "?gorunum=yonetici&rapor=%s" % self.tb, self.la + "?id=2", self.la.rstrip("/") + "?x=" + self.tb):
            r, g = self.yalniz_a(yol)
            self.assertEqual(r.status, 200, yol)
            self.assertIn("12:00:01Z", g)

    def test_a_belirteci_b_raporunu_silemez_ve_dogrulayamaz(self):
        self.iki_firma()
        con = depo.baglan(self.db)
        once = con.execute("SELECT id, dogrulandi, bitis_utc FROM rapor ORDER BY id").fetchall()
        bozuk = ("B" if self.tb[0] == "A" else "A") + self.tb[1:]   # ilk karakter her zaman degisir (64'te 1 cakisma olmasin)
        ters = self.tb[::-1]
        self.assertNotEqual(ters, self.tb)
        for yol in ("/rapor/%s/sil" % bozuk, "/rapor/%s/dogrula" % bozuk, "/rapor/%s/sil" % ters):
            self.assertEqual(self.post(yol)[0].status, 404, yol)
        self.assertEqual(con.execute("SELECT id, dogrulandi, bitis_utc FROM rapor ORDER BY id").fetchall(), once)
        # A'nin kendi belirteci yalniz A'yi siler
        self.assertEqual(self.post("/rapor/%s/sil" % self.ta)[0].status, 303)
        self.assertEqual(self.get(self.la)[0].status, 404)
        self.assertEqual(self.get(self.lb)[0].status, 200)
        self.assertEqual(con.execute("SELECT count(*) FROM rapor").fetchone()[0], 1)

    def test_bitis_sonrasi_hicbir_uc_veri_vermez(self):
        self.iki_firma()
        con = depo.baglan(self.db)
        con.execute("UPDATE rapor SET bitis_utc=? WHERE id=1", (GECMIS,))
        con.commit()
        for yol in (self.la, self.la.rstrip("/"), self.la + "?gorunum=yonetici", self.la + "?gorunum=teknik"):
            r, g = self.get(yol)
            self.assertEqual(r.status, 404, yol)
            self.assertNotIn(b"12:00:01Z", g)
            self.assertNotIn(b"Denetim sonu", g)
        r, g = self.post("/rapor/%s/dogrula" % self.ta)
        self.assertEqual(r.status, 404)   # dogrulanmis ama suresi dolmus: 303 ile "tamam" denmez
        self.assertEqual(g, b"yok\n")
        # silme ucu icerik vermez; sonrasinda rapor yine acilmaz
        r, g = self.post("/rapor/%s/sil" % self.ta)
        self.assertIn(r.status, (303, 404))   # temizlik calisana kadar satir durur; hangisi donerse donsun icerik gelmez
        self.assertNotIn(b"12:00:01Z", g)
        self.assertEqual(self.get(self.la)[0].status, 404)
        self.assertEqual(self.get(self.lb)[0].status, 200)   # B etkilenmez

    def test_bitis_siniri_saniye_hassasiyetinde(self):
        self.iki_firma()
        con = depo.baglan(self.db)
        con.execute("UPDATE rapor SET bitis_utc=? WHERE id=1", (depo.simdi(),))   # tam simdi: sure doldu sayilir (bitis > simdi aranir)
        con.commit()
        self.assertEqual(self.get(self.la)[0].status, 404)

    def test_silinen_rapor_belirteci_yeniden_yuklemeyle_dirilmez(self):
        self.iki_firma()
        self.assertEqual(self.post("/rapor/%s/sil" % self.ta)[0].status, 303)
        for yol in (self.la, self.la.rstrip("/")):
            self.assertEqual(self.get(yol)[0].status, 404)
        self.assertEqual(self.post("/rapor/%s/dogrula" % self.ta)[0].status, 404)   # silinen rapor dogrulanamaz
        self.assertEqual(self.post("/rapor/%s/sil" % self.ta)[0].status, 404)
        # ayni dosya yeniden yuklenirse yeni belirtec: eskisi yine 404
        yeni = self.yukle(test_tarama.farkli_belge(1), eposta="a@firma-a.com.tr", sirket="Firma A").getheader("Location")
        self.assertNotEqual(belirtec(yeni), self.ta)
        self.assertEqual(self.get(yeni)[0].status, 200)
        self.assertEqual(self.get(self.la)[0].status, 404)

    def test_rapor_yanitinda_onbellek_ve_yonlendirme_koruma_basliklari(self):
        self.iki_firma()
        r, g = self.get(self.la)
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer")   # belirtec yolda: baska siteye sizmasin
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn(b'name="robots" content="noindex,nofollow"', g)
        r404, _ = self.get("/rapor/%s/" % ("A" * 43))
        self.assertEqual(r404.getheader("Cache-Control"), "no-store")

    def test_belirtec_gunluge_ve_denetime_yazilmaz(self):
        self.iki_firma()
        self.post("/rapor/%s/sil" % self.ta)
        con = depo.baglan(self.db)
        for (olay,) in con.execute("SELECT olay FROM denetim"):
            self.assertNotIn(self.ta, olay)
            self.assertNotIn(self.tb, olay)
        self.assertNotIn(self.tb, "".join(str(x) for x in con.execute("SELECT * FROM rapor")))   # yalniz SHA-256 ozeti


class BekleyenRaporSureTests(test_tarama._SunucuTaban):
    """E-posta dogrulamasi acikken: bekleyen raporun suresi, silinmesi ve dogrulama ucu."""
    H_EK = {"eposta_dogrulama": True, "site_adresi": "https://alig.test"}

    def con(self):
        return depo.baglan(self.db)

    def bekleyen(self, n=1, eposta="a@firma-a.com.tr"):
        self.yukle(test_tarama.farkli_belge(n), eposta=eposta)
        metin = self.con().execute("SELECT metin FROM posta WHERE alici=? ORDER BY id DESC", (eposta,)).fetchone()[0]
        return test_tarama._baglanti(metin)

    def kullanim(self, eposta):
        return depo.kullanim_say(self.con(), depo.sirket_anahtari(eposta))

    def test_bekleyen_rapor_icerigi_onay_sayfasinda_yok(self):
        t = self.bekleyen()
        r, g = self.get("/rapor/%s/" % t)
        self.assertEqual(r.status, 200)
        self.assertNotIn(b"12:00:01Z", g)
        self.assertNotIn("Denetim sonuçları".encode(), g)

    def test_suresi_dolan_bekleyen_rapor_dogrulanamaz_ve_hak_harcamaz(self):
        t = self.bekleyen()
        c = self.con()
        c.execute("UPDATE rapor SET bitis_utc=?", (GECMIS,))
        c.commit()
        self.assertEqual(self.get("/rapor/%s/" % t)[0].status, 404)   # onay sayfasi da gelmez
        self.assertEqual(self.post("/rapor/%s/dogrula" % t)[0].status, 404)
        self.assertEqual(self.get("/rapor/%s/" % t)[0].status, 404)    # dogrulama ile dirilmedi
        self.assertEqual(self.con().execute("SELECT dogrulandi FROM rapor").fetchone()[0], 0)
        self.assertEqual(self.kullanim("a@firma-a.com.tr"), 0)

    def test_silinen_bekleyen_rapor_dogrulanamaz(self):
        t = self.bekleyen()
        self.assertEqual(self.post("/rapor/%s/sil" % t)[0].status, 303)
        self.assertEqual(self.post("/rapor/%s/dogrula" % t)[0].status, 404)
        self.assertEqual(self.get("/rapor/%s/" % t)[0].status, 404)
        self.assertEqual(self.kullanim("a@firma-a.com.tr"), 0)
        self.assertEqual(self.con().execute("SELECT count(*) FROM rapor").fetchone()[0], 0)

    def test_dogrulanmis_rapor_silinince_dogrula_yeniden_acmaz(self):
        t = self.bekleyen()
        self.assertEqual(self.post("/rapor/%s/dogrula" % t)[0].status, 303)
        self.assertEqual(self.get("/rapor/%s/" % t)[0].status, 200)
        self.assertEqual(self.post("/rapor/%s/sil" % t)[0].status, 303)
        self.assertEqual(self.post("/rapor/%s/dogrula" % t)[0].status, 404)
        self.assertEqual(self.get("/rapor/%s/" % t)[0].status, 404)

    def test_baska_firmanin_bekleyen_belirteci_ile_dogrulama_yapilmaz(self):
        ta = self.bekleyen(1, "a@firma-a.com.tr")
        tb = self.bekleyen(2, "b@firma-b.com.tr")
        self.assertEqual(self.post("/rapor/%s/dogrula" % ta)[0].status, 303)
        c = self.con()
        self.assertEqual(c.execute("SELECT dogrulandi FROM rapor WHERE id=2").fetchone()[0], 0)   # B hala bekliyor
        self.assertEqual(self.kullanim("b@firma-b.com.tr"), 0)
        self.assertNotIn(b"12:00:02Z", self.get("/rapor/%s/" % ta)[1])
        self.assertNotIn(b"Denetim sonu", self.get("/rapor/%s/" % tb)[1])


class RaporKacisTests(unittest.TestCase):
    """Rapor HTML'i: nesne adi ve metin degerleri etiket ya da oznitelik kiramaz (yukleme denetimini atlayan kayit dahil)."""

    def _rapor(self, belge, dil="tr"):
        return {"id": 1, "olusturma_utc": "2026-11-10T12:00:00Z", "bitis_utc": "2026-12-10T12:00:00Z", "motor": "postgresql", "dil": dil, "belge": belge}

    def test_her_denetimde_her_metin_kolonu_kacislidir(self):
        belge = zehirli_belge()
        gorulen = False
        for dil in ("tr", "en"):
            for g in rapor.GORUNUMLER:
                sayfa = rapor.sayfa(self._rapor(belge, dil), dil, "T" * 43, gorunum=g)
                kacis_denetle(self, sayfa, "%s/%s" % (dil, g))
                gorulen = gorulen or html.escape(ZQ) in sayfa
        self.assertTrue(gorulen, "kotu nesne adi raporda hic gorunmedi: test anlamsiz kalir")

    def test_token_ve_ust_alanlar_kacislidir(self):
        belge = zehirli_belge()
        belge["olusturma_utc"] = ZQ
        r = self._rapor(belge)
        r["bitis_utc"] = ZQ
        sayfa = rapor.sayfa(r, "tr", ZQ)   # belirtec yol deseniyle sinirli; yine de kacislanir
        kacis_denetle(self, sayfa, "ust alanlar")

    def test_atlanan_veritabani_adi_kacislidir(self):
        belge = test_tarama.temiz_belge()
        belge["kontroller"]["pg_kapsam"]["satirlar"] = [{"veritabani": "a", "veritabani_sayisi": 2}]
        belge["kontroller"]["pg_kapsam"]["atlanan"] = [{"veritabani": ZQ, "neden": "yetki"}]
        sayfa = rapor.sayfa(self._rapor(belge), "tr", "T" * 43)
        kacis_denetle(self, sayfa, "atlanan")
        self.assertIn("ZQ&quot;&gt;&lt;svg", sayfa)


class RaporKacisSunucuTests(test_tarama._SunucuTaban):
    """Kotu nesne adli rapor, musteri baglantisindan iki dilde ve iki gorunumde kacisli gelir."""

    def test_musteri_baglantisi(self):
        con = depo.baglan(self.db)
        firma = depo.firma_kaydet(con, "kacis.com", "Kacis", "x@kacis.com", "tarama")
        for dil in ("tr", "en"):
            t = secrets.token_urlsafe(32)
            depo.rapor_ekle(con, t, "postgresql", dil, zehirli_belge(), firma["id"], "x@kacis.com")
            for g in ("teknik", "yonetici"):
                r, govde = self.get("/rapor/%s/?gorunum=%s" % (t, g))
                self.assertEqual(r.status, 200)
                kacis_denetle(self, govde.decode(), "%s/%s" % (dil, g))
        r, govde = self.get("/rapor/%s/?gorunum=%s" % (t, ZQ.replace(" ", "")))   # yansiyan parametre: bilinmeyen gorunum teknik olur
        self.assertEqual(r.status, 200)
        kacis_denetle(self, govde.decode(), "gorunum parametresi")


class PortalKacisTests(test_portal.HttpTaban):
    """Portal sayfalari: firma adi, talep metni ve rapor icerigi kacisli."""

    def test_portal_sayfalari(self):
        self.hesap("ali@kacis.com.tr", ZQ[:60])
        con = self.con()
        fid = depo.firma_listele(con)[0]["id"]
        depo.rapor_ekle(con, secrets.token_urlsafe(32), "postgresql", "tr", zehirli_belge(), fid, "ali@kacis.com.tr")
        rid = con.execute("SELECT max(id) FROM rapor").fetchone()[0]
        _, kod = self.giris("ali@kacis.com.tr")
        ks = portal_depo.kapsam(self.con(), kod)
        self.assertEqual(ks.talep_ekle("destek", ZQ[:60], ZQ)[1], None)
        gorulen = False
        for yol in ("/portal/", "/portal/rapor/%d/" % rid, "/portal/rapor/%d/?gorunum=yonetici" % rid, "/portal/rapor/%d/sil" % rid,
                    "/portal/talepler", "/portal/hesap", "/portal/?dil=en"):
            r = self.istek("GET", yol, cerez=kod)
            self.assertEqual(r.status, 200, yol)
            kacis_denetle(self, r.govde, yol)
            gorulen = gorulen or "ZQ&quot;&gt;&lt;svg" in r.govde
        self.assertTrue(gorulen)
        for yol in ("/portal/?dil=" + ZQ.replace(" ", "%20"), "/portal/kayit?dil=%22%3E%3Csvg%20onload=alert(1)%3E"):
            r = self.istek("GET", yol)
            kacis_denetle(self, r.govde, yol)


class YonetimKacisTests(test_yonetim.Taban):
    """Yonetim paneli: depolanmis (rapor, firma notu, talep, giris adi) ve yansiyan (sorgu) degerler kacisli."""

    def setUp(self):
        super().setUp()
        t = depo.baglan(self.tdb)
        depo.rapor_ekle(t, "zehir-kacis", "postgresql", "tr", zehirli_belge(), self.firma["id"], "ayse@firma.com.tr")
        depo.firma_not_yaz(t, self.firma["id"], ZQ)
        t.close()
        f = sqlite3.connect(self.fdb)
        f.execute("INSERT INTO contact VALUES(2,'2026-11-11T10:00:00Z',?,?,'z@zq.com','pg',?,'h')", (ZQ, ZQ, ZQ))
        f.commit()
        f.close()
        # kotu kullanici adiyla basarisiz giris: yonetim denetim kaydina yazilir ve orada gorunur
        r, _ = self.istek("POST", "/yonetim/giris", {"ad": ZQ[:64], "parola": "yanlis-parola-000", "kod": "000000"}, cerez=False)
        self.assertEqual(r.status, 401)
        self.assertEqual(self.giris().status, 303)

    def test_depolanmis_degerler_kacislidir(self):
        fid = self.firma["id"]
        gorulen = set()
        for yol in ("/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar/%d" % fid, "/yonetim/talepler", "/yonetim/taramalar",
                    "/yonetim/taramalar/2", "/yonetim/taramalar/2?gorunum=yonetici", "/yonetim/portal-talepleri",
                    "/yonetim/denetim", "/yonetim/denetim?kaynak=yonetim", "/yonetim/sistem"):
            r, g = self.istek("GET", yol)
            self.assertEqual(r.status, 200, yol)
            kacis_denetle(self, g, yol)
            if "ZQ&quot;&gt;&lt;svg" in g:
                gorulen.add(yol)
        for gerekli in ("/yonetim/taramalar/2", "/yonetim/firmalar/%d" % fid, "/yonetim/talepler", "/yonetim/denetim?kaynak=yonetim"):
            self.assertIn(gerekli, gorulen, "kotu deger bu sayfada gorunmedi: test anlamsiz kalir")

    def test_yansiyan_sorgu_parametreleri_kacislidir(self):
        for yol in ("/yonetim/firmalar?ara=", "/yonetim/firmalar?durum=", "/yonetim/talepler?durum=", "/yonetim/talepler?sayfa=",
                    "/yonetim/denetim?kaynak=", "/yonetim/portal-talepleri?durum=", "/yonetim/taramalar/2?gorunum="):
            r, g = self.istek("GET", yol + ZQ.replace(" ", "%20").replace("&", "%26").replace("#", "%23"))
            self.assertIn(r.status, (200, 404), yol)
            kacis_denetle(self, g, yol)
        for yol in ("/yonetim/firmalar.csv?ara=", "/yonetim/talepler.csv?durum="):   # CSV: HTML degil, formul kacisi
            r, g = self.istek("GET", yol + "%3D1%2B1")
            self.assertTrue(r.getheader("Content-Type").startswith("text/csv"))
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")


class YonetimOturumsuzTests(test_yonetim.Taban):
    """Yonetim uclarinin tamami oturumsuz erisime kapali: tablo guduml, her gecersiz kimlik durumu icin."""

    GET = ("/yonetim", "/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar?ara=ornek", "/yonetim/firmalar?durum=aktif",
           "/yonetim/firmalar.csv", "/yonetim/firmalar.csv?durum=aktif&ara=ornek", "/yonetim/talepler.csv", "/yonetim/talepler.csv?durum=yeni",
           "/yonetim/firmalar/1", "/yonetim/talepler", "/yonetim/talepler?durum=yeni&sayfa=1", "/yonetim/portal-talepleri",
           "/yonetim/kip-b", "/yonetim/kip-b?firma=1&durum=bekliyor&sayfa=1", "/yonetim/taramalar", "/yonetim/taramalar/1", "/yonetim/taramalar/1?gorunum=yonetici", "/yonetim/denetim",
           "/yonetim/denetim?kaynak=yonetim", "/yonetim/sistem", "/yonetim/yok", "/yonetim/firmalar/1/", "/yonetim/%2e%2e/yonetim/sistem",
           "/yonetim/giris/../sistem", "/yonetim/firmalar/999999999", "/yonetimx")
    POST = (("/yonetim/cikis", {}), ("/yonetim/talepler/1/durum", {"durum": "kapandi", "aciklama": "x"}),
            ("/yonetim/portal-talepleri/1/durum", {"durum": "tamamlandi"}),
            ("/yonetim/firmalar/1/durum", {"durum": "pasif"}), ("/yonetim/firmalar/1/not", {"aciklama": "x"}),
            ("/yonetim/firmalar/1/sinir", {}), ("/yonetim/firmalar/1/izin", {"izin": "1"}),
            ("/yonetim/firmalar/1/sil", {"emin": "evet", "talepler": "evet"}), ("/yonetim/taramalar/1/sil", {}), ("/yonetim/yok", {}))
    ACIK = {"/yonetim/giris"}   # giris sayfasi bilerek herkese acik
    TOHUM = ("ada@ornek.com", "Ornek AS", "ayse@firma.com.tr", "firma.com.tr", "Firma &lt;i&gt;", "TLS kapal", "Ada &lt;", "alig-firmalar", "alig-talepler")

    def setUp(self):
        super().setUp()
        self._k = 0
        self.con_y = ydepo.baglan(self.ydb)

    # ---- yardimcilar ----
    def oturum_ac(self, ad="ali", gizli=None, parola=PAROLA):
        """Gecerli oturum kodu (TOTP sayaci her cagrida ilerler: tekrar kullanim kuralina takilmaz)."""
        self._k += 1
        t = time.time() + 30 * self._k
        kod, neden = ydepo.giris(self.con_y, ad, parola, guvenlik.totp_kod(gizli or self.gizli, int(t // 30)), "192.0.2.1", simdi=t)
        self.assertIsNotNone(kod, neden)
        return kod

    def cerezler(self):
        """{durum: Cookie degeri ya da None}. Hepsi 'oturumsuz' sayilmali; 'gecerli' kontrol amacli."""
        ad = "__Host-alig_oturum"
        out = {"yok": None, "bos": ad + "=", "sahte": ad + "=" + "A" * 43, "sahte_uzun": ad + "=" + "A" * 5000, "bozuk": "%s=a; ;;=%s" % (ad, ad)}
        g = self.oturum_ac()
        out["yanlis_cerez_adi"] = "alig_oturum=" + g            # __Host- oneki olmadan
        out["ozet_cereze_konmus"] = ad + "=" + guvenlik.ozet(g)   # veritabani sizsa bile ozet oturum acmaz
        e = self.oturum_ac()
        self.con_y.execute("UPDATE oturum SET son_erisim_utc=? WHERE kod_sha256=?", (GECMIS, guvenlik.ozet(e)))
        self.con_y.commit()
        out["bosta_suresi_dolmus"] = ad + "=" + e
        e2 = self.oturum_ac()
        self.con_y.execute("UPDATE oturum SET olusturma_utc=? WHERE kod_sha256=?", (GECMIS, guvenlik.ozet(e2)))
        self.con_y.commit()
        out["toplam_suresi_dolmus"] = ad + "=" + e2
        c = self.oturum_ac()
        ydepo.cikis(self.con_y, c)
        out["cikis_yapilmis"] = ad + "=" + c
        return out

    def durum(self, haric=("oturum",)):
        """Tum veritabanlarinin icerik ozeti: oturumsuz istek hicbir seyi degistirmemeli."""
        d = {}
        for ad, yol in (("y", self.ydb), ("t", self.tdb), ("f", self.fdb)):
            c = sqlite3.connect(yol)
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
                if t not in haric:
                    d[(ad, t)] = hashlib.sha256(repr(c.execute('SELECT * FROM "%s" ORDER BY 1' % t).fetchall()).encode()).hexdigest()
            c.close()
        return d

    def istek_c(self, metod, yol, cerez, veri=None, basliklar=None):
        self.cerez = cerez
        return self.istek(metod, yol, veri, cerez=cerez is not None, basliklar=basliklar)

    def kapali_mi(self, r, g, ne):
        self.assertIn(r.status, (303, 403), ne)
        if r.status == 303:
            self.assertEqual(r.getheader("Location"), "/yonetim/giris", ne)
        self.assertIsNone(r.getheader("Content-Disposition"), ne)
        self.assertFalse((r.getheader("Content-Type") or "").startswith("text/csv"), ne)
        self.assertIsNone(r.getheader("Set-Cookie"), ne)   # oturumsuz istek cerez vermez
        for tohum in self.TOHUM:
            self.assertNotIn(tohum, g, "%s: %r sizdi" % (ne, tohum))
        self.assertNotIn(self.gizli, g)

    # ---- tablo butunlugu ----
    def test_tablo_menu_ve_kaynak_yollarini_kapsar(self):
        """Yeni bir yonetim yolu eklenirse bu tabloya da eklenmeden test kirilir."""
        kaynak = inspect.getsource(server.H.do_GET) + inspect.getsource(server.H.do_POST)
        yollar = set(re.findall(r'"(/yonetim[^"]*)"', kaynak)) | {"/" + m.split("$")[0].lstrip("^/") for m in re.findall(r'r"(\^/yonetim[^"]*\$)"', kaynak)}
        tablo = {u.split("?")[0] for u in self.GET} | {u for u, _ in self.POST}
        for m, _ in server.MENU:
            self.assertIn(m.split("?")[0], tablo, "menu yolu tabloda yok: " + m)
        self.assertGreater(len(yollar), 15)
        for y in yollar - self.ACIK:
            if "(" in y:   # duzenli ifade: tabloda onu eslesen bir ornek olmali
                kalip = re.compile("^" + y.replace("\\d", r"\d") + "$")
                self.assertTrue(any(kalip.match(t) for t in tablo), "tabloda eslesen yok: " + y)
            else:
                self.assertIn(y, tablo | {"/yonetim/"}, "tabloda yok: " + y)

    def test_kontrol_gecerli_oturum_tablodaki_yollari_acar(self):
        """Tablo bos yere gecmesin: gecerli oturumla GET yollari gercekten acilir (404 olanlar bilerek yok yollar)."""
        self.cerez = "%s=%s" % ("__Host-alig_oturum", self.oturum_ac())
        yok = {"/yonetim/yok", "/yonetim/%2e%2e/yonetim/sistem", "/yonetim/giris/../sistem", "/yonetim/firmalar/999999999", "/yonetim/firmalar/1/", "/yonetimx"}
        for u in self.GET:
            r, g = self.istek("GET", u)
            if u in yok:
                self.assertIn(r.status, (303, 404), u)
            else:
                self.assertEqual(r.status, 200, u)
        r, g = self.istek("GET", "/yonetim/firmalar.csv")
        self.assertTrue(r.getheader("Content-Type").startswith("text/csv"))
        self.assertIn("Ornek AS", g)

    # ---- oturumsuz erisim ----
    def test_oturumsuz_her_get_yolu_girise_gider_veri_sizmaz(self):
        cerezler = self.cerezler()   # oturumlarin kendisi once acilir: denetim kayitlari karsilastirmaya girmez
        once = self.durum()
        for ad, cerez in cerezler.items():
            for u in self.GET:
                r, g = self.istek_c("GET", u, cerez)
                self.kapali_mi(r, g, "%s %s" % (ad, u))
        self.assertEqual(self.durum(), once)   # hic denetim kaydi, firma esitlemesi ya da durum degisikligi yok

    def test_oturumsuz_her_post_yolu_girise_gider_durum_degismez(self):
        cerezler = self.cerezler()
        once = self.durum()
        for ad, cerez in cerezler.items():
            for u, veri in self.POST:
                for csrf in ("", "x" * 43):
                    r, g = self.istek_c("POST", u, cerez, dict(veri, csrf=csrf))
                    self.kapali_mi(r, g, "%s POST %s" % (ad, u))
        self.assertEqual(self.durum(), once)
        self.assertIsNotNone(tdepo_rapor(self.tdb, 1))   # silme uclari rapor ve firmayi silmedi

    def test_oturumlu_ama_csrf_ya_da_kaynak_yanlis_post_reddedilir(self):
        g = self.oturum_ac()
        cerez = "__Host-alig_oturum=" + g
        once = self.durum(haric=("oturum", "denetim"))
        for u, veri in self.POST:
            for ek in ({}, {"csrf": ""}, {"csrf": "yanlis"}):
                r, _ = self.istek_c("POST", u, cerez, dict(veri, **ek))
                self.assertEqual(r.status, 403, "%s %r" % (u, ek))
            r, _ = self.istek_c("POST", u, cerez, dict(veri, csrf="x"), basliklar={"Origin": "https://kotu.example"})
            self.assertEqual(r.status, 403, u)
        self.assertEqual(self.durum(haric=("oturum", "denetim")), once)
        self.assertEqual(self.istek_c("GET", "/yonetim/sistem", cerez)[0].status, 200)   # oturum yine gecerli

    def test_oturum_baska_yollarla_gecersiz_olunca_acilmaz(self):
        for ad, islem in (("kullanici silindi", lambda u: ydepo.kullanici_sil(self.con_y, u)),
                          ("parola degisti", lambda u: ydepo.kullanici_parola(self.con_y, u, "yeni-parola-456789")),
                          ("dogrulama anahtari yenilendi", lambda u: ydepo.kullanici_totp_yenile(self.con_y, u))):
            kul = "u" + str(self._k)
            gizli = ydepo.kullanici_ekle(self.con_y, kul, PAROLA)
            cerez = "__Host-alig_oturum=" + self.oturum_ac(kul, gizli)
            self.assertEqual(self.istek_c("GET", "/yonetim/firmalar.csv", cerez)[0].status, 200, ad)
            islem(kul)
            for u in ("/yonetim/firmalar.csv", "/yonetim/talepler.csv", "/yonetim/sistem"):
                r, g = self.istek_c("GET", u, cerez)
                self.kapali_mi(r, g, "%s: %s" % (ad, u))

    # ---- CSV ----
    def test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir(self):
        sayac = lambda: self.con_y.execute("SELECT count(*) FROM denetim WHERE olay LIKE '%csv indirildi%'").fetchone()[0]  # noqa: E731
        self.istek("GET", "/yonetim/firmalar", cerez=False)
        for u in ("/yonetim/firmalar.csv", "/yonetim/talepler.csv"):
            r, g = self.istek("GET", u, cerez=False)
            self.assertEqual((r.status, g), (303, ""), u)
        for u in ("/yonetim/firmalar.csv", "/yonetim/talepler.csv"):
            r, g = self.istek_c("GET", u, "__Host-alig_oturum=" + guvenlik.rastgele_kod())
            self.assertEqual((r.status, g), (303, ""), u)
        self.assertEqual(sayac(), 0)   # yetkisiz denemeler indirme olarak yazilmaz
        cerez = "__Host-alig_oturum=" + self.oturum_ac()
        r, g = self.istek_c("GET", "/yonetim/talepler.csv", cerez)
        self.assertEqual(r.status, 200)
        self.assertIn("ada@ornek.com", g)
        self.assertEqual(sayac(), 1)
        self.assertEqual(r.getheader("Cache-Control"), "no-store")   # indirilen kisisel veri onbelleklenmez
        self.assertIn("attachment", r.getheader("Content-Disposition"))

    def test_csv_yontemi_ve_yol_varyantlari(self):
        cerez = "__Host-alig_oturum=" + self.oturum_ac()
        for u in ("/yonetim/firmalar.csv/", "/yonetim/Firmalar.csv", "/yonetim/firmalar.CSV", "/yonetim/firmalar.csv%00"):
            r, g = self.istek_c("GET", u, None)
            self.assertIn(r.status, (303, 403), u)
            self.assertNotIn("Ornek AS", g)
        r, _ = self.istek_c("POST", "/yonetim/firmalar.csv", cerez, {"csrf": self.csrf_of(cerez)})
        self.assertEqual(r.status, 404)   # POST ile dosya verilmez

    def csrf_of(self, cerez):
        _, g = self.istek_c("GET", "/yonetim/talepler", cerez)
        return re.search(r'name="csrf" value="([^"]+)"', g).group(1)

    def test_yetki_modeli_tek_rol_belgelenmis_varsayim(self):
        """Panelde rol ayrimi yok: her kullanici her yonetim ucunu acar (docs/kod-inceleme.md, ALIG-SEC-001 S5). Ikinci kullanici da CSV alir."""
        ikinci = ydepo.kullanici_ekle(self.con_y, "veli", PAROLA)
        t = time.time() + 30 * 50
        kod, _ = ydepo.giris(self.con_y, "veli", PAROLA, guvenlik.totp_kod(ikinci, int(t // 30)), "192.0.2.2", simdi=t)
        r, g = self.istek_c("GET", "/yonetim/firmalar.csv", "__Host-alig_oturum=" + kod)
        self.assertEqual(r.status, 200)
        self.assertIn("veli", self.istek_c("GET", "/yonetim/denetim?kaynak=yonetim", "__Host-alig_oturum=" + kod)[1])   # kim indirdiyse izlenir


def tdepo_rapor(yol, rid):
    c = depo.baglan(yol)
    try:
        return depo.rapor_getir_id(c, rid)
    finally:
        c.close()



class TotpTekrarVeOturumOzetiTests(unittest.TestCase):
    """Zaten var oldugu soylenen korumalar testle kanitlanir: TOTP tekrar kullanimi ve oturum kodunun yalniz ozetle saklanmasi."""

    def setUp(self):
        self.dizin = Path(tempfile.mkdtemp())
        self.con = ydepo.baglan(str(self.dizin / "y.sqlite"))
        self.gizli = ydepo.kullanici_ekle(self.con, "ali", PAROLA)
        self.t0 = 1_700_000_000.0
        self.s = int(self.t0 // 30)

    def giris(self, sayac, parola=PAROLA, ip="192.0.2.1", simdi=None):
        return ydepo.giris(self.con, "ali", parola, guvenlik.totp_kod(self.gizli, sayac), ip, simdi=self.t0 if simdi is None else simdi)

    def oturum_say(self):
        return self.con.execute("SELECT count(*) FROM oturum").fetchone()[0]

    def sayac(self):
        return self.con.execute("SELECT totp_sayac FROM kullanici WHERE ad='ali'").fetchone()[0]

    def test_ayni_kod_ikinci_kez_hicbir_yolla_gecmez(self):
        self.assertIsNotNone(self.giris(self.s)[0])
        self.assertEqual(self.sayac(), self.s)
        for ip in ("192.0.2.1", "198.51.100.7"):   # baska IP'den de gecmez
            self.assertEqual(self.giris(self.s, ip=ip), (None, "hatali"))
        self.assertEqual(self.oturum_say(), 1)   # tekrar yeni oturum acmadi
        self.assertEqual(self.sayac(), self.s)

    def test_sayac_tek_yonlu_eski_pencere_kodu_da_gecmez(self):
        self.assertIsNotNone(self.giris(self.s + 1, simdi=self.t0 + 30)[0])   # ileri kod kabul
        self.assertEqual(self.giris(self.s, simdi=self.t0 + 30), (None, "hatali"))   # pencere icinde ama daha eski sayac
        self.assertEqual(self.giris(self.s - 1, simdi=self.t0 + 30), (None, "hatali"))
        self.assertEqual(self.sayac(), self.s + 1)

    def test_yanlis_parola_sayaci_ilerletmez_ve_kodu_yakmaz(self):
        self.assertEqual(self.giris(self.s, parola="yanlis-parola-000"), (None, "hatali"))
        self.assertEqual(self.sayac(), 0)
        self.assertIsNotNone(self.giris(self.s)[0])   # dogru parolayla ayni kod hala gecerli

    def test_tekrar_denemesi_denetime_basarisiz_olarak_yazilir(self):
        self.giris(self.s)
        self.giris(self.s)
        olaylar = [r[0] for r in self.con.execute("SELECT olay FROM denetim ORDER BY seq")]
        self.assertEqual(sum("basarisiz giris" in o for o in olaylar), 1)
        self.assertIsNone(ydepo.denetim_dogrula(self.con))

    def test_anahtar_yenilenince_sayac_sifirlanir_eski_anahtar_gecmez(self):
        self.giris(self.s)
        yeni = ydepo.kullanici_totp_yenile(self.con, "ali")
        self.assertNotEqual(yeni, self.gizli)
        self.assertEqual(self.sayac(), 0)
        self.assertEqual(self.giris(self.s + 1, simdi=self.t0 + 30), (None, "hatali"))   # eski anahtarin kodu
        kod, _ = ydepo.giris(self.con, "ali", PAROLA, guvenlik.totp_kod(yeni, self.s + 1), "192.0.2.1", simdi=self.t0 + 30)
        self.assertIsNotNone(kod)

    def test_oturum_kodu_yalniz_sha256_ozetiyle_saklanir(self):
        kod, _ = self.giris(self.s)
        satirlar = self.con.execute("SELECT * FROM oturum").fetchall()
        self.assertEqual(len(satirlar), 1)
        self.assertEqual(satirlar[0][0], hashlib.sha256(kod.encode()).hexdigest())   # birincil anahtar = SHA-256 ozeti
        self.assertNotIn(kod, [str(v) for v in satirlar[0]])
        self.assertEqual([c[1] for c in self.con.execute("PRAGMA table_info(oturum)")], ["kod_sha256", "ad", "csrf", "olusturma_utc", "son_erisim_utc"])
        self.con.close()
        for p in self.dizin.iterdir():   # veritabani, WAL ve paylasilan bellek dosyalari dahil hicbir dosyada ham kod yok
            self.assertNotIn(kod.encode(), p.read_bytes(), p.name)
        con = ydepo.baglan(str(self.dizin / "y.sqlite"))
        self.assertEqual(ydepo.oturum(con, kod)["ad"], "ali")
        self.assertIsNone(ydepo.oturum(con, satirlar[0][0]), "ozet cerez olarak kabul edilmemeli: sizan veritabani oturum acmaz")
        self.assertNotIn(kod, "".join(str(x) for x in con.execute("SELECT * FROM denetim")))

    def test_portal_oturum_kodu_da_yalniz_ozetle_saklanir(self):
        con = test_portal.yeni_db()
        test_portal.hesap_ac(con, "ali@firma-a.com.tr", "Firma A")
        kod, _ = portal_depo.giris(con, "ali@firma-a.com.tr", test_portal.PAROLA, test_portal.IP)
        oz = guvenlik_ozet(kod)
        self.assertEqual(con.execute("SELECT kod_sha256 FROM portal_oturum").fetchone()[0], oz)
        self.assertNotIn(kod, "".join(str(x) for x in con.execute("SELECT * FROM portal_oturum")))
        self.assertIsNotNone(portal_depo.kapsam(con, kod))
        self.assertIsNone(portal_depo.kapsam(con, oz))   # ozet oturum acmaz


def guvenlik_ozet(kod):
    return hashlib.sha256(kod.encode("utf-8")).hexdigest()


class TotpSirriSizmazTests(test_yonetim.Taban):
    """TOTP sirri duz metin saklanir (SEC-K1, acik karar); en azindan hicbir cikti yolundan disari cikmamali."""

    def test_sir_panelde_csvde_denetimde_ve_cli_listesinde_yok(self):
        self.assertEqual(self.giris().status, 303)
        sayfalar = ["/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar.csv", "/yonetim/talepler", "/yonetim/talepler.csv", "/yonetim/taramalar",
                    "/yonetim/denetim", "/yonetim/denetim?kaynak=yonetim", "/yonetim/sistem", "/yonetim/portal-talepleri"]
        for u in sayfalar:
            r, g = self.istek("GET", u)
            self.assertNotIn(self.gizli, g, u)
            self.assertNotIn(guvenlik.totp_uri(self.gizli, "ali"), g, u)
        con = sqlite3.connect(self.ydb)
        for (olay, alanlar) in con.execute("SELECT olay, alanlar FROM denetim"):
            self.assertNotIn(self.gizli, olay + alanlar)
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kullanici.main(["--db", self.ydb, "liste"])
        self.assertNotIn(self.gizli, cikti.getvalue())
        self.assertIn("ali", cikti.getvalue())

    def test_sir_veritabaninda_duz_metin_oldugu_belgelenmis_bulgudur(self):
        """Bu test bulguyu SABITLER: sir sifreli saklanmaya baslarsa (SEC-K1 karari uygulanirsa) bilincli olarak guncellenmeli."""
        satir = sqlite3.connect(self.ydb).execute("SELECT totp FROM kullanici WHERE ad='ali'").fetchone()[0]
        self.assertEqual(satir, self.gizli)
        belge = (ROOT / "docs" / "kod-inceleme.md").read_text(encoding="utf-8")
        self.assertIn("SEC-K1", belge)


class TotpKurtarmaTests(unittest.TestCase):
    """Dogrulama cihazi kaybi: yonetim/kullanici.py totp-yenile yolu (docs/runbook.md 'Dogrulama cihazi kaybi')."""

    def setUp(self):
        self.yol = str(Path(tempfile.mkdtemp()) / "y.sqlite")
        self.con = ydepo.baglan(self.yol)
        self.eski = ydepo.kullanici_ekle(self.con, "ali", PAROLA)
        self.t0 = 1_700_000_000.0
        self.kod, _ = ydepo.giris(self.con, "ali", PAROLA, guvenlik.totp_kod(self.eski, int(self.t0 // 30)), "192.0.2.1", simdi=self.t0)
        self.assertIsNotNone(self.kod)

    def cli(self, *argv):
        cikti = io.StringIO()
        with contextlib.redirect_stdout(cikti):
            kod = kullanici.main(["--db", self.yol] + list(argv))
        return kod, cikti.getvalue()

    def test_totp_yenile_yeni_anahtar_verir_oturumlari_kapatir_parolayi_degistirmez(self):
        kod, cikti = self.cli("totp-yenile", "ali")
        self.assertEqual(kod, 0)
        yeni = re.search(r"Anahtar: ([A-Z2-7]+)", cikti).group(1)
        self.assertNotEqual(yeni, self.eski)
        self.assertIn("otpauth://totp/", cikti)
        con = ydepo.baglan(self.yol)
        self.assertEqual(con.execute("SELECT totp FROM kullanici WHERE ad='ali'").fetchone()[0], yeni)
        self.assertIsNone(ydepo.oturum(con, self.kod))   # kayip cihazla acilmis oturum kapandi
        t = self.t0 + 60
        self.assertEqual(ydepo.giris(con, "ali", PAROLA, guvenlik.totp_kod(self.eski, int(t // 30)), "192.0.2.1", simdi=t), (None, "hatali"))   # eski cihaz artik giremez
        yeni_kod, _ = ydepo.giris(con, "ali", PAROLA, guvenlik.totp_kod(yeni, int(t // 30)), "192.0.2.1", simdi=t)
        self.assertIsNotNone(yeni_kod)   # parola ayni, yeni anahtarla giris olur
        olaylar = [(a, o) for a, o in con.execute("SELECT aktor, olay FROM denetim ORDER BY seq")]
        self.assertIn(("cli", "dogrulama kodu anahtari yenilendi: ali"), olaylar)
        self.assertIsNone(ydepo.denetim_dogrula(con))

    def test_olmayan_kullanici_ve_gecersiz_ad_kayit_birakmaz(self):
        once = self.con.execute("SELECT count(*) FROM denetim").fetchone()[0]
        self.assertEqual(self.cli("totp-yenile", "yok")[1].strip(), "kullanici yok")
        for ad in ("", "a b", "ali;drop", "x" * 33, "ça"):
            with self.assertRaises(SystemExit):
                self.cli("totp-yenile", ad)
        self.assertEqual(self.con.execute("SELECT count(*) FROM denetim").fetchone()[0], once)
        self.assertEqual(self.con.execute("SELECT totp FROM kullanici WHERE ad='ali'").fetchone()[0], self.eski)

    def test_anahtar_yalniz_bir_kez_yazilir_ve_liste_gostermez(self):
        _, cikti = self.cli("totp-yenile", "ali")
        yeni = re.search(r"Anahtar: ([A-Z2-7]+)", cikti).group(1)
        self.assertNotIn(yeni, self.cli("liste")[1])
        self.assertNotIn(PAROLA, cikti)

    def test_kilitli_kullanici_yenilemeden_sonra_sure_dolana_kadar_kilitli_kalir(self):
        """Bilinen sinir (runbook'ta yazili): totp-yenile deneme sayacini sifirlamaz; engel 15 dakikada kendiliginden kalkar."""
        for _ in range(ydepo.DENEME_KULLANICI):
            ydepo.giris(self.con, "ali", PAROLA, "000000", "192.0.2.9")
        self.cli("totp-yenile", "ali")
        con = ydepo.baglan(self.yol)
        yeni = con.execute("SELECT totp FROM kullanici WHERE ad='ali'").fetchone()[0]
        t = self.t0 + 90
        self.assertEqual(ydepo.giris(con, "ali", PAROLA, guvenlik.totp_kod(yeni, int(t // 30)), "192.0.2.1", simdi=t), (None, "engelli"))


class CliDosyaIzniTests(unittest.TestCase):
    """yonetim.sqlite parola ozetleri ve TOTP sirlari tasir: CLI ilk olusturan olsa da dosya yalniz sahibine acik olmali."""

    def test_cli_gevsek_umask_altinda_bile_dosyayi_0600_olusturur(self):
        d = Path(tempfile.mkdtemp())
        yol = d / "y.sqlite"
        r = subprocess.run([sys.executable, str(ROOT / "yonetim" / "kullanici.py"), "--db", str(yol), "liste"],
                           preexec_fn=lambda: os.umask(0o022), capture_output=True, text=True, timeout=60)   # sudo -u ile gelen tipik umask
        self.assertEqual(r.returncode, 0, r.stderr)
        for p in d.iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode) & 0o077, 0, "%s: %o" % (p.name, stat.S_IMODE(p.stat().st_mode)))
        self.assertTrue(yol.exists())


class BelgeTests(unittest.TestCase):
    """Bulgular ve karar kayitli: kod-inceleme.md, kararlar.md, runbook.md."""

    def okut(self, ad):
        return (ROOT / "docs" / ad).read_text(encoding="utf-8")

    def test_kod_inceleme_bulgulari_biciminde_kayitli(self):
        m = self.okut("kod-inceleme.md")
        self.assertIn("ALIG-SEC-001", m)
        bolum = m[m.index("ALIG-SEC-001"):]
        for alan in ("**FINDING:**", "**EVIDENCE:**", "**RISK:**", "**RECOMMENDATION:**"):
            self.assertIn(alan, bolum)
        self.assertRegex(bolum, r"TOTP secret")
        self.assertIn("SEC-K1", bolum)
        for secenek in ("systemd-creds", "0700", "disk encryption"):
            self.assertIn(secenek, bolum)

    def test_karar_satiri_sec_k1(self):
        satir = [s for s in self.okut("kararlar.md").splitlines() if s.startswith("| SEC-K1 |")]
        self.assertEqual(len(satir), 1)
        self.assertIn("Waiting for Ali", satir[0])
        self.assertIn("0700", satir[0])
        self.assertIn("disk encryption", satir[0])
        self.assertEqual(len(satir[0].split("|")), len([s for s in self.okut("kararlar.md").splitlines() if s.startswith("| DB-K1 |")][0].split("|")))   # sutun sayisi tablo ile ayni

    def test_runbook_dogrulama_cihazi_kaybi_proseduru(self):
        m = self.okut("runbook.md")
        self.assertIn("Verification device loss", m)
        bolum = m[m.index("Verification device loss"):]
        for ifade in ("totp-yenile", "parola", "liste", "15 minutes", "audit"):
            self.assertIn(ifade, bolum)


if __name__ == "__main__":
    unittest.main()
