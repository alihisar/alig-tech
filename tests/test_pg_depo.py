"""ALIG-DB-003c: the scan store and the portal store on PostgreSQL (tarama/depo_pg.py, tarama/portal_depo_pg.py).

Part 1 re-runs the EXISTING test classes of the SQLite stores against PostgreSQL 16 (a temporary cluster with the real schema):
the existing test module is imported, its module-level names (depo, portal_depo, ...) are pointed at the PostgreSQL modules for the
duration of each test, and the class is subclassed. Tests that exercise SQLite itself (PRAGMA, sqlite_master, SQLite file
migration, sqlite3.IntegrityError, fake non-hex digests that the PostgreSQL CHECK constraints rightly refuse) are listed in
ATLA with the reason; nothing is skipped silently, and where the behaviour matters it is re-tested natively in part 2.
Part 2: PostgreSQL-native tests (atomic quota, chain, idempotency, least privilege, settings).

Reused classes run as the cluster superuser (their raw-SQL fixtures update tables the application role may not touch);
PgAppRolu... classes in part 2 run the same stores as the least-privileged application role alig_app.
SKIPPED when PostgreSQL 16 or libpq is missing: a skip is never a pass.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_depo_yardimci as Y  # noqa: E402
import pg_yardimci  # noqa: E402
from tarama import depo_pg, portal_depo_pg  # noqa: E402

import test_baglanti  # noqa: E402
import test_gecmis  # noqa: E402
import test_portal  # noqa: E402
import test_posta  # noqa: E402
import test_tarama  # noqa: E402


def setUpModule():
    Y.kur()


def tearDownModule():
    Y.kapat()


# ---------------------------------------------------------------------------------------------------------------------
# Part 1: reuse of the existing tests

class _DepoVekili:
    """Stands in for the module `depo` inside the old test modules: everything is depo_pg, except baglan(path), which treats the path
    as a database name: the first time a path is seen the database is emptied (a fresh database, like a new SQLite file), later
    calls with the same path (a server handler opening a connection per request) just connect."""

    def __init__(self):
        self._gorulen = set()

    def baglan(self, yol):
        if yol not in self._gorulen:
            self._gorulen.add(yol)
            Y.sifirla()
        c = depo_pg.baglan(Y.yonetici_ayar())
        c.execute("SET search_path = alig, pg_catalog")
        return c

    def __getattr__(self, ad):
        return getattr(depo_pg, ad)


class PgYama:
    """Mixin: before the old setUp runs, repoint the old module's names to the PostgreSQL modules."""
    YAMALAR = ()    # ((module, name, "depo" | "portal_depo"), ...)

    def setUp(self):
        Y.sifirla()
        vekil = _DepoVekili()
        for modul, ad, tur in self.YAMALAR:
            p = mock.patch.object(modul, ad, vekil if tur == "depo" else portal_depo_pg)
            p.start()
            self.addCleanup(p.stop)
        super().setUp()


def _modul(adi):
    import importlib
    return importlib.import_module(adi)


from tarama import portal as tportal, posta as tposta, server as tserver  # noqa: E402

SUNUCU_YAMALARI = ((tserver, "depo", "depo"), (tportal, "depo", "depo"), (tportal, "portal_depo", "portal_depo"), (tposta, "depo", "depo"))

# (class, test): reason. These test SQLite itself or use fixtures that PostgreSQL's constraints refuse; each is covered natively in part 2 when it matters.
ATLA = {
    ("DepoTests", "test_wal_ve_surum"): "SQLite PRAGMA (journal_mode, user_version); the PostgreSQL schema version is db/uygula.py (tests/test_pg_sema.py)",
    ("DepoTests", "test_zincir_saglam_ve_kirik"): "tampers with the chain through the same connection; the application role may not UPDATE the chain -> PgZincirTests",
    ("DepoTests", "test_zincir_silinen_kayit"): "tampers with the chain (DELETE) through the same connection -> PgZincirTests",
    ("DepoTests", "test_anahtarli_zincir_ve_eski_kayitlar"): "inserts a 'pre-version' record with a hand-written seq; reproduced natively in PgZincirTests",
    ("DepoTests", "test_anahtarsiz_yeniden_uretilen_zincir_yakalanir"): "tampers with the chain -> PgZincirTests",
    ("DepoTests", "test_zincir_basi_disa_aktarilir_ve_bastan_uretim_yakalanir"): "tampers with the chain -> PgZincirTests",
    ("DepoTests", "test_yapisal_alanlar_ozete_dahil_ve_kisitli"): "tampers with the chain -> PgZincirTests",
    ("DepoTests", "test_alansiz_surume_dusurme_yakalanir"): "tampers with the chain -> PgZincirTests",
    ("DepoTests", "test_eszamanli_surecler_zinciri_bozmaz_kayit_kaybetmez"): "SQLite file + fork helper; the PostgreSQL concurrent chain test is PgZincirTests.test_eszamanli_yazarlar_zinciri_bozmaz_kayit_kaybetmez",
    ("DepoTests", "test_eszamanli_ilk_acilis_ve_goc_cokmez"): "SQLite first-open migration race; PostgreSQL migrations are db/uygula.py (advisory lock, tests/test_pg_sema.py)",
    ("DepoTests", "test_acik_islem_icinde_denetim_ekle_calisir"): "SQLite implicit-transaction semantics (in_transaction after a bare INSERT); nested islem is PgIslemTests",
    ("DepoTests", "test_eski_firma_ve_rapor_tablosu_kimlikleri_korunarak_tasinir"): "SQLite table rebuild migration (AUTOINCREMENT); N/A on PostgreSQL (identity columns); ALIG-DB-004 covers id carry-over",
    ("GirisTests", "test_dogrulanmis_kullanicinin_firmasi_zorunlu"): "expects sqlite3.IntegrityError; PostgreSQL raises ButunlukHatasi (23514) -> PgKisitTests",
    ("OncekiRaporTests", "test_bozuk_eski_kayit_atlanir"): "writes invalid JSON into belge_json; the PostgreSQL CHECK (IS JSON OBJECT) refuses it, which is stronger -> PgKisitTests",
    ("PortalIslemTests", "test_silme_talebi_tek_acik_ve_firma_kapsamli"): "expects sqlite3.IntegrityError and uses a non-timestamp fixture -> PgKisitTests (the store-level concurrency is PgPortalYerelTests)",
    ("SunucuTests", "test_eski_veritabani_goc_eder"): "SQLite file migration of an old database (GOCLER); N/A on PostgreSQL (db/uygula.py, tests/test_pg_sema.py)",
    ("DepoTests", "test_cli_bas_ve_dogrula"): "runs tarama/depo.py against a SQLite file; the PostgreSQL CLI is tested in PgZincirTests.test_cli_bas_ve_dogrula",
}


def _atlama_uygula(sinif, taban_adi):
    for (sinif_adi, test), neden in ATLA.items():
        if sinif_adi == taban_adi and hasattr(sinif, test):
            setattr(sinif, test, unittest.skip("not applicable to PostgreSQL: " + neden)(lambda self: None))


def _uret(modul, taban_adi, yamalar, ad):
    taban = getattr(modul, taban_adi)
    sinif = type(ad, (PgYama, taban), {"YAMALAR": yamalar, "__module__": __name__, "__doc__": "PostgreSQL run of %s.%s" % (modul.__name__, taban_adi)})
    _atlama_uygula(sinif, taban_adi)
    return pg_yardimci.pg_testi(Y.PG_VAR, Y.PG_NEDEN)(sinif)


_TARAMA = ((test_tarama, "depo", "depo"),)
_PORTAL = ((test_portal, "depo", "depo"), (test_portal, "portal_depo", "portal_depo"))

PgDepoTests = _uret(test_tarama, "DepoTests", _TARAMA, "PgDepoTests")
PgKayitTests = _uret(test_portal, "KayitTests", _PORTAL, "PgKayitTests")
PgGirisTests = _uret(test_portal, "GirisTests", _PORTAL, "PgGirisTests")
PgIzolasyonTests = _uret(test_portal, "IzolasyonTests", _PORTAL, "PgIzolasyonTests")
PgPortalIslemTests = _uret(test_portal, "PortalIslemTests", _PORTAL, "PgPortalIslemTests")
PgOncekiRaporTests = _uret(test_gecmis, "OncekiRaporTests", ((test_gecmis, "depo", "depo"),), "PgOncekiRaporTests")
PgPostaKutuTests = _uret(test_posta, "KutuTests", ((test_posta, "depo", "depo"), (tposta, "depo", "depo")), "PgPostaKutuTests")

_SUNUCU = SUNUCU_YAMALARI + ((test_tarama, "depo", "depo"),)
PgSunucuTests = _uret(test_tarama, "SunucuTests", _SUNUCU, "PgSunucuTests")
PgEpostaDogrulamaTests = _uret(test_tarama, "EpostaDogrulamaTests", _SUNUCU, "PgEpostaDogrulamaTests")
PgPortalSunucuTests = _uret(test_portal, "SunucuTests", SUNUCU_YAMALARI + _PORTAL, "PgPortalSunucuTests")
PgPortalIslemHttpTests = _uret(test_portal, "PortalIslemHttpTests", SUNUCU_YAMALARI + _PORTAL, "PgPortalIslemHttpTests")
PgPortalKapaliTests = _uret(test_portal, "KapaliTests", SUNUCU_YAMALARI + _PORTAL, "PgPortalKapaliTests")
PgGecmisSunucuTests = _uret(test_gecmis, "SunucuTests", SUNUCU_YAMALARI + ((test_gecmis, "depo", "depo"), (test_tarama, "depo", "depo")), "PgGecmisSunucuTests")
PgBaglantiSunucuTests = _uret(test_baglanti, "SunucuTests", SUNUCU_YAMALARI + ((test_baglanti, "depo", "depo"), (test_tarama, "depo", "depo")), "PgBaglantiSunucuTests")

if __name__ == "__main__":
    unittest.main()
