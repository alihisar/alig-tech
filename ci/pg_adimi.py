#!/usr/bin/env python3
"""ALIG-CI-001: the "postgresql tests" CI step. Runs the PostgreSQL tests (classes tagged PG_TESTI under tests/)
separately from the unit tests; the summary reports the PASS/FAIL/SKIP counts and the PostgreSQL version.

SKIP does not count as success: if PostgreSQL is missing or some tests were skipped, the summary line says "skipped" and not "ok".
CI normally does not fail; in --release mode (production tag) a skipped PostgreSQL test is an error (v5: "a test that did not run is not a PASS").

  python3 ci/pg_adimi.py            # prints a JSON result line (run_all.py reads it)
"""
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import pg_yardimci  # noqa: E402


class _Sayac(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.gecen = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.gecen += 1


def _duzlestir(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _duzlestir(t)
        else:
            yield t


def calistir_sayilari(root=ROOT, dahil=None):
    """Runs the tests tagged PG_TESTI: ({'PASS':n,'FAIL':n,'SKIP':n}, details). dahil: only these test modules."""
    root = Path(root)
    yukleyici = unittest.TestLoader()
    if dahil:
        suite = unittest.TestSuite(yukleyici.loadTestsFromName(m) for m in dahil)
    else:
        suite = yukleyici.discover(str(root / "tests"))
    secilen = unittest.TestSuite(t for t in _duzlestir(suite) if getattr(type(t), "PG_TESTI", False))
    akim = io.StringIO()
    sonuc = unittest.TextTestRunner(stream=akim, verbosity=0, resultclass=_Sayac).run(secilen)
    sayilar = {"PASS": sonuc.gecen, "FAIL": len(sonuc.failures) + len(sonuc.errors) + len(sonuc.unexpectedSuccesses),
               "SKIP": len(sonuc.skipped)}
    ayrinti = [str(t) + ": " + m.strip().splitlines()[-1] for t, m in sonuc.failures + sonuc.errors if m.strip()]
    return sayilar, ayrinti


def pg_surumu():
    """(pg_var, version): external server or the system PostgreSQL binary."""
    d = pg_yardimci.dis_hedef()
    if d:
        try:
            r = subprocess.run(["psql", "-X", "-A", "-t", "-h", d.host, "-p", d.port, "-U", d.kullanici, "-d", "postgres",
                                "-c", "SHOW server_version"], capture_output=True, text=True, timeout=20)
            return True, (r.stdout.strip().split()[0] if r.returncode == 0 and r.stdout.strip() else "unknown")
        except (OSError, subprocess.SubprocessError):
            return True, "unknown"
    b = pg_yardimci.pg_bul()
    return b.var, (b.surum or "unknown") if b.var else None


def ozet(sayilar, surum, release, pg_var):
    """(status, summary line, did CI pass). status: 'ok' | 'skipped' | 'ERROR'.
    'ok' only if FAIL is 0, SKIP is 0 and there is at least one PASS; SKIP never counts as success."""
    p, f, s = sayilar["PASS"], sayilar["FAIL"], sayilar["SKIP"]
    say = "PASS %d / FAIL %d / SKIP %d" % (p, f, s)
    if surum:
        say += " (PostgreSQL %s)" % surum
    if f:
        return "ERROR", "%s: %s" % ("postgresql tests", say), False
    if not pg_var:
        satir = "postgresql tests: skipped (no PostgreSQL); %s" % say
        return ("ERROR", satir + "; in --release mode a skipped PostgreSQL test is an error", False) if release \
            else ("skipped", satir, True)
    if s or not p:
        neden = "partly skipped" if p else "no PostgreSQL test ran, skipped"
        satir = "postgresql tests: %s; %s" % (neden, say)
        return ("ERROR", satir + "; in --release mode a skipped PostgreSQL test is an error", False) if release \
            else ("skipped", satir, True)
    return "ok", "postgresql tests: %s" % say, True


def main(argv=None):
    pg_var, surum = pg_surumu()
    sayilar, ayrinti = calistir_sayilari()
    print(json.dumps({"sayilar": sayilar, "surum": surum, "pg_var": pg_var, "ayrinti": ayrinti}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
