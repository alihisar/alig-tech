#!/usr/bin/env python3
"""In CI definitions, every external action (uses:) must be pinned to a 40-character commit SHA."""
import re
import sys
from pathlib import Path

from common import ROOT, read_text, rel

USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.M)
PINNED = re.compile(r"^[\w.\-]+/[\w.\-/]+@[0-9a-f]{40}$")


def check(root=ROOT):
    problems = []
    wf_dir = Path(root) / ".github" / "workflows"
    if not wf_dir.is_dir():
        return problems
    for path in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        for ref in USES.findall(read_text(path)):
            if ref.startswith("./") or PINNED.match(ref):
                continue
            problems.append(f"{rel(path, root)}: action not pinned to a SHA: {ref}")
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1] if len(sys.argv) > 1 else ROOT)
    print("\n".join(out) or "workflow pinning: ok")
    sys.exit(1 if out else 0)
