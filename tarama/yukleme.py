"""Yuklenen toplama dosyasi guvenilmeyen girdidir: katı sema, bilinmeyen alan reddi, boyut ve tur sinirlari."""
import json
import math
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


# Kolon turleri (PostgreSQL). None her kolonda kabul edilir (SQL NULL); eksik kolon None sayilir.
# Kural motoru bu turlere guvenir; tur disi deger yuklemede reddedilir. SQL Server kurallari degerleri kendisi denetler.
TUR_DENETIMI = {
    "tamsayi": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "sayi": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
    "metin": lambda v: isinstance(v, str),
    "mantik": lambda v: isinstance(v, bool),
}
_M, _T, _S, _B = "metin", "tamsayi", "sayi", "mantik"
TURLER = {
    "pg_surum": {"surum_num": _T},
    "pg_kapsam": {"veritabani": _M, "veritabani_sayisi": _T},
    "pg_xid_yasi": {"datname": _M, "yas": _T, "mxid_yas": _T, "freeze_max_age": _T},
    "pg_bosta_islem": {"usename": _M, "durum": _M, "sure_sn": _T},
    "pg_baglanti": {"kullanilan": _T, "ust": _T},
    "pg_olu_satir": {"schemaname": _M, "relname": _M, "canli": _T, "olu": _T, "son_autovacuum": _M},
    "pg_gecersiz_indeks": {"schemaname": _M, "indexrelname": _M},
    "pg_kullanilmayan_indeks": {"schemaname": _M, "indexrelname": _M, "bayt": _T},
    "pg_sequence": {"schemaname": _M, "sequencename": _M, "oran": _S},
    "pg_sequence_gorunurluk": {"toplam": _T, "okunamayan": _T},
    "pg_slot": {"slot_name": _M, "active": _B, "wal_status": _M, "geri_bayt": _T},
    "pg_arsiv": {"archive_mode": _M, "basarili": _T, "hatali": _T, "son_basari_utc": _M, "son_hata_utc": _M},
    "pg_tls_parola": {"ssl": _M, "password_encryption": _M, "ssl_min_protocol_version": _M},
    "pg_md5_roller": {"sayi": _T},
    "pg_super_roller": {"rolname": _M, "rolcanlogin": _B},
    "pg_public_create": {"public_create": _B},
    "pg_log_ayarlari": {"name": _M, "setting": _M},
    "pg_eklentiler": {"extname": _M, "extversion": _M},
}

MAX_DERINLIK = 8   # belge > kontroller > kontrol > satirlar > satir: 5 duzey; pay birakildi


def _derinlik_denetle(veri):
    """Ayristirmadan once ic ice yapi derinligini sinirlar (metin icindeki parantezler sayilmaz)."""
    derinlik, metinde, kacis = 0, False, False
    for b in veri:
        if metinde:
            if kacis:
                kacis = False
            elif b == 0x5C:      # ters bolu
                kacis = True
            elif b == 0x22:      # cift tirnak
                metinde = False
        elif b == 0x22:
            metinde = True
        elif b in (0x5B, 0x7B):  # [ {
            derinlik += 1
            if derinlik > MAX_DERINLIK:
                raise Gecersiz("yapi cok derin", "derin")
        elif b in (0x5D, 0x7D):  # ] }
            derinlik -= 1


def _sabit_yok(ad):
    raise ValueError("standart disi sabit: " + ad)


def _tekil_anahtar(ciftler):
    d = dict(ciftler)
    if len(d) != len(ciftler):
        raise ValueError("yinelenen anahtar")
    return d


def coz(veri, motorlar=("postgresql",)):
    if len(veri) > MAX_BAYT:
        raise Gecersiz("dosya cok buyuk", "buyuk")
    _derinlik_denetle(veri)
    try:
        belge = json.loads(veri.decode("utf-8"), parse_constant=_sabit_yok, object_pairs_hook=_tekil_anahtar)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Gecersiz("gecerli JSON degil", "json")
    return dogrula(belge, motorlar)


def _skaler(v):
    if v is None or isinstance(v, (bool, int)):
        return True
    if isinstance(v, float):
        return math.isfinite(v)   # 1e999 JSON'da sonsuz olarak cozulur
    return isinstance(v, str) and len(v) <= MAX_METIN


def dogrula(b, motorlar=("postgresql",)):
    if not isinstance(b, dict) or set(b) - UST_ALANLAR or not UST_ALANLAR - {"superuser", "maskeli"} <= set(b):
        raise Gecersiz("beklenmeyen ust duzey alanlar", "alanlar")
    if b["format"] != katalog.FORMAT or not isinstance(b["motor"], str) or b["motor"] not in katalog.MOTORLAR:
        raise Gecersiz("desteklenmeyen format ya da motor", "format")
    if b["motor"] not in motorlar:
        raise Gecersiz("bu motor icin tarama acik degil: " + b["motor"], "motor_kapali")
    if b["katalog_sha256"] != katalog_ozeti(b["motor"]):
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
        c = katalog.MOTOR_BY_ID[b["motor"]].get(cid)
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
        turler = TURLER.get(cid, {}) if b["motor"] == "postgresql" else {}
        for s in e["satirlar"]:
            if not isinstance(s, dict) or set(s) - izin:
                raise Gecersiz(cid + ": bilinmeyen kolon", "kolon", cid)
            if turler and set(s) != izin:   # PostgreSQL toplayicisi (json_agg) her kolonu yazar; eksik kolon elle degistirilmis dosyadir
                raise Gecersiz(cid + ": eksik kolon", "kolon", cid)
            if not all(_skaler(v) for v in s.values()):
                raise Gecersiz(cid + ": deger turu ya da uzunlugu gecersiz", "deger", cid)
            for kolon, v in s.items():
                if v is not None and kolon in turler and not TUR_DENETIMI[turler[kolon]](v):
                    raise Gecersiz("%s.%s: beklenen tur %s" % (cid, kolon, turler[kolon]), "deger", cid)
    return b
