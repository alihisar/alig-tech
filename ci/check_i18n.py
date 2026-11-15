#!/usr/bin/env python3
"""Two-language parity: translation keys, the English counterpart of every Turkish page, hreflang and html lang."""
import json
import re
import sys
from pathlib import Path

from common import ROOT, iter_files, read_text, rel

HREFLANG = re.compile(r'<link rel="alternate" hreflang="([a-zA-Z-]+)"')
HTML_LANG = re.compile(r'<html lang="([a-z-]+)"')


def check(dist, root=ROOT):
    dist = Path(dist)
    problems = []
    tr = json.loads(read_text(Path(root) / "site" / "i18n" / "tr.json"))
    en = json.loads(read_text(Path(root) / "site" / "i18n" / "en.json"))
    for key in sorted(set(tr) - set(en)):
        problems.append(f"i18n: missing in en.json: {key}")
    for key in sorted(set(en) - set(tr)):
        problems.append(f"i18n: missing in tr.json: {key}")
    for key in sorted(set(tr) & set(en)):
        if not tr[key].strip() or not en[key].strip():
            problems.append(f"i18n: empty value: {key}")

    for path in iter_files(dist, {".html"}, skip_dirs=set()):
        r = Path(rel(path, dist))
        is_en = r.parts[0] == "en"
        counterpart = dist / "en" / r if not is_en else dist / Path(*r.parts[1:])
        if not counterpart.is_file():
            problems.append(f"{r.as_posix()}: counterpart language page missing ({rel(counterpart, dist)})")
        text = read_text(path)
        m = HTML_LANG.search(text)
        if not m or m.group(1) != ("en" if is_en else "tr"):
            problems.append(f"{r.as_posix()}: wrong html lang ({m.group(1) if m else 'none'})")
        langs = set(HREFLANG.findall(text))
        if not {"tr", "en", "x-default"} <= langs:
            problems.append(f"{r.as_posix()}: hreflang incomplete ({sorted(langs)})")
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1])
    print("\n".join(out) or "language parity: ok")
    sys.exit(1 if out else 0)
