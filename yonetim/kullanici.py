#!/usr/bin/env python3
"""Admin panel users. The password is asked for in the terminal, never typed on the command line.

  python3 yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite ekle ali
    ... parola ali | totp-yenile ali | sil ali | liste | kod ali (instant code for local testing only)
"""
import argparse
import getpass
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yonetim import depo, guvenlik  # noqa: E402


def parola_sor():
    p1 = getpass.getpass("Password (at least %d characters): " % guvenlik.PAROLA_EN_AZ)
    if len(p1) < guvenlik.PAROLA_EN_AZ:
        raise SystemExit("password too short")
    if getpass.getpass("Password (again): ") != p1:
        raise SystemExit("passwords do not match")
    return p1


def goster(ad, gizli):
    print("Add this to your authenticator app (Google Authenticator, Aegis, etc.):")
    print("  Key: %s" % gizli)
    print("  URI    : %s" % guvenlik.totp_uri(gizli, ad))
    print("This key will not be shown again.")


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
        raise SystemExit("user name: letters, digits, - and _ (at most 32)")
    if a.komut == "ekle":
        if con.execute("SELECT 1 FROM kullanici WHERE ad=?", (a.ad,)).fetchone():
            raise SystemExit("this user already exists")
        goster(a.ad, depo.kullanici_ekle(con, a.ad, parola_sor()))
    elif a.komut == "parola":
        print("updated" if depo.kullanici_parola(con, a.ad, parola_sor()) else "user not found")
    elif a.komut == "totp-yenile":
        g = depo.kullanici_totp_yenile(con, a.ad)
        goster(a.ad, g) if g else print("user not found")
    elif a.komut == "sil":
        print("deleted" if depo.kullanici_sil(con, a.ad) else "user not found")
    elif a.komut == "kod":
        s = con.execute("SELECT totp FROM kullanici WHERE ad=?", (a.ad,)).fetchone()
        print(guvenlik.totp_kod(s[0], int(time.time() // 30)) if s else "user not found")
    return 0


if __name__ == "__main__":
    os.umask(0o077)   # a loose umask inherited via sudo -u must not make yonetim.sqlite (password digest, TOTP secret) world-readable
    sys.exit(main())
