#!/usr/bin/env python3
"""'[doldurulacak ...]' alanlarini listeler. --release ile (uretim etiketi) kalan alan varsa kirilir.

--write docs/doldurulacak.md kaynak metinlerdeki (site/i18n) alanlari belge olarak yazar.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from common import ROOT, iter_files, read_text, rel

MARK = re.compile(r"\[doldurulacak[^\]]*\]")


def scan_dist(dist):
    found = {}
    for path in iter_files(dist, {".html"}, skip_dirs=set()):
        hits = MARK.findall(read_text(path))
        if hits:
            found[rel(path, dist)] = hits
    return found


def scan_i18n(root=ROOT):
    rows = []
    for lang in ("tr", "en"):
        data = json.loads(read_text(Path(root) / "site" / "i18n" / f"{lang}.json"))
        for key, value in data.items():
            for hit in MARK.findall(value):
                rows.append((lang, key, hit))
    return rows


def render_doc(rows):
    lines = ["# Doldurulması gereken alanlar", "",
             "Bu liste `python3 ci/check_placeholders.py --write docs/doldurulacak.md` ile üretilir.",
             "Üretim etiketinde (`--release`) bu alanlardan biri kalırsa CI kırılır.", "",
             "| Dil | Anahtar | Alan |", "| --- | --- | --- |"]
    lines += [f"| {lang} | `{key}` | {hit} |" for lang, key, hit in rows]
    lines += ["", "Diğer açık kararlar (metinde değil, yapılandırmada):", "",
              "- İletişim e-posta adresi, CI sağlayıcısı, barındırma sağlayıcısı, hedef müşteri kesimi",
              "- KVKK aydınlatma ve çerez metinleri (hukukçu onayı)", ""]
    return "\n".join(lines)


def check(dist, release=False):
    found = scan_dist(dist)
    for page, hits in found.items():
        print(f"{page}: {len(hits)} alan")
    if release and found:
        return [f"{p}: {len(h)} doldurulmamış alan" for p, h in found.items()]
    return []


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--write")
    args = ap.parse_args()
    if args.write:
        Path(args.write).write_text(render_doc(scan_i18n()), encoding="utf-8")
        print(f"yazildi: {args.write}")
    out = check(args.dist, args.release)
    print("\n".join(out) or "placeholder: tamam")
    sys.exit(1 if out else 0)
