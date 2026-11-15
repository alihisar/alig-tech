"""Health score and evidence coverage. Computed from the evidence records (tarama/kanit.py); no language model, the same records and the same
coefficients always give the same score.

The score is between 0 and 100, the weighted credit ratio of the applicable rules:

    score = 100 * sum(multiplier * weight * credit) / sum(multiplier * weight)

  agirlik (weight)   by the rule's risk level (its impact in the worst case if the rule fails): VARSAYILAN["agirlik"]
  carpan (multiplier) by the rule's category; the default is 1 for all
  kredi (credit)     PASS 1, FAIL 0, UNKNOWN 0, UNAVAILABLE 0; WARNING by the finding's severity (VARSAYILAN["kredi_uyari"])
  NOT_APPLICABLE enters neither the score nor the coverage.

An unknown status does not raise the score: a rule with no evidence loses as many points as a failed rule (credit 0, its weight stays
in the denominator). A rule whose evidence disappears does not improve the score. For this reason the score is always shown together with the evidence coverage, and the
breakdown separates whether each loss comes from a finding or from missing evidence. If there is no weighted evidence at all the score is not computed (None).

Evidence coverage: the ratio of applicable rules that have evidence (PASS, WARNING, FAIL), unweighted.
The integers shown are rounded down: 100 appears only if there is no loss, and 100% coverage only if every rule has evidence.

The coefficients are read from the JSON file given with ALIG_PUAN_AYARI; values not given stay at the default. Example:
    {"agirlik": {"kritik": 12}, "kredi_uyari": {"orta": 0.4}, "kategori_carpani": {"guvenlik": 1.5}}
Services do not start with an invalid file (yukle). Status credits are fixed: a setting that rewards an unknown status cannot be made.
"""
import copy
import json
import math
import os

from tarama import kanit

ORTAM = "ALIG_PUAN_AYARI"
KANITLI = ("PASS", "WARNING", "FAIL")
# Fixed status credits. The credit of WARNING comes from the coefficients, by the finding's severity.
KREDI = {"PASS": 1.0, "FAIL": 0.0, "UNKNOWN": 0.0, "UNAVAILABLE": 0.0}
# MUHENDISLIK: our own choice, not from an official standard (docs/doldurulacak.md).
VARSAYILAN = {
    "agirlik": {"kritik": 10, "yuksek": 6, "orta": 3, "dusuk": 1, "bilgi": 0},
    "kredi_uyari": {"orta": 0.5, "dusuk": 0.75, "bilgi": 1.0},
    "kategori_carpani": {k: 1.0 for k in kanit.KATEGORILER},
}
UST_SINIR = {"agirlik": 1000, "kredi_uyari": 1, "kategori_carpani": 100}   # no overflow or meaningless values
MAX_BAYT = 65536

ETKIN = copy.deepcopy(VARSAYILAN)   # set from the environment with yukle() when the service starts


class PuanAyarHatasi(ValueError):
    pass


def katsayi_dogrula(ham):
    """Validates the user setting and merges it with the defaults. PuanAyarHatasi if invalid; it does not silently fall back to the default."""
    if not isinstance(ham, dict):
        raise PuanAyarHatasi("the score setting must be a JSON object")
    bilinmeyen = sorted(set(ham) - set(VARSAYILAN))
    if bilinmeyen:
        raise PuanAyarHatasi("unknown field: %s (valid: %s)" % (", ".join(map(str, bilinmeyen)), ", ".join(VARSAYILAN)))
    sonuc = copy.deepcopy(VARSAYILAN)
    for alan, varsayilan in VARSAYILAN.items():
        deger = ham.get(alan, {})
        if not isinstance(deger, dict):
            raise PuanAyarHatasi("%s must be a JSON object" % alan)
        for anahtar, v in deger.items():
            if anahtar not in varsayilan:
                raise PuanAyarHatasi("%s.%s is unknown (valid: %s)" % (alan, anahtar, ", ".join(varsayilan)))
            # NaN and infinity are also rejected here: NaN is false in every comparison, infinity is larger than the upper limit
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= UST_SINIR[alan]:
                raise PuanAyarHatasi("%s.%s must be a number between 0 and %s" % (alan, anahtar, UST_SINIR[alan]))
            sonuc[alan][anahtar] = v
    for alan in ("agirlik", "kategori_carpani"):
        if not any(sonuc[alan].values()):
            raise PuanAyarHatasi("at least one of the %s values must be greater than zero" % alan)
    return sonuc


def _tekil(ciftler):
    d = dict(ciftler)
    if len(d) != len(ciftler):
        raise ValueError("duplicate key")
    return d


def ortamdan(ortam=None):
    """The coefficients in the ALIG_PUAN_AYARI file; the defaults if the variable is absent. An error on an unreadable or invalid file."""
    yol = (os.environ if ortam is None else ortam).get(ORTAM, "").strip()
    if not yol:
        return copy.deepcopy(VARSAYILAN)
    try:
        if not os.path.isfile(yol):   # not a directory, pipe or device: reading must not stall the service
            raise ValueError("not a regular file or does not exist")
        with open(yol, "rb") as f:
            veri = f.read(MAX_BAYT + 1)
        if len(veri) > MAX_BAYT:
            raise ValueError("file is larger than %d bytes" % MAX_BAYT)
        ham = json.loads(veri.decode("utf-8-sig"), object_pairs_hook=_tekil)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as ex:
        raise PuanAyarHatasi("%s=%s could not be read: %s" % (ORTAM, yol, (ex.strerror or ex) if isinstance(ex, OSError) else ex)) from None
    try:
        return katsayi_dogrula(ham)
    except PuanAyarHatasi as ex:
        raise PuanAyarHatasi("%s=%s: %s" % (ORTAM, yol, ex)) from None


def yukle(ortam=None):
    """Called once when the service starts: sets the active coefficients from the environment. A change takes effect when the service restarts."""
    global ETKIN
    ETKIN = ortamdan(ortam)
    return ETKIN


def varsayilan_mi(katsayilar=None):
    return (ETKIN if katsayilar is None else katsayilar) == VARSAYILAN


def kredi(kayit, katsayilar=None):
    """The record's contribution to the score (0-1). None for NOT_APPLICABLE: it does not enter the score."""
    durum = kayit["durum"]
    if durum == "NOT_APPLICABLE":
        return None
    if durum == "WARNING":
        return (ETKIN if katsayilar is None else katsayilar)["kredi_uyari"].get(kayit.get("onem"), 0.0)
    return KREDI.get(durum, 0.0)


class Puan:
    """genel     integer 0-100 or None (no weighted evidence: could not be computed)
    ham         fractional score; 0 when there is no evidence
    kapsam      percentage of applicable rules that have evidence (rounded down); kapsam_ham is fractional
    olculen, uygulanabilir   rule counts
    kategoriler {category: {puan, ham, kapsam, olculen, uygulanabilir}}: categories that have rules for the engine, in KATEGORILER order
    kayiplar    rules that lower the score, largest to smallest: {kural, kategori, durum, onem, neden, tur (bulgu|kanit), kayip}
    bulgu_kaybi, kanit_kaybi  totals of losses coming from findings and from missing evidence
    """

    def __init__(self, **alanlar):
        self.__dict__.update(alanlar)


def _tamsayi(ham, kayip_var):
    return 100 if not kayip_var else max(0, min(99, math.floor(ham + 1e-9)))


def _oran(kayitlar, agirlik, katsayilar):
    """(raw, losses, weighted_evidence_exists). kayip: the share of the score the rule took away (0-100)."""
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
    """kanit.Sonuc (or a list of records) -> Puan."""
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
