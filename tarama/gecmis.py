"""History comparison: a rule-by-rule comparison of two scans belonging to the same company and the same database identity.
No language model: the same two documents always give the same result.

Database identity (kimlik): the SHA-256 digest of the PostgreSQL cluster identifier (pg_control_system().system_identifier)
(pg_kume_kimligi check; the raw identifier never leaves the server) and the server role (pg_sunucu_rolu). A cluster's primary
and standbys carry the same identifier; the role is kept separate, so primary is compared with primary and standby with standby. Several
standbys of the same cluster cannot be told apart. If the identity cannot be read, no comparison is made. There is no identity for SQL Server yet.

Both scans are evaluated with today's rules and score coefficients; the scores are therefore comparable.

Record classes (sinif):
  S  problem: FAIL or WARNING
  T  clean: PASS (all evidence arrived, no finding)
  Y  not applicable: NOT_APPLICABLE derived from the data (for example, no slots)
  B  no evidence: UNKNOWN, UNAVAILABLE, a rule not evaluated on a standby (birincil_degil), no record at all

Statuses (rules with a problem in one of the two scans; a rule with no problem in either is not listed):
  NEW         problem now, not applicable before (Y -> S)
  REGRESSED   problem now, was clean before or the problem was milder (T -> S, S -> S with increased severity)
  PERSISTING  problem continues, same or milder severity (S -> S)
  RESOLVED    had a problem before, now clean with evidence or no longer applicable (S -> T, S -> Y)
  UNKNOWN     had a problem before, now evidence is insufficient (S -> B: vanished evidence does not count as resolved), or there is a problem
              now but no evidence before (B -> S: unknown whether it is new)
"""
import re

from tarama import kanit, kurallar, puan

DURUMLAR = ("NEW", "REGRESSED", "PERSISTING", "RESOLVED", "UNKNOWN")   # order in the report: new and worsening first
SORUN = ("FAIL", "WARNING")
KANITSIZ_UYGULANMAZ = ("birincil_degil",)   # not applicable, but not from the data: not evaluated on the standby
_OZET = re.compile(r"^[0-9a-f]{64}$")


def kimlik(belge):
    """Comparison key "postgresql:<cluster digest>:<primary|standby>" or None."""
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
    """S, T, Y or B (see the module docstring)."""
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
    """Comparison status of two records; None if there is no problem in either scan."""
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
    """onceki_tarih, yeni_tarih: scan times from the documents. onceki_puan, yeni_puan: puan.Puan.
    kurallar: [{kural, kategori, ad, durum, neden (kanit_kayboldu or onceki_kanit_yok for UNKNOWN), onceki, yeni}]
      onceki and yeni: {durum, onem, neden} from the evidence record. Ordered by DURUMLAR, within the same status by severity and then id.
    katalog_farkli: the two scans were made with different collector versions (a check absent in the older version counts as having no evidence before)."""

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
