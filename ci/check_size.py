#!/usr/bin/env python3
"""Size budget: total bytes of the home page (HTML + CSS + JS + font + icon).

For each language, all resources the home page requests are counted once. Font subsets (latin, latin-ext)
are all counted because both are downloaded for Turkish text.
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from common import read_text

DEFAULT_BUDGET = 300 * 1024
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.I)


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.refs.append(a["src"])
        if tag == "link" and a.get("href") and set((a.get("rel") or "").split()) & {"stylesheet", "icon"}:
            self.refs.append(a["href"])
        if tag in ("img", "source") and a.get("src"):
            self.refs.append(a["src"])


def local(dist, ref):
    if ref.startswith(("http:", "https:", "//", "data:")):
        return None
    p = dist / urlsplit(ref).path.lstrip("/")
    return p if p.is_file() else None


def page_weight(dist, page):
    refs = Refs()
    refs.feed(read_text(page))
    files = {page: page.stat().st_size}
    for ref in refs.refs:
        p = local(dist, ref)
        if not p:
            continue
        files[p] = p.stat().st_size
        if p.suffix == ".css":
            for u in CSS_URL.findall(read_text(p)):
                q = local(dist, u)
                if q:
                    files[q] = q.stat().st_size
    return files


def check(dist, budget=DEFAULT_BUDGET):
    dist = Path(dist)
    problems = []
    for lang, page in (("tr", dist / "index.html"), ("en", dist / "en" / "index.html")):
        if not page.is_file():
            problems.append(f"{lang}: home page missing ({page})")
            continue
        files = page_weight(dist, page)
        total = sum(files.values())
        print(f"{lang}: {total / 1024:.1f} KB / {budget / 1024:.0f} KB ({len(files)} files)")
        if total > budget:
            top = sorted(files.items(), key=lambda kv: -kv[1])[:5]
            detail = ", ".join(f"{p.name} {s // 1024} KB" for p, s in top)
            problems.append(f"{lang}: home page {total} bytes, budget {budget}. Largest: {detail}")
    return problems


if __name__ == "__main__":
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BUDGET
    out = check(sys.argv[1], budget)
    print("\n".join(out) or "size: ok")
    sys.exit(1 if out else 0)
