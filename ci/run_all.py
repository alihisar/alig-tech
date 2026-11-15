#!/usr/bin/env python3
"""Tum CI denetimlerini sirayla calistirir. Yerelde ve CI'da ayni komut:

  python3 ci/run_all.py --theme a            # birlestirme istegi
  python3 ci/run_all.py --theme a --release  # uretim etiketi: doldurulacak alan kalirsa kirilir
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build"))

import build as site_build  # noqa: E402
import check_banned  # noqa: E402
import check_external  # noqa: E402
import check_html  # noqa: E402
import check_i18n  # noqa: E402
import check_links  # noqa: E402
import check_placeholders  # noqa: E402
import check_secrets  # noqa: E402
import check_size  # noqa: E402
import check_workflows  # noqa: E402
import pg_adimi  # noqa: E402
import uret_readme  # noqa: E402
from common import ROOT  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="c", choices=site_build.THEMES)
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--budget", type=int, default=check_size.DEFAULT_BUDGET)
    args = ap.parse_args(argv)

    dist = ROOT / "dist" / f"ci-{args.theme}"
    results = []   # (ad, durum, ozet): durum "tamam" | "atlandi" | "HATA". "atlandi" basari sayilmaz ama CI'yi dusurmez.

    def step(name, fn):
        """fn sorun listesi dondurur; ya da (durum, ozet satiri, ayrinti listesi) uclusu dondurur."""
        print(f"\n== {name}")
        durum, ozet = None, ""
        try:
            sonuc = fn()
            if isinstance(sonuc, tuple):
                durum, ozet, problems = sonuc
            else:
                problems = sonuc
        except Exception as exc:  # denetimin kendisi coktu: kirmizi say
            problems = [f"denetim coktu: {exc!r}"]
            durum = "HATA"
        if ozet:
            print(f"  {ozet}")
        for p in problems:
            print(f"  - {p}")
        if durum is None:
            durum = "HATA" if problems else "tamam"
        results.append((name, durum, ozet))

    step("derleme", lambda: [] if site_build.main(["--theme", args.theme, "--out", str(dist)]) == 0 else ["derleme basarisiz"])

    def tests():
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-q"],
                           cwd=ROOT, capture_output=True, text=True, timeout=1200)  # asili kalan test CI'yi sonsuza dek bekletmesin
        print(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "")
        return [] if r.returncode == 0 else [r.stderr[-1500:]]

    def toplayici():
        r = subprocess.run([sys.executable, str(ROOT / "tarama" / "uret_toplayici.py"), "--kontrol"], capture_output=True, text=True, timeout=120)
        return [] if r.returncode == 0 else [r.stdout.strip() or r.stderr.strip()]

    def ornek_rapor():
        r = subprocess.run([sys.executable, str(ROOT / "tarama" / "uret_ornek_rapor.py"), "--kontrol"], capture_output=True, text=True, timeout=120)
        return [] if r.returncode == 0 else [r.stdout.strip() or r.stderr.strip()]

    step("toplayici guncel", toplayici)
    step("ornek rapor guncel", ornek_rapor)
    step("birim testleri", tests)

    def pg_testleri():
        # PostgreSQL testleri birim testlerinden ayri sayilir; SKIP basari degildir (ci/pg_adimi.py).
        r = subprocess.run([sys.executable, str(ROOT / "ci" / "pg_adimi.py")], cwd=ROOT, capture_output=True, text=True, timeout=1200)
        try:
            veri = json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return "HATA", "postgresql testleri: sonuc okunamadi", [(r.stderr or r.stdout)[-800:]]
        durum, satir, _ = pg_adimi.ozet(veri["sayilar"], veri["surum"], args.release, veri["pg_var"])
        return durum, satir, veri.get("ayrinti", []) + ([] if durum != "HATA" else ["bu adim --release kipinde ya da FAIL ile kirilir"])

    step("postgresql testleri", pg_testleri)
    step("html yapisi", lambda: check_html.check(dist))
    step("ic baglantilar", lambda: check_links.check(dist))
    step("dis kaynak", lambda: check_external.check(dist))
    step("boyut butcesi", lambda: check_size.check(dist, args.budget))
    step("sir taramasi", lambda: check_secrets.check(dist))
    step("is akisi sabitleme", lambda: check_workflows.check())
    step("yasakli kaliplar", lambda: check_banned.check(dist))
    step("dil esligi", lambda: check_i18n.check(dist))
    step("doldurulacak alanlar", lambda: check_placeholders.check(dist, args.release))
    def readme():
        # Yerelde README kendiliginden guncellenir; CI'da (CI ortam degiskeni) yalnizca denetlenir.
        if os.environ.get("CI"):
            return [] if uret_readme.main(["--kontrol"]) == 0 else ["README otomatik bolumleri guncel degil: python3 ci/uret_readme.py"]
        uret_readme.main([])
        return []

    step("readme guncel", readme)

    failed = [n for n, durum, _ in results if durum == "HATA"]
    print("\n== ozet")
    for name, durum, ozet in results:
        print(f"  {durum:7} {ozet or name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
