#!/usr/bin/env python3
"""PostgreSQL fiziksel yedek ve geri yukleme (ALIG-DB-005). Yalniz standart kutuphane; PostgreSQL istemci araclarini
(pg_basebackup, pg_verifybackup) alt surecle cagirir. Uygulamaya ve SQLite yedek araci deploy/bakim.py'ye bagli degildir.

  python3 db/yedek.py al --kok /yedek/pg [--bicim duz|tar] [--kullanici alig_backup]
  python3 db/yedek.py dogrula --yedek /yedek/pg/pg-<UTC zaman>
  python3 db/yedek.py geri-yukle --yedek /yedek/pg/pg-<zaman> --hedef /bos/dizin [--wal-arsivi /wal] [--hedef-zaman "2026-11-15 10:00:00+00"] [--evet]
  python3 db/yedek.py eskileri-sil --kok /yedek/pg --sakla 7 [--evet]
  python3 db/yedek.py arsiv-onerisi --wal-arsivi /wal

Baglanti ortam degiskenlerindendir (PGHOST, PGPORT); parola komut satirina KONMAZ (PGPASSFILE ya da peer/soket).
PITR icin WAL arsivi gerekir (archive_command; `arsiv-onerisi` metni yazar, sunucuya DOKUNMAZ). Yalniz yedek dizini ile
zamana donus yapilamaz; pg_dump ile PITR iddia edilmez. Yedek sifrelenmez: standart kutuphanede simetrik sifre yok
(karar DB-K6, docs/kararlar.md); yedek dizini sifreli hacimde ve 0700 olmalidir. Hicbir komut calisan bir kumenin
uzerine yazmaz: geri yukleme yalniz bos hedef dizine acar ve --evet olmadan yalniz plani yazar.
Cikis kodu: 0 basarili (ya da kuru calistirma), 1 hata (hedefe/yedege dokunulmadi), 2 kullanim hatasi."""
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
GUVENLI_YOL = re.compile(r"^/[A-Za-z0-9_./-]+$")   # restore_command / archive_command icine gomulen yollar
ZAMAN = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}(:?\d{2})?)$")
ZAMAN_ASIMI = 3600
VARSAYILAN_ROL = "alig_backup"


class YedekHatasi(Exception):
    pass


def _arac(ad):
    """Arac yolu: ALIG_PG_BIN verilmisse oradan, yoksa PATH."""
    d = os.environ.get("ALIG_PG_BIN")
    return str(Path(d) / ad) if d else ad


def _calistir(argv, **kw):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=ZAMAN_ASIMI, **kw)
    except FileNotFoundError:
        raise YedekHatasi("arac bulunamadi: %s (PostgreSQL istemci araclari PATH'te ya da ALIG_PG_BIN'de olmali)" % argv[0])
    except subprocess.TimeoutExpired:
        raise YedekHatasi("zaman asimi: %s" % argv[0])


def basebackup_argv(hedef, bicim="duz", kullanici=VARSAYILAN_ROL):
    """pg_basebackup komutu. Parola yok (-w: asla sorma); WAL ayni baglantida akitilir (-X stream); SHA-256 manifest."""
    return [_arac("pg_basebackup"), "-D", str(hedef), "-F", "t" if bicim == "tar" else "p", "-X", "stream",
            "-c", "fast", "--manifest-checksums=SHA256", "-U", kullanici, "-w"]


def _guvenli(arsiv):
    if not GUVENLI_YOL.match(str(arsiv)):
        raise YedekHatasi("arsiv yolu mutlak olmali ve yalniz [A-Za-z0-9_./-] icermeli: %s" % arsiv)
    return str(arsiv).rstrip("/")


def arsiv_komutu(arsiv):
    """Onerilen archive_command: var olan dosyanin ustune yazmaz, once gecici ada kopyalar sonra atomik tasir.
    (Belge ve test kumesi icin; canli sunucu degistirilmez.)"""
    a = _guvenli(arsiv)
    return "test ! -f %s/%%f && cp %%p %s/%%f.gecici && mv %s/%%f.gecici %s/%%f" % (a, a, a, a)


def restore_komutu(arsiv):
    a = _guvenli(arsiv)
    return "test -f %s/%%f && cp %s/%%f \"%%p\"" % (a, a)


def _sa(deger):
    return "'" + deger.replace("\\", "\\\\").replace("'", "''") + "'"


def kurtarma_ayarlari(arsiv=None, hedef_zaman=None):
    """postgresql.auto.conf'a eklenecek satirlar. archive_mode=off: geri yuklenen kume ayni arsive yazip onu bozmasin."""
    if hedef_zaman and not arsiv:
        raise YedekHatasi("--hedef-zaman icin --wal-arsivi gerekir (yalniz yedekle zamana donulemez)")
    satirlar = ["archive_mode = off"]
    if arsiv:
        satirlar.append("restore_command = " + _sa(restore_komutu(arsiv)))
    if hedef_zaman:
        if not ZAMAN.match(hedef_zaman):
            raise YedekHatasi("hedef zaman bicimi gecersiz (saat dilimi zorunlu, ornek '2026-11-15 10:00:00+00'): %s" % hedef_zaman)
        satirlar += ["recovery_target_time = " + _sa(hedef_zaman), "recovery_target_action = 'promote'"]
    return satirlar


def _pg_surum(arac):
    r = _calistir([_arac(arac), "--version"])
    m = re.search(r"\(PostgreSQL\)\s+(\d+)", r.stdout) if r.returncode == 0 else None
    if not m:
        raise YedekHatasi("%s surumu okunamadi" % arac)
    return int(m.group(1))


def bicim_bul(yedek):
    y = Path(yedek)
    return "tar" if (y / "base.tar").is_file() or (y / "base.tar.gz").is_file() else "duz"


def tar_ac(yedek, hedef):
    """tar bicimli yedegi (base.tar, pg_wal.tar) `hedef` dizinine acar. Tablespace tar'i ve sikistirilmis tar desteklenmez."""
    y, hedef = Path(yedek), Path(hedef)
    diger = sorted(p.name for p in y.iterdir() if p.name not in ("base.tar", "pg_wal.tar", "backup_manifest"))
    if diger or not (y / "base.tar").is_file():
        raise YedekHatasi("desteklenmeyen tar yedegi (tablespace ya da sikistirma): %s" % ", ".join(diger or ["base.tar yok"]))
    for ad, alt in (("base.tar", hedef), ("pg_wal.tar", hedef / "pg_wal")):
        if (y / ad).is_file():
            alt.mkdir(parents=True, exist_ok=True)
            with tarfile.open(y / ad) as t:
                t.extractall(alt, filter="data")
    shutil.copyfile(y / "backup_manifest", hedef / "backup_manifest")


def dogrula(yedek):
    """pg_verifybackup. Duz bicimde dogrudan; tar bicimi PG18'den once dogrudan dogrulanamaz, gecici dizine acilip dogrulanir
    (yedek degismez). (tamam, cikti) doner."""
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
    """Tam yedek. Once '.devam' dizinine yazilir; pg_verifybackup gecerse son ada tasinir. Basarisizsa yarim dizin silinir."""
    kok = Path(kok)
    kok.mkdir(parents=True, exist_ok=True)
    kok.chmod(0o700)
    ad = "pg-" + _simdi()
    gecici, son = kok / (ad + ".devam"), kok / ad
    if son.exists() or gecici.exists():
        raise YedekHatasi("ayni saniyede ikinci yedek: %s" % ad)
    gecici.mkdir(mode=0o700)
    try:
        r = _calistir(basebackup_argv(gecici, bicim, kullanici))
        if r.returncode != 0:
            raise YedekHatasi("pg_basebackup basarisiz:\n%s" % r.stderr.strip())
        tamam, cikti = dogrula(gecici)
        if not tamam:
            raise YedekHatasi("yedek dogrulamasi basarisiz (yedek silindi):\n%s" % cikti)
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
    """Plan yazar; evet ise hedef bos dizine yedegi acar ve kurtarma ayarlarini ekler. Dolu hedefte YedekHatasi."""
    y, h = Path(yedek).resolve(), Path(hedef).absolute()
    if not y.is_dir() or not (y / "backup_manifest").is_file():
        raise YedekHatasi("yedek dizini gecersiz (backup_manifest yok): %s" % y)
    if h == y or y in h.parents or h in y.parents:
        raise YedekHatasi("hedef ile yedek ic ice olamaz")
    bos, neden = hedef_bos_mu(h)
    if not bos:
        raise YedekHatasi(neden)
    ayarlar = kurtarma_ayarlari(arsiv, hedef_zaman)
    if arsiv and not Path(arsiv).is_dir():
        raise YedekHatasi("WAL arsivi dizini yok: %s" % arsiv)
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
        raise YedekHatasi("yedek dogrulamasi basarisiz, geri yukleme yapilmadi:\n%s" % cikti)
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
        shutil.rmtree(h, ignore_errors=True)   # yarim acilmis hedef; hedef baslangicta bostu
        raise
    yaz("GERI YUKLENDI: %s (baslatmadan once port/soket ayarlarini denetleyin: kopya, kaynak kumenin yapilandirmasini tasir)" % h)
    return h


def yedekleri_listele(kok):
    """Tamamlanmis yedekler, eskiden yeniye. Yalniz pg-<zaman> adli, backup_manifest'i olan, sembolik olmayan dizinler."""
    kok = Path(kok)
    if not kok.is_dir():
        return []
    return sorted(p for p in kok.iterdir() if YEDEK_AD.match(p.name) and p.is_dir() and not p.is_symlink()
                  and (p / "backup_manifest").is_file())


def eskileri_sil(kok, sakla, evet=False):
    """En yeni `sakla` yedek kalir. sakla >= 1 (hepsini silmek reddedilir). Silinecekler listesi doner; evet yoksa silinmez."""
    if sakla < 1:
        raise YedekHatasi("--sakla en az 1 olmali")
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
    ap = argparse.ArgumentParser(description="PostgreSQL yedek ve geri yukleme (pg_basebackup + WAL arsivi)")
    alt = ap.add_subparsers(dest="komut", required=True)
    a = alt.add_parser("al", help="tam yedek al ve dogrula")
    a.add_argument("--kok", required=True)
    a.add_argument("--bicim", choices=("duz", "tar"), default="duz")
    a.add_argument("--kullanici", default=VARSAYILAN_ROL)
    d = alt.add_parser("dogrula", help="pg_verifybackup")
    d.add_argument("--yedek", required=True)
    g = alt.add_parser("geri-yukle", help="bos hedef dizine ac (--evet olmadan yalniz plan)")
    g.add_argument("--yedek", required=True)
    g.add_argument("--hedef", required=True)
    g.add_argument("--wal-arsivi")
    g.add_argument("--hedef-zaman")
    g.add_argument("--evet", action="store_true")
    e = alt.add_parser("eskileri-sil", help="en yeni N yedegi sakla (--evet olmadan yalniz listeler)")
    e.add_argument("--kok", required=True)
    e.add_argument("--sakla", type=int, required=True)
    e.add_argument("--evet", action="store_true")
    o = alt.add_parser("arsiv-onerisi", help="archive_command onerisi yazar (sunucuya dokunmaz)")
    o.add_argument("--wal-arsivi", required=True)
    args = ap.parse_args(argv)
    try:
        if args.komut == "al":
            print("yedek alindi ve dogrulandi: %s" % al(args.kok, args.bicim, args.kullanici))
        elif args.komut == "dogrula":
            tamam, cikti = dogrula(args.yedek)
            print(cikti or ("yedek dogrulandi" if tamam else "yedek dogrulanamadi"))
            return 0 if tamam else 1
        elif args.komut == "geri-yukle":
            geri_yukle(args.yedek, args.hedef, args.wal_arsivi, args.hedef_zaman, args.evet)
        elif args.komut == "eskileri-sil":
            s = eskileri_sil(args.kok, args.sakla, args.evet)
            for p in s:
                print(("silindi: " if args.evet else "silinecek: ") + str(p))
            if not s:
                print("silinecek yedek yok")
            elif not args.evet:
                print("KURU CALISTIRMA: hicbir sey silinmedi; --evet ile silinir")
        else:
            print("archive_mode = on")
            print("archive_command = " + _sa(arsiv_komutu(args.wal_arsivi)))
            print("# WAL arsiv dizini sunucu kullanicisina ait, 0700 ve sifreli hacimde olmali; sunucuya bu komut dokunmaz.")
    except YedekHatasi as ex:
        print("hata: %s" % ex, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
