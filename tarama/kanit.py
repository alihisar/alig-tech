"""Common evidence model. PostgreSQL and SQL Server rules produce the same record format; the report, the panel and later the health
score and the history comparison read these records. No language model: the same document always gives the same records.

Every rule produces a single record in every scan (KAYIT_ALANLARI):
  kural        permanent id, for example PG-SEC-001. The id never changes; the id of a removed rule is not reused.
  motor        postgresql | mssql
  kategori     KATEGORILER
  risk         the rule's risk level: how important it is in the worst case if it fails (ONEM_SIRASI). Equal to the highest
               finding severity the rule can produce; it determines the rule's weight in the health score (tarama/puan.py)
  durum        FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE, PASS
  onem         the highest severity if there are findings (kritik ... bilgi), otherwise None
  guven        HIGH, MEDIUM, LOW. None if there is no evidence (UNKNOWN, UNAVAILABLE)
  kaynak       catalog views, functions or settings that were read
  kontroller   collection checks that provide the evidence (catalog ids; "toplayici" for the document's top-level field)
  toplama_utc  the moment the data was collected (olusturma_utc in the document)
  neden        reason code for UNKNOWN, UNAVAILABLE and NOT_APPLICABLE (texts in tarama/rapor.py)
  gozlem       settings and numbers the rule read. Contains no object names
  bulgular     findings the rule produced (format of tarama/kurallar.py, with the rule fields)
  ad, beklenen the rule's name and pass condition (tr, en)

Status rules:
  - FAIL (critical, high) or WARNING (medium, low, info) if there are findings; even if coverage is partial: a problem that is found is real.
  - If the source check requires a role on the scan account (privilege in the catalog: pg_read_all_stats, pg_read_all_settings) and
    the account lacks it, or the account's privileges could not be read (pg_hesap), the result is partial: other sessions may not be visible.
  - UNAVAILABLE if the primary source did not arrive: not run, privilege, timeout, not in this version, standby server, error, limit.
  - UNKNOWN if data arrived but is not enough for a conclusion: invalid format or type, a required value missing, an expected row absent,
    some databases not scanned, an additional source did not arrive.
  - NOT_APPLICABLE if the data shows the rule's subject does not exist on the server (for example, no replication slot).
  - A primary-specific rule (birincil=True: table statistics, archiving) is NOT_APPLICABLE on a standby: these
    statistics are not kept on a standby and would look clean with no data. If the server role could not be read (pg_sunucu_rolu) the result is partial.
  - PASS only if all sources arrived completely and there are no findings. PASS never appears when data is missing.
"""
from datetime import datetime, timezone
from typing import NamedTuple

from tarama import katalog
from tarama.yukleme import TUR_DENETIMI

DURUMLAR = ("FAIL", "WARNING", "UNKNOWN", "UNAVAILABLE", "NOT_APPLICABLE", "PASS")
KANITSIZ = ("UNKNOWN", "UNAVAILABLE")
GUVENLER = ("HIGH", "MEDIUM", "LOW")
KATEGORILER = ("guvenlik", "performans", "konfigurasyon", "bakim", "kapasite", "ha_dr", "yedek")
KATEGORI_KISALTMA = {"guvenlik": "SEC", "performans": "PERF", "konfigurasyon": "CONFIG", "bakim": "MAINT",
                     "kapasite": "CAP", "ha_dr": "HA", "yedek": "BACKUP"}
SATIR = ("tek", "en_az_bir", "herhangi")
ONEM_SIRASI = ("kritik", "yuksek", "orta", "dusuk", "bilgi")
BULGU_DURUMU = {"kritik": "FAIL", "yuksek": "FAIL", "orta": "WARNING", "dusuk": "WARNING", "bilgi": "WARNING"}
# Error reasons written by the collector: no data arrived at all.
ERISILEMEZ = frozenset({"calistirilmadi", "yetki", "zaman_asimi", "desteklenmiyor", "yedek_sunucu", "hata", "sinir", "ad"})
# SQL Server is a preview: the queries were not tested on a real server, evidence confidence is at most MEDIUM. For PostgreSQL, on a major version
# where the queries were not tested on a real server (outside katalog.SINANAN or an unknown version) confidence is also at most MEDIUM.
GUVEN_TAVANI = {"mssql": "MEDIUM"}
SINANMAMIS_SURUM_TAVANI = "MEDIUM"
ROL_YETKILERI = ("pg_read_all_stats", "pg_read_all_settings")   # if the account lacks them, the query runs but returns an incomplete result
TOPLAYICI = "toplayici"   # the document's top-level field as a source (superuser): the account the collector connected with
KAYIT_ALANLARI = ("kural", "motor", "kategori", "risk", "durum", "onem", "guven", "kaynak", "kontroller", "toplama_utc",
                  "neden", "gozlem", "bulgular", "ad", "beklenen")

# An error of type or key inside a rule: the rule becomes UNKNOWN with "gecersiz_veri" (invalid data); the report and the panel do not crash.
_VERI_HATASI = (TypeError, KeyError, ValueError, ZeroDivisionError, OverflowError, AttributeError, IndexError)


class Belirsiz(Exception):
    """Data arrived but the rule cannot reach a conclusion: status UNKNOWN."""

    def __init__(self, neden="eksik_veri"):
        super().__init__(neden)
        self.neden = neden


class Uygulanmaz(Exception):
    """The data shows the rule's subject does not exist on this server: status NOT_APPLICABLE."""

    def __init__(self, neden):
        super().__init__(neden)
        self.neden = neden


class Kaynak(NamedTuple):
    kontrol: str
    satir: str = "herhangi"   # tek: exactly one row; en_az_bir: an empty result means no data; herhangi: an empty result is valid
    zorunlu: tuple = ()        # columns that must be filled in the row; a row where one is empty does not enter the evaluation and the result is partial
    ek: bool = False           # additional source: if it does not arrive the rule still runs (the finding is reported) but cannot give PASS


class Kural(NamedTuple):
    kimlik: str
    motor: str
    kategori: str
    risk: str                  # ONEM_SIRASI: the highest finding severity the rule can produce
    guven: str                 # HIGH: a setting or catalog state; MEDIUM: a statistic or snapshot; LOW: an indirect sign
    kaynaklar: tuple           # the first is the primary source
    ad: dict
    beklenen: dict             # pass condition (tr, en)
    fn: object                 # fn(primary_rows, input) -> list of findings; may raise Belirsiz or Uygulanmaz
    kaynak: tuple = ()         # if empty, the "kaynak" list of the source checks in the catalog
    birincil: bool = False     # meaningful only on the primary server: NOT_APPLICABLE on a standby


def kayitci(liste, motor):
    """Decorator that registers a rule function: @kural("PG-SEC-001", "guvenlik", "yuksek", "HIGH", [Kaynak(...)], ad, beklenen)."""
    def kural(kimlik, kategori, risk, guven, kaynaklar, ad, beklenen, kaynak=(), birincil=False):
        if kategori not in KATEGORILER or risk not in ONEM_SIRASI or guven not in GUVENLER:
            raise ValueError("%s: category, risk or confidence is invalid" % kimlik)
        def sar(fn):
            liste.append(Kural(kimlik, motor, kategori, risk, guven, tuple(kaynaklar), ad, beklenen, fn, tuple(kaynak), birincil))
            return fn
        return sar
    return kural


class Girdi:
    """The data a rule function sees. Rows are those with required columns filled and of the right type."""

    def __init__(self, belge, taranan, veri):
        self.belge, self.taranan, self._veri = belge, taranan, veri
        self.kismi_nedenler, self.gozlem = [], {}

    def satirlar(self, kontrol):
        """Rows of the source; None if the additional source did not arrive."""
        return self._veri.get(kontrol)

    def kismi(self, neden):
        """The result is incomplete: if there are no findings the status becomes UNKNOWN."""
        self.kismi_nedenler.append(neden)

    def gozle(self, degerler=None, **kv):
        """A measurement shown in the report even on PASS. Only settings and numbers; no object names are written."""
        self.gozlem.update(degerler or {}, **kv)


def _parse_utc(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _tam_kapsam(kontroller):
    """Was every connectable database on the server scanned (pg_kapsam)? False if unknown."""
    e = kontroller.get("pg_kapsam")
    if not isinstance(e, dict) or e.get("durum") != "ok" or e.get("atlanan"):
        return False
    r = e.get("satirlar")
    if not isinstance(r, list) or not r or not all(isinstance(x, dict) for x in r):
        return False
    toplamlar = {x.get("veritabani_sayisi") for x in r}
    if len(toplamlar) != 1:
        return False
    toplam = toplamlar.pop()
    return isinstance(toplam, int) and not isinstance(toplam, bool) and toplam == len({x.get("veritabani") for x in r})


def _hesap(kontroller):
    """Privileges of the scan account (pg_hesap): {super_kullanici, pg_read_all_stats, pg_read_all_settings} or None."""
    e = kontroller.get("pg_hesap")
    if not isinstance(e, dict) or e.get("durum") != "ok":
        return None
    r = e.get("satirlar")
    if not isinstance(r, list) or len(r) != 1 or not isinstance(r[0], dict):
        return None
    h = r[0]
    if not all(isinstance(h.get(k), bool) for k in ("super_kullanici",) + ROL_YETKILERI):
        return None
    return h


def yedek_mi(kontroller):
    """Is the server a standby (pg_sunucu_rolu: pg_is_in_recovery)? True, False, or None if it could not be read."""
    e = kontroller.get("pg_sunucu_rolu")
    try:
        v = e["satirlar"][0]["yedek"] if e["durum"] == "ok" and len(e["satirlar"]) == 1 else None
    except (TypeError, KeyError, IndexError):
        return None
    return v if isinstance(v, bool) else None


def ana_surum(kontroller):
    """PostgreSQL major version (pg_surum) or None."""
    e = kontroller.get("pg_surum")
    try:
        n = e["satirlar"][0]["surum_num"] if e["durum"] == "ok" and len(e["satirlar"]) == 1 else None
    except (TypeError, KeyError, IndexError):
        return None
    return n // 10000 if isinstance(n, int) and not isinstance(n, bool) and n >= 90000 else None


def _satir_sorunu(s, zorunlu, turler):
    for kolon in zorunlu:
        if s.get(kolon) is None:
            return "eksik_veri"
    for kolon, tur in turler.items():
        v = s.get(kolon)
        if v is not None and not TUR_DENETIMI[tur](v):
            return "gecersiz_veri"
    return None


def _oku(belge, kontroller, kaynak, katalog_by_id, turler, tam_kapsam, hesap):
    """(rows, status, reason, partial_reasons). If rows is None the source is missing or unusable."""
    if kaynak.kontrol == TOPLAYICI:
        v = belge.get("superuser")
        if not isinstance(v, bool):
            return None, "UNAVAILABLE", "calistirilmadi", []
        return [{"superuser": v}], None, None, []
    e = kontroller.get(kaynak.kontrol)
    if e is None:
        return None, "UNAVAILABLE", "calistirilmadi", []
    if not isinstance(e, dict) or e.get("durum") not in ("ok", "hata"):
        return None, "UNKNOWN", "gecersiz_veri", []
    if e["durum"] == "hata":
        neden = e.get("neden")
        return None, "UNAVAILABLE", neden if neden in ERISILEMEZ else "hata", []
    satirlar = e.get("satirlar")
    if not isinstance(satirlar, list) or not all(isinstance(s, dict) for s in satirlar):
        return None, "UNKNOWN", "gecersiz_veri", []
    kismi = []
    c = katalog_by_id.get(kaynak.kontrol, {})
    if c.get("kapsam") == "veritabani" and (e.get("atlanan") or not tam_kapsam):
        kismi.append("kismi_veritabani")
    if c.get("yetki") in ROL_YETKILERI:
        if hesap is None:
            kismi.append("rol_bilinmiyor")
        elif not (hesap["super_kullanici"] or hesap[c["yetki"]]):
            kismi.append("rol_eksik")
    tur = turler.get(kaynak.kontrol, {})
    tam = []
    for s in satirlar:
        sorun = _satir_sorunu(s, kaynak.zorunlu, tur)
        if sorun is None:
            tam.append(s)
        elif sorun not in kismi:
            kismi.append(sorun)
    if kaynak.satir == "tek" and len(satirlar) > 1:
        return None, "UNKNOWN", "gecersiz_veri", []
    if kaynak.satir != "herhangi" and not tam:
        return None, "UNKNOWN", next((k for k in kismi if k != "kismi_veritabani"), "eksik_veri"), []
    return tam, None, None, kismi


def _kayit(kural, belge, kontroller, taranan, katalog_by_id, turler, tam_kapsam, hesap, surum_tavani, yedek):
    kaynak = list(kural.kaynak) or sorted({ad for k in kural.kaynaklar for ad in katalog_by_id.get(k.kontrol, {}).get("kaynak", ())})
    guven = kural.guven
    for tavan in (GUVEN_TAVANI.get(kural.motor), surum_tavani):
        if tavan:
            guven = max(guven, tavan, key=GUVENLER.index)   # the lower one
    kayit = {"kural": kural.kimlik, "motor": kural.motor, "kategori": kural.kategori, "risk": kural.risk, "durum": None, "onem": None, "guven": None,
             "kaynak": kaynak, "kontroller": [k.kontrol for k in kural.kaynaklar], "toplama_utc": belge.get("olusturma_utc"),
             "neden": None, "gozlem": {}, "bulgular": [], "ad": dict(kural.ad), "beklenen": dict(kural.beklenen)}   # copy: the rule does not change even if the record changes

    def bitir(durum, neden=None):
        kayit["durum"], kayit["neden"] = durum, neden
        kayit["guven"] = None if durum in KANITSIZ else guven
        return kayit

    if kural.birincil and yedek is True:
        return bitir("NOT_APPLICABLE", "birincil_degil")
    veri, kismi = {}, []
    if kural.birincil and yedek is None:
        kismi.append("sunucu_rolu_bilinmiyor")
    for k in kural.kaynaklar:
        satirlar, durum, neden, k_kismi = _oku(belge, kontroller, k, katalog_by_id, turler, tam_kapsam, hesap)
        if satirlar is None:
            if not k.ek:
                return bitir(durum, neden)
            kismi.append(neden)
        veri[k.kontrol] = satirlar
        kismi += k_kismi
    g = Girdi(belge, taranan, veri)
    uygulanmaz = None
    try:
        bulgular = list(kural.fn(veri[kural.kaynaklar[0].kontrol], g) or [])
    except Uygulanmaz as u:
        bulgular, uygulanmaz = [], u.neden
    except Belirsiz as b:
        kayit["gozlem"] = g.gozlem
        return bitir("UNKNOWN", b.neden)
    except _VERI_HATASI:
        return bitir("UNKNOWN", "gecersiz_veri")
    kayit["gozlem"] = g.gozlem
    kismi += g.kismi_nedenler
    if bulgular:
        for b in bulgular:
            b.update(kural=kural.kimlik, kategori=kural.kategori, durum=BULGU_DURUMU[b["onem"]], guven=guven, kaynak=kaynak)
        kayit["bulgular"] = bulgular
        kayit["onem"] = min((b["onem"] for b in bulgular), key=ONEM_SIRASI.index)
        return bitir("FAIL" if any(b["durum"] == "FAIL" for b in bulgular) else "WARNING")
    if kismi:
        return bitir("UNKNOWN", kismi[0])
    if uygulanmaz:
        return bitir("NOT_APPLICABLE", uygulanmaz)
    return bitir("PASS")


class Sonuc:
    """Evaluation of one document: records (in rule order), findings (in severity order), the unmeasurable.
    baglam: ana_surum, sinanan (was the version tested on a real server), yedek (is the server a standby; None if unknown) for PostgreSQL;
    hesap (scan account privileges)."""

    def __init__(self, kayitlar, baglam=None):
        self.kayitlar = kayitlar
        self.baglam = baglam or {}
        self.bulgular = sorted((b for k in kayitlar for b in k["bulgular"]), key=lambda b: ONEM_SIRASI.index(b["onem"]))
        self.olculemeyen = [(k["kural"], k["neden"]) for k in kayitlar if k["durum"] in KANITSIZ]

    def sayim(self):
        return {d: sum(1 for k in self.kayitlar if k["durum"] == d) for d in DURUMLAR}


def calistir(belge, kurallar, katalog_by_id, turler):
    """Runs the data in the document through the rules; one record per rule. A corrupt document also produces records (UNAVAILABLE)."""
    belge = belge if isinstance(belge, dict) else {}
    kontroller = belge.get("kontroller") if isinstance(belge.get("kontroller"), dict) else {}
    taranan = _parse_utc(belge.get("olusturma_utc")) or datetime.now(timezone.utc)
    tam, hesap = _tam_kapsam(kontroller), _hesap(kontroller)
    baglam, surum_tavani, yedek = {"hesap": hesap}, None, False
    if belge.get("motor", "postgresql") == "postgresql":
        ana, yedek = ana_surum(kontroller), yedek_mi(kontroller)
        baglam.update(ana_surum=ana, sinanan=ana in katalog.SINANAN, yedek=yedek)
        surum_tavani = None if baglam["sinanan"] else SINANMAMIS_SURUM_TAVANI
    return Sonuc([_kayit(k, belge, kontroller, taranan, katalog_by_id, turler, tam, hesap, surum_tavani, yedek) for k in kurallar], baglam)
