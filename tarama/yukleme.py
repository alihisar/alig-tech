"""Yuklenen toplama dosyasi guvenilmeyen girdidir: katı sema, bilinmeyen alan reddi, boyut ve tur sinirlari."""
import json
import re

from tarama import katalog
from tarama.uret_toplayici import katalog_ozeti

MAX_BAYT = 5 * 1024 * 1024
MAX_SATIR = 200
MAX_METIN = 200
ZAMAN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DURUMLAR = {"ok", "hata"}
NEDENLER = {"yetki", "zaman_asimi", "desteklenmiyor", "yedek_sunucu", "hata", "calistirilmadi"}
UST_ALANLAR = {"format", "motor", "katalog_sha256", "olusturma_utc", "maskeli", "superuser", "kontroller"}


class Gecersiz(ValueError):
    """mesaj: ic kayit icin. kod ve ek: musteriye gosterilen metni secmek icin (tarama/hata.py)."""

    def __init__(self, mesaj, kod="bicim", ek=""):
        super().__init__(mesaj)
        self.kod = kod
        self.ek = ek


def coz(veri):
    if len(veri) > MAX_BAYT:
        raise Gecersiz("dosya cok buyuk", "buyuk")
    try:
        belge = json.loads(veri.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Gecersiz("gecerli JSON degil", "json")
    return dogrula(belge)


def _skaler(v):
    if v is None or isinstance(v, (bool, int, float)):
        return True
    return isinstance(v, str) and len(v) <= MAX_METIN


def dogrula(b):
    if not isinstance(b, dict) or set(b) - UST_ALANLAR or not UST_ALANLAR - {"superuser", "maskeli"} <= set(b):
        raise Gecersiz("beklenmeyen ust duzey alanlar", "alanlar")
    if b["format"] != katalog.FORMAT or b["motor"] != katalog.MOTOR:
        raise Gecersiz("desteklenmeyen format ya da motor", "format")
    if b["katalog_sha256"] != katalog_ozeti():
        raise Gecersiz("toplayici surumu eski: sitedeki guncel betigi indirin", "eski")
    if not isinstance(b["olusturma_utc"], str) or not ZAMAN.match(b["olusturma_utc"]):
        raise Gecersiz("olusturma_utc gecersiz", "zaman")
    for alan in ("superuser", "maskeli"):
        if alan in b and not isinstance(b[alan], bool):
            raise Gecersiz(alan + " bool olmali", "alan_turu", alan)
    k = b["kontroller"]
    if not isinstance(k, dict):
        raise Gecersiz("kontroller nesne olmali", "alanlar")
    for cid, e in k.items():
        c = katalog.PG_BY_ID.get(cid)
        if c is None:
            raise Gecersiz("bilinmeyen kontrol: " + cid[:40], "kontrol", cid[:40])
        if not isinstance(e, dict) or e.get("durum") not in DURUMLAR:
            raise Gecersiz(cid + ": durum gecersiz", "durum", cid)
        if e["durum"] == "hata":
            if set(e) != {"durum", "neden"} or e["neden"] not in NEDENLER:
                raise Gecersiz(cid + ": hata kaydi gecersiz", "hata_kaydi", cid)
            continue
        if set(e) != {"durum", "satirlar"} or not isinstance(e["satirlar"], list) or len(e["satirlar"]) > MAX_SATIR:
            raise Gecersiz(cid + ": satirlar gecersiz", "satirlar", cid)
        izin = set(c["kolonlar"])
        for s in e["satirlar"]:
            if not isinstance(s, dict) or set(s) - izin:
                raise Gecersiz(cid + ": bilinmeyen kolon", "kolon", cid)
            if not all(_skaler(v) for v in s.values()):
                raise Gecersiz(cid + ": deger turu ya da uzunlugu gecersiz", "deger", cid)
    return b
