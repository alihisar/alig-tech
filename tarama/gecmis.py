"""Gecmis karsilastirmasi: ayni firma ve ayni veritabani kimligine ait iki taramanin kural kural karsilastirmasi.
Dil modeli yok: ayni iki belge her zaman ayni sonucu verir.

Veritabani kimligi (kimlik): PostgreSQL kume tanimlayicisinin (pg_control_system().system_identifier) SHA-256 ozeti
(pg_kume_kimligi denetimi; ham tanimlayici sunucudan cikmaz) ve sunucunun rolu (pg_sunucu_rolu). Bir kumenin birincili
ve yedekleri ayni tanimlayiciyi tasir; rol ayri tutulur, birincil birincille, yedek yedekle karsilastirilir. Ayni kumenin
birden cok yedegi birbirinden ayrilmaz. Kimlik okunamazsa karsilastirma yapilmaz. SQL Server icin henuz kimlik yok.

Iki tarama da bugunku kurallar ve puan katsayilariyla degerlendirilir; puanlar bu yuzden karsilastirilabilir.

Kayit siniflari (sinif):
  S  sorun: FAIL ya da WARNING
  T  temiz: PASS (butun kanit geldi, bulgu yok)
  Y  konu yok: veriden gelen NOT_APPLICABLE (ornegin slot yok)
  B  kanit yok: UNKNOWN, UNAVAILABLE, yedekte degerlendirilmeyen kural (birincil_degil), kayit hic yok

Durumlar (iki taramanin birinde sorun olan kurallar; ikisinde de sorun yoksa kural listelenmez):
  NEW         simdi sorun var, once konu yoktu (Y -> S)
  REGRESSED   simdi sorun var, once temizdi ya da sorun daha hafifti (T -> S, onemi artan S -> S)
  PERSISTING  sorun suruyor, onemi ayni ya da daha hafif (S -> S)
  RESOLVED    once sorun vardi, simdi kanitla temiz ya da konu kalkmis (S -> T, S -> Y)
  UNKNOWN     once sorun vardi simdi kanit yetersiz (S -> B: kaybolan kanit cozulmus sayilmaz) ya da simdi sorun var
              ama once kanit yoktu (B -> S: yeni mi bilinmez)
"""
import re

from tarama import kanit, kurallar, puan

DURUMLAR = ("NEW", "REGRESSED", "PERSISTING", "RESOLVED", "UNKNOWN")   # rapordaki sira: once yeni ve kotulesen
SORUN = ("FAIL", "WARNING")
KANITSIZ_UYGULANMAZ = ("birincil_degil",)   # uygulanmaz ama veriden degil: yedekte degerlendirilmedi
_OZET = re.compile(r"^[0-9a-f]{64}$")


def kimlik(belge):
    """Karsilastirma anahtari "postgresql:<kume ozeti>:<birincil|yedek>" ya da None."""
    if not isinstance(belge, dict) or belge.get("motor", "postgresql") != "postgresql" or not isinstance(belge.get("kontroller"), dict):
        return None
    k = belge["kontroller"]
    e = k.get("pg_kume_kimligi")
    try:
        oz = e["satirlar"][0]["kume"] if e["durum"] == "ok" and len(e["satirlar"]) == 1 else None
    except (TypeError, KeyError, IndexError):
        return None
    yedek = kanit.yedek_mi(k)
    if not isinstance(oz, str) or not _OZET.match(oz) or yedek is None:
        return None
    return "postgresql:%s:%s" % (oz, "yedek" if yedek else "birincil")


def sinif(kayit):
    """S, T, Y ya da B (modul aciklamasi)."""
    if kayit is None:
        return "B"
    d = kayit["durum"]
    if d in SORUN:
        return "S"
    if d == "PASS":
        return "T"
    if d == "NOT_APPLICABLE" and kayit.get("neden") not in KANITSIZ_UYGULANMAZ:
        return "Y"
    return "B"


def durum(onceki, yeni):
    """Iki kaydin karsilastirma durumu; iki taramada da sorun yoksa None."""
    o, y = sinif(onceki), sinif(yeni)
    if y == "S":
        if o == "S":
            agir = kanit.ONEM_SIRASI.index(yeni["onem"]) < kanit.ONEM_SIRASI.index(onceki["onem"])
            return "REGRESSED" if agir else "PERSISTING"
        return {"T": "REGRESSED", "Y": "NEW"}.get(o, "UNKNOWN")
    if o == "S":
        return "RESOLVED" if y in ("T", "Y") else "UNKNOWN"
    return None


class Karsilastirma:
    """onceki_tarih, yeni_tarih: belgelerdeki tarama zamani. onceki_puan, yeni_puan: puan.Puan.
    kurallar: [{kural, kategori, ad, durum, neden (UNKNOWN icin kanit_kayboldu ya da onceki_kanit_yok), onceki, yeni}]
      onceki ve yeni: kanit kaydindaki {durum, onem, neden}. DURUMLAR sirasiyla, ayni durumda onem ve kimlik sirasiyla.
    katalog_farkli: iki tarama toplayicinin farkli surumleriyle yapildi (eski surumde olmayan denetim once kanitsiz sayilir)."""

    def __init__(self, **alanlar):
        self.__dict__.update(alanlar)

    def say(self):
        return {d: sum(1 for x in self.kurallar if x["durum"] == d) for d in DURUMLAR}


def _ozet(k):
    return {"durum": k["durum"], "onem": k["onem"], "neden": k["neden"]}


def karsilastir(onceki_belge, yeni_belge, katsayilar=None):
    so, sy = kurallar.incele(onceki_belge), kurallar.incele(yeni_belge)
    once = {k["kural"]: k for k in so.kayitlar}
    satirlar = []
    for y in sy.kayitlar:
        o = once.get(y["kural"])
        d = durum(o, y)
        if d is None:
            continue
        neden = None
        if d == "UNKNOWN":
            neden = "kanit_kayboldu" if sinif(o) == "S" else "onceki_kanit_yok"
        onem = y["onem"] if y["durum"] in SORUN else o["onem"]
        satirlar.append({"kural": y["kural"], "kategori": y["kategori"], "ad": y["ad"], "durum": d, "neden": neden,
                         "onceki": _ozet(o) if o else {"durum": None, "onem": None, "neden": None}, "yeni": _ozet(y),
                         "_sira": (DURUMLAR.index(d), kanit.ONEM_SIRASI.index(onem), y["kural"])})
    satirlar.sort(key=lambda x: x["_sira"])
    for x in satirlar:
        del x["_sira"]
    return Karsilastirma(onceki_tarih=onceki_belge.get("olusturma_utc"), yeni_tarih=yeni_belge.get("olusturma_utc"),
                         onceki_puan=puan.hesapla(so, katsayilar), yeni_puan=puan.hesapla(sy, katsayilar), kurallar=satirlar,
                         katalog_farkli=onceki_belge.get("katalog_sha256") != yeni_belge.get("katalog_sha256"))
