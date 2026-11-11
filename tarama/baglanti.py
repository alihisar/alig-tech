"""Kip B: dogrudan baglantiyla tarama. Yalnizca standart kutuphane; `psql` alt sureciyle calisir.

Guvenlik kurallari (docs/kip-b-tasarim.md):
- Hedef once `tarama.hedef.dogrula` ile dogrulanir; baglanti ada degil dogrulanan IP'ye acilir (hostaddr).
- Parola yalnizca alt surecin ortaminda durur; arguman listesine, gunluge, diske yazilmaz.
- Once sahiplik kaniti okunur. Uyusmazsa ya da hesap super kullaniciysa katalogdan hicbir sorgu calismaz.
- Sunucudan gelen her deger `yukleme.dogrula` ile (kati sema) dogrulanir.
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
    kontroller = {}
    for c in katalog.PG:
        kalan = bitis - time.monotonic()
        if kalan <= 1:
            kontroller[c["id"]] = {"durum": "hata", "neden": "zaman_asimi"}
            continue
        sonuc, _ = _calistir(psql, dizgi, parola, c["sql"], min(30, kalan))
        if sonuc["durum"] == "ok":
            satirlar = [{k: v for k, v in s.items() if k in c["kolonlar"]} for s in sonuc["satirlar"][:yukleme.MAX_SATIR] if isinstance(s, dict)]
            if maske:
                for s in satirlar:
                    for kolon in c["maske"]:
                        if kolon in s:
                            s[kolon] = maske.al(s[kolon])
            sonuc = {"durum": "ok", "satirlar": satirlar}
        kontroller[c["id"]] = sonuc

    belge = {"format": katalog.FORMAT, "motor": "postgresql", "katalog_sha256": katalog_ozeti(),
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": False, "kontroller": kontroller}
    try:
        return yukleme.dogrula(belge)   # sunucudan gelen her deger guvenilmezdir
    except yukleme.Gecersiz:
        raise BaglantiHatasi("bicim")
