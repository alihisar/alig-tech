#!/usr/bin/env python3
"""Yayin paketi: dist/alig-site-<surum>.tar.gz (tekrarlanabilir: sirali, mtime=0, sahip yok).

  python3 deploy/paketle.py --surum 1.0.0 [--base-url https://alig.tech] [--release]

Icerik: site/ (derlenmis tema c), form/, tarama/, deploy/bakim.py, deploy/duman_testi.py, VERSION, MANIFEST.sha256.
--release: doldurulacak alan kalirsa durur (CI ile ayni denetim).
"""
import argparse
import gzip
import hashlib
import io
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "ci"))
import build as site_build  # noqa: E402
import check_placeholders  # noqa: E402

SURUM = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
KOD_DIZINLERI = ("form", "tarama", "yonetim")
HARIC = ("__pycache__", ".pyc", ".sqlite")


def dosyalar(kok, onek):
    for p in sorted(kok.rglob("*")):
        if p.is_file() and not any(h in p.as_posix() for h in HARIC):
            yield p, f"{onek}/{p.relative_to(kok).as_posix()}"


def paketle(surum, base_url, release=False, out_dir=None):
    if not SURUM.match(surum):
        raise SystemExit("surum X.Y.Z biciminde olmali")
    out_dir = Path(out_dir or ROOT / "dist")
    site_dir = out_dir / "paket-site"
    site_build.build("c", site_dir, base_url, False)
    if release:
        sorunlar = check_placeholders.check(site_dir, True)
        if sorunlar:
            raise SystemExit("doldurulacak alanlar var:\n  " + "\n  ".join(sorunlar))
    girdiler = {}
    for p, ad in dosyalar(site_dir, "site"):
        girdiler[ad] = p.read_bytes()
    for d in KOD_DIZINLERI:
        for p, ad in dosyalar(ROOT / d, d):
            girdiler[ad] = p.read_bytes()
    for ad in ("bakim.py", "duman_testi.py"):
        girdiler["deploy/" + ad] = (ROOT / "deploy" / ad).read_bytes()
    girdiler["VERSION"] = (surum + "\n").encode()
    girdiler["site/surum.txt"] = (surum + "\n").encode()
    manifest = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(girdiler.items()))
    girdiler["MANIFEST.sha256"] = manifest.encode()

    hedef = out_dir / f"alig-site-{surum}.tar.gz"
    out_dir.mkdir(parents=True, exist_ok=True)
    ham = io.BytesIO()
    with tarfile.open(fileobj=ham, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for ad in sorted(girdiler):
            bilgi = tarfile.TarInfo(ad)
            bilgi.size, bilgi.mtime, bilgi.uid, bilgi.gid, bilgi.uname, bilgi.gname = len(girdiler[ad]), 0, 0, 0, "", ""
            bilgi.mode = 0o644
            tar.addfile(bilgi, io.BytesIO(girdiler[ad]))
    with open(hedef, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
        gz.write(ham.getvalue())
    ozet = hashlib.sha256(hedef.read_bytes()).hexdigest()
    (out_dir / f"alig-site-{surum}.tar.gz.sha256").write_text(f"{ozet}  {hedef.name}\n")
    return hedef, ozet


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--surum", required=True)
    ap.add_argument("--base-url", default="https://alig.tech")
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    hedef, ozet = paketle(a.surum, a.base_url, a.release, a.out)
    print(f"{hedef}\nsha256 {ozet}")


if __name__ == "__main__":
    main()
