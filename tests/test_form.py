import http.client
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "form"))
import server  # noqa: E402

GOOD = {"name": "Ada", "company": "Ornek AS", "email": "ada@example.com", "db": "pg", "message": "merhaba", "website": ""}


class FormTests(unittest.TestCase):
    def setUp(self):
        self.db = str(Path(tempfile.mkdtemp()) / "f.sqlite")
        server.connect(self.db).close()
        self.limiter = server.RateLimiter(per_window=50)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.db, self.limiter, "tuz"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def post(self, data, path="/api/iletisim", ctype="application/x-www-form-urlencoded", raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        body = raw if raw is not None else urlencode(data).encode()
        c.request("POST", path, body=body, headers={"Content-Type": ctype})
        r = c.getresponse()
        r.read()
        return r

    def rows(self):
        con = server.connect(self.db)
        try:
            return con.execute("SELECT name,db,created_utc,ip_hash FROM contact").fetchall()
        finally:
            con.close()

    def test_valid_saved_utc_and_hashed_ip(self):
        r = self.post(GOOD)
        self.assertEqual(r.status, 303)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][2].endswith("Z"))
        self.assertNotIn("127.0.0.1", rows[0][3])

    def test_english_referer_redirect(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/api/iletisim", body=urlencode(GOOD).encode(),
                  headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": "https://alig.tech/en/"})
        r = c.getresponse()
        self.assertEqual(r.getheader("Location"), "/en/tesekkurler/")

    def test_wal_mode(self):
        con = server.connect(self.db)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        con.close()

    def test_invalid_fields_rejected(self):
        for bad in ({**GOOD, "email": "x"}, {**GOOD, "name": " "}, {**GOOD, "db": "oracle"}, {**GOOD, "message": "a" * 2001}):
            self.assertEqual(self.post(bad).status, 422)
        self.assertEqual(self.rows(), [])

    def test_honeypot_silent(self):
        self.assertEqual(self.post({**GOOD, "website": "http://spam"}).status, 303)
        self.assertEqual(self.rows(), [])

    def test_rate_limit(self):
        self.limiter.n = 3
        codes = [self.post(GOOD).status for _ in range(4)]
        self.assertEqual(codes, [303, 303, 303, 429])

    def test_wrong_type_size_path(self):
        self.assertEqual(self.post(GOOD, ctype="application/json").status, 415)
        self.assertEqual(self.post(None, raw=b"a=" + b"x" * 9000).status, 413)
        self.assertEqual(self.post(GOOD, path="/baska").status, 404)

    def test_healthz(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("GET", "/healthz")
        self.assertEqual(c.getresponse().status, 200)

    def test_limiter_window(self):
        t = [0.0]
        rl = server.RateLimiter(2, 10, clock=lambda: t[0])
        self.assertTrue(rl.allow("a") and rl.allow("a") and not rl.allow("a"))
        t[0] = 11
        self.assertTrue(rl.allow("a"))


if __name__ == "__main__":
    unittest.main()
