#!/usr/bin/env python3
"""Dis kaynak taramasi: derlenmis ciktidan alig.tech disina giden betik, stil, yazi tipi, gorsel istegi varsa kirilir."""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from common import ALLOWED_HOSTS, iter_files, read_text, rel

RESOURCE_REL = {"stylesheet", "preload", "prefetch", "modulepreload", "icon", "apple-touch-icon",
                "preconnect", "dns-prefetch", "manifest", "mask-icon"}
RESOURCE_TAGS = {"script": "src", "img": "src", "source": "src", "iframe": "src", "video": "src",
                 "audio": "src", "embed": "src", "object": "data", "track": "src"}
NAMESPACE_OK = {"www.w3.org"}
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.I)
CSS_IMPORT = re.compile(r"@import\s+(?:url\()?\s*['\"]([^'\"]+)", re.I)
URL_IN_TEXT = re.compile(r"(?:https?:)?//[A-Za-z0-9.\-]+[^\s'\"`)<>]*")


def is_external(url):
    url = url.strip()
    if url.startswith(("data:", "#", "/", "./", "../")) and not url.startswith("//"):
        return False
    if not url.startswith(("http:", "https:", "//")):
        return False
    host = (urlsplit(url if not url.startswith("//") else "https:" + url).hostname or "").lower()
    return host not in ALLOWED_HOSTS and host not in NAMESPACE_OK


class Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link":
            rels = set((a.get("rel") or "").lower().split())
            if rels & RESOURCE_REL and a.get("href") and is_external(a["href"]):
                self.found.append(f"<link rel={a.get('rel')}> -> {a['href']}")
        if tag in RESOURCE_TAGS and a.get(RESOURCE_TAGS[tag]) and is_external(a[RESOURCE_TAGS[tag]]):
            self.found.append(f"<{tag}> -> {a[RESOURCE_TAGS[tag]]}")
        if tag in ("img", "source") and a.get("srcset"):
            for part in a["srcset"].split(","):
                u = part.strip().split(" ")[0]
                if u and is_external(u):
                    self.found.append(f"<{tag} srcset> -> {u}")
        if tag == "form" and a.get("action") and is_external(a["action"]):
            self.found.append(f"<form action> -> {a['action']}")
        if tag == "use":
            ref = a.get("href") or a.get("xlink:href") or ""
            if ref and is_external(ref):
                self.found.append(f"<use> -> {ref}")


def check(dist):
    dist = Path(dist)
    problems = []
    for path in iter_files(dist, {".html"}, skip_dirs=set()):
        s = Scan()
        s.feed(read_text(path))
        problems += [f"{rel(path, dist)}: {f}" for f in s.found]
    for path in iter_files(dist, {".css"}, skip_dirs=set()):
        text = read_text(path)
        for u in CSS_URL.findall(text) + CSS_IMPORT.findall(text):
            if is_external(u):
                problems.append(f"{rel(path, dist)}: css -> {u}")
    for path in iter_files(dist, {".js"}, skip_dirs=set()):
        for u in URL_IN_TEXT.findall(read_text(path)):
            if is_external(u):
                problems.append(f"{rel(path, dist)}: js icinde dis adres -> {u}")
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1])
    print("\n".join(out) or "dis kaynak: tamam")
    sys.exit(1 if out else 0)
