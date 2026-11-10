#!/usr/bin/env python3
"""CI tanimlarinda her dis eylem (uses:) 40 haneli commit SHA'sina sabitlenmeli."""
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
            problems.append(f"{rel(path, root)}: SHA'ya sabitlenmemis eylem: {ref}")
    return problems


if __name__ == "__main__":
    out = check(sys.argv[1] if len(sys.argv) > 1 else ROOT)
    print("\n".join(out) or "is akisi sabitleme: tamam")
    sys.exit(1 if out else 0)
