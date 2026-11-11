import base64
import http.client
import json
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import depo as tdepo  # noqa: E402
from yonetim import depo, guvenlik, server  # noqa: E402
from test_tarama import temiz_belge  # noqa: E402

PAROLA = "cok-gizli-parola-123"


class GuvenlikTests(unittest.TestCase):
    def test_totp_rfc6238_vektorleri(self):
        k = base64.b32encode(b"12345678901234567890").decode()
        for t, beklenen in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
            self.assertEqual(guvenlik.totp_kod(k, t // 30), beklenen)

    def test_totp_pencere_ve_tekrar(self):
        g = guvenlik.totp_gizli()
        t = 1700000000
        s = t // 30
        self.assertEqual(guvenlik.totp_dogrula(g, guvenlik.totp_kod(g, s), 0, t), s)
        self.assertEqual(guvenlik.totp_dogrula(g, guvenlik.totp_kod(g, s - 1), 0, t), s - 1)
        self.assertIsNone(guvenlik.totp_dogrula(g, guvenlik.totp_kod(g, s - 2), 0, t))
        self.assertIsNone(guvenlik.totp_dogrula(g, guvenlik.totp_kod(g, s), s, t))  # ayni kod ikinci kez
        self.assertIsNone(guvenlik.totp_dogrula(g, "12345", 0, t))
        self.assertIsNone(guvenlik.totp_dogrula(g, "abcdef", 0, t))

    def test_parola_ozeti(self):
        h = guvenlik.parola_ozetle(PAROLA)
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn(PAROLA, h)
        self.assertNotEqual(h, guvenlik.parola_ozetle(PAROLA))  # tuz
        self.assertTrue(guvenlik.parola_dogrula(PAROLA, h))
        self.assertFalse(guvenlik.parola_dogrula(PAROLA + "x", h))
        self.assertFalse(guvenlik.parola_dogrula(PAROLA, "bozuk"))


class Taban(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.ydb, self.fdb, self.tdb = str(d / "y.sqlite"), str(d / "f.sqlite"), str(d / "t.sqlite")
        con = depo.baglan(self.ydb)
        self.gizli = depo.kullanici_ekle(con, "ali", PAROLA)
        con.close()
        f = sqlite3.connect(self.fdb)
        f.execute("CREATE TABLE contact(id INTEGER PRIMARY KEY, created_utc TEXT, name TEXT, company TEXT, email TEXT, db TEXT, message TEXT, ip_hash TEXT)")
        f.execute("INSERT INTO contact VALUES(1,'2026-11-10T10:00:00Z','Ada <b>X</b>','Ornek AS','ada@ornek.com','pg','<script>alert(1)</script>','h')")
        f.commit()
        f.close()
        t = tdepo.baglan(self.tdb)
        b = temiz_belge()
        b["kontroller"]["pg_tls_parola"]["satirlar"][0]["ssl"] = "off"
        self.firma = tdepo.firma_kaydet(t, "firma.com.tr", "Firma <i>AS</i>", "ayse@firma.com.tr", "tarama")
        tdepo.rapor_ekle(t, "musteri-kodu", "postgresql", "tr", b, self.firma["id"])
        tdepo.kullanim_ekle(t, tdepo.sirket_anahtari("ayse@firma.com.tr"))
        t.close()
        self.H = type("H", (server.H,), {"ydb": self.ydb, "form_db": self.fdb, "tarama_db": self.tdb, "guvenli_cerez": True,
                                         "form_portu": 1, "tarama_portu": 1})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.cerez = None

    def kod(self, kayma=0):
        return guvenlik.totp_kod(self.gizli, int(time.time() // 30) + kayma)

    def istek(self, metod, yol, veri=None, cerez=True, basliklar=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        h = dict(basliklar or {})
        if veri is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if cerez and self.cerez:
            h["Cookie"] = self.cerez
        c.request(metod, yol, body=urlencode(veri).encode() if veri is not None else None, headers=h)
        r = c.getresponse()
        return r, r.read().decode("utf-8", "replace")

    def giris(self, parola=PAROLA, kod=None, ad="ali"):
        r, _ = self.istek("POST", "/yonetim/giris", {"ad": ad, "parola": parola, "kod": kod or self.kod()}, cerez=False)
        sc = r.getheader("Set-Cookie")
        if r.status == 303 and sc:
            self.cerez = sc.split(";")[0]
        return r

    def csrf(self):
        _, g = self.istek("GET", "/yonetim/talepler")
        return re.search(r'name="csrf" value="([^"]+)"', g).group(1)


class GirisTests(Taban):
    def test_girissiz_her_sayfa_girise_gider(self):
        for yol in ("/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar/1", "/yonetim/talepler", "/yonetim/taramalar", "/yonetim/taramalar/1", "/yonetim/denetim", "/yonetim/sistem"):
            r, g = self.istek("GET", yol)
            self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/giris"), yol)
            self.assertNotIn("Ornek AS", g)
        r, _ = self.istek("POST", "/yonetim/taramalar/1/sil", {"csrf": "x"})
        self.assertEqual(r.status, 303)
        self.assertIsNotNone(tdepo.rapor_getir_id(tdepo.baglan(self.tdb), 1))

    def test_basarili_giris_ve_cerez_bayraklari(self):
        r = self.giris()
        self.assertEqual(r.status, 303)
        sc = r.getheader("Set-Cookie")
        for b in ("__Host-alig_oturum=", "HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(b, sc)
        r, g = self.istek("GET", "/yonetim/")
        self.assertEqual(r.status, 200)
        self.assertIn("Özet", g)
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        # oturum kodu veritabaninda duz saklanmaz
        satirlar = json.dumps(sqlite3.connect(self.ydb).execute("SELECT * FROM oturum").fetchall())
        self.assertNotIn(self.cerez.split("=", 1)[1], satirlar)

    def test_yanlis_parola_kod_ve_kullanici_ayni_yanit(self):
        yanitlar = [self.giris(parola="yanlis-parola-000"), self.giris(kod="000000"), self.giris(ad="yok")]
        self.assertEqual([r.status for r in yanitlar], [401, 401, 401])
        self.assertIsNone(self.cerez)

    def test_totp_kodu_ikinci_kez_kullanilamaz(self):
        k = self.kod()
        self.assertEqual(self.giris(kod=k).status, 303)
        self.cerez = None
        self.assertEqual(self.giris(kod=k).status, 401)

    def test_kilitleme(self):
        for _ in range(depo.DENEME_KULLANICI):
            self.assertEqual(self.giris(parola="yanlis-parola-000").status, 401)
        self.assertEqual(self.giris().status, 401)  # dogru bilgiyle de engelli
        olaylar = [o[0] for o in sqlite3.connect(self.ydb).execute("SELECT olay FROM denetim")]
        self.assertTrue(any("engellendi" in o for o in olaylar))

    def test_oturum_zaman_asimi_ve_cikis(self):
        self.giris()
        con = sqlite3.connect(self.ydb)
        con.execute("UPDATE oturum SET son_erisim_utc='2000-01-01T00:00:00Z'")
        con.commit()
        self.assertEqual(self.istek("GET", "/yonetim/")[0].status, 303)
        self.cerez = None
        self.giris(kod=self.kod(1))
        r, _ = self.istek("POST", "/yonetim/cikis", {"csrf": self.csrf()})
        self.assertIn("Max-Age=0", r.getheader("Set-Cookie"))
        self.assertEqual(self.istek("GET", "/yonetim/")[0].status, 303)


class PanelTests(Taban):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.giris().status, 303)

    def test_sayfalar_acilir_ve_kacislidir(self):
        for yol, icerik in (("/yonetim/", "Yeni talep"), ("/yonetim/talepler", "ada@ornek.com"), ("/yonetim/taramalar", "Yüksek 1"),
                            ("/yonetim/denetim", "Zincir sağlam"), ("/yonetim/denetim?kaynak=yonetim", "giris yapildi"), ("/yonetim/sistem", "Veritabanları")):
            r, g = self.istek("GET", yol)
            self.assertEqual(r.status, 200, yol)
            self.assertIn(icerik, g, yol)
            self.assertNotIn("<script>alert", g)
            self.assertNotIn("<b>X</b>", g)
        self.assertEqual(self.istek("GET", "/yonetim/yok")[0].status, 404)

    def test_firmalar_listesi_iki_kaynaktan_gelir(self):
        r, g = self.istek("GET", "/yonetim/firmalar")
        self.assertEqual(r.status, 200)
        self.assertIn("Firma &lt;i&gt;AS&lt;/i&gt;", g)   # taramadan, kacisli
        self.assertNotIn("<i>AS</i>", g)
        self.assertIn("Ornek AS", g)                        # iletisim talebinden
        self.assertIn("Pasif et", g)
        self.assertIn("Ornek AS", self.istek("GET", "/yonetim/firmalar?ara=ornek")[1])
        self.assertNotIn("Ornek AS", self.istek("GET", "/yonetim/firmalar?ara=firma.com")[1])
        self.assertEqual(len(tdepo.firma_listele(tdepo.baglan(self.tdb))), 2)
        self.istek("GET", "/yonetim/firmalar")              # ikinci goruntuleme kayit cogaltmaz
        self.assertEqual(len(tdepo.firma_listele(tdepo.baglan(self.tdb))), 2)

    def test_firmalar_csv(self):
        self.assertEqual(self.istek("GET", "/yonetim/firmalar.csv", cerez=False)[0].status, 303)   # giris gerekir
        self.istek("GET", "/yonetim/firmalar")   # iletisim taleplerinden firmalari esitler
        r, g = self.istek("GET", "/yonetim/firmalar.csv")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/csv"))
        self.assertIn("attachment", r.getheader("Content-Disposition"))
        satirlar = g.lstrip("\ufeff").strip().splitlines()
        self.assertEqual(satirlar[0].split(";")[:4], ["Firma", "Alan adı ya da adres", "E-posta", "Durum"])
        self.assertEqual(len(satirlar), 3)
        self.assertIn("Ornek AS", g)
        self.assertEqual(len(self.istek("GET", "/yonetim/firmalar.csv?ara=ornek")[1].strip().splitlines()), 2)
        con = depo.baglan(self.ydb)
        self.assertTrue(any("csv" in x[0] for x in con.execute("SELECT olay FROM denetim")))

    def test_csv_formul_enjeksiyonu_etkisiz(self):
        tc = tdepo.baglan(self.tdb)
        tdepo.firma_kaydet(tc, "kotu.com", "=HYPERLINK(\"http://x\")", "a@kotu.com", "tarama")
        tc.close()
        g = self.istek("GET", "/yonetim/firmalar.csv")[1]
        self.assertIn("'=HYPERLINK", g)
        self.assertNotIn(";=HYPERLINK", g)
        self.assertNotIn("\n=HYPERLINK", g)

    def test_talepler_csv(self):
        r, g = self.istek("GET", "/yonetim/talepler.csv")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/csv"))
        self.assertIn("Ornek AS", g)

    def test_dogrudan_baglanti_izni(self):
        self.istek("GET", "/yonetim/firmalar")
        tc = tdepo.baglan(self.tdb)
        fid = tdepo.firma_listele(tc)[0]["id"]
        tc.close()
        self.assertIn("Doğrudan bağlantı izni ver", self.istek("GET", "/yonetim/firmalar/%d" % fid)[1])
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/izin" % fid, {"izin": "1"})[0].status, 403)   # CSRF
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/izin" % fid, {"izin": "x", "csrf": self.csrf()})[0].status, 422)
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/izin" % fid, {"izin": "1", "csrf": self.csrf()})[0].status, 303)
        tc = tdepo.baglan(self.tdb)
        self.assertEqual(tdepo.firma_getir(tc, fid)["dogrudan_izin"], 1)
        self.assertTrue(any("dogrudan baglanti izni: verildi" in x[0] for x in tc.execute("SELECT olay FROM denetim")))
        tc.close()
        self.assertIn("Doğrudan bağlantı iznini kaldır", self.istek("GET", "/yonetim/firmalar/%d" % fid)[1])
        self.istek("POST", "/yonetim/firmalar/%d/izin" % fid, {"izin": "0", "csrf": self.csrf()})
        tc = tdepo.baglan(self.tdb)
        self.assertEqual(tdepo.firma_getir(tc, fid)["dogrudan_izin"], 0)
        tc.close()

    def test_firma_detayi(self):
        r, g = self.istek("GET", "/yonetim/firmalar/%d" % self.firma["id"])
        self.assertEqual(r.status, 200)
        for parca in ("ayse@firma.com.tr", "Kalan ücretsiz tarama", "1 / 2", "/yonetim/taramalar/1", "Tarama hakkını sıfırla", "Kalıcı olarak sil"):
            self.assertIn(parca, g)
        self.assertEqual(self.istek("GET", "/yonetim/firmalar/999")[0].status, 404)

    def test_firma_pasif_aktif_dugmeleri(self):
        fid = self.firma["id"]
        t = tdepo.baglan(self.tdb)
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/durum" % fid, {"durum": "pasif", "donus": "liste", "csrf": self.csrf()})
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/firmalar"))
        self.assertEqual(tdepo.firma_getir(t, fid)["durum"], "pasif")
        self.assertIn("Aktif et", self.istek("GET", "/yonetim/firmalar?durum=pasif")[1])
        self.assertNotIn("Firma &lt;i&gt;", self.istek("GET", "/yonetim/firmalar?durum=aktif")[1])
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/durum" % fid, {"durum": "aktif", "csrf": self.csrf()})
        self.assertEqual(r.getheader("Location"), "/yonetim/firmalar/%d" % fid)
        self.assertEqual(tdepo.firma_getir(t, fid)["durum"], "aktif")
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/durum" % fid, {"durum": "silindi", "csrf": self.csrf()})[0].status, 422)
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/durum" % fid, {"durum": "pasif"})[0].status, 403)  # CSRF
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/999/durum", {"durum": "pasif", "csrf": self.csrf()})[0].status, 404)
        olaylar = [(a, o) for a, o in t.execute("SELECT aktor, olay FROM denetim")]
        self.assertIn(("yonetici:ali", "firma #%d durumu: pasif" % fid), olaylar)
        self.assertIsNone(tdepo.denetim_dogrula(t))
        self.assertIsNone(depo.denetim_dogrula(depo.baglan(self.ydb)))

    def test_firma_not_sinir_ve_silme(self):
        fid = self.firma["id"]
        t = tdepo.baglan(self.tdb)
        self.istek("POST", "/yonetim/firmalar/%d/not" % fid, {"aciklama": "Sozlesme <b>gorusuluyor</b>", "csrf": self.csrf()})
        self.assertEqual(tdepo.firma_getir(t, fid)["aciklama"], "Sozlesme <b>gorusuluyor</b>")
        self.assertNotIn("<b>gorusuluyor</b>", self.istek("GET", "/yonetim/firmalar/%d" % fid)[1])
        self.istek("POST", "/yonetim/firmalar/%d/sinir" % fid, {"csrf": self.csrf()})
        self.assertIn("2 / 2", self.istek("GET", "/yonetim/firmalar/%d" % fid)[1])
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/sil" % fid, {"csrf": self.csrf()})[0].status, 422)  # onay kutusu yok
        self.assertIsNotNone(tdepo.firma_getir(t, fid))
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/sil" % fid, {"emin": "evet", "csrf": self.csrf()})
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/firmalar"))
        self.assertIsNone(tdepo.firma_getir(t, fid))
        self.assertEqual(tdepo.rapor_listele(t), [])
        self.assertEqual(sqlite3.connect(self.fdb).execute("SELECT count(*) FROM contact").fetchone()[0], 1)  # talepler silinmez

    def test_taramalar_firma_adini_gosterir(self):
        self.assertIn("/yonetim/firmalar/%d" % self.firma["id"], self.istek("GET", "/yonetim/taramalar")[1])

    def test_csrf_ve_origin(self):
        self.assertEqual(self.istek("POST", "/yonetim/talepler/1/durum", {"durum": "kapandi"})[0].status, 403)
        self.assertEqual(self.istek("POST", "/yonetim/talepler/1/durum", {"durum": "kapandi", "csrf": "yanlis"})[0].status, 403)
        r, _ = self.istek("POST", "/yonetim/talepler/1/durum", {"durum": "kapandi", "csrf": self.csrf()}, basliklar={"Origin": "https://kotu.example"})
        self.assertEqual(r.status, 403)
        self.assertEqual(depo.talep_durumlari(depo.baglan(self.ydb)), {})

    def test_talep_durumu_guncellenir_ve_kaydedilir(self):
        r, _ = self.istek("POST", "/yonetim/talepler/1/durum", {"durum": "gorusuluyor", "aciklama": "arandi", "csrf": self.csrf()})
        self.assertEqual(r.status, 303)
        con = depo.baglan(self.ydb)
        self.assertEqual(depo.talep_durumlari(con)[1]["durum"], "gorusuluyor")
        self.assertEqual(self.istek("POST", "/yonetim/talepler/1/durum", {"durum": "uydurma", "csrf": self.csrf()})[0].status, 422)
        self.assertIn("Görüşülüyor", self.istek("GET", "/yonetim/talepler?durum=gorusuluyor")[1])
        self.assertNotIn("ada@ornek.com", self.istek("GET", "/yonetim/talepler?durum=kapandi")[1])
        self.assertIsNone(depo.denetim_dogrula(con))

    def test_rapor_goruntuleme_iki_zincire_de_yazilir_ve_silinir(self):
        r, g = self.istek("GET", "/yonetim/taramalar/1")
        self.assertEqual(r.status, 200)
        self.assertIn("TLS kapalı", g)
        self.assertNotIn("/rapor/", g)  # musteri silme formu ve baglantisi yok
        t = tdepo.baglan(self.tdb)
        self.assertTrue(any(a == "yonetici:ali" and "goruntulendi #1" in o for a, o in t.execute("SELECT aktor, olay FROM denetim")))
        self.assertTrue(any("goruntulendi #1" in o[0] for o in sqlite3.connect(self.ydb).execute("SELECT olay FROM denetim")))
        self.assertEqual(self.istek("POST", "/yonetim/taramalar/1/sil", {"csrf": self.csrf()})[0].status, 303)
        self.assertIsNone(tdepo.rapor_getir_id(t, 1))
        self.assertIsNone(tdepo.denetim_dogrula(t))
        self.assertEqual(self.istek("GET", "/yonetim/taramalar/1")[0].status, 404)

    def test_kirik_zincir_ozet_ve_denetimde_gorunur(self):
        t = tdepo.baglan(self.tdb)
        tdepo.denetim_ekle(t, "a", "bir")
        tdepo.denetim_ekle(t, "a", "iki")
        t.execute("UPDATE denetim SET olay='degisti' WHERE seq=1")
        t.commit()
        self.assertIn("KIRIK: kayıt #1", self.istek("GET", "/yonetim/")[1])
        self.assertIn("KIRIK: kayıt #1", self.istek("GET", "/yonetim/denetim")[1])

    def test_statik_dosya_yalniz_assets_ve_bilinen_tur(self):
        self.assertIn(self.istek("GET", "/assets/yonetim.css", cerez=False)[0].status, (200, 404))  # paket disinda 404 olabilir
        for yol in ("/assets/../../yonetim/depo.py", "/assets/%2e%2e/%2e%2e/form/server.py", "/assets/alig-toplayici.py", "/assets/../VERSION"):
            self.assertEqual(self.istek("GET", yol, cerez=False)[0].status, 404, yol)

    def test_buyuk_govde_ve_tur(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/yonetim/giris", body=b"a=" + b"x" * 9000, headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(c.getresponse().status, 400)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/yonetim/giris", body=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(c.getresponse().status, 400)


class CliTests(unittest.TestCase):
    def test_parola_degisince_oturumlar_kapanir(self):
        con = depo.baglan(str(Path(tempfile.mkdtemp()) / "y.sqlite"))
        g = depo.kullanici_ekle(con, "ali", PAROLA)
        kod, _ = depo.giris(con, "ali", PAROLA, guvenlik.totp_kod(g, int(time.time() // 30)), "1.1.1.1")
        self.assertIsNotNone(depo.oturum(con, kod))
        depo.kullanici_parola(con, "ali", "yeni-parola-456789")
        self.assertIsNone(depo.oturum(con, kod))
        self.assertNotIn(PAROLA, json.dumps(con.execute("SELECT * FROM kullanici").fetchall()))
        self.assertIsNone(depo.denetim_dogrula(con))


if __name__ == "__main__":
    unittest.main()
