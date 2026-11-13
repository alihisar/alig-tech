#!/usr/bin/env python3
"""Gunluk bakim (systemd zamanlayicisi): SQLite yedegi, eski yedekleri silme, suresi dolan raporlari silme.

  python3 bakim.py --veri /var/lib/alig --yedek /var/backups/alig --sakla 14
Yedek: SQLite backup API ile tutarli kopya, <ad>-<UTC zaman>.sqlite.

Geri yukleme (servisler durdurulmus olmali; --evet olmadan yalniz kontrol eder, hicbir sey degistirmez):
  python3 bakim.py geri-yukle --veri /var/lib/alig --dosya /var/backups/alig/tarama-<zaman>.sqlite [--bas bas.json] [--evet]
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
from tarama import depo, saklama  # noqa: E402
from yonetim import depo as ydepo  # noqa: E402

VERITABANLARI = ("form.sqlite", "tarama.sqlite", "yonetim.sqlite")


def yedekle(kaynak, hedef_dizin, zaman):
    hedef = hedef_dizin / f"{kaynak.stem}-{zaman}.sqlite"
    src = sqlite3.connect(f"file:{kaynak}?mode=ro", uri=True)
    dst = sqlite3.connect(hedef)
    try:
        src.backup(dst)
        sonuc = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if sonuc != "ok":
        hedef.unlink()
        raise RuntimeError(f"{kaynak.name}: yedek butunluk denetimi basarisiz")
    hedef.chmod(0o600)
    return hedef


def disk_yeterli(veri, yedek, kullanilan=shutil.disk_usage, oran=0.10):
    """Yedek icin yeterli yer var mi: bos alan, veritabanlarinin toplam boyutunun iki katindan ve disk boyutunun %10'undan az olmamali.
    (yeterli_mi, aciklama). Yer yoksa yedek alinmaz; veri silinmez."""
    toplam = sum((Path(veri) / ad).stat().st_size for ad in VERITABANLARI if (Path(veri) / ad).exists())
    d = kullanilan(str(yedek))
    gereken = max(2 * toplam, int(d.total * oran))
    mb = lambda x: x // (1 << 20)  # noqa: E731
    return d.free >= gereken, f"yedek diskinde bos {mb(d.free)} MB, gereken en az {mb(gereken)} MB"


def _ozet(yol):
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def yedegi_dogrula(dosya, ad, bas=None):
    """Yedegin geri yuklenebilirligini denetler; dosyayi DEGISTIRMEZ (gecici kopya uzerinde calisir).
    (hatalar, uyarilar) doner. Hata varsa geri yukleme yapilmaz."""
    hatalar, uyarilar = [], []
    dosya = Path(dosya)
    if not dosya.is_file():
        return [f"yedek dosyasi yok: {dosya}"], uyarilar
    gecici = Path(tempfile.mkdtemp()) / ad
    try:
        shutil.copyfile(dosya, gecici)
        try:
            con = sqlite3.connect(str(gecici))
            try:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    return ["yedek butunluk denetimi basarisiz"], uyarilar
                tablolar = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                surum = con.execute("PRAGMA user_version").fetchone()[0]
            finally:
                con.close()
        except sqlite3.DatabaseError as ex:
            return [f"yedek SQLite dosyasi degil ya da bozuk: {ex}"], uyarilar
        bilinen = {"tarama.sqlite": (depo.GOCLER, "denetim"), "yonetim.sqlite": (ydepo.GOCLER, "denetim"), "form.sqlite": (None, "contact")}
        if ad not in bilinen:
            return [f"bilinmeyen veritabani adi: {ad}"], uyarilar
        gocler, tablo = bilinen[ad]
        if tablo not in tablolar:
            hatalar.append(f"beklenen tablo yok: {tablo}")
        if gocler is not None and surum > len(gocler):
            hatalar.append(f"yedegin sema surumu ({surum}) bu kodun bildiginden yeni ({len(gocler)}): once kodu guncelleyin")
        if not hatalar and gocler is not None:
            modul = depo if ad == "tarama.sqlite" else ydepo
            con = modul.baglan(str(gecici))  # eski yedek ileri goc ile gecici kopyada guncellenir
            try:
                anahtar = depo.denetim_anahtari()
                d = depo.denetim_durum(con, anahtar, bas)
            finally:
                con.close()
            if d["bozuk"] is not None:
                hatalar.append(f"denetim zinciri kirik: kayit #{d['bozuk']}")
            elif d["dogrulanamayan"]:
                uyarilar.append(f"{d['dogrulanamayan']} anahtarli kayit anahtar olmadan dogrulanamadi (ALIG_DENETIM_ANAHTARI)")
            elif bas is None:
                uyarilar.append("zincir basi verilmedi: bastan uretilmis zincir ya da kesilmis son kayitlar yakalanamaz (--bas)")
    finally:
        shutil.rmtree(gecici.parent, ignore_errors=True)
    return hatalar, uyarilar


def geri_yukle(dosya, veri, evet=False, bas=None, cikti=print):
    """Yedegi veri dizinindeki ayni adli veritabaninin yerine koyar. Onceki dosya silinmez, '<ad>.onceki-<zaman>' olarak kalir.
    0 basarili ya da kuru calistirma, 1 dogrulama/yukleme hatasi, 2 kullanim hatasi."""
    dosya, veri = Path(dosya), Path(veri)
    ad = dosya.name.rsplit("-", 1)[0] + ".sqlite" if "-" in dosya.name else dosya.name
    if ad not in VERITABANLARI:
        cikti(f"HATA: dosya adi '<ad>-<zaman>.sqlite' bicimli degil ya da bilinmeyen veritabani: {dosya.name}")
        return 2
    bas_belgesi = None
    if bas:
        try:
            bas_belgesi = json.loads(Path(bas).read_text(encoding="utf-8"))
            bas_belgesi["seq"], bas_belgesi["ozet"]
        except (OSError, ValueError, KeyError, TypeError) as ex:
            cikti(f"HATA: zincir basi dosyasi okunamadi: {ex}")
            return 2
    hatalar, uyarilar = yedegi_dogrula(dosya, ad, bas_belgesi)
    for u in uyarilar:
        cikti(f"UYARI: {u}")
    if hatalar:
        for h in hatalar:
            cikti(f"HATA: {h}")
        cikti("geri yukleme YAPILMADI")
        return 1
    hedef = veri / ad
    if hedef.exists():
        try:
            k = sqlite3.connect(str(hedef), timeout=0)
            try:
                k.execute("BEGIN EXCLUSIVE")  # baska bir surec yaziyor ya da okuyorsa basarisiz olur
                k.execute("ROLLBACK")
            finally:
                k.close()
        except sqlite3.OperationalError as ex:
            cikti(f"HATA: hedef veritabani kullanimda ({ex}); once servisleri durdurun")
            return 1
    if not evet:
        cikti(f"KURU CALISTIRMA: yedek gecerli. Gercek yukleme icin --evet ekleyin. Hedef: {hedef}")
        return 0
    zaman = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    onceki = veri / f"{ad}.onceki-{zaman}"
    veri.mkdir(parents=True, exist_ok=True)
    yeni_gecici = veri / f".{ad}.geri-yukleme"
    shutil.copyfile(dosya, yeni_gecici)
    with open(yeni_gecici, "rb") as f:
        os.fsync(f.fileno())
    yeni_gecici.chmod(0o600)
    sahip = None
    if hedef.exists():
        st = hedef.stat()
        sahip = (st.st_uid, st.st_gid)
        os.replace(hedef, onceki)
    for ek in ("-wal", "-shm"):  # eski dosyanin gunlugu yeni dosyaya karismasin
        (veri / (ad + ek)).unlink(missing_ok=True)
    if sahip and os.geteuid() == 0:  # root olarak calisirsa servis kullanicisi dosyayi okuyabilsin
        os.chown(yeni_gecici, *sahip)
    os.replace(yeni_gecici, hedef)
    ok = False
    try:
        c = sqlite3.connect(str(hedef))
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            c.close()
        ok = ok and _ozet(hedef) == _ozet(dosya)
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        cikti("HATA: yuklenen dosya dogrulanamadi, onceki dosya geri konuyor")
        if onceki.exists():
            os.replace(onceki, hedef)
        else:
            hedef.unlink(missing_ok=True)
        return 1
    cikti(f"geri yuklendi: {hedef}" + (f" (onceki dosya: {onceki.name})" if onceki.exists() else ""))
    cikti("simdi servisleri baslatin ve zinciri dogrulayin: python3 tarama/depo.py dogrula " + str(hedef))
    return 0


def eskileri_sil(hedef_dizin, sakla):
    silinen = []
    for ad in VERITABANLARI:
        yedekler = sorted(hedef_dizin.glob(f"{Path(ad).stem}-*.sqlite"))
        for eski in yedekler[:-sakla] if sakla > 0 else yedekler:
            eski.unlink()
            silinen.append(eski.name)
    return silinen


def talepleri_sil(veri, simdi=None):
    """Saklama suresi dolan iletisim taleplerini ve durum notlarini siler; silme yonetim zincirine yazilir. Silinen sayiyi doner."""
    g = saklama.gun("talep")
    form = Path(veri) / "form.sqlite"
    if g is None or not form.exists():
        return 0
    esik = ((simdi or datetime.now(timezone.utc)) - timedelta(days=g)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(str(form))
    try:
        idler = [r[0] for r in con.execute("SELECT id FROM contact WHERE created_utc <= ?", (esik,))]
        con.execute("DELETE FROM contact WHERE created_utc <= ?", (esik,))
        con.commit()
    finally:
        con.close()
    yon = Path(veri) / "yonetim.sqlite"
    if idler and yon.exists():
        y = ydepo.baglan(str(yon))
        try:
            y.executemany("DELETE FROM talep_durum WHERE talep_id=?", [(i,) for i in idler])
            y.commit()
            ydepo.denetim_ekle(y, "sistem", "saklama suresi doldu, %d talep silindi" % len(idler))
        finally:
            y.close()
    return len(idler)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "geri-yukle":
        gp = argparse.ArgumentParser(prog="bakim.py geri-yukle")
        gp.add_argument("--veri", required=True)
        gp.add_argument("--dosya", required=True)
        gp.add_argument("--bas", default=None, help="disa aktarilmis zincir basi (JSON)")
        gp.add_argument("--evet", action="store_true", help="gercekten yukle; yoksa yalniz kontrol")
        g = gp.parse_args(argv[1:])
        return geri_yukle(g.dosya, g.veri, g.evet, g.bas)
    ap = argparse.ArgumentParser()
    ap.add_argument("--veri", required=True)
    ap.add_argument("--yedek", required=True)
    ap.add_argument("--sakla", type=int, default=14)
    a = ap.parse_args(argv)
    try:
        saklama.dogrula()
    except saklama.SaklamaHatasi as ex:
        print(f"HATA: {ex}", file=sys.stderr)
        return 2
    veri, yedek = Path(a.veri), Path(a.yedek)
    yedek.mkdir(parents=True, exist_ok=True)
    zaman = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    hata = 0
    yeterli, mesaj = disk_yeterli(veri, yedek)
    if not yeterli:
        print(f"HATA: disk dolu, yedek alinmadi ({mesaj})", file=sys.stderr)
        return 1
    tarama = veri / "tarama.sqlite"
    if tarama.exists():
        con = depo.baglan(str(tarama))
        print(f"suresi dolan rapor silindi: {depo.suresi_dolanlari_sil(con)}")
        print(f"saklama suresi dolan firma silindi: {depo.saklama_uygula(con)}")
        con.close()
    print(f"saklama suresi dolan talep silindi: {talepleri_sil(veri)}")
    for ad in VERITABANLARI:
        kaynak = veri / ad
        if not kaynak.exists():
            print(f"atlandi (yok): {ad}")
            continue
        try:
            print("yedek:", yedekle(kaynak, yedek, zaman).name)
        except Exception as e:  # tum veritabanlari denenir, sonunda hata kodu doner
            print(f"HATA {ad}: {e}", file=sys.stderr)
            hata = 1
    sil = eskileri_sil(yedek, a.sakla)
    if sil:
        print("eski yedek silindi:", ", ".join(sil))
    return hata


if __name__ == "__main__":
    sys.exit(main())
