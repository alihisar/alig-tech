#!/usr/bin/env python3
"""Updates the README sections that are derived from code (standard library only).

  python3 ci/uret_readme.py            # writes the automatic sections in README.md
  python3 ci/uret_readme.py --kontrol  # returns 1 if out of date (CI uses this)

Automatic sections sit between `<!-- oto:basla name -->` ... `<!-- oto:bitis name -->`
markers; text outside the markers is hand-written and this script does not touch it.
If a route is not found in the server source the script fails: when a route is
removed, the README warns as well.
"""
import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
sys.path.insert(0, str(ROOT / "build"))

import build as site_build  # noqa: E402

# Directory descriptions: the script fails if a directory does not exist.
DIZINLER = [
    ("site/", "Source: `i18n/` (TR and EN texts), `partials/`, `pages/`, `themes/`, `assets/`"),
    ("build/", "`build.py`, reproducible build and SHA-256 manifest"),
    ("ci/", "Check scripts, `run_all.py`, the generator script for this README"),
    ("tests/", "Unit tests"),
    ("docs/", "Design notes, plan, runbook, DNS, fields to be filled in"),
    ("form/", "Contact form endpoint (stdlib, SQLite)"),
    ("tarama/", "Health scan: collector templates, catalog, rules, server, store; `onsurum/` is the SQL Server preview"),
    ("yonetim/", "Admin panel (TOTP login, audit chain)"),
    ("deploy/", "Packaging, maintenance, smoke test, Ansible"),
]

# (path, source file, description). The path must appear in the source file.
ROTALAR = [
    ("/", "site", "Static site (TR), `/en/` English"),
    ("/demo/", "site", "Portal demo (client side only, no server)"),
    ("/saglik-taramasi/", "site", "Scan upload page"),
    ("/tarama-hazirlik/", "site", "Customer preparation guide (scan account, steps)"),
    ("/api/iletisim", "form/server.py", "Contact form (POST)"),
    ("/healthz", "form/server.py", "Form health check"),
    ("/api/tarama/yukle", "tarama/server.py", "Scan file upload (POST)"),
    ("/rapor/<token>/", "tarama/server.py", "Report page (random link)"),
    ("/rapor/<token>/sil", "tarama/server.py", "Delete the report immediately (POST)"),
    ("/rapor/<token>/dogrula", "tarama/server.py", "Email verification: opens the report, spends the allowance (POST, off by default)"),
    ("/api/tarama/saglik", "tarama/server.py", "Scan server health check"),
    ("/api/tarama/baglan", "tarama/server.py", "Direct connection form and request (off by default)"),
    ("/api/tarama/baglan/<token>", "tarama/server.py", "Take the password and run the scan (POST, off by default)"),
    ("/yonetim/giris", "yonetim/server.py", "Admin login (password + TOTP)"),
    ("/yonetim/", "yonetim/server.py", "Overview"),
    ("/yonetim/firmalar", "yonetim/server.py", "Companies: list, active/inactive"),
    ("/yonetim/firmalar/<id>", "yonetim/server.py", "Company details, note, scan allowance, deletion"),
    ("/yonetim/talepler", "yonetim/server.py", "Contact requests"),
    ("/yonetim/firmalar.csv", "yonetim/server.py", "Company list CSV export"),
    ("/yonetim/talepler.csv", "yonetim/server.py", "Request list CSV export"),
    ("/yonetim/taramalar", "yonetim/server.py", "Scan reports"),
    ("/yonetim/denetim", "yonetim/server.py", "Audit log and chain verification"),
    ("/yonetim/sistem", "yonetim/server.py", "System status"),
]

def denetim_adimlari():
    kaynak = (ROOT / "ci" / "run_all.py").read_text(encoding="utf-8")
    return re.findall(r'step\("([^"]+)"', kaynak)


def test_sayisi():
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    return suite.countTestCases()


def bolumleri_uret(hatalar):
    bolum = {}

    tema_metni = ", ".join(f"`{t}`" for t in site_build.THEMES)
    bolum["temalar"] = f"Design themes: {tema_metni}. The default theme is `c` (`--theme c`)."

    adimlar = denetim_adimlari()
    satirlar = [f"{i}. {ad}" for i, ad in enumerate(adimlar, 1)]
    bolum["denetimler"] = (
        f"`run_all.py` runs these {len(adimlar)} checks in order:\n\n"
        + "\n".join(satirlar)
    )
    bolum["testler"] = f"Unit tests: {test_sayisi()} tests (PostgreSQL tests are counted separately in the `postgresql tests` step: an external server if `ALIG_TEST_PG_HOST` is set, otherwise a temporary cluster with the system PostgreSQL 16; if neither exists, SKIP, and an error in `--release` mode)."

    dizin_satirlari = ["| Directory | Contents |", "| --- | --- |"]
    for dizin, aciklama in DIZINLER:
        if not (ROOT / dizin).is_dir():
            hatalar.append(f"directory missing: {dizin}")
        dizin_satirlari.append(f"| `{dizin}` | {aciklama} |")
    bolum["dizinler"] = "\n".join(dizin_satirlari)

    rota_satirlari = ["| Path | Source | Description |", "| --- | --- | --- |"]
    for yol, kaynak, aciklama in ROTALAR:
        if kaynak != "site":
            dosya = ROOT / kaynak
            if not dosya.is_file():
                hatalar.append(f"source file missing: {kaynak}")
                continue
            metin = dosya.read_text(encoding="utf-8")
            ana_yol = yol.split("<")[0].rstrip("/") or "/"
            if ana_yol not in metin:
                hatalar.append(f"route not found in source: {yol} ({kaynak})")
        rota_satirlari.append(f"| `{yol}` | `{kaynak}` | {aciklama} |")
    bolum["rotalar"] = "\n".join(rota_satirlari)

    roller = sorted(p.name for p in (ROOT / "deploy" / "ansible" / "roles").iterdir() if p.is_dir())
    bolum["ansible"] = "Ansible roles: " + ", ".join(f"`{r}`" for r in roller) + "."
    return bolum


def isaretli_yaz(metin, bolum):
    for ad, icerik in bolum.items():
        desen = re.compile(
            rf"(<!-- oto:basla {ad} -->)(.*?)(<!-- oto:bitis {ad} -->)", re.S)
        if not desen.search(metin):
            raise SystemExit(f"marker missing in README: {ad}")
        metin = desen.sub(lambda m: m.group(1) + "\n" + icerik + "\n" + m.group(3), metin, count=1)
    return metin


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kontrol", action="store_true", help="return 1 if out of date")
    args = ap.parse_args(argv)

    hatalar = []
    bolum = bolumleri_uret(hatalar)
    if hatalar:
        for h in hatalar:
            print(f"  - {h}")
        return 1

    mevcut = README.read_text(encoding="utf-8")
    yeni = isaretli_yaz(mevcut, bolum)
    if args.kontrol:
        if yeni != mevcut:
            print("  - README automatic sections are out of date: python3 ci/uret_readme.py")
            return 1
        return 0
    if yeni != mevcut:
        README.write_text(yeni, encoding="utf-8")
        print("README updated.")
    else:
        print("README is already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
