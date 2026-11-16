#!/usr/bin/env python3
"""Accessibility check of the built site (ALIG-UX-001). Standard library only.

Per theme and for both languages it checks:
  - html lang attribute present and equal to the language of the folder (tr at the root, en under en/);
  - alt attribute on every image (alt="" is allowed: decorative);
  - a label for every form field (label[for], wrapping label, aria-label, aria-labelledby);
  - heading order: exactly one h1, the first heading is h1, no level is skipped going down;
  - a visible focus style in the CSS (:focus-visible with an outline) and no rule that removes the outline;
  - colour contrast computed from the CSS tokens (WCAG 2.x AA): 4.5:1 for text pairs, 3:1 for large text and for
    non-text parts (focus ring, field borders). Thresholds are constants below and are never relaxed per page.

Server-rendered pages (tarama/, yonetim/) are out of scope.

  python3 ci/check_a11y.py dist/a --theme a
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from common import iter_files, read_text, rel

TEXT_MIN = 4.5      # WCAG 1.4.3, normal text
LARGE_MIN = 3.0     # WCAG 1.4.3 large text, WCAG 1.4.11 non-text contrast

FIELD_NO_LABEL = {"hidden", "submit", "button", "reset", "image"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

# (foreground, background, minimum ratio, what it is[, scope]). A name is a CSS token, "#rrggbb" is a literal colour.
# scope: a selector whose own custom properties (--focus: ...) override the :root tokens for that pair.
# required: every theme must define these tokens. Optional pairs are skipped when a token is absent.
REQUIRED = [
    ("fg", "bg", TEXT_MIN, "body text"),
    ("muted", "bg", TEXT_MIN, "secondary text"),
    ("on-signal", "signal", TEXT_MIN, "button text"),
    ("focus", "bg", LARGE_MIN, "focus ring"),
]
OPTIONAL = [
    ("fg", "input-bg", TEXT_MIN, "text in fields"),
    ("muted", "input-bg", TEXT_MIN, "secondary text in fields"),
    ("line-strong", "input-bg", LARGE_MIN, "field border"),
    ("term-fg", "term-bg", TEXT_MIN, "console text"),
    ("term-muted", "term-bg", TEXT_MIN, "console secondary text"),
    ("ok", "term-bg", TEXT_MIN, "console status ok"),
    ("bad", "term-bg", TEXT_MIN, "console status failure"),
    ("focus", "term-bg", LARGE_MIN, "focus ring on the console", ".console"),
]
# Colours that a theme hard-codes next to a token (theme file: site/themes/<theme>/style.css).
THEME_PAIRS = {
    "c": [
        ("signal", "bg", TEXT_MIN, "links and labels in signal colour"),
        ("#ffffff", "signal", TEXT_MIN, "top bar and hero text"),
        ("#dfe5ff", "signal", TEXT_MIN, "hero lead text"),
        ("rgba(255,255,255,.82)", "signal", TEXT_MIN, "top bar navigation links (opacity .82)"),
        ("signal", "#ffffff", TEXT_MIN, "button text on the white button"),
        ("#c9d2e4", "fg", TEXT_MIN, "footer text"),
        ("#ffffff", "fg", TEXT_MIN, "footer links"),
        ("#ffffff", "signal", LARGE_MIN, "focus ring on the top bar and hero"),
        ("focus", "term-bg", LARGE_MIN, "focus ring in the audit box", ".audit-box"),
    ],
}


# ---- colour maths -------------------------------------------------------------------------------------------

def parse_colour(text):
    """'#rgb', '#rrggbb', 'rgb(r,g,b)', 'rgba(r,g,b,a)' -> (r, g, b, a). Raises ValueError for anything else."""
    t = text.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3})", t)
    if m:
        return tuple(int(c * 2, 16) for c in m.group(1)) + (1.0,)
    m = re.fullmatch(r"#([0-9a-f]{6})", t)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)", t)
    if m:
        a = m.group(4)
        alpha = 1.0 if a is None else (float(a[:-1]) / 100 if a.endswith("%") else float(a))
        return float(m.group(1)), float(m.group(2)), float(m.group(3)), alpha
    raise ValueError(f"unsupported colour: {text!r}")


def _luminance(rgb):
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    """WCAG contrast ratio. A translucent foreground is composited over the background."""
    b = parse_colour(bg)
    f = parse_colour(fg)
    a = f[3]
    f = tuple(f[i] * a + b[i] * (1 - a) for i in range(3))
    l1, l2 = _luminance(f), _luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ---- CSS ----------------------------------------------------------------------------------------------------

def parse_css(text):
    """Flat list of (selector, {property: value}). At-rules: @media print and @font-face are dropped, other
    blocks (@media ...) are flattened. Enough for this site's hand-written CSS; it is not a general parser."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules = []

    def block(i, skip):
        """Parse rules from position i until the matching '}' (or end); returns the position after it."""
        while i < len(text):
            j = i
            while j < len(text) and text[j] not in "{};":
                j += 1
            if j >= len(text):
                return j
            if text[j] == "}":
                return j + 1
            if text[j] == ";":      # statement at-rule such as @import
                i = j + 1
                continue
            head = text[i:j].strip()
            if head.startswith("@"):
                drop = skip or head.startswith("@font-face") or re.match(r"@media[^{]*\bprint\b", head) is not None \
                    or head.startswith("@keyframes")
                if head.startswith("@font-face") or head.startswith("@keyframes"):
                    k = text.index("}", j)
                    if head.startswith("@keyframes"):
                        k = _skip_block(j)
                    i = k + 1
                    continue
                i = block(j + 1, drop)
                continue
            k = text.index("}", j) if "}" in text[j:] else len(text)
            if not skip:
                decls = {}
                for part in text[j + 1:k].split(";"):
                    if ":" in part:
                        name, _, value = part.partition(":")
                        decls[name.strip().lower()] = value.strip()
                rules.append((head, decls))
            i = k + 1
        return i

    def _skip_block(j):
        depth = 0
        for k in range(j, len(text)):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    return k
        return len(text) - 1

    block(0, False)
    return rules


def tokens_of(rules, scope=":root"):
    """--name -> value from :root rules (plus the rules of `scope`, if given); later rules override earlier ones;
    var(--x) references are resolved."""
    raw = {}
    for owner in (":root", scope):      # the scope's own properties win over :root, whatever the file order
        for selector, decls in rules:
            if owner in {s.strip() for s in selector.split(",")}:
                for name, value in decls.items():
                    if name.startswith("--"):
                        raw[name[2:]] = value

    def resolve(name, seen=()):
        value = raw.get(name)
        m = re.fullmatch(r"var\(\s*--([\w-]+)\s*(?:,[^)]*)?\)", value or "")
        if m:
            if m.group(1) in seen:
                return None
            return resolve(m.group(1), seen + (name,))
        return value

    return {name: resolve(name) for name in raw}


def is_literal(expr):
    return expr.startswith(("#", "rgb"))


def css_problems(dist, theme):
    problems = []
    sheets = [p for p in iter_files(dist, {".css"}, skip_dirs=set())]
    rules = []
    for p in sheets:
        rules += parse_css(read_text(p))
    if not sheets:
        return ["no stylesheet in the build output"], None

    # focus visibility
    has_focus = False
    for selector, decls in rules:
        outline = decls.get("outline", "")
        outline_removed = (outline.split() and outline.split()[0] in ("none", "0", "0px")) \
            or decls.get("outline-style") == "none" or decls.get("outline-width") in ("0", "0px")
        if outline_removed:
            problems.append(f"css: rule removes the focus outline: {selector} {{outline...}}")
        if ":focus-visible" in selector and outline and not outline_removed:
            has_focus = True
    if not has_focus:
        problems.append("css: no :focus-visible rule with an outline (focus must be visible)")

    # contrast
    tokens = tokens_of(rules)

    def value(expr, toks):  # noqa
        return expr if is_literal(expr) else toks.get(expr)

    def is_token(expr):
        return not is_literal(expr)

    pairs = [(p, True) for p in REQUIRED] + [(p, False) for p in OPTIONAL] + [(p, False) for p in THEME_PAIRS.get(theme, [])]
    for pair, required in pairs:
        fg, bg, minimum, what = pair[:4]
        toks = tokens_of(rules, pair[4]) if len(pair) > 4 else tokens
        missing = [e for e in (fg, bg) if is_token(e) and not toks.get(e)]
        if missing:
            if required:
                problems.append(f"css: required colour token missing: --{missing[0]}")
            continue
        try:
            ratio = contrast(value(fg, toks), value(bg, toks))
        except ValueError as exc:
            problems.append(f"css: {what}: {exc}")
            continue
        if ratio < minimum:
            problems.append(f"contrast: {what} ({fg} on {bg}) is {ratio:.2f}:1, needs {minimum:g}:1 "
                            f"({value(fg, toks)} on {value(bg, toks)})")
    return problems, tokens


# ---- HTML ---------------------------------------------------------------------------------------------------

class PageChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems = []
        self.lang = None
        self.in_svg = 0
        self.in_label = 0
        self.headings = []      # (level, line)
        self.ids = set()
        self.label_for = set()
        self.fields = []        # (line, tag, id, labelled, labelledby)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "svg":
            self.in_svg += 1
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "label":
            self.in_label += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag == "img" and "alt" not in a:
            self.problems.append(f"line {line}: img without alt attribute")
        if re.fullmatch(r"h[1-6]", tag) and not self.in_svg:
            self.headings.append((int(tag[1]), line))
        if tag in ("input", "select", "textarea") and (a.get("type") or "text").lower() not in FIELD_NO_LABEL:
            labelled = bool(self.in_label or (a.get("aria-label") or "").strip())
            self.fields.append((line, tag, a.get("id"), labelled, a.get("aria-labelledby")))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "svg":
            self.in_svg -= 1

    def handle_endtag(self, tag):
        if tag == "svg" and self.in_svg:
            self.in_svg -= 1
        if tag == "label" and self.in_label:
            self.in_label -= 1

    def finish(self, expected_lang):
        p = self.problems
        if not (self.lang or "").strip():
            p.append("missing html lang attribute")
        elif self.lang.lower().split("-")[0] != expected_lang:
            p.append(f"html lang={self.lang!r} but this page is in '{expected_lang}'")
        for line, tag, fid, labelled, by in self.fields:
            ok = labelled or (fid and fid in self.label_for) or (by and all(i in self.ids for i in by.split()))
            if not ok:
                p.append(f"line {line}: form field without a label ({tag}, id={fid})")
        h1s = [h for h in self.headings if h[0] == 1]
        if len(h1s) != 1:
            p.append(f"exactly one h1 required (found {len(h1s)})")
        previous = 0
        for level, line in self.headings:
            if level > previous + 1:
                p.append(f"line {line}: heading order: h{level} after "
                         f"{'nothing' if previous == 0 else 'h' + str(previous)}")
            previous = level


def html_problems(dist):
    problems = []
    dist = Path(dist)
    pages = list(iter_files(dist, {".html"}, skip_dirs=set()))
    if not pages:
        return ["no html page in the build output"]
    for required in ("index.html", "en/index.html"):
        if not (dist / required).is_file():
            problems.append(f"{required}: page missing (both languages are checked)")
    for path in pages:
        name = rel(path, dist)
        expected = "en" if name.split("/")[0] == "en" else "tr"
        c = PageChecker()
        c.feed(read_text(path))
        c.close()
        c.finish(expected)
        problems += [f"{name}: {m}" for m in c.problems]
    return problems


def check(dist, theme=None):
    """All problems of one built theme (a list of strings; empty means pass)."""
    dist = Path(dist)
    css, _ = css_problems(dist, theme)
    return html_problems(dist) + css


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("--theme", default=None)
    args = ap.parse_args(argv)
    out = check(args.dist, args.theme)
    print("\n".join(out) or "a11y: ok")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
