"""ALIG-DB-003c test helper: one temporary PG16 cluster with the real schema (db/sema/*.sql applied by db/uygula.py) shared by
the PostgreSQL store tests of a test module, plus a reset that gives every test a fresh database.

Two kinds of connections:
* app_ayar():   the application role alig_app (DML only; what production uses).
* yonetici_ayar(): the cluster superuser, used only for fixtures the application role is not allowed to do (reset, tampering with the
                   audit chain to test detection) and for the reused SQLite-era tests, whose raw-SQL fixtures need those rights.
"""
import os
import subprocess
import sys
import unittest
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
PG_NEDEN = BULGU.neden or ("libpq not found" if not LIBPQ_VAR else "")
DB = "aligtest"


class Ortam:
    kume = None


def kur():
    """Starts the cluster and applies the schema. Called from setUpModule; SkipTest if PostgreSQL 16 or libpq is missing."""
    if not PG_VAR:
        raise unittest.SkipTest(PG_NEDEN or "PostgreSQL 16 yok")
    k = pg_yardimci.GeciciKume()
    k.baslat()
    try:
        k.veritabani_olustur(DB)
        e = k.ortam(DB, "postgres")
        r = subprocess.run([sys.executable, str(ROOT / "db" / "uygula.py")], capture_output=True, text=True, env=e, timeout=120)
        if r.returncode != 0:
            raise RuntimeError("schema could not be applied: " + r.stderr[-500:])
    except BaseException:
        k.durdur()
        raise
    Ortam.kume = k
    return k


def kapat():
    if Ortam.kume is not None:
        Ortam.kume.durdur()
        Ortam.kume = None


def surum():
    return Ortam.kume.surum if Ortam.kume else None


def ayar(kullanici):
    k = Ortam.kume
    return {"host": k.soket, "port": k.port, "dbname": DB, "user": kullanici, "password": None}


def app_ayar():
    return ayar("alig_app")


def yonetici_ayar():
    return ayar("postgres")


def sifirla():
    """Empties every alig table (identity counters restart at 1), as the superuser. A fresh database for the next test."""
    b = pg.Baglanti.baglan(**yonetici_ayar())
    try:
        adlar = [r[0] for r in b.sorgu("SELECT tablename FROM pg_tables WHERE schemaname='alig' AND tablename<>'schema_migrations'")]
        b.sorgu("TRUNCATE " + ", ".join('alig."%s"' % a for a in adlar) + " RESTART IDENTITY CASCADE")
    finally:
        b.kapat()


def yonetici_sql(sql, parametreler=()):
    """One statement as the superuser (fixtures the application role is not allowed to do). Returns the rows."""
    b = pg.Baglanti.baglan(**yonetici_ayar())
    try:
        return b.sorgu(sql, list(parametreler))
    finally:
        b.kapat()
