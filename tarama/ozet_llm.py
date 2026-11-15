"""Language model (LLM) report summary: a pluggable interface. OFF BY DEFAULT; it cannot produce evidence or change the score (item 23).

Decision WEB-K5: no service has been chosen. This module has NO real provider and no network call; there is only a fake,
deterministic provider for tests. Adding a real provider is a separate job: it first needs the WEB-K5 decision and legal (KVKK, the Turkish data protection law) approval.

Enabling: the ALIG_LLM_OZET=1 environment variable AND a registered provider object. If either is missing, no summary is produced.

Data sent to the provider (GIRDI_ALANLARI): only the rule id derived from the rule output, status, severity and a short title.
Object names, query text, IP/host, email, evidence list, source, recommendation and score are NEVER sent; the title is masked anyway.
If the output does not pass the validator (a rule id not in the input, a number/percentage, a "PASS/passed" claim, length, control characters)
it is not shown and a log event is written without the content. The report runs the same without a summary in every case."""
import logging
import os
import re

ORTAM = "ALIG_LLM_OZET"
GIRDI_ALANLARI = ("kural", "durum", "onem", "baslik")   # the single, explicit list of fields sent to the provider
AZAMI_UZUNLUK = 1200
AZAMI_BASLIK = 160
GUNLUK = logging.getLogger("alig.ozet_llm")

_KIMLIK = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b")
_GECTI = re.compile(r"\bpass\w*|ge[cç]t[iİı]|ge[cç]er\b|ge[cç]iyor\b|ba[sş]ar[ıi]l[ıi]|success\w*", re.I)
_KONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MASKE = "[maskeli]"
_MASKELER = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),                                       # email
    re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])"),      # IPv6
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                                        # IPv4
    re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),                # host name
    re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`"),                                         # quoted object name / value
    re.compile(r"(?i:\bselect\b).*|\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY)\b.*"),   # query text
)

_saglayici = None


class Saglayici:
    """Provider interface. ozet(girdi, dil): girdi is a list of dicts made of GIRDI_ALANLARI; returns plain text."""

    def ozet(self, girdi, dil):
        raise NotImplementedError


class SahteSaglayici(Saglayici):
    """TEST ONLY: no network, no model. Counts the rule ids in the input in order; the same input gives the same text."""

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
        raise TypeError("provider must be of type Saglayici")
    _saglayici = saglayici


def temizle():
    global _saglayici
    _saglayici = None


def etkin(ortam=None):
    """True if the environment variable is exactly '1' AND a provider is registered. Default: off."""
    ortam = os.environ if ortam is None else ortam
    return ortam.get(ORTAM) == "1" and _saglayici is not None


def maskele(metin):
    """Removes identifier-like fragments: email, IP, host, quoted name, query text."""
    metin = str(metin)
    for desen in _MASKELER:
        metin = desen.sub(_MASKE, metin)
    return metin


def girdi_olustur(bulgular, dil):
    """Deterministic input ordered by severity that carries only allowlist fields from the findings. The title is masked and shortened."""
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
    """(ok, reason_code). The reason code is a fixed word; the text itself is never carried anywhere."""
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
    """The report is not broken even if the event writer is broken. Fields are only fixed codes and class names: no content is written."""
    try:
        if olay is None:
            GUNLUK.warning("%s %s", ad, " ".join("%s=%s" % (k, v) for k, v in sorted(alan.items())))
        else:
            olay(ad, **alan)
    except Exception:   # noqa: BLE001  the report must run in every case
        pass


def ozet_uret(bulgular, dil, ortam=None, olay=None):
    """A validated plain-text summary or None (off, no provider, error, rejected). Never raises.
    olay(ad, **alan): audit/log writer; if not given, the 'alig.ozet_llm' logger."""
    try:
        if not etkin(ortam):
            return None
        girdi = girdi_olustur(bulgular, dil)
        izinli = {o["kural"] for o in girdi}
        try:
            metin = _saglayici.ozet(girdi, "en" if dil == "en" else "tr")
        except Exception as ex:   # noqa: BLE001  a provider error does not break the report; no message is written, only the class name
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
