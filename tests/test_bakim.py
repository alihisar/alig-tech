"""Maintenance mode (ALIG-OPS-002, decision OPS-K1): ALIG_BAKIM=1 closes the write endpoints with 503 + Retry-After and a
bilingual page; reads, static files and /healthz stay open; with the flag off nothing changes."""
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "form"))
import server as form  # noqa: E402
from tarama import bakim, depo, server as tserver  # noqa: E402
from yonetim import server as yserver  # noqa: E402
from test_tarama import _SunucuTaban, temiz_belge  # noqa: E402

FORM_VERISI = {"name": "Ada", "company": "Ornek AS", "email": "ada@example.com", "db": "pg", "message": "merhaba", "website": ""}


class BakimModuluTests(unittest.TestCase):
    def test_etkin_yalniz_1_ile(self):
        self.assertTrue(bakim.etkin({"ALIG_BAKIM": "1"}))
        for v in (None, "", "0", "true", "yes", " 1", "2"):
            self.assertFalse(bakim.etkin({} if v is None else {"ALIG_BAKIM": v}), v)

    def test_bekle_sn_varsayilan_ve_gecersiz(self):
        self.assertEqual(bakim.bekle_sn({}), 300)
        self.assertEqual(bakim.bekle_sn({"ALIG_BAKIM_BEKLE_SN": "60"}), 60)
        for v in ("0", "-5", "abc", "", "86401", "1.5"):
            with self.assertRaises(ValueError, msg=v):
                bakim.bekle_sn({"ALIG_BAKIM_BEKLE_SN": v})

    def test_ayarla_siniflara_yazar(self):
        class K:
            bakim = False
            bakim_bekle = 300
        self.assertFalse(bakim.ayarla({}, K))
        self.assertFalse(K.bakim)
        self.assertTrue(bakim.ayarla({"ALIG_BAKIM": "1", "ALIG_BAKIM_BEKLE_SN": "90"}, K))
        self.assertTrue(K.bakim)
        self.assertEqual(K.bakim_bekle, 90)

    def test_dil_secimi(self):
        self.assertEqual(bakim.dil_sec("https://alig.tech/en/saglik-taramasi/"), "en")
        self.assertEqual(bakim.dil_sec("https://alig.tech/saglik-taramasi/"), "tr")
        self.assertEqual(bakim.dil_sec(None), "tr")
        self.assertEqual(bakim.dil_sec("https://alig.tech/english/"), "tr")

    def test_sayfa_iki_dilli_ve_csp_uyumlu(self):
        tr, en = bakim.sayfa("tr"), bakim.sayfa("en")
        self.assertIn('<html lang="tr">', tr)
        self.assertIn('<html lang="en">', en)
        self.assertNotEqual(tr, en)
        self.assertIn("bakım", tr.lower())
        self.assertIn("maintenance", en.lower())
        for s in (tr, en):
            self.assertNotIn("<script", s)
            self.assertNotIn("style=", s)
            self.assertNotIn("<style", s)
            self.assertIsNone(re.search(r"\son[a-z]+=", s))
            self.assertNotIn("http://", s)
            self.assertNotIn("https://", s)   # no external resources
        self.assertEqual(bakim.sayfa("fr"), tr)   # unknown language falls back to Turkish


class FormBakimTests(unittest.TestCase):
    def kur(self, **ek):
        self.db = str(Path(tempfile.mkdtemp()) / "f.sqlite")
        form.connect(self.db).close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), form.make_handler(self.db, form.RateLimiter(per_window=50), "tuz", **ek))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def istek(self, metod, yol, veri=None, basliklar=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        b = {"Content-Type": "application/x-www-form-urlencoded"}
        b.update(basliklar or {})
        c.request(metod, yol, body=urlencode(veri).encode() if veri is not None else None, headers=b)
        r = c.getresponse()
        r.govde = r.read()
        return r

    def satirlar(self):
        con = form.connect(self.db)
        try:
            return con.execute("SELECT COUNT(*) FROM contact").fetchone()[0]
        finally:
            con.close()

    def test_kapaliyken_davranis_ayni(self):
        self.kur()
        self.assertEqual(self.istek("POST", "/api/iletisim", FORM_VERISI).status, 303)
        self.assertEqual(self.satirlar(), 1)
        self.assertEqual(self.istek("GET", "/healthz").status, 200)

    def test_acikken_post_503_retry_after_ve_kayit_yok(self):
        self.kur(bakim=True, bakim_bekle=120)
        r = self.istek("POST", "/api/iletisim", FORM_VERISI)
        self.assertEqual(r.status, 503)
        self.assertEqual(r.getheader("Retry-After"), "120")
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))
        self.assertIn(b"maintenance", bakim.sayfa("en").encode().lower())
        self.assertIn('<html lang="tr">', r.govde.decode())
        self.assertEqual(self.satirlar(), 0)
        # even a honeypot or invalid request gets 503, not 303/422: nothing is processed during the freeze
        self.assertEqual(self.istek("POST", "/api/iletisim", dict(FORM_VERISI, website="x")).status, 503)
        self.assertEqual(self.istek("POST", "/api/iletisim", {"name": ""}).status, 503)

    def test_acikken_ingilizce_referer_ingilizce_sayfa(self):
        self.kur(bakim=True)
        r = self.istek("POST", "/api/iletisim", FORM_VERISI, {"Referer": "https://alig.tech/en/"})
        self.assertEqual(r.status, 503)
        self.assertIn('<html lang="en">', r.govde.decode())

    def test_acikken_healthz_canli(self):
        self.kur(bakim=True)
        r = self.istek("GET", "/healthz")
        self.assertEqual((r.status, r.govde), (200, b"ok\n"))
        self.assertEqual(self.istek("GET", "/baska").status, 404)


class TaramaBakimTests(_SunucuTaban):
    def test_kapaliyken_varsayilan_kapali(self):
        self.assertFalse(tserver.H.bakim)
        self.assertEqual(self.yukle(json.dumps(temiz_belge()).encode()).status, 303)

    def test_acikken_yazma_uclari_503(self):
        r = self.yukle(json.dumps(temiz_belge()).encode())
        self.assertEqual(r.status, 303)
        yol = r.getheader("Location")
        self.H.bakim, self.H.bakim_bekle = True, 45
        self.H.dogrudan, self.H.portal = True, True   # even the optional gates do not bypass the freeze
        con = depo.baglan(self.db)
        onceki = con.execute("SELECT COUNT(*) FROM rapor").fetchone()[0], con.execute("SELECT COUNT(*) FROM denetim").fetchone()[0]
        con.close()
        y = self.yukle(json.dumps(temiz_belge()).encode())
        self.assertEqual(y.status, 503)
        self.assertEqual(y.getheader("Retry-After"), "45")
        self.assertIn("<html", y.govde)
        for p in (yol + "sil", yol + "dogrula", "/api/tarama/baglan", "/api/tarama/baglan/" + "A" * 43,
                  "/portal/giris", "/portal/kayit", "/portal/cikis", "/portal/rapor-sil"):
            r, g = self.post(p)
            self.assertEqual(r.status, 503, p)
            self.assertEqual(r.getheader("Retry-After"), "45", p)
            self.assertIn(b"<html", g, p)
        con = depo.baglan(self.db)
        self.assertEqual((con.execute("SELECT COUNT(*) FROM rapor").fetchone()[0], con.execute("SELECT COUNT(*) FROM denetim").fetchone()[0]), onceki)
        con.close()

    def test_acikken_okuma_ve_saglik_acik(self):
        r = self.yukle(json.dumps(temiz_belge()).encode())
        yol = r.getheader("Location")
        self.H.bakim = True
        self.assertEqual(self.get(yol)[0].status, 200)             # the report can still be read
        self.assertEqual(self.get("/api/tarama/saglik")[0].status, 200)
        self.assertEqual(self.get("/rapor/" + "A" * 43 + "/")[0].status, 404)
        # and the delete did not happen
        self.assertEqual(self.post(yol + "sil")[0].status, 503)
        self.assertEqual(self.get(yol)[0].status, 200)

    def test_bakim_bitince_yazma_yeniden_acilir(self):
        self.H.bakim = True
        self.assertEqual(self.yukle(json.dumps(temiz_belge()).encode()).status, 503)
        self.H.bakim = False
        self.assertEqual(self.yukle(json.dumps(temiz_belge()).encode()).status, 303)


class YonetimBakimTests(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.H = type("H", (yserver.H,), {"ydb": str(d / "y.sqlite"), "form_db": str(d / "f.sqlite"), "tarama_db": str(d / "t.sqlite"),
                                          "guvenli_cerez": False})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def istek(self, metod, yol, veri=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request(metod, yol, body=urlencode(veri).encode() if veri is not None else None,
                  headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://127.0.0.1:%d" % self.srv.server_port,
                           "Host": "127.0.0.1:%d" % self.srv.server_port})
        r = c.getresponse()
        r.govde = r.read()
        return r

    def test_kapaliyken_varsayilan_kapali_ve_davranis_ayni(self):
        self.assertFalse(yserver.H.bakim)
        self.assertEqual(self.istek("POST", "/yonetim/giris", {"ad": "x", "parola": "y", "kod": "000000"}).status, 401)

    def test_acikken_post_503_get_acik(self):
        self.H.bakim, self.H.bakim_bekle = True, 30
        for p in ("/yonetim/giris", "/yonetim/cikis", "/yonetim/talepler/1/durum", "/yonetim/baska"):
            r = self.istek("POST", p, {"ad": "x"})
            self.assertEqual(r.status, 503, p)
            self.assertEqual(r.getheader("Retry-After"), "30", p)
            self.assertIn(b"<html", r.govde, p)
        self.assertEqual(self.istek("GET", "/yonetim/giris").status, 200)   # reading stays open


class _SahteSunucu:
    """ThreadingHTTPServer replacement: records the handler class and returns instead of serving."""
    son = None

    def __init__(self, adres, H):
        type(self).son = H

    def serve_forever(self):
        return None


class KurulumTests(unittest.TestCase):
    """main() of each service applies ALIG_BAKIM to its handler."""

    def calistir(self, ortam):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, ortam, clear=False):
            for k in ("ALIG_BAKIM", "ALIG_BAKIM_BEKLE_SN"):
                if k not in ortam:
                    os.environ.pop(k, None)
            with mock.patch.object(form, "ThreadingHTTPServer", _SahteSunucu):
                form.main(["--db", d + "/f.sqlite", "--salt", "tuz"])
                f = _SahteSunucu.son
            with mock.patch.object(tserver, "ThreadingHTTPServer", _SahteSunucu), \
                    mock.patch.object(depo, "denetim_anahtari"), mock.patch.object(tserver.puan, "yukle"), \
                    mock.patch.object(tserver.saklama, "dogrula"):
                try:
                    tserver.main(["--db", d + "/t.sqlite"])
                    t = (_SahteSunucu.son.bakim, _SahteSunucu.son.bakim_bekle)
                finally:
                    tserver.H.bakim, tserver.H.bakim_bekle = False, 300
            with mock.patch.object(yserver, "ThreadingHTTPServer", _SahteSunucu), \
                    mock.patch.object(yserver.depo.zincir, "denetim_anahtari"), mock.patch.object(yserver.puan, "yukle"), \
                    mock.patch.object(yserver.saklama, "dogrula"):
                try:
                    yserver.main(["--db", d + "/y.sqlite"])
                    y = _SahteSunucu.son
                    durum = (y.bakim, y.bakim_bekle)
                finally:
                    yserver.H.bakim, yserver.H.bakim_bekle = False, 300
        return (f.bakim, f.bakim_bekle), t, durum

    def test_varsayilan_kapali(self):
        for durum in self.calistir({}):
            self.assertEqual(durum, (False, 300))

    def test_bayrak_uc_servise_uygulanir(self):
        for durum in self.calistir({"ALIG_BAKIM": "1", "ALIG_BAKIM_BEKLE_SN": "120"}):
            self.assertEqual(durum, (True, 120))

    def test_gecersiz_bekleme_suresi_baslamaz(self):
        with mock.patch.dict(os.environ, {"ALIG_BAKIM": "1", "ALIG_BAKIM_BEKLE_SN": "abc"}):
            with self.assertRaises(SystemExit):
                form.main(["--db", tempfile.mkdtemp() + "/f.sqlite", "--salt", "tuz"])


if __name__ == "__main__":
    unittest.main()
