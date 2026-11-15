#!/usr/bin/env python3
"""PostgreSQL schema migration applier (ALIG-DB-003a). Standard library only; uses a psql subprocess.

  PGHOST=... PGPORT=... PGDATABASE=aligtech PGUSER=... python3 db/uygula.py [--dizin db/sema]

Migrations are NNNN_name.sql files and are applied in order. Each file runs in a SINGLE transaction (psql -1, ON_ERROR_STOP=1) and the
alig.schema_migrations row is written in the same transaction: a file that stops halfway leaves no trace. If the SHA-256 digest of a
previously applied file has changed, it stops without applying anything. Connection information comes from environment variables; the password is not
put on the command line (use ~/.pgpass or PGPASSFILE for the password). The first file (0001) is applied by an administrator with CREATEROLE privilege."""
import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

VARSAYILAN_DIZIN = Path(__file__).resolve().parent / "sema"
DOSYA_AD = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
GEREKLI_ORTAM = ("PGHOST", "PGDATABASE", "PGUSER")
ZAMAN_ASIMI = 300
KILIT_NO = 7430031  # pg_advisory_xact_lock: so two appliers do not apply the same file at the same time


class GocHatasi(Exception):
    pass


def dosyalari_oku(dizin):
    """[(name, path, sha256)] in order. GocHatasi on an invalid name, a duplicate number or a gap in numbering."""
    liste, gorulen = [], set()
    for p in sorted(Path(dizin).iterdir()):
        if not p.is_file() or p.suffix != ".sql":
            continue
        m = DOSYA_AD.match(p.name)
        if not m:
            raise GocHatasi("invalid migration file name: %s (expected: NNNN_name.sql)" % p.name)
        no = int(m.group(1))
        if no in gorulen:
            raise GocHatasi("duplicate migration number: %04d" % no)
        gorulen.add(no)
        liste.append((p.name, p, hashlib.sha256(p.read_bytes()).hexdigest()))
    for i, (ad, _, _) in enumerate(liste, 1):
        if int(ad[:4]) != i:
            raise GocHatasi("gap in migration numbering: expected %04d, found %s" % (i, ad))
    return liste


def psql_argv(dosya=None, degiskenler=None):
    """The psql command: -X (no psqlrc), single transaction (-1), stop at the first error. No password or connection information in the arguments."""
    argv = ["psql", "-X", "-q", "-1", "-v", "ON_ERROR_STOP=1"]
    for k, v in (degiskenler or {}).items():
        argv += ["-v", "%s=%s" % (k, v)]
    argv += ["-c", "SELECT pg_advisory_xact_lock(%d)" % KILIT_NO]
    if dosya is not None:
        argv += ["-f", str(dosya)]
    return argv


def _ortam():
    e = dict(os.environ)
    e.setdefault("PGCONNECT_TIMEOUT", "10")
    if "lock_timeout" not in e.get("PGOPTIONS", ""):
        e["PGOPTIONS"] = (e.get("PGOPTIONS", "") + " -c lock_timeout=30s").strip()
    return e


def _calistir(argv, girdi=None):
    try:
        return subprocess.run(argv, input=girdi, capture_output=True, text=True, env=_ortam(), timeout=ZAMAN_ASIMI)
    except FileNotFoundError:
        raise GocHatasi("psql not found (PATH)")
    except subprocess.TimeoutExpired:
        raise GocHatasi("psql did not finish within %d s" % ZAMAN_ASIMI)


def uygulananlar():
    """{version: sha256}; empty if schema_migrations does not exist yet."""
    r = _calistir(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                  "SELECT to_regclass('alig.schema_migrations') IS NOT NULL;")
    if r.returncode != 0:
        raise GocHatasi("could not connect to the database: %s" % r.stderr.strip())
    if r.stdout.strip() != "t":
        return {}
    r = _calistir(["psql", "-X", "-A", "-t", "-F", " ", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                  "SELECT surum, dosya_sha256 FROM alig.schema_migrations ORDER BY surum;")
    if r.returncode != 0:
        raise GocHatasi("could not read schema_migrations: %s" % r.stderr.strip())
    return dict(satir.split(" ", 1) for satir in r.stdout.splitlines() if satir.strip())


def planla(dosyalar, uygulanan):
    """Files to apply. GocHatasi on a changed or missing old file, or on a new file out of order."""
    adlar = {ad for ad, _, _ in dosyalar}
    for surum in sorted(uygulanan):
        if surum not in adlar:
            raise GocHatasi("applied migration file not found: %s" % surum)
    bekleyen, bekleyen_basladi = [], False
    for ad, yol, ozet in dosyalar:
        if ad in uygulanan:
            if uygulanan[ad] != ozet:
                raise GocHatasi("applied migration file has been changed: %s (recorded %s..., file %s...); "
                                "an old file must not be changed, add a new migration" % (ad, uygulanan[ad][:12], ozet[:12]))
            if bekleyen_basladi:
                raise GocHatasi("out-of-order migration: %s is applied but a file before it is not" % ad)
        else:
            bekleyen_basladi = True
            bekleyen.append((ad, yol, ozet))
    return bekleyen


# The record row is in the same transaction as the migration file and parameterized (a psql variable, embedded as an escaped :'ad' literal).
KAYIT_SQL = "INSERT INTO alig.schema_migrations(surum, dosya_sha256) VALUES (:'surum', :'sha');\n"


def uygula_dosya(ad, yol, ozet):
    argv = psql_argv(yol, {"surum": ad, "sha": ozet}) + ["-f", "-"]
    r = _calistir(argv, KAYIT_SQL)
    if r.returncode != 0:
        raise GocHatasi("%s could not be applied (transaction rolled back):\n%s" % (ad, r.stderr.strip()))


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="PostgreSQL schema migration applier")
    ap.add_argument("--dizin", default=str(VARSAYILAN_DIZIN), help="directory of migration files (default db/sema)")
    args = ap.parse_args(argv)
    eksik = [k for k in GEREKLI_ORTAM if not os.environ.get(k)]
    if eksik:
        print("error: environment variable missing: %s (PGPORT is optional; the password is not put on the command line)" % ", ".join(eksik), file=sys.stderr)
        return 2
    try:
        dosyalar = dosyalari_oku(args.dizin)
        bekleyen = planla(dosyalar, uygulananlar())
        for ad, yol, ozet in bekleyen:
            uygula_dosya(ad, yol, ozet)
            print("applied: %s" % ad)
    except GocHatasi as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 1
    if not bekleyen:
        print("no new migration (%d files, all applied)" % len(dosyalar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
