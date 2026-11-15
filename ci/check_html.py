#!/usr/bin/env python3
"""HTML structure check: balanced tags, unique ids, title, language, no inline script/style (CSP), alt text, labelled fields."""
import sys
from html.parser import HTMLParser
from pathlib import Path

from common import iter_files, read_text, rel

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
UNLABELLED_OK = {"hidden", "submit", "button", "reset", "image"}


class Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.ids = set()
        self.problems = []
        self.titles = 0
        self.title_text = ""
        self.h1 = 0
        self.has_lang = False
        self.has_viewport = False
        self.label_for = set()
        self.controls = []  # (id, aria_label, tag)
        self._in_title = False
        self._script_inline = None

    def err(self, msg):
        line, _ = self.getpos()
        self.problems.append(f"line {line}: {msg}")

    def _open(self, tag, attrs, selfclose):
        a = dict(attrs)
        in_svg = "svg" in self.stack
        if tag == "html" and a.get("lang"):
            self.has_lang = True
        if tag == "meta" and a.get("name") == "viewport":
            self.has_viewport = True
        if tag == "title" and not in_svg:
            self.titles += 1
            self._in_title = True
        if tag == "h1":
            self.h1 += 1
        if "id" in a:
            if a["id"] in self.ids:
                self.err(f"duplicate id: {a['id']}")
            self.ids.add(a["id"])
        for name in a:
            if name.startswith("on"):
                self.err(f"inline event handler: {name} (CSP)")
        if "style" in a:
            self.err("inline style attribute (CSP)")
        if tag == "style":
            self.err("<style> tag (CSP); use a stylesheet file")
        if tag == "script" and not a.get("src") and a.get("type") != "application/ld+json":
            self.err("inline script (CSP)")
        if tag == "img" and "alt" not in a:
            self.err("img without alt")
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in UNLABELLED_OK:
            self.controls.append((a.get("id"), a.get("aria-label"), tag, self.getpos()[0]))
        if tag not in VOID and not selfclose:
            self.stack.append(tag)

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag == "title":
            self._in_title = False
        if not self.stack or self.stack[-1] != tag:
            self.err(f"closing tag does not match: </{tag}> (open: {self.stack[-1] if self.stack else 'none'})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title_text += data

    def finish(self):
        if self.stack:
            self.problems.append(f"unclosed tags: {self.stack}")
        if not self.has_lang:
            self.problems.append("missing <html lang>")
        if not self.has_viewport:
            self.problems.append("missing viewport meta")
        if self.titles != 1 or not self.title_text.strip():
            self.problems.append(f"exactly one non-empty <title> required (found: {self.titles})")
        if self.h1 != 1:
            self.problems.append(f"exactly one <h1> required (found: {self.h1})")
        for cid, aria, tag, line in self.controls:
            if not aria and (not cid or cid not in self.label_for):
                self.problems.append(f"line {line}: unlabelled form field ({tag}, id={cid})")


def check(dist):
    dist = Path(dist)
    problems = []
    for path in iter_files(dist, {".html"}, skip_dirs=set()):
        c = Checker()
        c.feed(read_text(path))
        c.close()
        c.finish()
        problems += [f"{rel(path, dist)}: {p}" for p in c.problems]
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1])
    print("\n".join(out) or "html: ok")
    sys.exit(1 if out else 0)
