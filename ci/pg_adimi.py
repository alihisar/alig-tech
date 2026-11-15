#!/usr/bin/env python3
"""ALIG-CI-001: "postgresql testleri" CI adimi. PostgreSQL testlerini (tests/ altinda PG_TESTI etiketli siniflar)
birim testlerinden ayri kosar; ozette PASS/FAIL/SKIP sayisini ve PostgreSQL surumunu yazar.

SKIP basari sayilmaz: PostgreSQL yoksa ya da bir kisim test atlandiysa ozet satiri "atlandı" der ve "tamam" demez.
CI normalde dusmez; --release kipinde (uretim etiketi) atlanan PostgreSQL testi hatadir (v5: "calistirilmayan test PASS sayilmaz").

  python3 ci/pg_adimi.py            # JSON sonuc satiri yazar (run_all.py bunu okur)
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
    """PG_TESTI etiketli testleri kosar: ({'PASS':n,'FAIL':n,'SKIP':n}, ayrintilar). dahil: yalniz bu test modulleri."""
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
    """(pg_var, surum): dis sunucu ya da sistem PostgreSQL ikilisi."""
    d = pg_yardimci.dis_hedef()
    if d:
        try:
            r = subprocess.run(["psql", "-X", "-A", "-t", "-h", d.host, "-p", d.port, "-U", d.kullanici, "-d", "postgres",
                                "-c", "SHOW server_version"], capture_output=True, text=True, timeout=20)
            return True, (r.stdout.strip().split()[0] if r.returncode == 0 and r.stdout.strip() else "bilinmiyor")
        except (OSError, subprocess.SubprocessError):
            return True, "bilinmiyor"
    b = pg_yardimci.pg_bul()
    return b.var, (b.surum or "bilinmiyor") if b.var else None


def ozet(sayilar, surum, release, pg_var):
    """(durum, ozet satiri, CI gecti mi). durum: 'tamam' | 'atlandi' | 'HATA'.
    'tamam' yalnizca FAIL 0, SKIP 0 ve en az bir PASS varsa; SKIP hicbir zaman basari sayilmaz."""
    p, f, s = sayilar["PASS"], sayilar["FAIL"], sayilar["SKIP"]
    say = "PASS %d / FAIL %d / SKIP %d" % (p, f, s)
    if surum:
        say += " (PostgreSQL %s)" % surum
    if f:
        return "HATA", "%s: %s" % ("postgresql testleri", say), False
    if not pg_var:
        satir = "postgresql testleri: atlandı (PostgreSQL yok); %s" % say
        return ("HATA", satir + "; --release kipinde atlanan PostgreSQL testi hatadır", False) if release \
            else ("atlandi", satir, True)
    if s or not p:
        neden = "kısmen atlandı" if p else "çalışan PostgreSQL testi yok, atlandı"
        satir = "postgresql testleri: %s; %s" % (neden, say)
        return ("HATA", satir + "; --release kipinde atlanan PostgreSQL testi hatadır", False) if release \
            else ("atlandi", satir, True)
    return "tamam", "postgresql testleri: %s" % say, True


def main(argv=None):
    pg_var, surum = pg_surumu()
    sayilar, ayrinti = calistir_sayilari()
    print(json.dumps({"sayilar": sayilar, "surum": surum, "pg_var": pg_var, "ayrinti": ayrinti}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
