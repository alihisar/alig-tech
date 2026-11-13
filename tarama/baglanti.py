"""Kip B: dogrudan baglantiyla tarama. Yalnizca standart kutuphane; `psql` alt sureciyle calisir.

Guvenlik kurallari (docs/kip-b-tasarim.md):
- Hedef once `tarama.hedef.dogrula` ile dogrulanir; baglanti ada degil dogrulanan IP'ye acilir (hostaddr).
- Parola yalnizca alt surecin ortaminda durur; arguman listesine, gunluge, diske yazilmaz.
- Once sahiplik kaniti okunur. Uyusmazsa ya da hesap super kullaniciysa katalogdan hicbir sorgu calismaz.
- Sunucudan gelen her deger `yukleme.dogrula` ile (kati sema) dogrulanir.
- Tablo, indeks ve sequence denetimleri baglanilabilen her veritabaninda calisir; adi `AD` kalibina uymayan
  veritabani baglanti dizgisine hic girmez, "ad" nedeniyle atlanir.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from tarama import katalog, yukleme
from tarama.uret_toplayici import katalog_ozeti

AD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
EN_COK_VERITABANI = 20   # sure butcesi (toplam_sure) icinde kalsin diye toplayicidan dusuk
KANIT_ON_EK = "alig-kanit-"
ILK_SORGU = ("SELECT current_setting('is_superuser') = 'on' AS super, "
             "shobj_description((SELECT oid FROM pg_roles WHERE rolname = current_user), 'pg_authid') AS kanit")


class BaglantiHatasi(Exception):
    """kod: 'baglanti', 'kanit', 'super', 'zaman', 'bicim'."""

    def __init__(self, kod):
        super().__init__("dogrudan baglanti: " + kod)
        self.kod = kod


def kanit_metni(kanit):
    return KANIT_ON_EK + kanit


def kanit_komutu(kullanici, kanit):
    return "COMMENT ON ROLE %s IS '%s';" % (kullanici, kanit_metni(kanit))


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


def baglanti_dizgisi(hedef, veritabani, kullanici, sslmode="require"):
    if not AD.match(veritabani or "") or not AD.match(kullanici or ""):
        raise BaglantiHatasi("bicim")
    if sslmode not in ("require", "verify-ca", "verify-full", "prefer"):
        raise BaglantiHatasi("bicim")
    return "host=%s hostaddr=%s port=%d dbname=%s user=%s sslmode=%s connect_timeout=10 gssencmode=disable" % (
        hedef.ad, hedef.ip, hedef.port, veritabani, kullanici, sslmode)


def _ortam(parola):
    """Alt surece yalniz gerekenler verilir; servis ortami (tuzlar, anahtarlar, vekil ayarlari) devralinmaz."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "PGPASSWORD": parola,
            "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000",
            "PGAPPNAME": "alig-tarama", "PGCONNECT_TIMEOUT": "10", "PGPASSFILE": os.devnull, "PGSERVICEFILE": os.devnull,
            "PGSYSCONFDIR": os.devnull}


def _calistir(psql, dizgi, parola, sql, sure):
    sarmal = "SELECT coalesce(json_agg(t), '[]'::json) FROM (" + sql + ") t"
    cmd = [psql, "-X", "-A", "-t", "-w", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-d", dizgi, "-c", sarmal]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=max(1, sure), env=_ortam(parola), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"durum": "hata", "neden": "zaman_asimi"}, ""
    if r.returncode != 0:
        return {"durum": "hata", "neden": hata_sinifi(r.stderr)}, r.stderr
    try:
        satirlar = json.loads(r.stdout.strip() or "[]")
    except ValueError:
        return {"durum": "hata", "neden": "hata"}, ""
    return ({"durum": "ok", "satirlar": satirlar} if isinstance(satirlar, list) else {"durum": "hata", "neden": "hata"}), ""


class _Maske:
    def __init__(self):
        self.harita = {}

    def al(self, deger):
        if deger is None or not isinstance(deger, str):
            return deger
        return self.harita.setdefault(deger, "nesne-%d" % (len(self.harita) + 1))


def _temizle(c, satirlar, limit=yukleme.MAX_SATIR):
    """Sunucudan gelen satirlardan yalniz katalog kolonlari kalir."""
    return [{k: v for k, v in s.items() if k in c["kolonlar"]} for s in satirlar[:limit] if isinstance(s, dict)]


def _veritabanlari(psql, dizgi, parola, ilk_db, bitis):
    """(taranacak, atlanan). Liste alinamazsa yalniz ilk veritabani."""
    sonuc, _ = _calistir(psql, dizgi, parola, katalog.VT_LISTE_SQL, max(1, min(30, bitis - time.monotonic())))
    if sonuc["durum"] != "ok":
        return [ilk_db], []
    taranacak, atlanan = [], []
    for s in sonuc["satirlar"][:yukleme.MAX_ATLANAN]:
        ad = s.get("veritabani") if isinstance(s, dict) else None
        if not isinstance(ad, str) or len(ad) > yukleme.MAX_METIN:
            continue
        if not AD.match(ad):
            atlanan.append({"veritabani": ad, "neden": "ad"})
        elif s.get("baglanir") is not True:
            atlanan.append({"veritabani": ad, "neden": "yetki"})
        elif len(taranacak) >= EN_COK_VERITABANI:
            atlanan.append({"veritabani": ad, "neden": "sinir"})
        else:
            taranacak.append(ad)
    return taranacak, atlanan


def _her_veritabani(psql, parola, hedef, kullanici, sslmode, c, taranacak, atlanan, bitis):
    satirlar, at, calisti, ilk_neden = [], list(atlanan), False, None
    for db in taranacak:
        kalan = bitis - time.monotonic()
        if kalan <= 1:
            at.append({"veritabani": db, "neden": "zaman_asimi"})
            continue
        sonuc, _ = _calistir(psql, baglanti_dizgisi(hedef, db, kullanici, sslmode), parola, c["sql"], min(30, kalan))
        if sonuc["durum"] == "ok":
            calisti = True
            for s in _temizle(c, sonuc["satirlar"]):
                s["veritabani"] = db
                satirlar.append(s)
        else:
            at.append({"veritabani": db, "neden": sonuc["neden"]})
            ilk_neden = ilk_neden or sonuc["neden"]
    if not calisti:
        return {"durum": "hata", "neden": ilk_neden or ("yetki" if at else "calistirilmadi")}
    sonuc = {"durum": "ok", "satirlar": satirlar[:yukleme.MAX_SATIR_VT]}
    if at:
        sonuc["atlanan"] = at
    return sonuc


def tara(hedef, veritabani, kullanici, parola, kanit, psql="psql", sslmode="require", maskele=False, toplam_sure=90):
    """Dogrulanmis toplama belgesini dondurur ya da BaglantiHatasi firlatir."""
    if not isinstance(parola, str) or not parola or len(parola) > 1024 or "\x00" in parola:
        raise BaglantiHatasi("baglanti")
    dizgi = baglanti_dizgisi(hedef, veritabani, kullanici, sslmode)
    bitis = time.monotonic() + toplam_sure

    ilk, _ = _calistir(psql, dizgi, parola, ILK_SORGU, min(30, toplam_sure))
    if ilk["durum"] != "ok" or len(ilk["satirlar"]) != 1 or not isinstance(ilk["satirlar"][0], dict):
        raise BaglantiHatasi("zaman" if ilk.get("neden") == "zaman_asimi" else "baglanti")
    satir = ilk["satirlar"][0]
    if satir.get("kanit") != kanit_metni(kanit):
        raise BaglantiHatasi("kanit")
    if satir.get("super") is not False:
        raise BaglantiHatasi("super")

    maske = _Maske() if maskele else None
    taranacak, atlanan = _veritabanlari(psql, dizgi, parola, veritabani, bitis)
    kontroller = {}
    for c in katalog.PG:
        if c.get("kapsam") == "veritabani":
            sonuc = _her_veritabani(psql, parola, hedef, kullanici, sslmode, c, taranacak, atlanan, bitis)
        else:
            kalan = bitis - time.monotonic()
            if kalan <= 1:
                kontroller[c["id"]] = {"durum": "hata", "neden": "zaman_asimi"}
                continue
            sonuc, _ = _calistir(psql, dizgi, parola, c["sql"], min(30, kalan))
            if sonuc["durum"] == "ok":
                sonuc = {"durum": "ok", "satirlar": _temizle(c, sonuc["satirlar"])}
        if sonuc["durum"] == "ok" and maske:
            for s in sonuc["satirlar"]:
                for kolon in c["maske"]:
                    if kolon in s:
                        s[kolon] = maske.al(s[kolon])
            for a in sonuc.get("atlanan", []):
                a["veritabani"] = maske.al(a["veritabani"])
        kontroller[c["id"]] = sonuc

    belge = {"format": katalog.FORMAT, "motor": "postgresql", "katalog_sha256": katalog_ozeti(),
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": False, "kontroller": kontroller}
    try:
        return yukleme.dogrula(belge)   # sunucudan gelen her deger guvenilmezdir
    except yukleme.Gecersiz:
        raise BaglantiHatasi("bicim")
