#!/usr/bin/env python3
"""PostgreSQL physical backup and restore (ALIG-DB-005). Standard library only; calls the PostgreSQL client tools
(pg_basebackup, pg_verifybackup) as subprocesses. Not tied to the application or to the SQLite backup tool deploy/bakim.py.

  python3 db/yedek.py al --kok /yedek/pg [--bicim duz|tar] [--kullanici alig_backup]
  python3 db/yedek.py dogrula --yedek /yedek/pg/pg-<UTC time>
  python3 db/yedek.py geri-yukle --yedek /yedek/pg/pg-<time> --hedef /bos/dizin [--wal-arsivi /wal] [--hedef-zaman "2026-11-15 10:00:00+00"] [--evet]
  python3 db/yedek.py eskileri-sil --kok /yedek/pg --sakla 7 [--evet]
  python3 db/yedek.py arsiv-onerisi --wal-arsivi /wal

The connection comes from environment variables (PGHOST, PGPORT); the password is NOT put on the command line (PGPASSFILE or peer/socket).
PITR needs a WAL archive (archive_command; `arsiv-onerisi` writes the text, it does NOT touch the server). Point-in-time recovery cannot be done
with the backup directory alone; PITR is not claimed with pg_dump. The backup is not encrypted: there is no symmetric cipher in the standard library
(decision DB-K6, docs/kararlar.md); the backup directory must be on an encrypted volume and be 0700. No command overwrites a running
cluster: restore opens only into an empty target directory and, without --evet, writes only the plan.
Exit code: 0 success (or dry run), 1 error (the target/backup was not touched), 2 usage error."""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

YEDEK_AD = re.compile(r"^pg-(\d{8}T\d{6}Z)$")
GUVENLI_YOL = re.compile(r"^/[A-Za-z0-9_./-]+$")   # paths embedded in restore_command / archive_command
ZAMAN = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}(:?\d{2})?)$")
ZAMAN_ASIMI = 3600
VARSAYILAN_ROL = "alig_backup"


class YedekHatasi(Exception):
    pass


def _arac(ad):
    """Tool path: from ALIG_PG_BIN if given, otherwise from PATH."""
    d = os.environ.get("ALIG_PG_BIN")
    return str(Path(d) / ad) if d else ad


def _calistir(argv, **kw):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=ZAMAN_ASIMI, **kw)
    except FileNotFoundError:
        raise YedekHatasi("tool not found: %s (the PostgreSQL client tools must be in PATH or in ALIG_PG_BIN)" % argv[0])
    except subprocess.TimeoutExpired:
        raise YedekHatasi("timeout: %s" % argv[0])


def basebackup_argv(hedef, bicim="duz", kullanici=VARSAYILAN_ROL):
    """The pg_basebackup command. No password (-w: never prompt); WAL is streamed on the same connection (-X stream); SHA-256 manifest."""
    return [_arac("pg_basebackup"), "-D", str(hedef), "-F", "t" if bicim == "tar" else "p", "-X", "stream",
            "-c", "fast", "--manifest-checksums=SHA256", "-U", kullanici, "-w"]


def _guvenli(arsiv):
    if not GUVENLI_YOL.match(str(arsiv)):
        raise YedekHatasi("the archive path must be absolute and contain only [A-Za-z0-9_./-]: %s" % arsiv)
    return str(arsiv).rstrip("/")


def arsiv_komutu(arsiv):
    """Recommended archive_command: does not overwrite an existing file, first copies to a temporary name and then moves atomically.
    (For documentation and the test cluster; the live server is not changed.)"""
    a = _guvenli(arsiv)
    return "test ! -f %s/%%f && cp %%p %s/%%f.gecici && mv %s/%%f.gecici %s/%%f" % (a, a, a, a)


def restore_komutu(arsiv):
    a = _guvenli(arsiv)
    return "test -f %s/%%f && cp %s/%%f \"%%p\"" % (a, a)


def _sa(deger):
    return "'" + deger.replace("\\", "\\\\").replace("'", "''") + "'"


def kurtarma_ayarlari(arsiv=None, hedef_zaman=None):
    """Lines to be appended to postgresql.auto.conf. archive_mode=off: so the restored cluster does not write to the same archive and corrupt it."""
    if hedef_zaman and not arsiv:
        raise YedekHatasi("--hedef-zaman needs --wal-arsivi (a point in time cannot be restored with the backup alone)")
    satirlar = ["archive_mode = off"]
    if arsiv:
        satirlar.append("restore_command = " + _sa(restore_komutu(arsiv)))
    if hedef_zaman:
        if not ZAMAN.match(hedef_zaman):
            raise YedekHatasi("target time format is invalid (time zone is mandatory, example '2026-11-15 10:00:00+00'): %s" % hedef_zaman)
        satirlar += ["recovery_target_time = " + _sa(hedef_zaman), "recovery_target_action = 'promote'"]
    return satirlar


def _pg_surum(arac):
    r = _calistir([_arac(arac), "--version"])
    m = re.search(r"\(PostgreSQL\)\s+(\d+)", r.stdout) if r.returncode == 0 else None
    if not m:
        raise YedekHatasi("could not read the version of %s" % arac)
    return int(m.group(1))


def bicim_bul(yedek):
    y = Path(yedek)
    return "tar" if (y / "base.tar").is_file() or (y / "base.tar.gz").is_file() else "duz"


def tar_ac(yedek, hedef):
    """Extracts a tar-format backup (base.tar, pg_wal.tar) into the `hedef` directory. Tablespace tar and compressed tar are not supported."""
    y, hedef = Path(yedek), Path(hedef)
    diger = sorted(p.name for p in y.iterdir() if p.name not in ("base.tar", "pg_wal.tar", "backup_manifest"))
    if diger or not (y / "base.tar").is_file():
        raise YedekHatasi("unsupported tar backup (tablespace or compression): %s" % ", ".join(diger or ["base.tar missing"]))
    for ad, alt in (("base.tar", hedef), ("pg_wal.tar", hedef / "pg_wal")):
        if (y / ad).is_file():
            alt.mkdir(parents=True, exist_ok=True)
            with tarfile.open(y / ad) as t:
                t.extractall(alt, filter="data")
    shutil.copyfile(y / "backup_manifest", hedef / "backup_manifest")


def dogrula(yedek):
    """pg_verifybackup. Directly for the plain format; the tar format cannot be verified directly before PG18, so it is extracted to a temporary directory and verified
    (the backup does not change). Returns (ok, output)."""
    y = Path(yedek)
    if not (y / "backup_manifest").is_file():
        return False, "backup_manifest yok: yedek tamamlanmamis ya da bozuk"
    if bicim_bul(y) == "duz":
        r = _calistir([_arac("pg_verifybackup"), str(y)])
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    if _pg_surum("pg_verifybackup") >= 18:
        r = _calistir([_arac("pg_verifybackup"), "-F", "t", str(y)])
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    gecici = Path(tempfile.mkdtemp(prefix="aligdogrula"))
    try:
        tar_ac(y, gecici / "d")
        r = _calistir([_arac("pg_verifybackup"), str(gecici / "d")])
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


def _simdi():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def al(kok, bicim="duz", kullanici=VARSAYILAN_ROL):
    """Full backup. First written to a '.devam' (in progress) directory; if pg_verifybackup passes it is moved to the final name. If it fails the partial directory is deleted."""
    kok = Path(kok)
    kok.mkdir(parents=True, exist_ok=True)
    kok.chmod(0o700)
    ad = "pg-" + _simdi()
    gecici, son = kok / (ad + ".devam"), kok / ad
    if son.exists() or gecici.exists():
        raise YedekHatasi("second backup in the same second: %s" % ad)
    gecici.mkdir(mode=0o700)
    try:
        r = _calistir(basebackup_argv(gecici, bicim, kullanici))
        if r.returncode != 0:
            raise YedekHatasi("pg_basebackup failed:\n%s" % r.stderr.strip())
        tamam, cikti = dogrula(gecici)
        if not tamam:
            raise YedekHatasi("backup verification failed (backup deleted):\n%s" % cikti)
        gecici.rename(son)
    except BaseException:
        shutil.rmtree(gecici, ignore_errors=True)
        raise
    return son


def hedef_bos_mu(hedef):
    h = Path(hedef)
    if h.is_symlink():
        return False, "hedef sembolik baglanti: %s" % h
    if not h.exists():
        return True, "hedef dizin yok, olusturulacak"
    if not h.is_dir():
        return False, "hedef bir dizin degil: %s" % h
    if any(h.iterdir()):
        return False, "hedef dizin bos degil (calisan ya da eski bir kume olabilir; uzerine yazilmaz): %s" % h
    return True, "hedef dizin bos"


def geri_yukle(yedek, hedef, arsiv=None, hedef_zaman=None, evet=False, yaz=print):
    """Writes the plan; if evet, extracts the backup into an empty target directory and adds the recovery settings. YedekHatasi on a non-empty target."""
    y, h = Path(yedek).resolve(), Path(hedef).absolute()
    if not y.is_dir() or not (y / "backup_manifest").is_file():
        raise YedekHatasi("invalid backup directory (no backup_manifest): %s" % y)
    if h == y or y in h.parents or h in y.parents:
        raise YedekHatasi("the target and the backup cannot be nested")
    bos, neden = hedef_bos_mu(h)
    if not bos:
        raise YedekHatasi(neden)
    ayarlar = kurtarma_ayarlari(arsiv, hedef_zaman)
    if arsiv and not Path(arsiv).is_dir():
        raise YedekHatasi("WAL archive directory does not exist: %s" % arsiv)
    tar = bicim_bul(y) == "tar"
    yaz("PLAN geri yukleme: yedek=%s bicim=%s hedef=%s (%s)" % (y, "tar" if tar else "duz", h, neden))
    if arsiv:
        yaz("PLAN kurtarma: recovery.signal + restore_command, " + ("hedef zaman " + hedef_zaman if hedef_zaman else "arsivin sonuna kadar"))
    else:
        yaz("PLAN kurtarma: arsiv yok; yedekteki akitilmis WAL ile tutarli noktaya kadar (zamana donus yok)")
    yaz("PLAN postgresql.auto.conf eklenecek: " + "; ".join(ayarlar))
    yaz("PLAN once pg_verifybackup%s; kume BASLATILMAZ (port, soket ve yapilandirma elle gozden gecirilir)"
        % (" (tar, PG18 oncesi gecici dizinde)" if tar else ""))
    if not evet:
        yaz("KURU CALISTIRMA: hicbir sey yazilmadi; uygulamak icin --evet verin")
        return None
    tamam, cikti = dogrula(y)
    if not tamam:
        raise YedekHatasi("backup verification failed, no restore was done:\n%s" % cikti)
    h.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if tar:
            tar_ac(y, h)
        else:
            for p in sorted(y.iterdir()):
                (shutil.copytree if p.is_dir() else shutil.copy2)(p, h / p.name)
        (h / "backup_manifest").unlink(missing_ok=True)
        h.chmod(0o700)
        with open(h / "postgresql.auto.conf", "a", encoding="utf-8") as f:
            f.write("\n# alig yedek.py geri yukleme (%s)\n%s\n" % (_simdi(), "\n".join(ayarlar)))
        if arsiv:
            (h / "recovery.signal").write_text("")
    except BaseException:
        shutil.rmtree(h, ignore_errors=True)   # a partially extracted target; the target was empty at the start
        raise
    yaz("GERI YUKLENDI: %s (baslatmadan once port/soket ayarlarini denetleyin: kopya, kaynak kumenin yapilandirmasini tasir)" % h)
    return h


def yedekleri_listele(kok):
    """Completed backups, oldest to newest. Only directories named pg-<time>, that have a backup_manifest, and that are not symlinks."""
    kok = Path(kok)
    if not kok.is_dir():
        return []
    return sorted(p for p in kok.iterdir() if YEDEK_AD.match(p.name) and p.is_dir() and not p.is_symlink()
                  and (p / "backup_manifest").is_file())


def eskileri_sil(kok, sakla, evet=False):
    """The newest `sakla` backups remain. sakla >= 1 (deleting all is refused). Returns the list to be deleted; nothing is deleted without evet."""
    if sakla < 1:
        raise YedekHatasi("--sakla must be at least 1")
    liste = yedekleri_listele(kok)
    silinecek = liste[:-sakla] if len(liste) > sakla else []
    if evet:
        for p in silinecek:
            shutil.rmtree(p)
    return silinecek


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="PostgreSQL backup and restore (pg_basebackup + WAL archive)")
    alt = ap.add_subparsers(dest="komut", required=True)
    a = alt.add_parser("al", help="take a full backup and verify it")
    a.add_argument("--kok", required=True)
    a.add_argument("--bicim", choices=("duz", "tar"), default="duz")
    a.add_argument("--kullanici", default=VARSAYILAN_ROL)
    d = alt.add_parser("dogrula", help="pg_verifybackup")
    d.add_argument("--yedek", required=True)
    g = alt.add_parser("geri-yukle", help="extract into an empty target directory (without --evet, plan only)")
    g.add_argument("--yedek", required=True)
    g.add_argument("--hedef", required=True)
    g.add_argument("--wal-arsivi")
    g.add_argument("--hedef-zaman")
    g.add_argument("--evet", action="store_true")
    e = alt.add_parser("eskileri-sil", help="keep the newest N backups (without --evet, only lists)")
    e.add_argument("--kok", required=True)
    e.add_argument("--sakla", type=int, required=True)
    e.add_argument("--evet", action="store_true")
    o = alt.add_parser("arsiv-onerisi", help="writes an archive_command suggestion (does not touch the server)")
    o.add_argument("--wal-arsivi", required=True)
    args = ap.parse_args(argv)
    try:
        if args.komut == "al":
            print("backup taken and verified: %s" % al(args.kok, args.bicim, args.kullanici))
        elif args.komut == "dogrula":
            tamam, cikti = dogrula(args.yedek)
            print(cikti or ("backup verified" if tamam else "backup could not be verified"))
            return 0 if tamam else 1
        elif args.komut == "geri-yukle":
            geri_yukle(args.yedek, args.hedef, args.wal_arsivi, args.hedef_zaman, args.evet)
        elif args.komut == "eskileri-sil":
            s = eskileri_sil(args.kok, args.sakla, args.evet)
            for p in s:
                print(("deleted: " if args.evet else "to be deleted: ") + str(p))
            if not s:
                print("no backup to delete")
            elif not args.evet:
                print("DRY RUN: nothing was deleted; use --evet to delete")
        else:
            print("archive_mode = on")
            print("archive_command = " + _sa(arsiv_komutu(args.wal_arsivi)))
            print("# The WAL archive directory must belong to the server user, be 0700 and be on an encrypted volume; this command does not touch the server.")
    except YedekHatasi as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
