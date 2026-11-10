#!/usr/bin/env python3
"""Sir taramasi: depo kaynagi ve derlenmis cikti. Ornek degerler (CHANGE_ME, example) hata sayilmaz."""
import re
import sys
from pathlib import Path

from common import ROOT, TEXT_SUFFIXES, iter_files, read_text, rel

PATTERNS = [
    ("ozel anahtar blogu", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("AWS erisim anahtari", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub belirteci", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack belirteci", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Bearer belirteci", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{24,}")),
    ("atanmis sir", re.compile(
        r"(?i)\b[\w.-]*(?:password|passwd|secret|api[_-]?key|token)[\w.-]*\s*[:=]\s*['\"]?([A-Za-z0-9/+_\-.]{12,})")),
]
BENIGN = re.compile(r"CHANGE_ME|example|placeholder|dummy|\$\{|\{\{", re.I)


def scan_tree(base, skip_dirs):
    problems = []
    for path in iter_files(base, TEXT_SUFFIXES, skip_dirs=skip_dirs):
        if path.name.startswith("LICENSE"):
            continue
        for n, line in enumerate(read_text(path).splitlines(), 1):
            if BENIGN.search(line):
                continue
            for label, rx in PATTERNS:
                if rx.search(line):
                    problems.append(f"{rel(path, base)}:{n}: {label}")
    return problems


def check(dist=None, root=ROOT):
    problems = scan_tree(root, {".git", "dist", "__pycache__", "tests"})
    if dist:
        problems += [f"dist/{p}" for p in scan_tree(Path(dist), set())]
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1] if len(sys.argv) > 1 else None)
    print("\n".join(out) or "sir: tamam")
    sys.exit(1 if out else 0)
