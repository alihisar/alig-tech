"""Dil modeli (LLM) rapor ozeti: takilabilir arayuz. VARSAYILAN KAPALI; kanit uretemez, puani degistiremez (madde 23).

Karar WEB-K5: hizmet secilmedi. Bu modulde GERCEK saglayici ve ag cagrisi yoktur; yalniz test icin sahte, deterministik
saglayici vardir. Gercek saglayici eklemek ayri bir is: once WEB-K5 karari ve hukuki (KVKK) onay gerekir.

Acilis: ALIG_LLM_OZET=1 ortam degiskeni VE kaydedilmis bir saglayici nesnesi. Biri eksikse ozet uretilmez.

Saglayiciya giden veri (GIRDI_ALANLARI): yalniz kural ciktisindan turemis kural kimligi, durum, onem ve kisa baslik.
Nesne adi, sorgu metni, IP/host, e-posta, kanit listesi, kaynak, oneri ve puan HIC gonderilmez; baslik yine de maskelenir.
Cikti dogrulayicidan gecmezse (girdide olmayan kural kimligi, sayi/yuzde, "PASS/gecti" iddiasi, uzunluk, kontrol karakteri)
gosterilmez ve icerik yazilmadan bir gunluk olayi yazilir. Rapor her durumda ozetsiz ayni calisir."""
import logging
import os
import re

ORTAM = "ALIG_LLM_OZET"
GIRDI_ALANLARI = ("kural", "durum", "onem", "baslik")   # saglayiciya giden alanlarin tek ve acik listesi
AZAMI_UZUNLUK = 1200
AZAMI_BASLIK = 160
GUNLUK = logging.getLogger("alig.ozet_llm")

_KIMLIK = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b")
_GECTI = re.compile(r"\bpass\w*|ge[cç]t[iİı]|ge[cç]er\b|ge[cç]iyor\b|ba[sş]ar[ıi]l[ıi]|success\w*", re.I)
_KONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MASKE = "[maskeli]"
_MASKELER = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),                                       # e-posta
    re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])"),      # IPv6
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                                        # IPv4
    re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),                # host adi
    re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`"),                                         # tirnakli nesne adi / deger
    re.compile(r"(?i:\bselect\b).*|\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY)\b.*"),   # sorgu metni
)

_saglayici = None


class Saglayici:
    """Saglayici arayuzu. ozet(girdi, dil): girdi GIRDI_ALANLARI'ndan olusan sozluklerin listesi; duz metin dondurur."""

    def ozet(self, girdi, dil):
        raise NotImplementedError


class SahteSaglayici(Saglayici):
    """YALNIZ TEST: ag yok, model yok. Girdideki kural kimliklerini sirayla sayar; ayni girdiye ayni metin."""

    def ozet(self, girdi, dil):
        kimlikler = ", ".join(o["kural"] for o in girdi)
        if not kimlikler:
            return "Bulgu yok." if dil != "en" else "No findings."
        if dil == "en":
            return "Test summary (fake provider): review %s first." % kimlikler
        return "Test özeti (sahte sağlayıcı): önce %s incelenmeli." % kimlikler


def kaydet(saglayici):
    global _saglayici
    if not isinstance(saglayici, Saglayici):
        raise TypeError("saglayici Saglayici turunden olmali")
    _saglayici = saglayici


def temizle():
    global _saglayici
    _saglayici = None


def etkin(ortam=None):
    """Ortam degiskeni tam '1' VE kayitli saglayici varsa True. Varsayilan: kapali."""
    ortam = os.environ if ortam is None else ortam
    return ortam.get(ORTAM) == "1" and _saglayici is not None


def maskele(metin):
    """Tanimlayici gibi gorunen parcalari siler: e-posta, IP, host, tirnakli ad, sorgu metni."""
    metin = str(metin)
    for desen in _MASKELER:
        metin = desen.sub(_MASKE, metin)
    return metin


def girdi_olustur(bulgular, dil):
    """Bulgulardan yalniz allowlist alanlarini tasiyan, onem sirali ve deterministik girdi. Baslik maskelenir ve kisaltilir."""
    d = "en" if dil == "en" else "tr"
    sira = ("kritik", "yuksek", "orta", "dusuk", "bilgi")
    secili = sorted(bulgular, key=lambda b: (sira.index(b["onem"]) if b["onem"] in sira else len(sira), b["kural"]))
    cikti = []
    for b in secili:
        baslik = b.get("baslik")
        baslik = baslik.get(d, "") if isinstance(baslik, dict) else ""
        deger = {"kural": b["kural"], "durum": b["durum"], "onem": b["onem"], "baslik": maskele(baslik)[:AZAMI_BASLIK]}
        cikti.append({a: deger[a] for a in GIRDI_ALANLARI})
    return cikti


def dogrula(metin, izinli_kimlikler):
    """(tamam, neden_kodu). Neden kodu sabit bir sozcuktur; metnin kendisi hicbir yere tasinmaz."""
    if not isinstance(metin, str):
        return False, "tur"
    duz = " ".join(metin.split())
    if not duz:
        return False, "bos"
    if len(duz) > AZAMI_UZUNLUK:
        return False, "uzun"
    if _KONTROL.search(metin):
        return False, "kontrol"
    for k in _KIMLIK.findall(duz):
        if k not in izinli_kimlikler:
            return False, "kimlik"
    kalan = _KIMLIK.sub(" ", duz)
    if re.search(r"\d|%|\u066a|\uff05", kalan):
        return False, "sayi"
    if _GECTI.search(kalan):
        return False, "gecti"
    return True, "tamam"


def _olay_yaz(olay, ad, **alan):
    """Olay yazici bozuk olsa da rapor bozulmaz. Alanlar yalniz sabit kodlar ve sinif adlari: icerik yazilmaz."""
    try:
        if olay is None:
            GUNLUK.warning("%s %s", ad, " ".join("%s=%s" % (k, v) for k, v in sorted(alan.items())))
        else:
            olay(ad, **alan)
    except Exception:   # noqa: BLE001  rapor her durumda calismali
        pass


def ozet_uret(bulgular, dil, ortam=None, olay=None):
    """Dogrulanmis duz metin ozet ya da None (kapali, saglayici yok, hata, reddedildi). Asla istisna firlatmaz.
    olay(ad, **alan): denetim/gunluk yazici; verilmezse 'alig.ozet_llm' gunlugu."""
    try:
        if not etkin(ortam):
            return None
        girdi = girdi_olustur(bulgular, dil)
        izinli = {o["kural"] for o in girdi}
        try:
            metin = _saglayici.ozet(girdi, "en" if dil == "en" else "tr")
        except Exception as ex:   # noqa: BLE001  saglayici hatasi raporu bozmaz; ileti yazilmaz, yalniz sinif adi
            _olay_yaz(olay, "ozet_hata", sinif=re.sub(r"\W", "", type(ex).__name__)[:60])
            return None
        tamam, neden = dogrula(metin, izinli)
        if not tamam:
            _olay_yaz(olay, "ozet_reddedildi", neden=neden)
            return None
        return " ".join(metin.split())
    except Exception as ex:   # noqa: BLE001
        _olay_yaz(olay, "ozet_hata", sinif=re.sub(r"\W", "", type(ex).__name__)[:60])
        return None
