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
from datetime import datetime, timedelta, timezone
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
        self.assertIsNone(guvenlik.totp_dogrula(g, guvenlik.totp_kod(g, s), s, t))  # the same code a second time
        self.assertIsNone(guvenlik.totp_dogrula(g, "12345", 0, t))
        self.assertIsNone(guvenlik.totp_dogrula(g, "abcdef", 0, t))

    def test_parola_ozeti(self):
        h = guvenlik.parola_ozetle(PAROLA)
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn(PAROLA, h)
        self.assertNotEqual(h, guvenlik.parola_ozetle(PAROLA))  # salt
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
        # the session code is not stored in plain text in the database
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
        self.assertEqual(self.giris().status, 401)  # blocked even with the correct credentials
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
        for yol, icerik in (("/yonetim/", "Açık iletişim talebi"), ("/yonetim/talepler", "ada@ornek.com"), ("/yonetim/taramalar", "Yüksek 1"),
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
        self.assertIn("Firma &lt;i&gt;AS&lt;/i&gt;", g)   # from the scan, escaped
        self.assertNotIn("<i>AS</i>", g)
        self.assertIn("Ornek AS", g)                        # from the contact request
        self.assertIn("Pasif et", g)
        self.assertIn("Ornek AS", self.istek("GET", "/yonetim/firmalar?ara=ornek")[1])
        self.assertNotIn("Ornek AS", self.istek("GET", "/yonetim/firmalar?ara=firma.com")[1])
        self.assertEqual(len(tdepo.firma_listele(tdepo.baglan(self.tdb))), 2)
        self.istek("GET", "/yonetim/firmalar")              # a second view does not duplicate records
        self.assertEqual(len(tdepo.firma_listele(tdepo.baglan(self.tdb))), 2)

    def test_firmalar_csv(self):
        self.assertEqual(self.istek("GET", "/yonetim/firmalar.csv", cerez=False)[0].status, 303)   # login required
        self.istek("GET", "/yonetim/firmalar")   # syncs companies from contact requests
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
        self.istek("GET", "/yonetim/firmalar")  # a company record is created from the request
        t = tdepo.baglan(self.tdb)
        f = next(x for x in tdepo.firma_listele(t) if x["anahtar"] == "ornek.com")
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/sil" % f["id"], {"emin": "evet", "csrf": self.csrf()})
        self.assertEqual(r.status, 303)
        for yol in ("/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar.csv"):
            self.istek("GET", yol)
        self.assertNotIn("ornek.com", [x["anahtar"] for x in tdepo.firma_listele(t)])
        self.assertNotIn("ornek.com", json.dumps(t.execute("SELECT * FROM firma_silinen").fetchall()))  # the trace does not keep a plain address
        fc = sqlite3.connect(self.fdb)  # a new request coming AFTER deletion opens a new record
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
        self.assertEqual(len([x for x in csv_.splitlines() if x.strip()]), 152)   # header + 151 rows, no silent truncation

    def test_zehirli_rapor_paneli_dusurmez(self):
        t = tdepo.baglan(self.tdb)
        b = temiz_belge()
        b["kontroller"]["pg_surum"] = {"durum": "ok", "satirlar": [{"surum_num": "abc"}]}  # a corrupt record that bypasses the load check
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
            self.assertIn("hesaplanamadı (kapsam %0)", g, yol)   # no score is written without evidence
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
        self.assertNotIn("Önceki taramayla karşılaştırma", self.istek("GET", "/yonetim/taramalar/1")[1])   # an old report without identity

    def test_yonetim_raporu_iki_gorunum_sunar(self):
        g = self.istek("GET", "/yonetim/taramalar/1")[1]
        self.assertIn("Denetim sonuçları", g)                      # default: technical
        self.assertIn('href="?gorunum=yonetici"', g)
        o = self.istek("GET", "/yonetim/taramalar/1?gorunum=yonetici")[1]
        self.assertIn("Genel durum", o)
        self.assertNotIn("Denetim sonuçları", o)
        self.assertNotIn("/sil\"><button class=\"btn btn-ghost\" type=\"submit\">Raporu şimdi sil", o)   # no customer deletion form
        self.assertEqual(self.istek("GET", "/yonetim/taramalar/1?gorunum=x")[1], g)

    def portal_talepleri_ekle(self):
        t = tdepo.baglan(self.tdb)
        tdepo.firma_kaydet(t, "ornek.com.tr", "Ornek AS", "a@ornek.com.tr", "portal")
        fid = t.execute("SELECT id FROM firma WHERE anahtar='ornek.com.tr'").fetchone()[0]
        z = tdepo.simdi()
        for tur, konu, mesaj in (("denetim", "Yillik <b>denetim</b>", "13 kume"), ("silme", "", "")):
            t.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, konu, mesaj, olusturma_utc, guncelleme_utc) VALUES(?,?,?,?,?,?,?)", (fid, 1, tur, konu, mesaj, z, z))
        t.commit()
        ids = [r[0] for r in t.execute("SELECT id FROM portal_talep ORDER BY id")]
        t.close()
        return fid, ids

    def test_portal_talepleri_listelenir_ve_durum_degisir(self):
        fid, (denetim, silme) = self.portal_talepleri_ekle()
        g = self.istek("GET", "/yonetim/portal-talepleri")
        self.assertEqual(g[0].status, 200)
        self.assertIn("Portal talepleri", g[1])
        self.assertIn("Denetim talebi", g[1])
        self.assertIn("Hesap ve veri silme talebi", g[1])
        self.assertIn("Yillik &lt;b&gt;denetim&lt;/b&gt;", g[1])            # escaped
        self.assertNotIn("<b>denetim</b>", g[1])
        self.assertIn('href="/yonetim/firmalar/%d"' % fid, g[1])             # deletion is from the company page
        r, _ = self.istek("POST", "/yonetim/portal-talepleri/%d/durum" % denetim, {"durum": "inceleniyor", "csrf": self.csrf()})
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/portal-talepleri"))
        t = tdepo.baglan(self.tdb)
        self.assertEqual(t.execute("SELECT durum FROM portal_talep WHERE id=?", (denetim,)).fetchone()[0], "inceleniyor")
        self.assertTrue(any("portal talebi #%d durumu: inceleniyor" % denetim == o for (o,) in t.execute("SELECT olay FROM denetim")))
        self.assertIsNone(tdepo.denetim_dogrula(t))
        self.assertIn("Yillik", self.istek("GET", "/yonetim/portal-talepleri?durum=inceleniyor")[1])
        self.assertNotIn("Yillik", self.istek("GET", "/yonetim/portal-talepleri?durum=yeni")[1])

    def test_portal_talebi_durum_korumalari(self):
        _, (denetim, silme) = self.portal_talepleri_ekle()
        yol = "/yonetim/portal-talepleri/%d/durum" % denetim
        self.assertEqual(self.istek("POST", yol, {"durum": "tamamlandi"})[0].status, 403)                         # CSRF
        self.assertEqual(self.istek("POST", yol, {"durum": "silindi", "csrf": self.csrf()})[0].status, 422)
        self.assertEqual(self.istek("POST", "/yonetim/portal-talepleri/99999/durum", {"durum": "yeni", "csrf": self.csrf()})[0].status, 404)
        self.assertEqual(self.istek("POST", yol, {"durum": "tamamlandi"}, cerez=False)[0].status, 303)            # no session
        t = tdepo.baglan(self.tdb)
        self.assertEqual(t.execute("SELECT durum FROM portal_talep WHERE id=?", (denetim,)).fetchone()[0], "yeni")
        # a closed deletion request cannot be reopened while another open deletion request exists for the same company
        self.istek("POST", "/yonetim/portal-talepleri/%d/durum" % silme, {"durum": "tamamlandi", "csrf": self.csrf()})
        t.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) SELECT firma_id, 1, 'silme', olusturma_utc, olusturma_utc FROM portal_talep WHERE id=?", (silme,))
        t.commit()
        self.assertEqual(self.istek("POST", "/yonetim/portal-talepleri/%d/durum" % silme, {"durum": "yeni", "csrf": self.csrf()})[0].status, 409)
        self.assertEqual(t.execute("SELECT durum FROM portal_talep WHERE id=?", (silme,)).fetchone()[0], "tamamlandi")

    def test_portal_talepleri_menude_ve_giris_ister(self):
        self.assertIn('href="/yonetim/portal-talepleri"', self.istek("GET", "/yonetim/")[1])
        r, _ = self.istek("GET", "/yonetim/portal-talepleri", cerez=False)
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/giris"))

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
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/%d/sil" % fid, {"csrf": self.csrf()})[0].status, 422)  # no confirmation checkbox
        self.assertIsNotNone(tdepo.firma_getir(t, fid))
        r, _ = self.istek("POST", "/yonetim/firmalar/%d/sil" % fid, {"emin": "evet", "csrf": self.csrf()})
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/firmalar"))
        self.assertIsNone(tdepo.firma_getir(t, fid))
        self.assertEqual(tdepo.rapor_listele(t), [])
        self.assertEqual(sqlite3.connect(self.fdb).execute("SELECT count(*) FROM contact").fetchone()[0], 1)  # requests are not deleted

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
        self.assertNotIn("/rapor/", g)  # no customer deletion form or link
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
        self.assertNotIn(" style=", g)   # no inline style: no need to loosen the CSP

    def test_statik_dosya_yalniz_assets_ve_bilinen_tur(self):
        self.assertIn(self.istek("GET", "/assets/yonetim.css", cerez=False)[0].status, (200, 404))  # may be 404 outside the package
        for yol in ("/assets/../../yonetim/depo.py", "/assets/%2e%2e/%2e%2e/form/server.py", "/assets/alig-toplayici.py", "/assets/../VERSION",
                    "/assets/../themes/c/style.css", "/assets/../../site/themes/b/style.css"):  # allowed extension but outside assets
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
        t = time.time() + 30 * adim * 3  # each login has its own TOTP window (the code is single use)
        return depo.giris(con, "ali", parola, guvenlik.totp_kod(gizli, int(t // 30)), ip, simdi=t)

    def son(self, con):
        return con.execute("SELECT olay, alanlar FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()

    def test_yeni_ip_uyari_ilk_giris_ve_bilinen_ip_degil(self):
        con, g = self.kur()
        self.assertIsNotNone(self.gir(con, g, "198.51.100.1", 1)[0])
        olay, al = self.son(con)
        self.assertEqual(olay, "giris yapildi")  # the first login is not a warning
        self.assertEqual(json.loads(al)["yeni_ip"], 0)
        self.assertIsNotNone(self.gir(con, g, "198.51.100.1", 2)[0])
        self.assertEqual(self.son(con)[0], "giris yapildi")
        self.assertIsNotNone(self.gir(con, g, "203.0.113.9", 3)[0])
        olay, al = self.son(con)
        self.assertEqual(olay, "yeni IP'den giris yapildi")
        a = json.loads(al)
        self.assertEqual((a["yeni_ip"], a["sonuc"], a["kullanici"]), (1, "basarili", "ali"))
        self.assertNotIn("203.0.113.9", al + olay)  # a plain address is not written to the audit
        self.assertNotIn("203.0.113.9", json.dumps(con.execute("SELECT * FROM giris_ip").fetchall()))
        self.assertIsNotNone(self.gir(con, g, "203.0.113.9", 4)[0])
        self.assertEqual(self.son(con)[0], "giris yapildi")  # now a known IP
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
    """Business action and audit record together: if the audit record cannot be written, the action is rolled back too."""

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
            except Exception:  # noqa: BLE001 - the server cuts the request short
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
        kod = self.kod(1)   # the setUp login used the current code; the code of the next window
        b, sonuc = th.Barrier(2), []
        gercek = guvenlik.totp_dogrula

        def yavas(*a, **k):   # widen the window between reading and writing the counter: the race is clearly visible in lock-free code
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
            self.assertLessEqual(say.call_count, 1)   # only requests in the last second are looked at again
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


class KipBPanelTests(Taban):
    """Mode B request list: read-only, paginated, with company and status filters; password, proof and token are not visible."""

    def setUp(self):
        super().setUp()
        t = tdepo.baglan(self.tdb)
        self.diger = tdepo.firma_kaydet(t, "diger.com.tr", "Diger AS", "x@diger.com.tr", "tarama")
        for i in range(30):
            fid = self.firma["id"] if i < 27 else self.diger["id"]
            tdepo.istek_ekle(t, "tk-%02d" % i, fid, "kanit-gizli-%02d" % i, "db%02d.ornek.com" % i, "93.184.216.%d" % (i + 1), 5432, "veri%02d" % i, "alig_hc", i % 2 == 0, "tr")
        t.execute("UPDATE baglanti_istegi SET durum='tamam' WHERE id IN (1,2,28)")
        t.execute("UPDATE baglanti_istegi SET bitis_utc='2000-01-01T00:00:00Z' WHERE id=3")   # expired pending
        t.commit()
        t.close()
        self.giris()

    def test_liste_alanlari_gosterir_gizlileri_gostermez(self):
        r, g = self.istek("GET", "/yonetim/kip-b")
        self.assertEqual(r.status, 200)
        self.assertIn("db29.ornek.com:5432", g)   # newest first
        self.assertIn("veri29", g)
        self.assertIn("Diger AS", g)
        for gizli in ("kanit-gizli", "tk-", "93.184.216", "host=", "sslmode", "password", "parola", "alig-kanit"):
            self.assertNotIn(gizli, g.replace("Parola yok", ""), gizli)
        self.assertNotIn("<form", g.split("</nav>")[-1].replace('action="/yonetim/cikis"', ""))   # read-only: no action form

    def test_sayfalama(self):
        r, g1 = self.istek("GET", "/yonetim/kip-b")
        self.assertIn("db29.ornek.com", g1)
        self.assertNotIn("db00.ornek.com", g1)   # at most 25 records on the first page
        self.assertIn("sayfa=2", g1)
        r, g2 = self.istek("GET", "/yonetim/kip-b?sayfa=2")
        self.assertIn("db00.ornek.com", g2)
        self.assertNotIn("db29.ornek.com", g2)
        for kotu in ("0", "-3", "abc", "999999999999"):
            self.assertEqual(self.istek("GET", "/yonetim/kip-b?sayfa=" + kotu)[0].status, 200, kotu)

    def test_firma_ve_durum_suzgeci(self):
        _, g = self.istek("GET", "/yonetim/kip-b?firma=%d" % self.diger["id"])
        self.assertIn("db29.ornek.com", g)
        self.assertNotIn("db00.ornek.com", g)
        _, g = self.istek("GET", "/yonetim/kip-b?durum=tamam")
        self.assertIn("db00.ornek.com", g)   # id 1
        self.assertNotIn("db10.ornek.com", g)
        _, g = self.istek("GET", "/yonetim/kip-b?durum=tamam&firma=%d" % self.diger["id"])
        self.assertIn("db27.ornek.com", g)   # id 28
        self.assertNotIn("db00.ornek.com", g)
        # an invalid filter is ignored, it does not reach SQL
        r, g = self.istek("GET", "/yonetim/kip-b?durum=x'%20OR%201=1--&firma=abc")
        self.assertEqual(r.status, 200)
        self.assertIn("db29.ornek.com", g)

    def test_suresi_dolan_bekleyen_ayri_gosterilir(self):
        _, g = self.istek("GET", "/yonetim/kip-b?firma=%d" % self.firma["id"])
        self.assertIn("Süresi doldu", g)   # id 3

    def test_xss_kacisi(self):
        t = tdepo.baglan(self.tdb)
        t.execute("UPDATE baglanti_istegi SET ad='<script>alert(1)</script>.ornek.com', veritabani='<img src=x>' WHERE id=30")
        t.commit()
        t.close()
        _, g = self.istek("GET", "/yonetim/kip-b")
        self.assertNotIn("<script>alert(1)", g)
        self.assertNotIn("<img src=x>", g)
        self.assertIn("&lt;script&gt;", g)

    def test_oturum_gerekli_ve_menude(self):
        _, g = self.istek("GET", "/yonetim/kip-b")
        self.assertIn('href="/yonetim/kip-b"', g)
        r, g = self.istek("GET", "/yonetim/kip-b", cerez=False)
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/giris"))
        self.assertNotIn("db29", g)

    def test_tarama_veritabani_yoksa_bos_sayfa(self):
        Path(self.tdb).unlink()
        r, g = self.istek("GET", "/yonetim/kip-b")
        self.assertEqual(r.status, 200)
        self.assertIn("veritabanı yok", g)

    def test_goruntuleme_denetim_kaydina_yazilir(self):
        self.istek("GET", "/yonetim/kip-b")
        y = depo.baglan(self.ydb)
        self.assertTrue(any("kip b istekleri goruntulendi" in r[0] for r in y.execute("SELECT olay FROM denetim")))


class SurecDepoTests(unittest.TestCase):
    """Commercial process state machine (tarama/depo.py): aday -> gorusuluyor -> teklif -> musteri, from every state -> kapandi."""

    def setUp(self):
        self.con = tdepo.baglan(str(Path(tempfile.mkdtemp()) / "t.sqlite"))
        self.fid = tdepo.firma_kaydet(self.con, "firma.com.tr", "Firma", "a@firma.com.tr", "tarama")["id"]

    def durum(self):
        return tdepo.firma_getir(self.con, self.fid)["surec"]

    def test_yeni_firma_aday_baslar(self):
        self.assertEqual(self.durum(), "aday")
        self.assertEqual(tdepo.SUREC_DURUMLARI, ("aday", "gorusuluyor", "teklif", "musteri", "kapandi"))

    def test_gecerli_zincir_ve_not(self):
        for hedef in ("gorusuluyor", "teklif", "musteri", "kapandi"):
            self.assertEqual(tdepo.firma_surec_gecis(self.con, self.fid, hedef, "not " + hedef)[1], hedef)
            f = tdepo.firma_getir(self.con, self.fid)
            self.assertEqual((f["surec"], f["surec_notu"]), (hedef, "not " + hedef))
            self.assertTrue(f["surec_utc"])

    def test_her_durumdan_kapandiya_gecilir(self):
        for baslangic in ("aday", "gorusuluyor", "teklif", "musteri"):
            self.con.execute("UPDATE firma SET surec=? WHERE id=?", (baslangic, self.fid))
            tdepo.firma_surec_gecis(self.con, self.fid, "kapandi")
            self.assertEqual(self.durum(), "kapandi")

    def test_gecersiz_gecis_reddedilir_ve_durum_degismez(self):
        gecersiz = (("aday", "teklif"), ("aday", "musteri"), ("aday", "aday"), ("gorusuluyor", "aday"), ("gorusuluyor", "musteri"),
                    ("teklif", "gorusuluyor"), ("musteri", "teklif"), ("musteri", "aday"), ("kapandi", "aday"), ("kapandi", "musteri"),
                    ("kapandi", "kapandi"), ("aday", "yok"), ("aday", ""))
        for bas, hedef in gecersiz:
            self.con.execute("UPDATE firma SET surec=?, surec_notu='eski' WHERE id=?", (bas, self.fid))
            with self.assertRaises(tdepo.SurecHatasi, msg="%s -> %s" % (bas, hedef)):
                tdepo.firma_surec_gecis(self.con, self.fid, hedef, "yeni not")
            f = tdepo.firma_getir(self.con, self.fid)
            self.assertEqual((f["surec"], f["surec_notu"]), (bas, "eski"))

    def test_var_olmayan_firma_none_doner(self):
        self.assertIsNone(tdepo.firma_surec_gecis(self.con, 9999, "gorusuluyor"))

    def test_not_500_karakterle_sinirlanir(self):
        tdepo.firma_surec_gecis(self.con, self.fid, "gorusuluyor", "x" * 900)
        self.assertEqual(len(tdepo.firma_getir(self.con, self.fid)["surec_notu"]), 500)

    def test_firma_silinince_surec_ve_not_da_gider(self):
        tdepo.firma_surec_gecis(self.con, self.fid, "gorusuluyor", "kisi adi iceren not")
        tdepo.firma_sil(self.con, self.fid)
        self.assertEqual(self.con.execute("SELECT count(*) FROM firma WHERE surec_notu<>''").fetchone()[0], 0)
        self.assertEqual(tdepo.firma_listele(self.con), [])

    def test_eski_veritabani_surec_sutunlarini_alir(self):
        yol = str(Path(tempfile.mkdtemp()) / "eski.sqlite")
        i = next(k for k, g in enumerate(tdepo.GOCLER) if "surec" in g)
        c = sqlite3.connect(yol)
        for g in tdepo.GOCLER[:i]:
            c.execute(g)
        c.execute("PRAGMA user_version=%d" % i)
        c.execute("INSERT INTO firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES('a.com','A','x@a.com','tarama','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
        c.commit()
        c.close()
        con = tdepo.baglan(yol)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], len(tdepo.GOCLER))
        self.assertEqual(tdepo.firma_listele(con)[0]["surec"], "aday")

    def test_saklama_politikasi_notun_firmayla_silindigini_yazar(self):
        from tarama import saklama
        self.assertIn("ticari surec", saklama.SINIFLAR["firma"][3])
        self.assertIn("süreç", (ROOT / "docs" / "saklama-politikasi.md").read_text(encoding="utf-8"))


class SurecPanelTests(Taban):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.giris().status, 303)
        self.fid = self.firma["id"]
        self.yol = "/yonetim/firmalar/%d/surec" % self.fid

    def surec(self):
        t = tdepo.baglan(self.tdb)
        try:
            return tdepo.firma_getir(t, self.fid)
        finally:
            t.close()

    def olaylar(self):
        t, y = tdepo.baglan(self.tdb), depo.baglan(self.ydb)
        try:
            return ([o for (o,) in t.execute("SELECT olay FROM denetim")], [o for (o,) in y.execute("SELECT olay FROM denetim")],
                    tdepo.denetim_dogrula(t), depo.denetim_dogrula(y))
        finally:
            t.close()
            y.close()

    def test_firma_sayfasi_durumu_ve_yalniz_gecerli_hedefleri_gosterir(self):
        g = self.istek("GET", "/yonetim/firmalar/%d" % self.fid)[1]
        self.assertIn("Ticari süreç", g)
        self.assertIn("Aday", g)
        secenekler = re.search(r'name="surec">(.*?)</select>', g, re.S).group(1)
        self.assertIn('value="gorusuluyor"', secenekler)
        self.assertIn('value="kapandi"', secenekler)
        self.assertNotIn('value="teklif"', secenekler)
        self.assertNotIn('value="musteri"', secenekler)

    def test_gecis_iki_zincire_yazilir_not_zincire_yazilmaz(self):
        r, _ = self.istek("POST", self.yol, {"surec": "gorusuluyor", "aciklama": "Ahmet Bey ile gorusuldu <b>x</b>", "csrf": self.csrf()})
        self.assertEqual((r.status, r.getheader("Location")), (303, "/yonetim/firmalar/%d" % self.fid))
        f = self.surec()
        self.assertEqual((f["surec"], f["surec_notu"]), ("gorusuluyor", "Ahmet Bey ile gorusuldu <b>x</b>"))
        tarama_o, yonetim_o, tz, yz = self.olaylar()
        olay = "firma #%d surec: aday -> gorusuluyor" % self.fid
        self.assertIn(olay, tarama_o)
        self.assertIn(olay, yonetim_o)
        self.assertFalse(any("Ahmet" in o for o in tarama_o + yonetim_o))
        self.assertEqual((tz, yz), (None, None))
        g = self.istek("GET", "/yonetim/firmalar/%d" % self.fid)[1]
        self.assertIn("Ahmet Bey ile gorusuldu &lt;b&gt;x&lt;/b&gt;", g)
        self.assertNotIn("<b>x</b>", g)

    def test_gecersiz_gecis_422_ve_iz_birakmaz(self):
        suz = lambda o: ([x for x in o[0] if "surec" in x], [x for x in o[1] if "surec" in x])  # noqa: E731
        onceki = suz(self.olaylar())
        for hedef in ("teklif", "musteri", "aday", "yok", ""):
            self.assertEqual(self.istek("POST", self.yol, {"surec": hedef, "csrf": self.csrf()})[0].status, 422, hedef)
        self.assertEqual(self.surec()["surec"], "aday")
        self.assertEqual(suz(self.olaylar()), onceki)
        self.assertEqual(onceki, ([], []))

    def test_tam_zincir_ve_kapandi_sonrasi_degisim_yok(self):
        for hedef in ("gorusuluyor", "teklif", "musteri", "kapandi"):
            self.assertEqual(self.istek("POST", self.yol, {"surec": hedef, "csrf": self.csrf()})[0].status, 303, hedef)
        self.assertEqual(self.surec()["surec"], "kapandi")
        self.assertEqual(self.istek("POST", self.yol, {"surec": "aday", "csrf": self.csrf()})[0].status, 422)
        self.assertEqual(self.olaylar()[2:], (None, None))

    def test_csrf_oturum_ve_var_olmayan_firma(self):
        self.assertEqual(self.istek("POST", self.yol, {"surec": "gorusuluyor"})[0].status, 403)
        self.assertEqual(self.surec()["surec"], "aday")
        self.assertEqual(self.istek("POST", self.yol, {"surec": "gorusuluyor"}, cerez=False)[0].status, 303)
        self.assertEqual(self.surec()["surec"], "aday")
        self.assertEqual(self.istek("POST", "/yonetim/firmalar/99999/surec", {"surec": "gorusuluyor", "csrf": self.csrf()})[0].status, 404)
        self.assertEqual(self.istek("POST", self.yol, {"surec": "gorusuluyor", "csrf": self.csrf()}, basliklar={"Origin": "http://baska.example"})[0].status, 403)

    def test_firma_listesi_surece_gore_suzulur(self):
        t = tdepo.baglan(self.tdb)
        tdepo.firma_kaydet(t, "diger.com.tr", "Diger Firma", "x@diger.com.tr", "tarama")
        t.close()
        self.istek("POST", self.yol, {"surec": "gorusuluyor", "csrf": self.csrf()})
        g = self.istek("GET", "/yonetim/firmalar?surec=gorusuluyor")[1]
        self.assertIn("ayse@firma.com.tr", g)
        self.assertNotIn("x@diger.com.tr", g)
        g = self.istek("GET", "/yonetim/firmalar?surec=aday")[1]
        self.assertIn("x@diger.com.tr", g)
        self.assertNotIn("ayse@firma.com.tr", g)
        g = self.istek("GET", "/yonetim/firmalar?surec=gecersiz")[1]   # an invalid filter is ignored
        self.assertIn("x@diger.com.tr", g)
        self.assertIn("ayse@firma.com.tr", g)

    def test_firma_silinince_not_gider(self):
        self.istek("POST", self.yol, {"surec": "gorusuluyor", "aciklama": "gizli not", "csrf": self.csrf()})
        self.istek("POST", "/yonetim/firmalar/%d/sil" % self.fid, {"emin": "evet", "csrf": self.csrf()})
        t = tdepo.baglan(self.tdb)
        self.assertEqual(t.execute("SELECT count(*) FROM firma WHERE surec_notu LIKE '%gizli not%'").fetchone()[0], 0)

    def test_ticari_tutar_alani_yok(self):
        t = tdepo.baglan(self.tdb)
        kolonlar = [r[1] for r in t.execute("PRAGMA table_info(firma)")]
        for yasak in ("fiyat", "tutar", "teklif_tutari", "musteri_adi", "ucret"):
            self.assertNotIn(yasak, kolonlar)


class GostergeTests(Taban):
    def test_sayilar_dogru_ve_okunamayan_none(self):
        t = tdepo.baglan(self.tdb)
        tdepo.firma_kaydet(t, "pasif.com.tr", "P", "p@pasif.com.tr", "tarama")
        tdepo.firma_durum_yaz(t, t.execute("SELECT id FROM firma WHERE anahtar='pasif.com.tr'").fetchone()[0], "pasif")
        eski = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tdepo.rapor_ekle(t, "eski-kod", "postgresql", "tr", temiz_belge(), self.firma["id"])
        t.execute("UPDATE rapor SET olusturma_utc=? WHERE token_sha256=?", (eski, tdepo.token_ozeti("eski-kod")))
        z = tdepo.simdi()
        for tur, durum in (("destek", "yeni"), ("denetim", "inceleniyor"), ("silme", "tamamlandi")):
            t.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, durum, olusturma_utc, guncelleme_utc) VALUES(?,?,?,?,?,?)", (self.firma["id"], 1, tur, durum, z, z))
        tdepo.istek_ekle(t, "tk1", self.firma["id"], "k", "ad", "10.0.0.1", 5432, "db", "u", False, "tr")
        tdepo.istek_ekle(t, "tk2", self.firma["id"], "k", "ad", "10.0.0.1", 5432, "db", "u", False, "tr")
        t.execute("UPDATE baglanti_istegi SET durum='bitti' WHERE id=2")
        tdepo.posta_ekle(t, "a@b.com", "k", "m")
        tdepo.posta_ekle(t, "c@d.com", "k", "m")
        tdepo.posta_sonuc(t, 2)
        t.commit()
        t.close()
        y = depo.baglan(self.ydb)
        depo.talep_durum_yaz(y, 1, "gorusuluyor", "", "ali")
        g = depo.gosterge(y, self.tdb, self.fdb)
        self.assertEqual((g["tarama_7"], g["tarama_30"]), (1, 2))
        self.assertEqual((g["firma_aktif"], g["firma_pasif"]), (1, 1))
        self.assertEqual(g["iletisim_acik"], 1)     # gorusuluyor is still open
        self.assertEqual(g["portal_acik"], 2)
        self.assertEqual(g["kipb_bekleyen"], 1)
        self.assertEqual(g["posta_bekleyen"], 1)
        self.assertEqual(g["zincir_tarama"]["bozuk"], None)
        self.assertEqual(g["zincir_yonetim"]["bozuk"], None)
        depo.talep_durum_yaz(y, 1, "kapandi", "", "ali")
        self.assertEqual(depo.gosterge(y, self.tdb, self.fdb)["iletisim_acik"], 0)

    def test_dosya_yoksa_sayilar_none_sifir_degil(self):
        y = depo.baglan(self.ydb)
        yok = str(Path(self.tdb).parent / "yok.sqlite")
        g = depo.gosterge(y, yok, yok)
        for k in ("tarama_7", "tarama_30", "firma_aktif", "firma_pasif", "iletisim_acik", "portal_acik", "kipb_bekleyen", "posta_bekleyen", "zincir_tarama"):
            self.assertIsNone(g[k], k)
        self.assertIsNotNone(g["zincir_yonetim"])
        self.assertFalse(Path(yok).exists())   # read-only: no file is created

    def test_bozuk_tablo_none_doner(self):
        c = sqlite3.connect(self.fdb)
        c.execute("DROP TABLE contact")
        c.commit()
        c.close()
        y = depo.baglan(self.ydb)
        self.assertIsNone(depo.gosterge(y, self.tdb, self.fdb)["iletisim_acik"])
        self.assertEqual(depo.gosterge(y, self.tdb, self.fdb)["firma_aktif"], 1)

    def test_gosterge_salt_okumadir(self):
        y = depo.baglan(self.ydb)
        yonetim_once = y.execute("SELECT count(*) FROM denetim").fetchone()[0]
        t = tdepo.baglan(self.tdb)
        tarama_once = t.execute("SELECT count(*) FROM denetim").fetchone()[0]
        t.close()
        depo.gosterge(y, self.tdb, self.fdb)
        self.assertEqual(y.execute("SELECT count(*) FROM denetim").fetchone()[0], yonetim_once)
        t = tdepo.baglan(self.tdb)
        self.assertEqual(t.execute("SELECT count(*) FROM denetim").fetchone()[0], tarama_once)

    def test_ozet_sayfasi_gostergeyi_gosterir(self):
        self.giris()
        g = self.istek("GET", "/yonetim/")[1]
        for etiket in ("Tarama (son 7 gün)", "Tarama (son 30 gün)", "Aktif firma", "Pasif firma", "Açık iletişim talebi", "Açık portal talebi",
                       "Bekleyen Kip B isteği", "Giden kutusunda bekleyen posta", "Tarama denetim zinciri", "Yönetim denetim zinciri"):
            self.assertIn(etiket, g)
        self.assertNotIn("veri yok", g)

    def test_ozet_sayfasi_eksik_veriyi_sifir_gostermez(self):
        self.giris()
        Path(self.fdb).unlink()
        g = self.istek("GET", "/yonetim/")[1]
        kutu = re.search(r'Açık iletişim talebi</p><p class="stat-v">([^<]*)<', g)
        self.assertEqual(kutu.group(1), "veri yok")

    def test_ozet_kirik_zinciri_gosterir(self):
        self.giris()
        t = tdepo.baglan(self.tdb)
        tdepo.denetim_ekle(t, "x", "olay")
        t.execute("UPDATE denetim SET olay='degistirildi' WHERE seq=(SELECT max(seq) FROM denetim)")
        t.commit()
        t.close()
        g = self.istek("GET", "/yonetim/")[1]
        self.assertRegex(g, r"Tarama denetim zinciri</p><p class=\"stat-v\">KIRIK")


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
