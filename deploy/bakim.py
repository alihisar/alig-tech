#!/usr/bin/env python3
"""Gunluk bakim (systemd zamanlayicisi): SQLite yedegi, eski yedekleri silme, suresi dolan raporlari silme.

  python3 bakim.py --veri /var/lib/alig --yedek /var/backups/alig --sakla 14
Yedek: SQLite backup API ile tutarli kopya, <ad>-<UTC zaman>.sqlite. Geri yukleme: servisleri durdur,
yedegi veri dizinine kopyala (docs/runbook.md).
"""
import argparse
import sqlite3
import sys
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
