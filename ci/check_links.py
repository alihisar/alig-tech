#!/usr/bin/env python3
"""Kirik ic baglanti taramasi: href/src hedefleri ve #parca (id) varligi."""
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from common import iter_files, read_text, rel

SKIP_SCHEMES = ("http:", "https:", "mailto:", "tel:", "data:", "javascript:", "//")


class Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.refs = []  # (url, tag)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "form":
            return  # action sunucu uc noktasidir, dosya degil
        if tag == "link" and "alternate" in (a.get("rel") or "") and "hreflang" in a:
            return  # mutlak adresler, dis kaynak denetimi bakar
        for name in ("href", "src"):
            if a.get(name):
                self.refs.append((a[name], tag))


def url_to_file(dist, url_path):
    if url_path.endswith("/"):
        return dist / url_path.lstrip("/") / "index.html"
    p = dist / url_path.lstrip("/")
    if p.is_file():
        return p
    return p / "index.html"


def check(dist):
    dist = Path(dist)
    pages = {}
    for path in iter_files(dist, {".html"}, skip_dirs=set()):
        c = Collect()
        c.feed(read_text(path))
        pages[path] = c
    problems = []
    for path, c in pages.items():
        page_url = "/" + rel(path, dist).removesuffix("index.html")
        for ref, tag in c.refs:
            if ref.startswith(SKIP_SCHEMES):
                continue
            parts = urlsplit(ref)
            if parts.path == "":
                target_path = path
            else:
                base = parts.path if parts.path.startswith("/") else page_url + parts.path
                target_path = url_to_file(dist, base)
            if not target_path.is_file():
                problems.append(f"{rel(path, dist)}: kirik baglanti <{tag}> {ref}")
                continue
            if parts.fragment and target_path.suffix == ".html":
                ids = pages.get(target_path).ids if target_path in pages else set()
                if parts.fragment not in ids:
                    problems.append(f"{rel(path, dist)}: hedefte id yok {ref}")
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1])
    print("\n".join(out) or "baglanti: tamam")
    sys.exit(1 if out else 0)
