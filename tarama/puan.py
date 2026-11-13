"""Saglik puani ve kanit kapsami. Kanit kayitlarindan (tarama/kanit.py) hesaplanir; dil modeli yok, ayni kayitlar ve ayni
katsayilar her zaman ayni puani verir.

Puan 0-100 arasidir, uygulanabilir kurallarin agirlikli kredi oranidir:

    puan = 100 * toplam(carpan * agirlik * kredi) / toplam(carpan * agirlik)

  agirlik  kuralin risk duzeyine gore (kural basarisiz olursa en kotu durumda etkisi): VARSAYILAN["agirlik"]
  carpan   kuralin kategorisine gore; varsayilan hepsi 1
  kredi    PASS 1, FAIL 0, UNKNOWN 0, UNAVAILABLE 0; WARNING bulgunun onemine gore (VARSAYILAN["kredi_uyari"])
  NOT_APPLICABLE puana da kapsama da girmez.

Bilinmeyen durum puani yukseltmez: kaniti olmayan kural, basarisiz kural kadar puan kaybettirir (kredisi 0, agirligi
paydada kalir). Kaniti kaybolan kural puani iyilestirmez. Bu yuzden puan her zaman kanit kapsamiyla birlikte gosterilir ve
dokum her kaybin bulgudan mi kanit eksikliginden mi geldigini ayirir. Agirlikli kanit hic yoksa puan hesaplanmaz (None).

Kanit kapsami: uygulanabilir kurallardan kaniti olanlarin (PASS, WARNING, FAIL) orani, agirliksiz.
Gosterilen tamsayilar asagi yuvarlanir: 100 yalniz kayip yoksa, %100 kapsam yalniz her kuralin kaniti varsa gorunur.

Katsayilar ALIG_PUAN_AYARI ile verilen JSON dosyasindan okunur; verilmeyen deger varsayilan kalir. Ornek:
    {"agirlik": {"kritik": 12}, "kredi_uyari": {"orta": 0.4}, "kategori_carpani": {"guvenlik": 1.5}}
Gecersiz dosyayla servisler baslamaz (yukle). Durum kredileri sabittir: bilinmeyen durumu odullendiren ayar yapilamaz.
"""
import copy
import json
import math
import os

from tarama import kanit

ORTAM = "ALIG_PUAN_AYARI"
KANITLI = ("PASS", "WARNING", "FAIL")
# Sabit durum kredileri. WARNING'in kredisi bulgunun onemine gore katsayilardan gelir.
KREDI = {"PASS": 1.0, "FAIL": 0.0, "UNKNOWN": 0.0, "UNAVAILABLE": 0.0}
# MUHENDISLIK: kendi secimimiz, resmi bir standarttan gelmez (docs/doldurulacak.md).
VARSAYILAN = {
    "agirlik": {"kritik": 10, "yuksek": 6, "orta": 3, "dusuk": 1, "bilgi": 0},
    "kredi_uyari": {"orta": 0.5, "dusuk": 0.75, "bilgi": 1.0},
    "kategori_carpani": {k: 1.0 for k in kanit.KATEGORILER},
}
UST_SINIR = {"agirlik": 1000, "kredi_uyari": 1, "kategori_carpani": 100}   # tasma ve anlamsiz deger olmasin
MAX_BAYT = 65536

ETKIN = copy.deepcopy(VARSAYILAN)   # servis baslarken yukle() ile ortamdan ayarlanir


class PuanAyarHatasi(ValueError):
    pass


def katsayi_dogrula(ham):
    """Kullanici ayarini dogrular, varsayilanlarla birlestirir. Gecersizse PuanAyarHatasi; sessizce varsayilana donmez."""
    if not isinstance(ham, dict):
        raise PuanAyarHatasi("puan ayari bir JSON nesnesi olmali")
    bilinmeyen = sorted(set(ham) - set(VARSAYILAN))
    if bilinmeyen:
        raise PuanAyarHatasi("bilinmeyen alan: %s (gecerli: %s)" % (", ".join(map(str, bilinmeyen)), ", ".join(VARSAYILAN)))
    sonuc = copy.deepcopy(VARSAYILAN)
    for alan, varsayilan in VARSAYILAN.items():
        deger = ham.get(alan, {})
        if not isinstance(deger, dict):
            raise PuanAyarHatasi("%s bir JSON nesnesi olmali" % alan)
        for anahtar, v in deger.items():
            if anahtar not in varsayilan:
                raise PuanAyarHatasi("%s.%s bilinmiyor (gecerli: %s)" % (alan, anahtar, ", ".join(varsayilan)))
            # NaN ve sonsuz da burada reddedilir: NaN her karsilastirmada yanlis, sonsuz ust sinirdan buyuk
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= UST_SINIR[alan]:
                raise PuanAyarHatasi("%s.%s 0 ile %s arasinda bir sayi olmali" % (alan, anahtar, UST_SINIR[alan]))
            sonuc[alan][anahtar] = v
    for alan in ("agirlik", "kategori_carpani"):
        if not any(sonuc[alan].values()):
            raise PuanAyarHatasi("%s degerlerinden en az biri sifirdan buyuk olmali" % alan)
    return sonuc


def _tekil(ciftler):
    d = dict(ciftler)
    if len(d) != len(ciftler):
        raise ValueError("yinelenen anahtar")
    return d


def ortamdan(ortam=None):
    """ALIG_PUAN_AYARI dosyasindaki katsayilar; degisken yoksa varsayilanlar. Okunamayan ya da gecersiz dosyada hata."""
    yol = (os.environ if ortam is None else ortam).get(ORTAM, "").strip()
    if not yol:
        return copy.deepcopy(VARSAYILAN)
    try:
        if not os.path.isfile(yol):   # dizin, boru ya da aygit degil: okuma servisi bekletmesin
            raise ValueError("duzenli bir dosya degil ya da yok")
        with open(yol, "rb") as f:
            veri = f.read(MAX_BAYT + 1)
        if len(veri) > MAX_BAYT:
            raise ValueError("dosya %d bayttan buyuk" % MAX_BAYT)
        ham = json.loads(veri.decode("utf-8-sig"), object_pairs_hook=_tekil)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as ex:
        raise PuanAyarHatasi("%s=%s okunamadi: %s" % (ORTAM, yol, (ex.strerror or ex) if isinstance(ex, OSError) else ex)) from None
    try:
        return katsayi_dogrula(ham)
    except PuanAyarHatasi as ex:
        raise PuanAyarHatasi("%s=%s: %s" % (ORTAM, yol, ex)) from None


def yukle(ortam=None):
    """Servis baslarken bir kez cagrilir: etkin katsayilari ortamdan ayarlar. Degisiklik servis yeniden baslayinca gecerli olur."""
    global ETKIN
    ETKIN = ortamdan(ortam)
    return ETKIN


def varsayilan_mi(katsayilar=None):
    return (ETKIN if katsayilar is None else katsayilar) == VARSAYILAN


def kredi(kayit, katsayilar=None):
    """Kaydin puana katkisi (0-1). NOT_APPLICABLE icin None: puana girmez."""
    durum = kayit["durum"]
    if durum == "NOT_APPLICABLE":
        return None
    if durum == "WARNING":
        return (ETKIN if katsayilar is None else katsayilar)["kredi_uyari"].get(kayit.get("onem"), 0.0)
    return KREDI.get(durum, 0.0)


class Puan:
    """genel     0-100 tamsayi ya da None (agirlikli kanit yok: hesaplanamadi)
    ham         kesirli puan; kanit yokken 0
    kapsam      kaniti olan uygulanabilir kural yuzdesi (asagi yuvarlanir); kapsam_ham kesirli
    olculen, uygulanabilir   kural sayilari
    kategoriler {kategori: {puan, ham, kapsam, olculen, uygulanabilir}}: motorun kurali olan kategoriler, KATEGORILER sirasiyla
    kayiplar    puani dusuren kurallar, buyukten kucuge: {kural, kategori, durum, onem, neden, tur (bulgu|kanit), kayip}
    bulgu_kaybi, kanit_kaybi  kayiplarin bulgudan ve kanit eksikliginden gelen toplamlari
    """

    def __init__(self, **alanlar):
        self.__dict__.update(alanlar)


def _tamsayi(ham, kayip_var):
    return 100 if not kayip_var else max(0, min(99, math.floor(ham + 1e-9)))


def _oran(kayitlar, agirlik, katsayilar):
    """(ham, kayiplar, agirlikli_kanit_var). kayip: kuralin puandan goturdugu pay (0-100)."""
    uyg = [k for k in kayitlar if k["durum"] != "NOT_APPLICABLE"]
    toplam = sum(agirlik(k) for k in uyg)
    if toplam <= 0:
        return 0.0, [], False
    kayiplar = []
    for k in uyg:
        kayip = 100.0 * agirlik(k) * (1.0 - kredi(k, katsayilar)) / toplam
        if kayip > 0:
            kayiplar.append({"kural": k["kural"], "kategori": k["kategori"], "durum": k["durum"], "onem": k.get("onem"),
                             "neden": k.get("neden"), "tur": "bulgu" if k["durum"] in KANITLI else "kanit", "kayip": kayip})
    kanit_var = any(agirlik(k) > 0 for k in uyg if k["durum"] in KANITLI)
    return max(0.0, 100.0 - sum(x["kayip"] for x in kayiplar)), kayiplar, kanit_var


def hesapla(sonuc, katsayilar=None):
    """kanit.Sonuc (ya da kayit listesi) -> Puan."""
    ayar = ETKIN if katsayilar is None else katsayilar
    kayitlar = sonuc.kayitlar if hasattr(sonuc, "kayitlar") else list(sonuc)
    uyg = [x for x in kayitlar if x["durum"] != "NOT_APPLICABLE"]
    olculen = sum(1 for x in uyg if x["durum"] in KANITLI)

    ham, kayiplar, kanit_var = _oran(kayitlar, lambda x: ayar["kategori_carpani"][x["kategori"]] * ayar["agirlik"][x["risk"]], ayar)
    kayiplar.sort(key=lambda x: (-x["kayip"], x["kural"]))
    kategoriler = {}
    for kat in kanit.KATEGORILER:
        kk = [x for x in kayitlar if x["kategori"] == kat]
        if not kk:
            continue
        k_ham, k_kayip, k_kanit = _oran(kk, lambda x: ayar["agirlik"][x["risk"]], ayar)
        k_uyg = sum(1 for x in kk if x["durum"] != "NOT_APPLICABLE")
        k_olc = sum(1 for x in kk if x["durum"] in KANITLI)
        kategoriler[kat] = {"puan": _tamsayi(k_ham, k_kayip) if k_kanit else None, "ham": k_ham,
                            "kapsam": k_olc * 100 // k_uyg if k_uyg else 0, "olculen": k_olc, "uygulanabilir": k_uyg}
    return Puan(genel=_tamsayi(ham, kayiplar) if kanit_var else None, ham=ham,
                kapsam=olculen * 100 // len(uyg) if uyg else 0, kapsam_ham=100 * olculen / len(uyg) if uyg else 0.0,
                olculen=olculen, uygulanabilir=len(uyg), kategoriler=kategoriler, kayiplar=kayiplar,
                bulgu_kaybi=sum(x["kayip"] for x in kayiplar if x["tur"] == "bulgu"),
                kanit_kaybi=sum(x["kayip"] for x in kayiplar if x["tur"] == "kanit"))
