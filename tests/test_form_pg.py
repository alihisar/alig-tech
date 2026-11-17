"""ALIG-DB-003e: the contact form on PostgreSQL. The shared behaviour tests of tests/test_form.py (FormOrtak) run against the PostgreSQL store,
plus PG-specific ones: atomic rate limit with 429 + Retry-After, 503 + Retry-After when the database is unusable, no SQLite fallback.
Real temporary PostgreSQL 16 cluster; SKIPped (never PASS) when PostgreSQL 16 or libpq is missing."""
import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "form"))
sys.path.insert(0, str(ROOT / "tests"))
import server  # noqa: E402
import test_form  # noqa: E402
import pg_sema_kume  # noqa: E402
import pg_yardimci  # noqa: E402
from ortak import pg  # noqa: E402
from ortak import sinir_pg  # noqa: E402

GOOD = test_form.GOOD
iletisim_pg = server._pg_modul()


@pg_yardimci.pg_testi(pg_sema_kume.PG_VAR, pg_sema_kume.PG_NEDEN)
class FormPgTests(test_form.FormOrtak, pg_sema_kume.SemaKumesi, unittest.TestCase):
    LIMIT = 50

    def sunucu(self, baglan, limit=None, pg_nesnesi=True):
        pol = dict(sinir_pg.SINIRLAR, iletisim=sinir_pg.Politika(limit or self.LIMIT, 3600))
        sn = sinir_pg.SinirPg(baglan, tuz="tuz", politikalar=pol)
        self.addCleanup(sn.kapat)
        depo = iletisim_pg.IletisimPg(baglan)
        self.addCleanup(depo.kapat)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(None, iletisim_pg.FormSinir(sn), "tuz", pg=depo))
        srv.request_queue_size = 128   # set after bind in the stdlib: re-listen so the 30 simultaneous clients are not reset
        srv.socket.listen(128)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def setUp(self):
        self.sql("TRUNCATE alig.contact, alig.sinir_sayac")
        self.srv = self.sunucu(lambda: pg.Baglanti.baglan(**self.app_ayar()))

    def rows(self):
        out = self.sql("SELECT name || '|' || db || '|' || to_char(created_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') || '|' || ip_hash "
                       "FROM alig.contact ORDER BY id")
        return [tuple(x.split("|")) for x in out.split("\n")] if out else []

    def get(self, srv, yol="/healthz"):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_port)
        c.request("GET", yol)
        r = c.getresponse()
        r.read()
        return r

    def post_srv(self, srv, data=GOOD):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_port)
        c.request("POST", "/api/iletisim", body=urlencode(data).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.read()
        return r

    def test_rate_limit_429_ve_retry_after(self):
        srv = self.sunucu(lambda: pg.Baglanti.baglan(**self.app_ayar()), limit=3)
        yanit = [self.post_srv(srv) for _ in range(4)]
        self.assertEqual([r.status for r in yanit], [303, 303, 303, 429])
        ra = int(yanit[3].getheader("Retry-After"))
        self.assertTrue(1 <= ra <= 3600, ra)
        self.assertEqual(len(self.rows()), 3)

    def test_sinir_iki_sunucu_ornegi_arasinda_paylasilir(self):
        a = self.sunucu(lambda: pg.Baglanti.baglan(**self.app_ayar()), limit=4)
        b = self.sunucu(lambda: pg.Baglanti.baglan(**self.app_ayar()), limit=4)
        kodlar = [self.post_srv(s).status for s in (a, b, a, b, a, b)]
        self.assertEqual(kodlar, [303, 303, 303, 303, 429, 429])   # a per-process in-memory limiter would have allowed 8

    def test_es_zamanli_http_istekleri_siniri_asmaz(self):
        srv = self.sunucu(lambda: pg.Baglanti.baglan(**self.app_ayar()), limit=5)
        n, bar, kodlar = 30, threading.Barrier(30), []

        def is_():
            bar.wait(10)
            kodlar.append(self.post_srv(srv).status)
        ts = [threading.Thread(target=is_) for _ in range(n)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        self.assertEqual(sorted(kodlar), [303] * 5 + [429] * 25)
        self.assertEqual(len(self.rows()), 5)

    def test_hata_kayit_edilmez_sayac_yine_artar(self):
        # an invalid request still costs one unit of the limit (like the SQLite limiter: the count is taken before validation)
        srv = self.sunucu(lambda: pg.Baglanti.baglan(**self.app_ayar()), limit=2)
        self.assertEqual(self.post_srv(srv, {**GOOD, "email": "x"}).status, 422)
        self.assertEqual(self.post_srv(srv).status, 303)
        self.assertEqual(self.post_srv(srv).status, 429)

    def test_rate_limit_ayrica_iletisim_kovasinda_sayilir(self):
        self.post_srv(self.srv)
        self.assertEqual(self.sql("SELECT kova || ' ' || adet FROM alig.sinir_sayac"), "iletisim 1")

    def test_veritabani_yoksa_503_ve_retry_after_kayit_yok(self):
        def kopuk():
            return pg.Baglanti.baglan(host="/nonexistent-alig-dir", port=1, dbname="x", user="x", baglanti_zaman_asimi=2)
        srv = self.sunucu(kopuk)
        r = self.post_srv(srv)
        self.assertEqual(r.status, 503)
        self.assertEqual(r.getheader("Retry-After"), "30")
        h = self.get(srv)
        self.assertEqual((h.status, h.getheader("Retry-After")), (503, "30"))
        self.assertEqual(self.rows(), [])

    def test_kayit_yazilamazsa_503_sqlite_kullanilmaz(self):
        """The limiter works but the INSERT is refused by the database (privilege removed for this test): 503, no SQLite fallback, no row."""
        self.sql("REVOKE INSERT ON alig.contact FROM alig_app")
        self.addCleanup(self.sql, "GRANT INSERT ON alig.contact TO alig_app")
        r = self.post(GOOD)
        self.assertEqual((r.status, r.getheader("Retry-After")), (503, "30"))
        self.assertEqual(self.rows(), [])

    def test_baglantilar_havuzla_sinirli_kalir(self):
        """ThreadingHTTPServer starts a thread per request: connections must be pooled, not one per request thread."""
        for _ in range(40):
            self.assertEqual(self.post(GOOD).status, 303)
        n = int(self.sql("SELECT count(*) FROM pg_stat_activity WHERE usename = 'alig_app'"))
        self.assertLessEqual(n, 4)

    def test_main_postgresql_ayarli_ama_ulasilamazsa_baslamaz(self):
        eski = server._pg_ayar
        server._pg_ayar = lambda ortam: dict(host="/nonexistent-alig-dir", port=1, dbname="x", user="x", baglanti_zaman_asimi=2)
        self.addCleanup(setattr, server, "_pg_ayar", eski)
        with self.assertRaises(SystemExit) as c:
            server.main(["--salt", "x", "--port", "0"])
        self.assertIn("refusing to fall back to SQLite", str(c.exception))

    def test_saglik_200(self):
        self.assertEqual(self.get(self.srv).status, 200)

    def test_baglanti_koparsa_hata_bildirilir_sonra_yeniden_baglanir(self):
        self.assertEqual(self.post(GOOD).status, 303)
        self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'alig_app' AND pid <> pg_backend_pid()")
        # the limiter pool and the store pool each hold one dead connection: a broken one is reported (503), never retried or
        # silently replaced by SQLite, and discarded; within a few requests both pools have reconnected
        kodlar = [self.post(GOOD).status for _ in range(4)]
        self.assertEqual(kodlar[0], 503)
        self.assertEqual(kodlar[-1], 303)
        self.assertEqual(set(kodlar) - {503, 303}, set())
        self.assertEqual(len(self.rows()), 1 + kodlar.count(303))


if __name__ == "__main__":
    unittest.main()
