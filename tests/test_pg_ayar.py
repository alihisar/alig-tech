"""ALIG-DB-003c: ortak/pg_ayar.py, the one place where ALIG_DB_* settings are parsed. No PostgreSQL needed."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ortak import pg_ayar  # noqa: E402


class PgAyarTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, True))

    def dosya(self, ad, icerik, mod=0o600):
        p = self.d / ad
        p.write_bytes(icerik)
        os.chmod(p, mod)
        return str(p)

    def test_ayar_yoksa_none(self):
        self.assertIsNone(pg_ayar.yukle({}))
        self.assertIsNone(pg_ayar.yukle({"PATH": "/bin", "ALIG_TARAMA_DB": "x.sqlite", "ALIG_PORTAL": "1"}))
        self.assertIsNone(pg_ayar.yukle({"ALIG_DB_HOST": "  ", "ALIG_DB_NAME": ""}))   # empty values count as not set

    def test_unix_soketi_varsayilanlar(self):
        a = pg_ayar.yukle({"ALIG_DB_HOST": "/var/run/postgresql"})
        self.assertEqual(a, {"host": "/var/run/postgresql", "port": 5432, "dbname": "aligtech", "user": "alig_app", "password": None})

    def test_tcp_icin_parola_dosyasi_verify_full_ve_ca_zorunlu(self):
        par = self.dosya("p", b"gizli-parola\n")
        ca = self.dosya("ca.pem", b"-----BEGIN CERTIFICATE-----\n", 0o644)
        a = pg_ayar.yukle({"ALIG_DB_HOST": "db.ornek.test", "ALIG_DB_PORT": "5433", "ALIG_DB_NAME": "x", "ALIG_DB_USER": "alig_app",
                           "ALIG_DB_PAROLA_DOSYASI": par, "ALIG_DB_SSLROOTCERT": ca})
        self.assertEqual(a["password"], "gizli-parola")        # trailing newline removed
        self.assertEqual((a["host"], a["port"], a["dbname"], a["sslmode"], a["sslrootcert"]), ("db.ornek.test", 5433, "x", "verify-full", ca))
        temel = {"ALIG_DB_HOST": "db.ornek.test", "ALIG_DB_PAROLA_DOSYASI": par, "ALIG_DB_SSLROOTCERT": ca}
        for degisim, parca in (({"ALIG_DB_SSLMODE": "require"}, "verify-full"), ({"ALIG_DB_SSLMODE": "disable"}, "verify-full"),
                               ({"ALIG_DB_SSLMODE": "verify-ca"}, "verify-full")):
            with self.assertRaises(pg_ayar.PgAyarHatasi) as e:
                pg_ayar.yukle(dict(temel, **degisim))
            self.assertIn(parca, str(e.exception))
        with self.assertRaises(pg_ayar.PgAyarHatasi) as e:
            pg_ayar.yukle({k: v for k, v in temel.items() if k != "ALIG_DB_SSLROOTCERT"})
        self.assertIn("SSLROOTCERT", str(e.exception))
        with self.assertRaises(pg_ayar.PgAyarHatasi) as e:
            pg_ayar.yukle({k: v for k, v in temel.items() if k != "ALIG_DB_PAROLA_DOSYASI"})
        self.assertIn("PAROLA_DOSYASI", str(e.exception))
        with self.assertRaises(pg_ayar.PgAyarHatasi):
            pg_ayar.yukle(dict(temel, ALIG_DB_SSLROOTCERT=str(self.d / "yok.pem")))

    def test_kismi_ayar_sqlite_a_dusmez(self):
        for ortam in ({"ALIG_DB_NAME": "aligtech"}, {"ALIG_DB_HOTS": "x"}, {"ALIG_DB_PORT": "5432"}):
            with self.assertRaises(pg_ayar.PgAyarHatasi) as e:
                pg_ayar.yukle(ortam)
            self.assertIn("ALIG_DB_HOST is required", str(e.exception))

    def test_gecersiz_degerler(self):
        for ek in ({"ALIG_DB_PORT": "0"}, {"ALIG_DB_PORT": "70000"}, {"ALIG_DB_PORT": "abc"}, {"ALIG_DB_PORT": "-1"},
                   {"ALIG_DB_USER": "postgres"}, {"ALIG_DB_USER": "POSTGRES"}, {"ALIG_DB_HOST": "a b"}, {"ALIG_DB_HOST": "a'b"},
                   {"ALIG_DB_HOST": "a,b"}, {"ALIG_DB_NAME": "x\x00y"}):
            with self.assertRaises(pg_ayar.PgAyarHatasi, msg=str(ek)):
                pg_ayar.yukle(dict({"ALIG_DB_HOST": "/tmp"}, **ek))

    def test_soket_ile_tls_ayari_celisir(self):
        for ek in ({"ALIG_DB_SSLMODE": "verify-full"}, {"ALIG_DB_SSLROOTCERT": "/x"}):
            with self.assertRaises(pg_ayar.PgAyarHatasi):
                pg_ayar.yukle(dict({"ALIG_DB_HOST": "/tmp"}, **ek))

    def test_parola_dosyasi_kurallari_ve_parola_hata_metnine_girmez(self):
        ok = self.dosya("p", b"SirrinKendisi-123\n")
        self.assertEqual(pg_ayar.yukle({"ALIG_DB_HOST": "/tmp", "ALIG_DB_PAROLA_DOSYASI": ok})["password"], "SirrinKendisi-123")
        acik = self.dosya("acik", b"SirrinKendisi-123", 0o644)
        with self.assertRaises(pg_ayar.PgAyarHatasi) as e:
            pg_ayar.yukle({"ALIG_DB_HOST": "/tmp", "ALIG_DB_PAROLA_DOSYASI": acik})
        self.assertIn("chmod 600", str(e.exception))
        self.assertNotIn("SirrinKendisi", str(e.exception))
        for ad, icerik in (("bos", b"\n"), ("ikili", b"\xff\xfe\x00"), ("buyuk", b"x" * 5000)):
            with self.assertRaises(pg_ayar.PgAyarHatasi, msg=ad) as e:
                pg_ayar.yukle({"ALIG_DB_HOST": "/tmp", "ALIG_DB_PAROLA_DOSYASI": self.dosya(ad, icerik)})
            self.assertNotIn("xxxx", str(e.exception))
        with self.assertRaises(pg_ayar.PgAyarHatasi):
            pg_ayar.yukle({"ALIG_DB_HOST": "/tmp", "ALIG_DB_PAROLA_DOSYASI": str(self.d)})          # a directory
        with self.assertRaises(pg_ayar.PgAyarHatasi):
            pg_ayar.yukle({"ALIG_DB_HOST": "/tmp", "ALIG_DB_PAROLA_DOSYASI": str(self.d / "yok")})   # missing

    def test_parola_dogrudan_ortam_degiskeninde_kabul_edilmez(self):
        """The password only comes from a file: there is no ALIG_DB_PAROLA setting, so a password in the environment is not silently used."""
        a = pg_ayar.yukle({"ALIG_DB_HOST": "/tmp", "ALIG_DB_PAROLA": "x"})
        self.assertIsNone(a["password"])

    def test_sonuc_baglan_anahtarlariyla_uyumlu(self):
        import inspect
        from ortak import pg
        kabul = set(inspect.signature(pg.Baglanti.baglan).parameters)
        a = pg_ayar.yukle({"ALIG_DB_HOST": "/tmp"})
        self.assertTrue(set(a) <= kabul, set(a) - kabul)


if __name__ == "__main__":
    unittest.main()
