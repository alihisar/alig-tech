#!/usr/bin/env python3
"""Banned patterns: exaggerated promises and generated-site cliches (text), gradient/glass/shadow/uppercase (style), emoji."""
import json
import re
import sys
from pathlib import Path

from common import ROOT, iter_files, read_text, rel

PHRASES = [
    r"güçlendir", r"dönüştür", r"yenilikçi", r"uçtan uca", r"kesintisiz", r"sıfır kesinti", r"%\s?100",
    r"tam otonom", r"geleceğe taşı", r"çığır açan", r"devrim",
    r"empower", r"transform", r"seamless", r"cutting-edge", r"zero downtime", r"100\s?%",
    r"fully autonomous", r"revolution", r"game-chang", r"next-gen", r"unlock", r"leverage",
]
PHRASE_RX = re.compile("|".join(PHRASES), re.I)
EMOJI_RX = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")
CSS_RX = [
    ("gradient", re.compile(r"gradient\(", re.I)),
    ("glass/blur", re.compile(r"backdrop-filter|blur\(", re.I)),
    ("shadow", re.compile(r"box-shadow|text-shadow|drop-shadow", re.I)),
    ("uppercase transform", re.compile(r"text-transform\s*:\s*uppercase", re.I)),
]


def check(dist, root=ROOT):
    problems = []
    for lang in ("tr", "en"):
        path = Path(root) / "site" / "i18n" / f"{lang}.json"
        for key, value in json.loads(read_text(path)).items():
            m = PHRASE_RX.search(value)
            if m:
                problems.append(f"i18n/{lang}.json:{key}: banned phrase '{m.group(0)}'")
            if EMOJI_RX.search(value):
                problems.append(f"i18n/{lang}.json:{key}: emoji")
    for base in (Path(root) / "site", Path(dist)):
        for path in iter_files(base, {".css"}, skip_dirs=set()):
            text = read_text(path)
            for label, rx in CSS_RX:
                if rx.search(text):
                    problems.append(f"{rel(path, base)}: {label}")
    for path in iter_files(Path(dist), {".html"}, skip_dirs=set()):
        if EMOJI_RX.search(read_text(path)):
            problems.append(f"{rel(path, dist)}: emoji")
    return sorted(set(problems))


if __name__ == "__main__":
    out = check(sys.argv[1])
    print("\n".join(out) or "banned patterns: ok")
    sys.exit(1 if out else 0)
