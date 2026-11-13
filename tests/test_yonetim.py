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
                            ("/yonetim/denetim", "Zincir sağlam"), ("/yonetim/denetim?kaynak=yonetim", "giris yapildi"), ("/yonetim/denetim?kaynak=yonetim", "ip_ozeti"), ("/yonetim/sistem", "Veritabanları"), ("/yonetim/sistem", "Saklama süreleri")):
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

    def test_silinen_firma_talepten_geri_gelmez(self):
        self.istek("GET", "/yonetim/firmalar")  # talepten firma kaydi olusur
        t = tdepo.baglan(self.tdb)
        f = next(x for x in tdepo.firma_listele(t) if x["anahtar"] == "ornek.com")
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/sil" % f["id"], {"emin": "evet", "csrf": self.csrf()})
        self.assertEqual(r.status, 303)
        for yol in ("/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar.csv"):
            self.istek("GET", yol)
        self.assertNotIn("ornek.com", [x["anahtar"] for x in tdepo.firma_listele(t)])
        self.assertNotIn("ornek.com", json.dumps(t.execute("SELECT * FROM firma_silinen").fetchall()))  # iz duz adres tutmaz
        fc = sqlite3.connect(self.fdb)  # silmeden SONRA gelen yeni talep yeni kayit acar
        fc.execute("INSERT INTO contact VALUES(2,'2999-01-01T00:00:00Z','Ada','Ornek AS','ada@ornek.com','pg','yeniden','h')")
        fc.commit()
        fc.close()
        self.istek("GET", "/yonetim/firmalar")
        self.assertIn("ornek.com", [x["anahtar"] for x in tdepo.firma_listele(t)])

    def test_eposta_dogrulama_durumu_ve_yukleyen_gorunur(self):
        g = self.istek("GET", "/yonetim/firmalar")[1]
        self.assertIn("doğrulanmamış", g)
        t = tdepo.baglan(self.tdb)
        tdepo.firma_eposta_dogrula(t, self.firma["id"], "ayse@firma.com.tr")
        tdepo.rapor_ekle(t, "bekleyen", "postgresql", "tr", temiz_belge(), self.firma["id"], "mehmet@firma.com.tr", dogrulandi=False)
        t.close()
        self.assertIn("doğrulandı", self.istek("GET", "/yonetim/firmalar/%d" % self.firma["id"])[1])
        g = self.istek("GET", "/yonetim/taramalar")[1]
        self.assertIn("mehmet@firma.com.tr", g)
        self.assertIn("doğrulama bekliyor", g)

    def test_talepler_sayfali_csv_eksiksiz(self):
        f = sqlite3.connect(self.fdb)
        f.executemany("INSERT INTO contact VALUES(?,?,?,?,?,?,?,?)",
                      [(100 + i, "2026-11-11T10:%02d:%02dZ" % (i // 60, i % 60), "Kisi %d" % i, "Sirket", "k%d@cok.com" % i, "pg", "m", "h") for i in range(150)])
        f.commit()
        f.close()
        g = self.istek("GET", "/yonetim/talepler")[1]
        self.assertIn("151 talep.", g)
        self.assertEqual(g.count("action=\"/yonetim/talepler/"), 100)
        self.assertIn("/yonetim/talepler?sayfa=2", g)
        g2 = self.istek("GET", "/yonetim/talepler?sayfa=2")[1]
        self.assertEqual(g2.count("action=\"/yonetim/talepler/"), 51)
        csv_ = self.istek("GET", "/yonetim/talepler.csv")[1]
        self.assertEqual(len([x for x in csv_.splitlines() if x.strip()]), 152)   # baslik + 151 satir, sessiz kesme yok

    def test_zehirli_rapor_paneli_dusurmez(self):
        t = tdepo.baglan(self.tdb)
        b = temiz_belge()
        b["kontroller"]["pg_surum"] = {"durum": "ok", "satirlar": [{"surum_num": "abc"}]}  # yukleme denetimini atlayan bozuk kayit
        tdepo.rapor_ekle(t, "zehir", "postgresql", "tr", b, self.firma["id"])
        t.close()
        for yol in ("/yonetim/", "/yonetim/taramalar", "/yonetim/taramalar/2", "/yonetim/firmalar/%d" % self.firma["id"]):
            self.assertEqual(self.istek("GET", yol)[0].status, 200, yol)

    def test_beklenmeyen_kural_hatasi_paneli_dusurmez(self):
        from unittest import mock
        with mock.patch.object(server.kurallar, "incele", side_effect=RuntimeError("beklenmeyen")):
            for yol in ("/yonetim/", "/yonetim/taramalar", "/yonetim/firmalar/%d" % self.firma["id"], "/yonetim/taramalar/1"):
                self.assertEqual(self.istek("GET", yol)[0].status, 200, yol)
            self.assertIn("Bu raporu kalıcı olarak sil", self.istek("GET", "/yonetim/taramalar/1")[1])
            self.assertIn("değerlendirilemedi", self.istek("GET", "/yonetim/taramalar")[1])
        with mock.patch.object(server.puan, "hesapla", side_effect=RuntimeError("beklenmeyen")):
            for yol in ("/yonetim/", "/yonetim/taramalar", "/yonetim/firmalar/%d" % self.firma["id"]):
                self.assertEqual(self.istek("GET", yol)[0].status, 200, yol)

    def test_puan_kapsamla_birlikte_gorunur(self):
        from tarama import kurallar, puan
        t = tdepo.baglan(self.tdb)
        p = puan.hesapla(kurallar.incele(tdepo.rapor_getir_id(t, 1)["belge"]))
        bos = temiz_belge()
        bos["kontroller"] = {cid: {"durum": "hata", "neden": "yetki"} for cid in bos["kontroller"]}
        del bos["superuser"]
        tdepo.rapor_ekle(t, "kanitsiz", "postgresql", "tr", bos, self.firma["id"])
        t.close()
        beklenen = "%d/100 (kapsam %%%d)" % (p.genel, p.kapsam)
        for yol in ("/yonetim/taramalar", "/yonetim/firmalar/%d" % self.firma["id"]):
            g = self.istek("GET", yol)[1]
            self.assertIn("<th scope=\"col\">Puan</th>", g, yol)
            self.assertIn(beklenen, g, yol)
            self.assertIn("hesaplanamadı (kapsam %0)", g, yol)   # kanit yoksa puan yazilmaz
        g = self.istek("GET", "/yonetim/taramalar/1")[1]
        self.assertIn("Sağlık puanı", g)
        self.assertIn("%d/100" % p.genel, g)

    def test_rapor_onceki_taramayla_karsilastirilir(self):
        import test_gecmis
        t = tdepo.baglan(self.tdb)
        once = test_gecmis.belge(zaman="2026-11-01T00:00:00Z")
        once["kontroller"]["pg_tls_parola"]["satirlar"][0]["ssl"] = "off"
        tdepo.rapor_ekle(t, "k1", "postgresql", "tr", once, self.firma["id"])
        tdepo.rapor_ekle(t, "k2", "postgresql", "tr", test_gecmis.belge(zaman="2026-11-05T00:00:00Z"), self.firma["id"])
        rid = t.execute("SELECT max(id) FROM rapor").fetchone()[0]
        t.close()
        g = self.istek("GET", "/yonetim/taramalar/%d" % rid)[1]
        self.assertIn("Önceki taramayla karşılaştırma", g)
        self.assertIn("Çözüldü", g)
        t = tdepo.baglan(self.tdb)
        self.assertTrue(any("rapor goruntulendi #%d (karsilastirma #%d)" % (rid, rid - 1) == o for (o,) in t.execute("SELECT olay FROM denetim")))
        self.assertNotIn("Önceki taramayla karşılaştırma", self.istek("GET", "/yonetim/taramalar/1")[1])   # kimliksiz eski rapor

    def test_yonetim_raporu_iki_gorunum_sunar(self):
        g = self.istek("GET", "/yonetim/taramalar/1")[1]
        self.assertIn("Denetim sonuçları", g)                      # varsayilan: teknik
        self.assertIn('href="?gorunum=yonetici"', g)
        o = self.istek("GET", "/yonetim/taramalar/1?gorunum=yonetici")[1]
        self.assertIn("Genel durum", o)
        self.assertNotIn("Denetim sonuçları", o)
        self.assertNotIn("/sil\"><button class=\"btn btn-ghost\" type=\"submit\">Raporu şimdi sil", o)   # musteri silme formu yok
        self.assertEqual(self.istek("GET", "/yonetim/taramalar/1?gorunum=x")[1], g)

    def test_sistem_sayfasi_puan_katsayilarini_gosterir(self):
        from tarama import puan
        g = self.istek("GET", "/yonetim/sistem")[1]
        self.assertIn("Sağlık puanı katsayıları", g)
        self.assertIn("kritik 10", g)
        self.assertIn("Varsayılan değerler", g)
        eski = puan.ETKIN
        self.addCleanup(setattr, puan, "ETKIN", eski)
        puan.ETKIN = puan.katsayi_dogrula({"agirlik": {"kritik": 12}})
        g = self.istek("GET", "/yonetim/sistem")[1]
        self.assertIn("kritik 12", g)
        self.assertIn("Bu kurulum için ayarlandı", g)

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

    def test_panel_kendi_csp_basligini_gonderir(self):
        r, g = self.istek("GET", "/yonetim/")
        csp = r.getheader("Content-Security-Policy") or ""
        for parca in ("default-src 'none'", "script-src 'none'", "style-src 'self'", "form-action 'self'", "frame-ancestors 'none'"):
            self.assertIn(parca, csp)
        self.assertNotIn("<script", g)
        self.assertNotIn(" style=", g)   # satir ici stil yok: CSP'yi gevsetmeye gerek kalmaz

    def test_statik_dosya_yalniz_assets_ve_bilinen_tur(self):
        self.assertIn(self.istek("GET", "/assets/yonetim.css", cerez=False)[0].status, (200, 404))  # paket disinda 404 olabilir
        for yol in ("/assets/../../yonetim/depo.py", "/assets/%2e%2e/%2e%2e/form/server.py", "/assets/alig-toplayici.py", "/assets/../VERSION",
                    "/assets/../themes/c/style.css", "/assets/../../site/themes/b/style.css"):  # izinli uzanti ama assets disi
            self.assertEqual(self.istek("GET", yol, cerez=False)[0].status, 404, yol)

    def test_buyuk_govde_ve_tur(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/yonetim/giris", body=b"a=" + b"x" * 9000, headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(c.getresponse().status, 400)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/yonetim/giris", body=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(c.getresponse().status, 400)


class YeniIpTests(unittest.TestCase):
    def kur(self):
        con = depo.baglan(str(Path(tempfile.mkdtemp()) / "y.sqlite"))
        return con, depo.kullanici_ekle(con, "ali", PAROLA)

    def gir(self, con, gizli, ip, adim, parola=PAROLA):
        t = time.time() + 30 * adim * 3  # her giris ayri TOTP penceresi (kod tek kullanimlik)
        return depo.giris(con, "ali", parola, guvenlik.totp_kod(gizli, int(t // 30)), ip, simdi=t)

    def son(self, con):
        return con.execute("SELECT olay, alanlar FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()

    def test_yeni_ip_uyari_ilk_giris_ve_bilinen_ip_degil(self):
        con, g = self.kur()
        self.assertIsNotNone(self.gir(con, g, "198.51.100.1", 1)[0])
        olay, al = self.son(con)
        self.assertEqual(olay, "giris yapildi")  # ilk giris uyari degil
        self.assertEqual(json.loads(al)["yeni_ip"], 0)
        self.assertIsNotNone(self.gir(con, g, "198.51.100.1", 2)[0])
        self.assertEqual(self.son(con)[0], "giris yapildi")
        self.assertIsNotNone(self.gir(con, g, "203.0.113.9", 3)[0])
        olay, al = self.son(con)
        self.assertEqual(olay, "yeni IP'den giris yapildi")
        a = json.loads(al)
        self.assertEqual((a["yeni_ip"], a["sonuc"], a["kullanici"]), (1, "basarili", "ali"))
        self.assertNotIn("203.0.113.9", al + olay)  # duz adres denetime yazilmaz
        self.assertNotIn("203.0.113.9", json.dumps(con.execute("SELECT * FROM giris_ip").fetchall()))
        self.assertIsNotNone(self.gir(con, g, "203.0.113.9", 4)[0])
        self.assertEqual(self.son(con)[0], "giris yapildi")  # artik bilinen IP
        self.assertIsNone(depo.denetim_dogrula(con))

    def test_basarisiz_giris_yapisal_kayit_ve_kullanici_silinince_ip_silinir(self):
        con, g = self.kur()
        self.assertIsNone(self.gir(con, g, "198.51.100.1", 1, parola="yanlis-parola-000")[0])
        a = json.loads(self.son(con)[1])
        self.assertEqual((a["sonuc"], a["neden"]), ("basarisiz", "hatali"))
        self.assertNotIn("198.51.100.1", self.son(con)[1])
        self.gir(con, g, "198.51.100.1", 2)
        self.assertEqual(con.execute("SELECT count(*) FROM giris_ip").fetchone()[0], 1)
        depo.kullanici_sil(con, "ali")
        self.assertEqual(con.execute("SELECT count(*) FROM giris_ip").fetchone()[0], 0)


class IslemTests(Taban):
    """Is eylemi ve denetim kaydi birlikte: denetim yazilamazsa eylem de geri alinir."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.giris().status, 303)

    def bozuk_denetim(self, modul):
        from unittest import mock
        return mock.patch.object(modul, "denetim_ekle", side_effect=RuntimeError("denetim yazilamadi"))

    def test_firma_silme_denetimsiz_kalmaz(self):
        fid = self.firma["id"]
        csrf = self.csrf()
        with self.bozuk_denetim(tdepo):
            try:
                self.istek("POST", "/yonetim/firmalar/%d/sil" % fid, {"emin": "evet", "csrf": csrf})
            except Exception:  # noqa: BLE001 - sunucu istegi yarida keser
                pass
        self.assertIsNotNone(tdepo.firma_getir(tdepo.baglan(self.tdb), fid))

    def test_talep_durumu_denetimsiz_kalmaz(self):
        con = depo.baglan(self.ydb)
        with self.bozuk_denetim(depo):
            with self.assertRaises(RuntimeError):
                depo.talep_durum_yaz(con, 1, "kapandi", "", "ali")
        self.assertEqual(depo.talep_durumlari(con), {})

    def test_kullanici_ekleme_denetimsiz_kalmaz(self):
        con = depo.baglan(self.ydb)
        with self.bozuk_denetim(depo):
            with self.assertRaises(RuntimeError):
                depo.kullanici_ekle(con, "veli", PAROLA)
        self.assertIsNone(con.execute("SELECT 1 FROM kullanici WHERE ad='veli'").fetchone())

    def test_ayni_dogrulama_kodu_es_zamanli_iki_giriste_bir_kez_gecer(self):
        import threading as th
        from unittest import mock
        kod = self.kod(1)   # setUp girisi su anki kodu kullandi; bir sonraki pencerenin kodu
        b, sonuc = th.Barrier(2), []
        gercek = guvenlik.totp_dogrula

        def yavas(*a, **k):   # sayaci okuma ile yazma arasindaki pencereyi genislet: yaris kilitsiz kodda kesin gorunur
            time.sleep(0.3)
            return gercek(*a, **k)

        def gir():
            c = depo.baglan(self.ydb)
            b.wait()
            sonuc.append(depo.giris(c, "ali", PAROLA, kod, "198.51.100.%d" % len(sonuc))[0] is not None)
            c.close()
        with mock.patch.object(guvenlik, "totp_dogrula", side_effect=yavas):
            ts = [th.Thread(target=gir) for _ in range(2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(sorted(sonuc), [False, True])

    def test_firma_esitleme_yalniz_yeni_talepleri_isler(self):
        from unittest import mock
        f = sqlite3.connect(self.fdb)
        f.executemany("INSERT INTO contact VALUES(?,?,?,?,?,?,?,?)",
                      [(20 + i, "2026-11-11T10:00:%02dZ" % i, "K", "S%d" % i, "k@s%d.com" % i, "pg", "m", "h") for i in range(5)])
        f.commit()
        f.close()
        self.istek("GET", "/yonetim/firmalar")
        gercek = tdepo.firma_kaydet
        with mock.patch.object(server.tdepo, "firma_kaydet", side_effect=gercek) as say:
            self.istek("GET", "/yonetim/firmalar")
            self.assertLessEqual(say.call_count, 1)   # yalniz son saniyedeki talep yeniden bakilir
        f = sqlite3.connect(self.fdb)
        f.execute("INSERT INTO contact VALUES(97,'2999-01-01T00:00:00Z','Yeni','Yeni AS','x@yeni.com','pg','m','h')")
        f.commit()
        f.close()
        self.istek("GET", "/yonetim/firmalar")
        self.assertIn("yeni.com", [x["anahtar"] for x in tdepo.firma_listele(tdepo.baglan(self.tdb))])

    def test_firma_silinirken_talepleri_de_silinebilir(self):
        self.istek("GET", "/yonetim/firmalar")
        t = tdepo.baglan(self.tdb)
        f = next(x for x in tdepo.firma_listele(t) if x["anahtar"] == "ornek.com")
        con = depo.baglan(self.ydb)
        depo.talep_durum_yaz(con, 1, "gorusuluyor", "not", "ali")
        self.assertIn("İletişim taleplerini de sil", self.istek("GET", "/yonetim/firmalar/%d" % f["id"])[1])
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/sil" % f["id"], {"emin": "evet", "talepler": "evet", "csrf": self.csrf()})
        self.assertEqual(r.status, 303)
        self.assertEqual(sqlite3.connect(self.fdb).execute("SELECT count(*) FROM contact WHERE email='ada@ornek.com'").fetchone()[0], 0)
        self.assertEqual(depo.talep_durumlari(depo.baglan(self.ydb)), {})
        olaylar = [x[0] for x in depo.baglan(self.ydb).execute("SELECT olay FROM denetim")]
        self.assertTrue(any("1 iletisim talebi silindi" in o for o in olaylar))
        self.assertFalse(any("ada@ornek.com" in o for o in olaylar))

    def test_talepleri_silmeden_firma_silme_talebe_dokunmaz(self):
        self.istek("GET", "/yonetim/firmalar")
        t = tdepo.baglan(self.tdb)
        f = next(x for x in tdepo.firma_listele(t) if x["anahtar"] == "ornek.com")
        self.istek("POST", "/yonetim/firmalar/%d/sil" % f["id"], {"emin": "evet", "csrf": self.csrf()})
        self.assertEqual(sqlite3.connect(self.fdb).execute("SELECT count(*) FROM contact").fetchone()[0], 1)


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
