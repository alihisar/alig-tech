#!/usr/bin/env python3
"""alig.tech saglik taramasi toplayicisi, SQL Server (ON SURUM). Yalnizca standart kutuphane, Python 3.9+.

Musterinin kendi agi icinde calisir, AGA HICBIR SEY GONDERMEZ. Sabit, yalnizca SELECT iceren
sorgu katalogunu `sqlcmd` ile calistirir ve tek bir JSON dosyasi yazar. SQL Server 2016 ve ustu.

Kullanim:
  python3 alig-toplayici-mssql.py --sunucu sql.ornek.local,1433 --kullanici alig_hc --sifrele --maskele
  python3 alig-toplayici-mssql.py --sunucu sql.ornek.local --windows --maskele
Parola: SQLCMDPASSWORD ortam degiskeni. Komut satirindan parola kabul edilmez.
Calisan sorgularin tam listesi: sorgu-katalogu-mssql.txt
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

ON_EK = ("SET NOCOUNT ON; SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED; SET LOCK_TIMEOUT 2000; "
         "SET DEADLOCK_PRIORITY LOW; DECLARE @j nvarchar(max) = (")
SON_EK = " FOR JSON PATH, INCLUDE_NULL_VALUES); SELECT ISNULL(@j, N'[]');"


def hata_sinifi(metin):
    s = (metin or "").lower()
    if "permission" in s or "denied" in s or "not have permission" in s:
        return "yetki"
    if "timeout expired" in s or "lock request time out" in s:
        return "zaman_asimi"
    if "invalid object name" in s or "invalid column name" in s or "incorrect syntax" in s or "not a recognized" in s:
        return "desteklenmiyor"
    return "hata"


def json_ayikla(cikti):
    """sqlcmd ciktisinda baslik ya da bos satir olabilir: ilk '[' ile son ']' arasini alir."""
    a, b = cikti.find("["), cikti.rfind("]")
    if a < 0 or b < a:
        raise ValueError("json yok")
    veri = json.loads(cikti[a:b + 1].replace("\r", "").replace("\n", ""))
    if not isinstance(veri, list):
        raise ValueError("liste degil")
    return veri


def calistir(sqlcmd, baglanti, sql):
    cmd = [sqlcmd] + baglanti + ["-b", "-l", "15", "-t", "15", "-y", "0", "-Q", ON_EK + sql + SON_EK]
    env = dict(os.environ)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45, env=env)
    except subprocess.TimeoutExpired:
        return {"durum": "hata", "neden": "zaman_asimi"}
    except FileNotFoundError:
        raise SystemExit("sqlcmd bulunamadi: --sqlcmd ile yolunu verin")
    if r.returncode != 0:
        return {"durum": "hata", "neden": hata_sinifi(r.stdout + r.stderr)}
    try:
        return {"durum": "ok", "satirlar": json_ayikla(r.stdout)}
    except ValueError:
        return {"durum": "hata", "neden": hata_sinifi(r.stdout + r.stderr)}


class Maske:
    def __init__(self):
        self.harita = {}

    def al(self, kolon, deger):
        if deger is None or not isinstance(deger, str):
            return deger
        return self.harita.setdefault(deger, "nesne-%d" % (len(self.harita) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech saglik taramasi toplayicisi, SQL Server (on surum, yalnizca SELECT)")
    ap.add_argument("--sunucu", required=True, help="sunucu[,port] ya da sunucu\\ornek")
    ap.add_argument("--kullanici", help="SQL girisi; parola SQLCMDPASSWORD ortam degiskeninden okunur")
    ap.add_argument("--windows", action="store_true", help="Windows kimlik dogrulamasi (-E)")
    ap.add_argument("--sifrele", action="store_true", help="baglantiyi sifrele (-N)")
    ap.add_argument("--sertifikaya-guven", action="store_true", help="sunucu sertifikasini dogrulamadan kabul et (-C)")
    ap.add_argument("--sqlcmd", default="sqlcmd")
    ap.add_argument("--out", default="alig-toplama-mssql.json")
    ap.add_argument("--maskele", action="store_true", help="veritabani, dosya, giris, grup ve replika adlarini takma adla degistir")
    args = ap.parse_args(argv)
    if bool(args.kullanici) == bool(args.windows):
        raise SystemExit("--kullanici ya da --windows seceneklerinden tam olarak birini verin")
    if args.kullanici and not os.environ.get("SQLCMDPASSWORD"):
        raise SystemExit("parola SQLCMDPASSWORD ortam degiskeninde olmali")

    baglanti = ["-S", args.sunucu, "-d", "master"]
    baglanti += ["-E"] if args.windows else ["-U", args.kullanici]
    if args.sifrele:
        baglanti.append("-N")
    if args.sertifikaya_guven:
        baglanti.append("-C")

    ilk = calistir(args.sqlcmd, baglanti, "SELECT CAST(IS_SRVROLEMEMBER('sysadmin') AS int) AS yonetici")
    if ilk["durum"] != "ok" or not ilk["satirlar"]:
        raise SystemExit("baglanti kurulamadi (%s). Sunucu, giris, parola ve sifreleme seceneklerini denetleyin. SQL Server 2016 ve ustu gerekir." % ilk.get("neden"))
    yonetici = bool(ilk["satirlar"][0].get("yonetici"))
    if yonetici:
        print("UYARI: sysadmin uyesi bir girisle calisiyorsunuz. Yalnizca VIEW SERVER STATE ve VIEW ANY DEFINITION yetkili bir giris onerilir.", file=sys.stderr)

    maske = Maske() if args.maskele else None
    kontroller = {}
    for c in KATALOG["kontroller"]:
        sonuc = calistir(args.sqlcmd, baglanti, c["sql"])
        if sonuc["durum"] == "ok":
            sonuc["satirlar"] = [{k: v for k, v in s.items() if k in c["kolonlar"]} for s in sonuc["satirlar"] if isinstance(s, dict)]
            if maske:
                for satir in sonuc["satirlar"]:
                    for kolon in c["maske"]:
                        if kolon in satir:
                            satir[kolon] = maske.al(kolon, satir[kolon])
        kontroller[c["id"]] = sonuc
        print("%-26s %s" % (c["id"], sonuc["durum"] if sonuc["durum"] == "ok" else "ATLANDI (%s)" % sonuc["neden"]))

    belge = {"format": FORMAT, "motor": KATALOG["motor"], "katalog_sha256": KATALOG_OZETI,
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": yonetici, "kontroller": kontroller}
    veri = json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    with open(args.out, "wb") as f:
        f.write(veri)
    print("\nYazildi: %s\nSHA-256: %s\nDosyayi acip inceleyebilirsiniz. Siteye yuklemeden once hicbir sey gonderilmedi." % (
        args.out, hashlib.sha256(veri).hexdigest()))


if __name__ == "__main__":
    main()
