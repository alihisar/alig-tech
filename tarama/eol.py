"""PostgreSQL end-of-life (EOL) table and evaluation (ALIG-SCAN-002, rule PG-MAINT-009; PG-MAINT-001 reads the same table).

Source: the PostgreSQL versioning policy, https://www.postgresql.org/support/versioning/ ; the dates below were retrieved on
2026-11-16. "Final release" is the last minor release the community publishes for a major version. Versions older than the first
row are no longer supported; no date is invented for them. The table must be verified against the source every year
(docs/doldurulacak.md).

The evaluation is a pure function of (major version, date, settings): the scan date is passed in (it comes from the scan
document), there is no clock call here. Evidence on a day: on the final release date itself the version counts as "approaching" with
0 days left; from the next day on it is "ended".

Settings can be overridden without a code change with the JSON file given in ALIG_EOL_AYARI; values not given stay at the default:
    {"pencere_gun": 90, "son_tarihler": {"14": "2027-06-30", "19": "2031-11-13"}}
  pencere_gun   warn this many days before the final release date (default 180; 0-3650)
  son_tarihler  major version -> final release date (YYYY-MM-DD); replaces the date in the table or adds a new major version
Services do not start with an invalid file (yukle). The module is advisory only: nothing here changes a customer system.
"""
import copy
import json
import os
from datetime import date, datetime

KAYNAK_URL = "https://www.postgresql.org/support/versioning/"
ALINMA_TARIHI = "2026-11-16"
ORTAM = "ALIG_EOL_AYARI"
MAX_BAYT = 65536
UST_PENCERE = 3650

# BELGE: first release and final release (EOL) per major version, from KAYNAK_URL
VARSAYILAN = {
    "tablo": {
        13: {"ilk": "2020-09-24", "son": "2025-11-13"},
        14: {"ilk": "2021-09-30", "son": "2026-11-12"},
        15: {"ilk": "2022-10-13", "son": "2027-11-11"},
        16: {"ilk": "2023-09-14", "son": "2028-11-09"},
        17: {"ilk": "2024-09-26", "son": "2029-11-08"},
        18: {"ilk": "2025-09-25", "son": "2030-11-14"},
    },
    "pencere_gun": 180,   # MUHENDISLIK: our own choice, configurable
}
ETKIN = copy.deepcopy(VARSAYILAN)   # set from the environment with yukle() when the service starts


class EolAyarHatasi(ValueError):
    pass


def _tarih(metin, ad):
    if not isinstance(metin, str) or len(metin) != 10:
        raise EolAyarHatasi("%s must be a date in YYYY-MM-DD form" % ad)
    try:
        return date.fromisoformat(metin)
    except ValueError:
        raise EolAyarHatasi("%s must be a real date in YYYY-MM-DD form" % ad) from None


def ayar_dogrula(ham):
    """Validates the user setting and merges it with the defaults. EolAyarHatasi if invalid; never a silent fallback."""
    if not isinstance(ham, dict):
        raise EolAyarHatasi("the EOL setting must be a JSON object")
    bilinmeyen = sorted(set(ham) - {"pencere_gun", "son_tarihler"})
    if bilinmeyen:
        raise EolAyarHatasi("unknown field: %s (valid: pencere_gun, son_tarihler)" % ", ".join(map(str, bilinmeyen)))
    sonuc = copy.deepcopy(VARSAYILAN)
    if "pencere_gun" in ham:
        p = ham["pencere_gun"]
        if isinstance(p, bool) or not isinstance(p, int) or not 0 <= p <= UST_PENCERE:
            raise EolAyarHatasi("pencere_gun must be a whole number between 0 and %d" % UST_PENCERE)
        sonuc["pencere_gun"] = p
    tarihler = ham.get("son_tarihler", {})
    if not isinstance(tarihler, dict):
        raise EolAyarHatasi("son_tarihler must be a JSON object")
    for anahtar, deger in tarihler.items():
        if not isinstance(anahtar, str) or not anahtar.isascii() or not anahtar.isdigit() or not 9 <= int(anahtar) <= 999:
            raise EolAyarHatasi("son_tarihler key %r must be a major version number such as 14" % (anahtar,))
        ana = int(anahtar)
        son = _tarih(deger, "son_tarihler.%s" % anahtar)
        ilk = sonuc["tablo"].get(ana, {}).get("ilk")
        if ilk and son <= date.fromisoformat(ilk):
            raise EolAyarHatasi("son_tarihler.%s is not after the first release date %s" % (anahtar, ilk))
        sonuc["tablo"].setdefault(ana, {"ilk": None})["son"] = son.isoformat()
    return sonuc


def _tekil(ciftler):
    d = dict(ciftler)
    if len(d) != len(ciftler):
        raise ValueError("duplicate key")
    return d


def ortamdan(ortam=None):
    """The settings in the ALIG_EOL_AYARI file; the defaults if the variable is absent. An error on an unreadable or invalid file."""
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
        raise EolAyarHatasi("%s=%s could not be read: %s" % (ORTAM, yol, (ex.strerror or ex) if isinstance(ex, OSError) else ex)) from None
    try:
        return ayar_dogrula(ham)
    except EolAyarHatasi as ex:
        raise EolAyarHatasi("%s=%s: %s" % (ORTAM, yol, ex)) from None


def yukle(ortam=None):
    """Called once when the service starts: sets the active settings from the environment. A change takes effect when the service restarts."""
    global ETKIN
    ETKIN = ortamdan(ortam)
    return ETKIN


def son_tarihler(ayar=None):
    """{major version: final release date as an ISO string} of the active (or given) settings."""
    return {m: v["son"] for m, v in (ETKIN if ayar is None else ayar)["tablo"].items()}


def degerlendir(ana, tarih, ayar=None):
    """EOL status of a major version on the given date (date or datetime; only the calendar date is used).

    None: supported and outside the warning window (also for a major version newer than the table: nothing is claimed).
    Otherwise a dict: durum "bitmis" (no longer supported), "yaklasiyor" (inside the window); destek_sonu is the final release date
    or None for a version older than the table (no date is invented for it); kalan_gun is given when there is a date.
    """
    ayar = ETKIN if ayar is None else ayar
    bugun = tarih.date() if isinstance(tarih, datetime) else tarih
    tablo = ayar["tablo"]
    if ana in tablo:
        son = date.fromisoformat(tablo[ana]["son"])
        kalan = (son - bugun).days
        if kalan < 0:
            return {"durum": "bitmis", "destek_sonu": son.isoformat(), "kalan_gun": kalan}
        if kalan <= ayar["pencere_gun"]:
            return {"durum": "yaklasiyor", "destek_sonu": son.isoformat(), "kalan_gun": kalan}
        return None
    if ana < min(tablo):
        return {"durum": "bitmis", "destek_sonu": None, "kalan_gun": None}
    return None
