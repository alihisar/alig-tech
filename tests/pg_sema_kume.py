"""ALIG-DB-003e test helper: a temporary PostgreSQL 16 cluster with the real schema (db/sema/0001-0006) applied by db/uygula.py.

SemaKumesi is a mixin for unittest.TestCase classes: setUpClass opens the cluster (trust authentication on the Unix socket, this test cluster
only) and applies every migration as the postgres superuser; app_ayar() gives Baglanti kwargs for the NON-superuser application role alig_app.
Tests SKIP (never PASS) when PostgreSQL 16 is missing."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_yardimci  # noqa: E402
from ortak import pg  # noqa: E402

BULGU = pg_yardimci.pg_bul()
try:
    LIBPQ_VAR = pg.kutuphane_yukle() is not None
except pg.KutuphaneHatasi:
    LIBPQ_VAR = False
PG_VAR = BULGU.var and LIBPQ_VAR
PG_NEDEN = BULGU.neden or "libpq yok"
UYGULA = ROOT / "db" / "uygula.py"


class SemaKumesi:
    DB = "aligtest"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kume = pg_yardimci.GeciciKume()
        cls.kume.baslat()
        cls.addClassCleanup(cls.kume.durdur)
        cls.kume.veritabani_olustur(cls.DB)
        r = subprocess.run([sys.executable, str(UYGULA)], capture_output=True, text=True, timeout=120,
                           env=cls.kume.ortam(cls.DB, "postgres"))
        assert r.returncode == 0, r.stderr

    @classmethod
    def app_ayar(cls, kullanici="alig_app", **ek):
        ayar = dict(host=cls.kume.soket, port=cls.kume.port, dbname=cls.DB, user=kullanici)
        ayar.update(ek)
        return ayar

    def baglan(self, kullanici="alig_app", **ek):
        b = pg.Baglanti.baglan(**self.app_ayar(kullanici, **ek))
        self.addCleanup(b.kapat)
        return b

    @classmethod
    def sql(cls, sorgu):
        """Runs trusted fixed SQL as the superuser (setup, inspection and fault injection only)."""
        return cls.kume.sql(sorgu, db=cls.DB)
