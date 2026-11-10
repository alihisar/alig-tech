#!/usr/bin/env python3
"""alig.tech saglik taramasi toplayicisi. Yalnizca standart kutuphane, Python 3.9+.

Musterinin kendi agi icinde calisir, AGA HICBIR SEY GONDERMEZ. Sabit, salt okunur
sorgu katalogunu `psql` ile calistirir ve tek bir JSON dosyasi yazar. Dosyayi okuyup,
istediginizde siteye kendiniz yuklersiniz.

Kullanim:
  python3 alig-toplayici.py --host db.ornek.local --user alig_hc --dbname postgres --maskele
Parola: PGPASSWORD ortam degiskeni ya da ~/.pgpass. Komut satirindan parola kabul edilmez.
Calisan sorgularin tam listesi: sorgu-katalogu.txt (ayni SHA-256 sayfada yazar).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

KATALOG = json.loads(r'''__KATALOG_JSON__''')
FORMAT = KATALOG["format"]
KATALOG_OZETI = hashlib.sha256(json.dumps(KATALOG["kontroller"], sort_keys=True).encode()).hexdigest()


def hata_sinifi(stderr):
    s = (stderr or "").lower()
    if "permission denied" in s or "must be superuser" in s or "must be member" in s:
        return "yetki"
    if "statement timeout" in s or "canceling statement" in s:
        return "zaman_asimi"
    if "does not exist" in s or "unrecognized" in s:
        return "desteklenmiyor"
    if "in recovery" in s or "recovery is in progress" in s:
        return "yedek_sunucu"
    return "hata"


def calistir(psql, baglanti, sql):
    sarmal = "SELECT coalesce(json_agg(t), '[]'::json) FROM (" + sql + ") t"
    env = dict(os.environ)
    env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000"
    env["PGAPPNAME"] = "alig-toplayici"
    cmd = [psql, "-X", "-A", "-t", "--no-psqlrc", "-v", "ON_ERROR_STOP=1"] + baglanti + ["-c", sarmal]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    except subprocess.TimeoutExpired:
        return {"durum": "hata", "neden": "zaman_asimi"}
    except FileNotFoundError:
        raise SystemExit("psql bulunamadi: --psql ile yolunu verin")
    if r.returncode != 0:
        return {"durum": "hata", "neden": hata_sinifi(r.stderr)}
    try:
        return {"durum": "ok", "satirlar": json.loads(r.stdout.strip() or "[]")}
    except ValueError:
        return {"durum": "hata", "neden": "hata"}


class Maske:
    def __init__(self):
        self.harita = {}

    def al(self, kolon, deger):
        if deger is None or not isinstance(deger, str):
            return deger
        return self.harita.setdefault(deger, "nesne-%d" % (len(self.harita) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech saglik taramasi toplayicisi (salt okunur)")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--user")
    ap.add_argument("--dbname", default="postgres")
    ap.add_argument("--sslmode", default="prefer")
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--out", default="alig-toplama.json")
    ap.add_argument("--maskele", action="store_true", help="veritabani, sema, tablo, indeks, rol ve slot adlarini takma adla degistir")
    args = ap.parse_args(argv)

    baglanti = ["-d", "dbname=%s sslmode=%s" % (args.dbname, args.sslmode)]
    if args.host:
        baglanti += ["-h", args.host]
    if args.port:
        baglanti += ["-p", args.port]
    if args.user:
        baglanti += ["-U", args.user]

    ilk = calistir(args.psql, baglanti, "SELECT current_setting('is_superuser') = 'on' AS super, pg_is_in_recovery() AS yedek")
    if ilk["durum"] != "ok":
        raise SystemExit("baglanti kurulamadi (%s). Sunucu, kullanici, parola ve sslmode'u denetleyin." % ilk.get("neden"))
    super_ = bool(ilk["satirlar"][0]["super"])
    if super_:
        print("UYARI: super kullanici ile calisiyorsunuz. Yetkisiz bir rol (pg_monitor uyesi) onerilir.", file=sys.stderr)

    maske = Maske() if args.maskele else None
    kontroller = {}
    for c in KATALOG["kontroller"]:
        sonuc = calistir(args.psql, baglanti, c["sql"])
        if sonuc["durum"] == "ok" and maske:
            for satir in sonuc["satirlar"]:
                for kolon in c["maske"]:
                    if kolon in satir:
                        satir[kolon] = maske.al(kolon, satir[kolon])
        kontroller[c["id"]] = sonuc
        print("%-26s %s" % (c["id"], sonuc["durum"] if sonuc["durum"] == "ok" else "ATLANDI (%s)" % sonuc["neden"]))

    belge = {"format": FORMAT, "motor": KATALOG["motor"], "katalog_sha256": KATALOG_OZETI,
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": super_, "kontroller": kontroller}
    veri = json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    with open(args.out, "wb") as f:
        f.write(veri)
    print("\nYazildi: %s\nSHA-256: %s\nDosyayi acip inceleyebilirsiniz. Siteye yuklemeden once hicbir sey gonderilmedi." % (
        args.out, hashlib.sha256(veri).hexdigest()))


if __name__ == "__main__":
    main()
