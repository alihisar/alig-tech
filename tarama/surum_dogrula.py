#!/usr/bin/env python3
"""Version verification: runs the collector on the site against a real PostgreSQL server and its streaming standby, and records the result.

Sets up a temporary cluster (initdb), creates scenario objects, starts a streaming standby with pg_basebackup and
runs the collector with these accounts:
  pg_monitor  a role that is only a member of pg_monitor, as in alig-rol.sql (the recommended scan account)
  yetkisiz    a role with no extra privileges
  super       the setup superuser
  yedek       the pg_monitor role, on the standby (evidence of the queries that run on a standby)
Scenario: an invalid index, an inactive replication slot (on the primary and on the standby), dead rows and a table with autovacuum
disabled, a sequence near its limit, an idle open transaction, a role with an MD5 password, a database without connect privilege, a public
schema with CREATE granted to PUBLIC, a sort that writes to a temporary file, a replica whose replay is paused (lagging); if
the package has it, pg_stat_statements is loaded. The status of each check (ok or skipped, with the reason), the row count and the null count are recorded;
the clusters are deleted at the end. It touches only the temporary clusters it created itself.

  python3 tarama/surum_dogrula.py --pg-bin /usr/lib/postgresql/16/bin --cikti docs/surum-dogrulama.json \
      --belge-dizini tests/veri/surum

If --belge-dizini is given, the raw collected documents are written as <dir>/<major version>/<account>.json; the tests use them as real
server output (scenario objects only, no customer data).

Does not run as root (initdb does not allow it). The result goes into docs/surum-matrisi.md (tarama/uret_kurallar.py).
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import katalog, yukleme  # noqa: E402
from tarama.uret_toplayici import katalog_ozeti  # noqa: E402

TOPLAYICI = ROOT / "site" / "assets" / "alig-toplayici.py"
KURUCU = "alig_kurulum"
HESAPLAR = {"pg_monitor": "alig_hc", "yetkisiz": "alig_duz", "super": KURUCU}   # on the primary
YEDEK_HESABI = ("yedek", "alig_hc")                                              # on the standby

KURULUM = [
    "CREATE ROLE alig_hc LOGIN",
    "GRANT pg_monitor TO alig_hc",
    "ALTER ROLE alig_hc SET default_transaction_read_only = on",
    "CREATE ROLE alig_duz LOGIN",
    "SET password_encryption = 'md5'; CREATE ROLE eski_md5 LOGIN PASSWORD 'alig-deneme-md5'",
    'CREATE DATABASE "satis db"',
    "CREATE DATABASE gizli",
    "REVOKE CONNECT ON DATABASE gizli FROM PUBLIC",
    "SELECT pg_create_physical_replication_slot('bos_slot', true)",
]
VERITABANI = [   # inside postgres and "satis db"
    "CREATE TABLE olu (i int) WITH (autovacuum_enabled = false)",
    "INSERT INTO olu SELECT generate_series(1, 30000)",
    "DELETE FROM olu",
    "CREATE TABLE cift (x int)",
    "INSERT INTO cift VALUES (1), (1)",
    "CREATE TABLE buyuk (i int)",
    "INSERT INTO buyuk SELECT generate_series(1, 700000)",
    "CREATE INDEX buyuk_i ON buyuk (i)",   # over 10 MB, never scanned index
    "CREATE SEQUENCE yakin_seq MAXVALUE 100",
    "SELECT setval('yakin_seq', 99)",
]
GECERSIZ_INDEKS = "CREATE UNIQUE INDEX CONCURRENTLY cift_x ON cift (x)"   # fails because of a duplicate value, stays invalid
GECICI_DOSYA = "SET work_mem = '64kB'; SELECT count(*) FROM (SELECT i FROM buyuk ORDER BY i + 0 DESC) s"   # does not use the expression index


def _bos_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _calistir(komut, beklenen_hata=False, **kw):
    r = subprocess.run(komut, capture_output=True, text=True, timeout=180, **kw)
    if (r.returncode != 0) != beklenen_hata:
        raise SystemExit("command %s: %s\n%s" % ("succeeded" if beklenen_hata else "failed", " ".join(map(str, komut)), r.stderr[-2000:]))
    return r.stdout


def _pss_var(pg_bin):
    """Does this PostgreSQL package have the pg_stat_statements library (contrib)?"""
    try:
        lib = subprocess.run([str(Path(pg_bin) / "pg_config"), "--pkglibdir"], capture_output=True, text=True, timeout=30).stdout.strip()
    except OSError:
        lib = ""
    return any((Path(d) / "pg_stat_statements.so").exists() for d in (lib, Path(pg_bin).parent / "lib") if d)


class Kume:
    """Temporary PostgreSQL cluster: unix socket only, random port. A primary and a streaming standby taken from it."""

    def __init__(self, pg_bin, psql):
        self.bin, self.psql = Path(pg_bin), psql
        self.dizin = Path(tempfile.mkdtemp(prefix="alig-surum-"))
        self.veri, self.soket, self.port = self.dizin / "veri", self.dizin / "soket", _bos_port()
        self.yveri, self.ysoket, self.yport = self.dizin / "yedek", self.dizin / "ysoket", _bos_port()
        self.soket.mkdir()
        self.ysoket.mkdir()
        self.pss = _pss_var(pg_bin)
        self.ortak = " -c shared_preload_libraries=pg_stat_statements" if self.pss else ""

    def kur(self):
        _calistir([str(self.bin / "initdb"), "-D", str(self.veri), "-U", KURUCU, "--auth=trust", "-E", "UTF8", "--no-locale"])
        _calistir([str(self.bin / "pg_ctl"), "-D", str(self.veri), "-l", str(self.dizin / "gunluk"), "-w", "start",
                   "-o", "-k %s -p %d -c listen_addresses='' -c wal_level=replica -c max_replication_slots=4%s" % (self.soket, self.port, self.ortak)])

    def yedek_kur(self):
        """Streaming standby: pg_basebackup -R, separate socket and port. Waits until it is streaming."""
        _calistir([str(self.bin / "pg_basebackup"), "-h", str(self.soket), "-p", str(self.port), "-U", KURUCU, "-D", str(self.yveri),
                   "-R", "-X", "stream", "--checkpoint=fast"])   # a spread checkpoint can take minutes
        _calistir([str(self.bin / "pg_ctl"), "-D", str(self.yveri), "-l", str(self.dizin / "ygunluk"), "-w", "start",
                   "-o", "-k %s -p %d -c listen_addresses=''%s" % (self.ysoket, self.yport, self.ortak)])
        for _ in range(150):
            if self.sql("SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'") == "1":
                return
            time.sleep(0.2)
        raise SystemExit("the standby server did not start streaming")

    def sql(self, sql, db="postgres", beklenen_hata=False, yedek=False):
        soket, port = (self.ysoket, self.yport) if yedek else (self.soket, self.port)
        return _calistir([self.psql, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", str(soket), "-p", str(port),
                          "-U", KURUCU, "-d", db, "-c", sql], beklenen_hata=beklenen_hata).strip()

    def kapat(self):
        for veri in (self.yveri, self.veri):
            if veri.exists():
                subprocess.run([str(self.bin / "pg_ctl"), "-D", str(veri), "-m", "immediate", "stop"], capture_output=True, timeout=60)
        shutil.rmtree(self.dizin, ignore_errors=True)


def senaryo(k):
    for s in KURULUM:
        k.sql(s)
    for db in ("postgres", "satis db"):
        for s in VERITABANI:
            k.sql(s, db)
        k.sql(GECERSIZ_INDEKS, db, beklenen_hata=True)
    k.sql("GRANT CREATE ON SCHEMA public TO PUBLIC", "satis db")
    if k.pss:
        k.sql("CREATE EXTENSION pg_stat_statements")
    k.sql(GECICI_DOSYA)


def yedek_senaryosu(k):
    """An inactive slot on the standby; replay is paused and WAL is generated on the primary: the replica falls behind."""
    k.yedek_kur()
    k.sql("SELECT pg_create_physical_replication_slot('yedek_slot', true)", yedek=True)
    k.sql("SELECT pg_wal_replay_pause()", yedek=True)
    k.sql("CREATE TABLE gecikme AS SELECT generate_series(1, 100000) AS i")
    for _ in range(50):   # until the lag becomes visible on the primary
        if k.sql("SELECT coalesce(max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)), 0) > 0 FROM pg_stat_replication") == "t":
            return
        time.sleep(0.2)
    raise SystemExit("the standby did not fall behind")


def bosta_islem(k):
    """An open transaction idling with the setup account: BEGIN, SELECT, then the shell waits (the session waits inside the transaction)."""
    p = subprocess.Popen([k.psql, "-X", "-q", "-h", str(k.soket), "-p", str(k.port), "-U", KURUCU, "-d", "postgres"],
                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                         start_new_session=True)   # at the end it is closed together with the shell's sleep process (_kapat)
    p.stdin.write("BEGIN;\nSELECT 1;\n\\! sleep 300\n")
    p.stdin.flush()
    for _ in range(50):
        if k.sql("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'") != "0":
            return p
        time.sleep(0.1)
    _kapat(p)
    raise SystemExit("no idle transaction was created")


def _kapat(p):
    """The shell started by psql and \\!: they are in the same session group, all are closed."""
    try:
        os.killpg(p.pid, 9)
    except OSError:
        p.kill()


def topla(k, hesap, kullanici, yedek=False):
    cikti = k.dizin / ("%s.json" % hesap)
    soket, port = (k.ysoket, k.yport) if yedek else (k.soket, k.port)
    _calistir([sys.executable, str(TOPLAYICI), "--host", str(soket), "--port", str(port), "--user", kullanici,
               "--dbname", "postgres", "--out", str(cikti)])
    return yukleme.coz(cikti.read_bytes())


def ozetle(belge):
    """Status, row count and null count per check; for a single-row check that carries no name, the values too (comparison
    between accounts). The null count distinguishes an account that sees the row but cannot see its value (for example pg_stat_replication)."""
    kontroller = {}
    for cid, e in sorted(belge["kontroller"].items()):
        if e["durum"] == "ok":
            kontroller[cid] = {"durum": "ok", "satir": len(e["satirlar"]), "atlanan": len(e.get("atlanan") or []),
                               "bos": sum(1 for s in e["satirlar"] for v in s.values() if v is None)}
            if len(e["satirlar"]) == 1 and not katalog.PG_BY_ID[cid]["maske"]:
                kontroller[cid]["deger"] = e["satirlar"][0]
        else:
            kontroller[cid] = {"durum": "hata", "neden": e["neden"]}
    return {"kontroller": kontroller}


def dogrula(pg_bin, psql):
    """(major version, summary, {account: raw document})."""
    k = Kume(pg_bin, psql)
    p = None
    try:
        k.kur()
        tam = k.sql("SELECT version()")
        senaryo(k)
        time.sleep(1.5)   # so the statistics collector can write on PostgreSQL 14 and earlier
        yedek_senaryosu(k)
        p = bosta_islem(k)
        belgeler = {h: topla(k, h, kullanici) for h, kullanici in HESAPLAR.items()}
        belgeler[YEDEK_HESABI[0]] = topla(k, YEDEK_HESABI[0], YEDEK_HESABI[1], yedek=True)
        ana = int(k.sql("SHOW server_version_num")) // 10000
    finally:
        if p:
            _kapat(p)
        k.kapat()
    return ana, {"tam_surum": tam, "tarih": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "katalog_sha256": katalog_ozeti(),
                 "hesaplar": {h: ozetle(b) for h, b in belgeler.items()}}, belgeler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pg-bin", action="append", required=True, help="directory of initdb, pg_ctl and postgres (may be given more than once)")
    ap.add_argument("--psql", default=shutil.which("psql") or "psql")
    ap.add_argument("--cikti", default="-", help="result JSON file (appended to an existing file) or - (standard output)")
    ap.add_argument("--belge-dizini", help="directory to write the raw documents to (<dir>/<major version>/<account>.json)")
    a = ap.parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("error: does not run as root (initdb does not allow it); run it as a separate user", file=sys.stderr)
        return 2
    kayit = {"surumler": {}}
    if a.cikti != "-" and Path(a.cikti).exists():
        kayit = json.loads(Path(a.cikti).read_text(encoding="utf-8"))
    for b in a.pg_bin:
        ana, sonuc, belgeler = dogrula(b, a.psql)
        kayit["surumler"][str(ana)] = sonuc
        if a.belge_dizini:
            d = Path(a.belge_dizini) / str(ana)
            d.mkdir(parents=True, exist_ok=True)
            for h, belge in belgeler.items():
                (d / ("%s.json" % h)).write_text(json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        print("PostgreSQL %d: %s" % (ana, sonuc["tam_surum"]), file=sys.stderr)
    metin = json.dumps(kayit, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if a.cikti == "-":
        sys.stdout.write(metin)
    else:
        Path(a.cikti).write_text(metin, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
