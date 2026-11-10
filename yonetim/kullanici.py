#!/usr/bin/env python3
"""Yonetim paneli kullanicilari. Parola terminalden sorulur, komut satirina yazilmaz.

  python3 yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite ekle ali
  ... parola ali | totp-yenile ali | sil ali | liste | kod ali (yalniz yerel deneme icin anlik kod)
"""
import argparse
import getpass
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yonetim import depo, guvenlik  # noqa: E402


def parola_sor():
    p1 = getpass.getpass("Parola (en az %d karakter): " % guvenlik.PAROLA_EN_AZ)
    if len(p1) < guvenlik.PAROLA_EN_AZ:
        raise SystemExit("parola cok kisa")
    if getpass.getpass("Parola (tekrar): ") != p1:
        raise SystemExit("parolalar ayni degil")
    return p1


def goster(ad, gizli):
    print("Dogrulama uygulamasina (Google Authenticator, Aegis vb.) ekleyin:")
    print("  Anahtar: %s" % gizli)
    print("  URI    : %s" % guvenlik.totp_uri(gizli, ad))
    print("Bu anahtar bir daha gosterilmez.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("komut", choices=["ekle", "parola", "totp-yenile", "sil", "liste", "kod"])
    ap.add_argument("ad", nargs="?")
    a = ap.parse_args(argv)
    con = depo.baglan(a.db)
    if a.komut == "liste":
        for ad, z in con.execute("SELECT ad, olusturma_utc FROM kullanici ORDER BY ad"):
            print(ad, z)
        return 0
    if not a.ad or not a.ad.isascii() or not a.ad.replace("_", "").replace("-", "").isalnum() or len(a.ad) > 32:
        raise SystemExit("kullanici adi: harf, rakam, - ve _ (en cok 32)")
    if a.komut == "ekle":
        if con.execute("SELECT 1 FROM kullanici WHERE ad=?", (a.ad,)).fetchone():
            raise SystemExit("bu kullanici var")
        goster(a.ad, depo.kullanici_ekle(con, a.ad, parola_sor()))
    elif a.komut == "parola":
        print("guncellendi" if depo.kullanici_parola(con, a.ad, parola_sor()) else "kullanici yok")
    elif a.komut == "totp-yenile":
        g = depo.kullanici_totp_yenile(con, a.ad)
        goster(a.ad, g) if g else print("kullanici yok")
    elif a.komut == "sil":
        print("silindi" if depo.kullanici_sil(con, a.ad) else "kullanici yok")
    elif a.komut == "kod":
        s = con.execute("SELECT totp FROM kullanici WHERE ad=?", (a.ad,)).fetchone()
        print(guvenlik.totp_kod(s[0], int(time.time() // 30)) if s else "kullanici yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
