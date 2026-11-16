#!/usr/bin/env python3
"""Runs all CI checks in order. The same command locally and in CI:

  python3 ci/run_all.py --theme a            # pull request
  python3 ci/run_all.py --theme a --release  # production tag: fails if any field remains to be filled in
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
import check_a11y  # noqa: E402
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
    results = []   # (name, status, summary): status "ok" | "skipped" | "ERROR". "skipped" does not count as success but does not fail CI.

    def step(name, fn):
        """fn returns a list of problems, or a (status, summary line, detail list) triple."""
        print(f"\n== {name}")
        durum, ozet = None, ""
        try:
            sonuc = fn()
            if isinstance(sonuc, tuple):
                durum, ozet, problems = sonuc
            else:
                problems = sonuc
        except Exception as exc:  # the check itself crashed: count it as failed
            problems = [f"check crashed: {exc!r}"]
            durum = "ERROR"
        if ozet:
            print(f"  {ozet}")
        for p in problems:
            print(f"  - {p}")
        if durum is None:
            durum = "ERROR" if problems else "ok"
        results.append((name, durum, ozet))

    step("build", lambda: [] if site_build.main(["--theme", args.theme, "--out", str(dist)]) == 0 else ["build failed"])

    def tests():
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-q"],
                           cwd=ROOT, capture_output=True, text=True, timeout=1200)  # a hung test must not make CI wait forever
        print(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "")
        return [] if r.returncode == 0 else [r.stderr[-1500:]]

    def toplayici():
        r = subprocess.run([sys.executable, str(ROOT / "tarama" / "uret_toplayici.py"), "--kontrol"], capture_output=True, text=True, timeout=120)
        return [] if r.returncode == 0 else [r.stdout.strip() or r.stderr.strip()]

    def ornek_rapor():
        r = subprocess.run([sys.executable, str(ROOT / "tarama" / "uret_ornek_rapor.py"), "--kontrol"], capture_output=True, text=True, timeout=120)
        return [] if r.returncode == 0 else [r.stdout.strip() or r.stderr.strip()]

    step("collector up to date", toplayici)
    step("sample report up to date", ornek_rapor)
    step("unit tests", tests)

    def pg_testleri():
        # PostgreSQL tests are counted separately from the unit tests; SKIP is not success (ci/pg_adimi.py).
        r = subprocess.run([sys.executable, str(ROOT / "ci" / "pg_adimi.py")], cwd=ROOT, capture_output=True, text=True, timeout=1200)
        try:
            veri = json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return "ERROR", "postgresql tests: could not read the result", [(r.stderr or r.stdout)[-800:]]
        durum, satir, _ = pg_adimi.ozet(veri["sayilar"], veri["surum"], args.release, veri["pg_var"])
        return durum, satir, veri.get("ayrinti", []) + ([] if durum != "ERROR" else ["this step fails in --release mode or on FAIL"])

    step("postgresql tests", pg_testleri)
    step("html structure", lambda: check_html.check(dist))
    step("internal links", lambda: check_links.check(dist))
    step("external resources", lambda: check_external.check(dist))
    step("size budget", lambda: check_size.check(dist, args.budget))
    def a11y():
        # all three themes, both languages; the build is deterministic and fast, so each theme gets its own tree
        problems = []
        for theme in site_build.THEMES:
            out = ROOT / "dist" / f"a11y-{theme}"
            if site_build.main(["--theme", theme, "--out", str(out)]) != 0:
                problems.append(f"theme {theme}: build failed")
                continue
            problems += [f"theme {theme}: {p}" for p in check_a11y.check(out, theme)]
        return problems

    step("accessibility", a11y)
    step("secret scan", lambda: check_secrets.check(dist))
    step("workflow pinning", lambda: check_workflows.check())
    step("banned patterns", lambda: check_banned.check(dist))
    step("language parity", lambda: check_i18n.check(dist))
    step("placeholders", lambda: check_placeholders.check(dist, args.release))
    def readme():
        # Locally the README is updated automatically; in CI (CI environment variable) it is only checked.
        if os.environ.get("CI"):
            return [] if uret_readme.main(["--kontrol"]) == 0 else ["README auto-generated sections are out of date: python3 ci/uret_readme.py"]
        uret_readme.main([])
        return []

    step("readme up to date", readme)

    failed = [n for n, durum, _ in results if durum == "ERROR"]
    print("\n== summary")
    for name, durum, ozet in results:
        print(f"  {durum:7} {ozet or name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
