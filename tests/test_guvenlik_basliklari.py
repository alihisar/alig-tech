"""ALIG-SEC-002: security headers pinned for every endpoint (table-driven: every path x expected header).

Two layers: (1) the application processes' own responses (form, scan, portal, admin panel), which are also reached
without nginx (SSH tunnel, local smoke test), and (2) the nginx template that adds the headers for the public site.
"""
import http.client
import importlib.util
import json
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_portal  # noqa: E402
import test_tarama  # noqa: E402
import test_yonetim  # noqa: E402

SABLON = ROOT / "deploy" / "ansible" / "roles" / "web" / "templates"

# Headers every application response must carry (value pinned exactly).
ORTAK = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
# Strict CSP for HTML responses (reports, portal, admin panel, error pages): no script, no inline style.
CSP_HTML = ("default-src 'none'; script-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
# Everything that is not HTML (plain text, redirects, CSV, static files): nothing may load or embed.
CSP_DUZ = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


class BaslikDenetimi:
    """Mixin: checks one response against the expected header table."""

    def denetle(self, r, ad):
        for k, v in ORTAK.items():
            self.assertEqual(r.getheader(k), v, "%s: %s" % (ad, k))
        html = (r.getheader("Content-Type") or "").startswith("text/html")
        csp = [v for k, v in r.getheaders() if k.lower() == "content-security-policy"]
        self.assertEqual(csp, [CSP_HTML if html else CSP_DUZ], "%s: exactly one CSP" % ad)
        for k in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"):
            self.assertEqual(len([1 for n, _ in r.getheaders() if n.lower() == k.lower()]), 1, "%s: duplicate %s" % (ad, k))
        # HSTS is only meaningful over TLS: nginx sends it, the loopback application processes must not.
        self.assertIsNone(r.getheader("Strict-Transport-Security"), ad)


class TaramaBasliklari(BaslikDenetimi, test_tarama._SunucuTaban):
    H_EK = {"dogrudan": True}

    def test_her_yol_icin_basliklar(self):
        rapor_yolu = self.yukle(json.dumps(test_tarama.temiz_belge()).encode()).getheader("Location")
        satirlar = [
            ("GET", "/api/tarama/saglik", 200),
            ("GET", "/api/tarama/baglan", 200),                 # HTML form (Mode B gate open in this test)
            ("GET", rapor_yolu, 200),                           # report HTML
            ("GET", rapor_yolu + "?gorunum=teknik", 200),
            ("GET", "/rapor/%s/" % ("A" * 43), 404),            # unknown token
            ("GET", "/bilinmeyen", 404),
            ("POST", "/bilinmeyen", 404),
            ("POST", "/api/tarama/yukle", 415),                 # not multipart: error page
            ("POST", rapor_yolu + "sil", 303),                  # redirect
        ]
        for metod, yol, kod in satirlar:
            c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
            c.request(metod, yol)
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, kod, yol)
            self.denetle(r, "%s %s" % (metod, yol))

    def test_hata_sayfasi_html_ve_katidir(self):
        r = self.yukle(b"{}", yetki=False)
        self.assertEqual(r.status, 422)
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))
        self.denetle(r, "hata sayfasi")

    def test_rapor_yaniti_kati_csp(self):
        yol = self.yukle(json.dumps(test_tarama.temiz_belge()).encode()).getheader("Location")
        r, govde = self.get(yol)
        self.assertEqual(r.getheader("Content-Security-Policy"), CSP_HTML)
        self.assertNotIn(b"<script", govde)
        self.assertNotIn(b" style=", govde)
        self.assertNotIn("unsafe-inline", r.getheader("Content-Security-Policy"))


class PortalBasliklari(BaslikDenetimi, test_portal.HttpTaban):
    def test_portal_yollari(self):
        self.hesap()
        _, cerez = self.giris()
        for yol, kod in (("/portal/", 200), ("/portal/kayit", 200), ("/portal/rapor/999/", 404), ("/portal/bilinmeyen", 404)):
            r = self.istek("GET", yol, cerez=cerez)
            self.assertEqual(r.status, kod, yol)
            self.denetle(r, yol)
        r = self.istek("GET", "/portal", cerez=cerez)           # redirect
        self.assertEqual(r.status, 301)
        self.denetle(r, "/portal")
        r = self.istek("POST", "/portal/cikis", {"dil": "tr"}, cerez=cerez)
        self.denetle(r, "/portal/cikis")
        r = self.istek("POST", "/portal/giris", {"eposta": "x@y.com", "parola": "yanlis", "dil": "tr"}, origin=False)
        self.denetle(r, "origin yok")


class YonetimBasliklari(BaslikDenetimi, test_yonetim.Taban):
    def test_panel_yollari(self):
        r, _ = self.istek("GET", "/yonetim/giris", cerez=False)
        self.denetle(r, "/yonetim/giris")
        r, _ = self.istek("GET", "/yonetim/", cerez=False)      # redirect to the login
        self.assertEqual(r.status, 303)
        self.denetle(r, "/yonetim/ (no session)")
        self.assertEqual(self.giris().status, 303)
        for yol in ("/yonetim/", "/yonetim/firmalar", "/yonetim/firmalar.csv", "/yonetim/talepler", "/yonetim/talepler.csv",
                    "/yonetim/denetim", "/yonetim/taramalar", "/yonetim/portal-talepleri", "/yonetim/yok", "/bilinmeyen"):
            r, _ = self.istek("GET", yol)
            self.denetle(r, yol)
        for yol in ("/assets/base.css", "/assets/yok.css"):
            r, _ = self.istek("GET", yol, cerez=False)
            self.denetle(r, yol)
        r, _ = self.istek("GET", "/yonetim/")
        self.assertEqual(r.getheader("X-Robots-Tag"), "noindex, nofollow")


class FormBasliklari(BaslikDenetimi, unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("alig_form_server", ROOT / "form" / "server.py")
        self.fs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fs)
        db = str(Path(tempfile.mkdtemp()) / "f.sqlite")
        self.fs.connect(db).close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.fs.make_handler(db, self.fs.RateLimiter(per_window=50), "tuz"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def istek(self, metod, yol, govde=None, ctype=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request(metod, yol, body=govde, headers={"Content-Type": ctype} if ctype else {})
        r = c.getresponse()
        r.read()
        return r

    def test_her_yol_icin_basliklar(self):
        form = b"name=Ada&company=Ornek&email=ada%40example.com&db=pg&message=merhaba&website="
        gecersiz = b"name=&company=&email=x&db=&message=&website="
        satirlar = [
            ("GET", "/healthz", None, None, 200),
            ("GET", "/bilinmeyen", None, None, 404),
            ("POST", "/bilinmeyen", None, None, 404),
            ("POST", "/api/iletisim", form, "application/x-www-form-urlencoded", 303),
            ("POST", "/api/iletisim", gecersiz, "application/x-www-form-urlencoded", 422),
            ("POST", "/api/iletisim", form, "text/plain", 415),
        ]
        for metod, yol, govde, ctype, kod in satirlar:
            r = self.istek(metod, yol, govde, ctype)
            self.assertEqual(r.status, kod, yol)
            self.denetle(r, "%s %s" % (metod, yol))


class NginxSablonu(unittest.TestCase):
    """The public site: the nginx template must give every response the full header set."""

    def basliklar(self):
        return (SABLON / "alig-basliklar.conf.j2").read_text()

    def test_tam_baslik_kumesi(self):
        t = self.basliklar()
        beklenen = {
            "Content-Security-Policy": ["default-src 'none'", "script-src 'self'", "style-src 'self'", "base-uri 'none'",
                                        "frame-ancestors 'none'", "form-action 'self'"],
            "X-Content-Type-Options": ["nosniff"],
            "X-Frame-Options": ["DENY"],
            "Referrer-Policy": ["no-referrer"],
            "Permissions-Policy": ["camera=()", "microphone=()", "geolocation=()"],
            "Strict-Transport-Security": ["max-age={{ hsts_saniye }}"],
        }
        for ad, parcalar in beklenen.items():
            m = re.search(r'(?m)^add_header %s "([^"]*)" always;$' % re.escape(ad), t)
            self.assertIsNotNone(m, "%s: add_header ... always is missing" % ad)
            for p in parcalar:
                self.assertIn(p, m.group(1), ad)
        self.assertNotIn("unsafe-inline", t)
        self.assertNotIn("unsafe-eval", t)

    def test_hsts_degeri_makul(self):
        var = (ROOT / "deploy" / "ansible" / "group_vars" / "all.yml").read_text()
        m = re.search(r"(?m)^hsts_saniye: (\d+)$", var)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 15552000)    # at least 180 days

    def test_uygulama_basliklari_cift_gonderilmez(self):
        """The application also sends these (tunnel mode); nginx hides the upstream copy so the browser sees one of each
        (two X-Frame-Options values are treated as invalid by browsers). The application CSP is kept: two CSPs intersect."""
        t = self.basliklar()
        for ad in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"):
            self.assertRegex(t, r"(?m)^proxy_hide_header %s;$" % re.escape(ad))
        self.assertNotRegex(t, r"(?m)^proxy_hide_header Content-Security-Policy;$")

    def test_her_konum_ve_her_443_sunucusu_basliklari_icerir(self):
        konum = (SABLON / "alig-konumlar.conf.j2").read_text()
        self.assertEqual(konum.count("location "), konum.count("include snippets/alig-basliklar.conf"))
        https = (SABLON / "alig-https.conf.j2").read_text()
        # the www redirect server answers over TLS too: it must carry HSTS and the rest
        bloklar = re.split(r"(?m)^server \{", https)[1:]
        tls = [b for b in bloklar if "listen 443" in b]
        self.assertEqual(len(tls), 2)
        for b in tls:
            self.assertTrue("include snippets/alig-basliklar.conf" in b or "alig-konumlar.conf.j2" in b)

    def test_http_sunucusu_hsts_gondermez(self):
        https = (SABLON / "alig-https.conf.j2").read_text()
        http_blok = re.split(r"(?m)^server \{", https)[1]
        self.assertIn("listen 80", http_blok)
        self.assertNotIn("alig-basliklar", http_blok)         # HSTS over plain HTTP is ignored by browsers and is misleading


if __name__ == "__main__":
    unittest.main()
