#!/usr/bin/env python3
"""PostgreSQL sema gocu uygulayici (ALIG-DB-003a). Yalniz standart kutuphane; psql alt sureci kullanir.

  PGHOST=... PGPORT=... PGDATABASE=aligtech PGUSER=... python3 db/uygula.py [--dizin db/sema]

Gocler NNNN_ad.sql dosyalaridir ve sirayla uygulanir. Her dosya TEK islemde (psql -1, ON_ERROR_STOP=1) calisir ve
alig.schema_migrations satiri ayni islemde yazilir: yarida kalan dosya hicbir iz birakmaz. Daha once uygulanmis bir dosyanin
SHA-256 ozeti degismisse hicbir sey uygulanmadan durulur. Baglanti bilgisi ortam degiskenlerindendir; parola komut satirina
konmaz (parola icin ~/.pgpass ya da PGPASSFILE kullanilir). Ilk dosya (0001) CREATEROLE yetkili yoneticiyle uygulanir."""
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
KILIT_NO = 7430031  # pg_advisory_xact_lock: ayni anda iki uygulayici ayni dosyayi uygulamasin


class GocHatasi(Exception):
    pass


def dosyalari_oku(dizin):
    """[(ad, yol, sha256)] sirali. Gecersiz ad, yinelenen numara ya da numara boslugu GocHatasi."""
    liste, gorulen = [], set()
    for p in sorted(Path(dizin).iterdir()):
        if not p.is_file() or p.suffix != ".sql":
            continue
        m = DOSYA_AD.match(p.name)
        if not m:
            raise GocHatasi("gecersiz goc dosya adi: %s (beklenen: NNNN_ad.sql)" % p.name)
        no = int(m.group(1))
        if no in gorulen:
            raise GocHatasi("yinelenen goc numarasi: %04d" % no)
        gorulen.add(no)
        liste.append((p.name, p, hashlib.sha256(p.read_bytes()).hexdigest()))
    for i, (ad, _, _) in enumerate(liste, 1):
        if int(ad[:4]) != i:
            raise GocHatasi("goc numarasinda bosluk: %04d bekleniyordu, %s bulundu" % (i, ad))
    return liste


def psql_argv(dosya=None, degiskenler=None):
    """psql komutu: -X (psqlrc yok), tek islem (-1), ilk hatada dur. Parola ve baglanti bilgisi argumanda yok."""
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
        raise GocHatasi("psql bulunamadi (PATH)")
    except subprocess.TimeoutExpired:
        raise GocHatasi("psql %d sn icinde bitmedi" % ZAMAN_ASIMI)


def uygulananlar():
    """{surum: sha256}; schema_migrations henuz yoksa bos."""
    r = _calistir(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                  "SELECT to_regclass('alig.schema_migrations') IS NOT NULL;")
    if r.returncode != 0:
        raise GocHatasi("veritabanina baglanilamadi: %s" % r.stderr.strip())
    if r.stdout.strip() != "t":
        return {}
    r = _calistir(["psql", "-X", "-A", "-t", "-F", " ", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                  "SELECT surum, dosya_sha256 FROM alig.schema_migrations ORDER BY surum;")
    if r.returncode != 0:
        raise GocHatasi("schema_migrations okunamadi: %s" % r.stderr.strip())
    return dict(satir.split(" ", 1) for satir in r.stdout.splitlines() if satir.strip())


def planla(dosyalar, uygulanan):
    """Uygulanacak dosyalar. Degismis ya da kaybolmus eski dosya, sirasiz yeni dosya GocHatasi."""
    adlar = {ad for ad, _, _ in dosyalar}
    for surum in sorted(uygulanan):
        if surum not in adlar:
            raise GocHatasi("uygulanmis goc dosyasi bulunamadi: %s" % surum)
    bekleyen, bekleyen_basladi = [], False
    for ad, yol, ozet in dosyalar:
        if ad in uygulanan:
            if uygulanan[ad] != ozet:
                raise GocHatasi("uygulanmis goc dosyasi degistirilmis: %s (kayitli %s..., dosya %s...); "
                                "eski dosya degistirilmez, yeni bir goc ekleyin" % (ad, uygulanan[ad][:12], ozet[:12]))
            if bekleyen_basladi:
                raise GocHatasi("sirasiz goc: %s uygulanmis ama kendinden onceki bir dosya uygulanmamis" % ad)
        else:
            bekleyen_basladi = True
            bekleyen.append((ad, yol, ozet))
    return bekleyen


# Kayit satiri, goc dosyasiyla ayni islemde ve parametreli (psql degiskeni, :'ad' kacisli sabit olarak gomulur).
KAYIT_SQL = "INSERT INTO alig.schema_migrations(surum, dosya_sha256) VALUES (:'surum', :'sha');\n"


def uygula_dosya(ad, yol, ozet):
    argv = psql_argv(yol, {"surum": ad, "sha": ozet}) + ["-f", "-"]
    r = _calistir(argv, KAYIT_SQL)
    if r.returncode != 0:
        raise GocHatasi("%s uygulanamadi (islem geri alindi):\n%s" % (ad, r.stderr.strip()))


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="PostgreSQL sema gocu uygulayici")
    ap.add_argument("--dizin", default=str(VARSAYILAN_DIZIN), help="goc dosyalarinin dizini (varsayilan db/sema)")
    args = ap.parse_args(argv)
    eksik = [k for k in GEREKLI_ORTAM if not os.environ.get(k)]
    if eksik:
        print("hata: ortam degiskeni eksik: %s (PGPORT istege bagli; parola komut satirina konmaz)" % ", ".join(eksik), file=sys.stderr)
        return 2
    try:
        dosyalar = dosyalari_oku(args.dizin)
        bekleyen = planla(dosyalar, uygulananlar())
        for ad, yol, ozet in bekleyen:
            uygula_dosya(ad, yol, ozet)
            print("uygulandi: %s" % ad)
    except GocHatasi as ex:
        print("hata: %s" % ex, file=sys.stderr)
        return 1
    if not bekleyen:
        print("yeni göç yok (%d dosya, hepsi uygulanmış)" % len(dosyalar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
