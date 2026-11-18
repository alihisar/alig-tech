"""PostgreSQL job queue for the direct connection (Mode B) scan (roadmap item 21). Standard library + ortak/pg.py only.

Not part of the default runtime: it is used only when the Mode B runner is started with --kuyruk (tarama/calistirici.py) and
PostgreSQL is configured (ortak/pg_ayar.py). Mode B itself stays closed by default (ALIG_DOGRUDAN).

What a job is. A row of alig.is_kuyrugu (db/sema/0008_is_kuyrugu.sql): a REFERENCE to a request (istek_id) of a company
(firma_id). There is no payload column: the customer's login secret is never in the queue, in a row, in an error text or in a log
(the table only has identifier-shaped text columns). The runner keeps the secret in memory next to the waiting connection
(see Kabul) and a crash loses it on purpose; the customer submits the request again.

Public API
----------
Functions over one ortak.pg.Baglanti (each opens its own short transaction; a Baglanti is not shared between threads):
    ekle(con, firma_id, istek_id, *, tur="kip_b_tarama", sahip=None, azami_deneme=5, azami_bekleyen=None, firma_azami=None) -> id
        Idempotent: the same (tur, istek_id) returns the existing id. azami_bekleyen / firma_azami are SOFT limits on waiting jobs
        (global, per company; checked before the insert, so a burst can pass them by a few rows) -> KuyrukDolu.
    al(con, isci, *, kira_sn=60, firma_basina=1, sahip=None, taban_s=2, tavan_s=300) -> Is | None
        First gives expired leases back (see birak_suresi_dolan), then claims ONE job. Order: the company whose last claim is the
        oldest (never served first, ties by company id), then that company's oldest eligible job. A company with `firma_basina` jobs
        running is skipped, so one company can neither take all workers nor run ahead of the others. Uses
        FOR UPDATE SKIP LOCKED; claiming increments `deneme` and `kira_no` (the fencing token). Only jobs whose `sahip` equals the given
        one are claimed (None claims only the unowned jobs).
    nabiz(con, is_, kira_sn=60)         extends the lease; KiraKaybedildi if the job is no longer leased with this kira_no.
    tamam(con, is_) -> "tamam" | "zaten"
        Completes. A second call (same kira_no) returns "zaten" and changes nothing. KiraKaybedildi if another worker took the job over
        (kira_no moved on), it was given back or dead-lettered, or it is not leased: a stale lease can never complete a job.
    basarisiz(con, is_, hata, *, yeniden_dene=True, taban_s=2, tavan_s=300) -> "bekliyor" | "olu" | "zaten"
        Ends this attempt. While attempts remain (and yeniden_dene) the job waits with an equal-jitter exponential back-off
        (taban_s * 2**(deneme-1), capped at tavan_s, then x[0.5, 1]); otherwise it becomes a dead letter ("olu"). `hata` must be a short
        [a-z0-9_] code, never an exception text. Repeating the call is "zaten"; KiraKaybedildi like tamam.
    birak_suresi_dolan(con) -> int          expired leases: back to waiting (with back-off) or dead letter (attempts used up / owned job).
    isci_birak(con, isci) -> int            restart recovery: gives back every job leased by this worker name at once (see Isci.calis).
    sahip_temizle(con, sahip) -> int        dead-letters every unfinished job owned by `sahip` (its in-memory inputs are gone after a restart).
    iptal(con, id) -> bool                  a waiting job becomes a dead letter ("iptal"); False if it is already leased or finished.
    durum_say(con) -> {durum: count}
Classes:
    Isci(baglan, isci, isleyici, ...)   the polling worker loop (one thread, own connections, a heartbeat thread while a job runs).
    Kabul(baglan, sahip, ...)           admission for the Mode B runner: queue + in-memory mailbox for the request inputs.
Errors: KuyrukHatasi > KiraKaybedildi, KuyrukDolu, KuyrukZamanAsimi; handler signals: Gecici (retry), Kalici (dead letter).

Time. Every timestamp is the database clock (clock_timestamp()), never a worker clock. Correctness does not depend on the leases:
the fencing token decides who may complete. A lease only decides when a silent worker's job is given to somebody else.

Delivery is at least once. A worker that stalls past its lease can still be running when the job is claimed again; its late
completion is rejected, but the work itself may have run twice, so a handler must be safe to repeat (Mode B: a scan is read-only
on the customer's side; its report is keyed by the request). Mode B jobs use azami_deneme=1 (the inputs cannot be replayed).

Polling, not LISTEN/NOTIFY: docs/postgresql-gecis.md section 10.
"""
import logging
import random
import re
import threading
import time
from collections import namedtuple

from ortak import pg

__all__ = ["Is", "KuyrukHatasi", "KiraKaybedildi", "KuyrukDolu", "KuyrukZamanAsimi", "Gecici", "Kalici", "ekle", "al", "nabiz",
           "tamam", "basarisiz", "birak_suresi_dolan", "isci_birak", "sahip_temizle", "iptal", "durum_say", "Isci", "Kabul", "TUR_KIP_B"]

TUR_KIP_B = "kip_b_tarama"
_AD = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_TUR = re.compile(r"^[a-z0-9_]{1,40}$")
_KOD = re.compile(r"^[a-z0-9_]{1,40}$")
_log = logging.getLogger("alig.is_kuyrugu")

Is = namedtuple("Is", "id firma_id istek_id tur sahip isci kira_no deneme azami_deneme")
_KOLON = "id, firma_id, istek_id, tur, sahip, isci, kira_no, deneme, azami_deneme"


class KuyrukHatasi(Exception):
    pass


class KiraKaybedildi(KuyrukHatasi):
    """The caller no longer holds the lease of the job (stale fencing token, given back, dead-lettered or done by another attempt)."""


class KuyrukDolu(KuyrukHatasi):
    pass


class KuyrukZamanAsimi(KuyrukHatasi):
    pass


class Gecici(Exception):
    """A handler raises this for a failure worth retrying (the job goes back to waiting while attempts remain)."""

    def __init__(self, kod="gecici"):
        super().__init__(kod)
        self.kod = kod


class Kalici(Exception):
    """A handler raises this for a failure that retrying cannot fix (the job becomes a dead letter at once)."""

    def __init__(self, kod="kalici"):
        super().__init__(kod)
        self.kod = kod


def _ad(deger, ad):
    if not isinstance(deger, str) or not _AD.match(deger):
        raise ValueError("%s must match [A-Za-z0-9_.-]{1,64}" % ad)
    return deger


def _kod(deger):
    if not isinstance(deger, str) or not _KOD.match(deger):
        raise ValueError("error code must match [a-z0-9_]{1,40} (a short code, never an exception text)")
    return deger


def _sayi(deger, ad, alt, ust=None):
    if isinstance(deger, bool) or not isinstance(deger, int) or deger < alt or (ust is not None and deger > ust):
        raise ValueError("%s must be an integer >= %d%s" % (ad, alt, "" if ust is None else " and <= %d" % ust))
    return deger


def _sure(deger, ad):
    if isinstance(deger, bool) or not isinstance(deger, (int, float)) or not 0 < deger <= 86400:
        raise ValueError("%s must be a number of seconds in (0, 86400]" % ad)
    return float(deger)


def _geri_cekilme(taban_s, tavan_s):
    taban, tavan = float(taban_s), float(tavan_s)
    if taban < 0 or tavan < taban:
        raise ValueError("0 <= taban_s <= tavan_s is required")
    return taban, tavan


def ekle(con, firma_id, istek_id, *, tur=TUR_KIP_B, sahip=None, azami_deneme=5, azami_bekleyen=None, firma_azami=None):
    _sayi(firma_id, "firma_id", 1)
    _sayi(istek_id, "istek_id", 1)
    _sayi(azami_deneme, "azami_deneme", 1, 20)
    if not isinstance(tur, str) or not _TUR.match(tur):
        raise ValueError("tur must match [a-z0-9_]{1,40}")
    if sahip is not None:
        _ad(sahip, "sahip")
    with con.islem():
        mevcut = con.sorgu("SELECT id FROM alig.is_kuyrugu WHERE tur = $1 AND istek_id = $2", (tur, istek_id))
        if mevcut:
            return mevcut[0][0]
        if azami_bekleyen is not None and con.sorgu("SELECT count(*) FROM alig.is_kuyrugu WHERE durum = 'bekliyor'")[0][0] >= azami_bekleyen:
            raise KuyrukDolu("queue is full")
        if firma_azami is not None and con.sorgu("SELECT count(*) FROM alig.is_kuyrugu WHERE durum = 'bekliyor' AND firma_id = $1",
                                                  (firma_id,))[0][0] >= firma_azami:
            raise KuyrukDolu("too many waiting jobs for this company")
        con.sorgu("INSERT INTO alig.is_kuyrugu_sira(firma_id) VALUES ($1) ON CONFLICT DO NOTHING", (firma_id,))
        r = con.sorgu("INSERT INTO alig.is_kuyrugu(tur, firma_id, istek_id, sahip, azami_deneme, uygun_utc, olusturma_utc) "
                      "VALUES ($1, $2, $3, $4, $5, clock_timestamp(), clock_timestamp()) ON CONFLICT (tur, istek_id) DO NOTHING RETURNING id",
                      (tur, firma_id, istek_id, sahip, azami_deneme))
        if r:
            return r[0][0]
    # lost a race with a concurrent identical enqueue: it is the same job
    return con.sorgu("SELECT id FROM alig.is_kuyrugu WHERE tur = $1 AND istek_id = $2", (tur, istek_id))[0][0]


def _serbest(con, where, parametreler, hata, taban_s, tavan_s):
    n = len(parametreler)
    h, t, c = "$%d::text" % (n + 1), "$%d::float8" % (n + 2), "$%d::float8" % (n + 3)
    olu = "(j.deneme >= j.azami_deneme OR j.sahip IS NOT NULL)"
    sql = ("WITH s AS (SELECT id FROM alig.is_kuyrugu j WHERE j.durum = 'calisiyor' AND (" + where + ") "
           "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 100) "
           "UPDATE alig.is_kuyrugu j SET durum = CASE WHEN " + olu + " THEN 'olu' ELSE 'bekliyor' END, son_hata = " + h + ", "
           "kira_bitis_utc = NULL, "
           "uygun_utc = CASE WHEN " + olu + " THEN j.uygun_utc ELSE clock_timestamp() + make_interval(secs => "
           "LEAST(" + c + ", " + t + " * power(2, j.deneme - 1)) * (0.5 + random() * 0.5)) END, "
           "bitis_utc = CASE WHEN " + olu + " THEN clock_timestamp() END "
           "FROM s WHERE j.id = s.id")
    con.sorgu(sql, tuple(parametreler) + (hata, taban_s, tavan_s))
    return con.etkilenen


def birak_suresi_dolan(con, taban_s=2, tavan_s=300):
    taban, tavan = _geri_cekilme(taban_s, tavan_s)
    with con.islem():
        return _serbest(con, "j.kira_bitis_utc <= clock_timestamp()", (), "kira_doldu", taban, tavan)


def isci_birak(con, isci, taban_s=2, tavan_s=300):
    _ad(isci, "isci")
    taban, tavan = _geri_cekilme(taban_s, tavan_s)
    with con.islem():
        return _serbest(con, "j.isci = $1::text", (isci,), "isci_yeniden_basladi", taban, tavan)


def sahip_temizle(con, sahip):
    _ad(sahip, "sahip")
    with con.islem():
        con.sorgu("UPDATE alig.is_kuyrugu SET durum = 'olu', son_hata = 'yeniden_basladi', kira_bitis_utc = NULL, bitis_utc = clock_timestamp() "
                  "WHERE sahip = $1 AND durum IN ('bekliyor', 'calisiyor')", (sahip,))
        return con.etkilenen


def al(con, isci, *, kira_sn=60, firma_basina=1, sahip=None, taban_s=2, tavan_s=300):
    _ad(isci, "isci")
    kira_sn = _sure(kira_sn, "kira_sn")
    _sayi(firma_basina, "firma_basina", 1, 1000)
    if sahip is not None:
        _ad(sahip, "sahip")
    taban, tavan = _geri_cekilme(taban_s, tavan_s)
    with con.islem():
        _serbest(con, "j.kira_bitis_utc <= clock_timestamp()", (), "kira_doldu", taban, tavan)
        # Fair pick: the company served longest ago that has an eligible job and a free slot. The company row lock is the turn lock:
        # a concurrent claimer skips it (SKIP LOCKED) and takes the next company.
        f = con.sorgu(
            "SELECT s.firma_id FROM alig.is_kuyrugu_sira s WHERE EXISTS (SELECT 1 FROM alig.is_kuyrugu j WHERE j.firma_id = s.firma_id "
            "AND j.durum = 'bekliyor' AND j.uygun_utc <= clock_timestamp() AND j.sahip IS NOT DISTINCT FROM $1::text) "
            "AND (SELECT count(*) FROM alig.is_kuyrugu r WHERE r.firma_id = s.firma_id AND r.durum = 'calisiyor') < $2::int "
            "ORDER BY s.son_hizmet_utc NULLS FIRST, s.firma_id FOR UPDATE OF s SKIP LOCKED LIMIT 1", (sahip, firma_basina))
        if not f:
            return None
        firma_id = f[0][0]
        # Re-count with a fresh snapshot: a claimer that committed just before we got the turn lock may not have been visible above.
        if con.sorgu("SELECT count(*) FROM alig.is_kuyrugu WHERE firma_id = $1 AND durum = 'calisiyor'", (firma_id,))[0][0] >= firma_basina:
            return None
        r = con.sorgu(
            "UPDATE alig.is_kuyrugu SET durum = 'calisiyor', isci = $2, kira_no = kira_no + 1, deneme = deneme + 1, "
            "kira_bitis_utc = clock_timestamp() + make_interval(secs => $3::float8), alma_utc = clock_timestamp(), son_hata = '' "
            "WHERE id = (SELECT id FROM alig.is_kuyrugu WHERE firma_id = $1 AND durum = 'bekliyor' AND uygun_utc <= clock_timestamp() "
            "AND sahip IS NOT DISTINCT FROM $4::text ORDER BY uygun_utc, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING " + _KOLON,
            (firma_id, isci, kira_sn, sahip))
        if not r:
            return None
        con.sorgu("UPDATE alig.is_kuyrugu_sira SET son_hizmet_utc = clock_timestamp() WHERE firma_id = $1", (firma_id,))
        return Is(*r[0])


def nabiz(con, is_, kira_sn=60):
    kira_sn = _sure(kira_sn, "kira_sn")
    with con.islem():
        r = con.sorgu("UPDATE alig.is_kuyrugu SET kira_bitis_utc = clock_timestamp() + make_interval(secs => $4::float8) "
                      "WHERE id = $1 AND kira_no = $2 AND isci = $3 AND durum = 'calisiyor' RETURNING id",
                      (is_.id, is_.kira_no, is_.isci, kira_sn))
    if not r:
        raise KiraKaybedildi("the lease of job %d is no longer held" % is_.id)


def _durum_oku(con, is_):
    r = con.sorgu("SELECT durum, kira_no FROM alig.is_kuyrugu WHERE id = $1", (is_.id,))
    return r[0] if r else (None, None)


def tamam(con, is_):
    with con.islem():
        r = con.sorgu("UPDATE alig.is_kuyrugu SET durum = 'tamam', bitis_utc = clock_timestamp(), kira_bitis_utc = NULL, son_hata = '' "
                      "WHERE id = $1 AND kira_no = $2 AND isci = $3 AND durum = 'calisiyor' RETURNING id", (is_.id, is_.kira_no, is_.isci))
        if r:
            return "tamam"
        durum, kira_no = _durum_oku(con, is_)
    if durum == "tamam" and kira_no == is_.kira_no:
        return "zaten"
    raise KiraKaybedildi("job %d cannot be completed with this lease" % is_.id)


def basarisiz(con, is_, hata, *, yeniden_dene=True, taban_s=2, tavan_s=300):
    _kod(hata)
    taban, tavan = _geri_cekilme(taban_s, tavan_s)
    olu = "(NOT $4::bool OR deneme >= azami_deneme OR sahip IS NOT NULL)"
    with con.islem():
        r = con.sorgu(
            "UPDATE alig.is_kuyrugu SET durum = CASE WHEN " + olu + " THEN 'olu' ELSE 'bekliyor' END, son_hata = $3, kira_bitis_utc = NULL, "
            "uygun_utc = CASE WHEN " + olu + " THEN uygun_utc ELSE clock_timestamp() + make_interval(secs => "
            "LEAST($6::float8, $5::float8 * power(2, deneme - 1)) * (0.5 + random() * 0.5)) END, "
            "bitis_utc = CASE WHEN " + olu + " THEN clock_timestamp() END "
            "WHERE id = $1 AND kira_no = $2 AND durum = 'calisiyor' RETURNING durum",
            (is_.id, is_.kira_no, hata, bool(yeniden_dene), taban, tavan))
        if r:
            return r[0][0]
        durum, kira_no = _durum_oku(con, is_)
    if durum in ("bekliyor", "olu") and kira_no == is_.kira_no:
        return "zaten"
    raise KiraKaybedildi("job %d cannot be failed with this lease" % is_.id)


def iptal(con, id_):
    with con.islem():
        r = con.sorgu("UPDATE alig.is_kuyrugu SET durum = 'olu', son_hata = 'iptal', bitis_utc = clock_timestamp() "
                      "WHERE id = $1 AND durum = 'bekliyor' RETURNING id", (id_,))
    return bool(r)


def durum_say(con):
    return {d: n for d, n in con.sorgu("SELECT durum, count(*) FROM alig.is_kuyrugu GROUP BY durum")}


# ----------------------------------------------------------------------------------------------- worker loop

class Isci:
    """A polling worker. `baglan` is a zero-argument factory returning a new ortak.pg.Baglanti (the worker owns what it opens).

    isleyici(is_, kira_gecerli) is called for each claimed job in the worker thread; kira_gecerli() is False once the heartbeat
    learned that the lease was lost (the handler should stop). It returns normally (job done), raises Gecici (retry), Kalici (dead
    letter) or anything else (counted as a retryable failure with the code "hata"; the exception text is never stored).

    Idle polling: when no job is claimable the worker sleeps bos_bekleme_s x uniform(0.5, 1.5) (jitter so many workers do not poll in step),
    waking at once when `durdur` is set. After a job it asks again immediately."""

    def __init__(self, baglan, isci, isleyici, *, sahip=None, kira_sn=60, nabiz_sn=None, bos_bekleme_s=1.0, firma_basina=1,
                 taban_s=2, tavan_s=300, durdur=None, rng=None, hata_bekleme_s=2.0):
        if not callable(baglan) or not callable(isleyici):
            raise TypeError("baglan and isleyici must be callables")
        self.baglan, self.isci, self.isleyici, self.sahip = baglan, _ad(isci, "isci"), isleyici, sahip
        self.kira_sn = _sure(kira_sn, "kira_sn")
        self.nabiz_sn = _sure(nabiz_sn if nabiz_sn is not None else self.kira_sn / 3.0, "nabiz_sn")
        if self.nabiz_sn >= self.kira_sn:
            raise ValueError("nabiz_sn must be shorter than kira_sn")
        self.bos_bekleme_s, self.firma_basina = _sure(bos_bekleme_s, "bos_bekleme_s"), firma_basina
        self.taban_s, self.tavan_s = _geri_cekilme(taban_s, tavan_s)
        self.hata_bekleme_s = _sure(hata_bekleme_s, "hata_bekleme_s")
        self.durdur = durdur if durdur is not None else threading.Event()
        self._rng = rng or random.Random()
        self._con = None

    def bekleme_suresi(self):
        return self.bos_bekleme_s * self._rng.uniform(0.5, 1.5)

    def _baglanti(self):
        if self._con is None or self._con.kopuk:
            self._con = self.baglan()
        return self._con

    def _kapat(self):
        c, self._con = self._con, None
        if c is not None:
            try:
                c.kapat()
            except pg.PgHata:
                pass

    def bir_tur(self):
        """Claims and runs at most one job. Returns True if a job was processed (whatever its outcome)."""
        con = self._baglanti()
        is_ = al(con, self.isci, kira_sn=self.kira_sn, firma_basina=self.firma_basina, sahip=self.sahip,
                 taban_s=self.taban_s, tavan_s=self.tavan_s)
        if is_ is None:
            return False
        kayip, bitti = threading.Event(), threading.Event()
        nabizci = threading.Thread(target=self._nabiz_dongusu, args=(is_, kayip, bitti), name="alig-nabiz", daemon=True)
        nabizci.start()
        sonuc, kod = "tamam", ""
        try:
            self.isleyici(is_, lambda: not kayip.is_set())
        except Gecici as e:
            sonuc, kod = "gecici", _kod_guvenli(e.kod)
        except Kalici as e:
            sonuc, kod = "kalici", _kod_guvenli(e.kod)
        except Exception:   # the text is not kept anywhere: it could echo an input
            sonuc, kod = "gecici", "hata"
        finally:
            bitti.set()
            nabizci.join(timeout=self.nabiz_sn + 5)
        if kayip.is_set():
            _log.warning("job %d: lease lost while running; result not recorded", is_.id)
            return True
        try:
            con = self._baglanti()
            if sonuc == "tamam":
                tamam(con, is_)
            else:
                basarisiz(con, is_, kod, yeniden_dene=(sonuc == "gecici"), taban_s=self.taban_s, tavan_s=self.tavan_s)
        except KiraKaybedildi:
            _log.warning("job %d: lease lost before the result was recorded", is_.id)
        return True

    def _nabiz_dongusu(self, is_, kayip, bitti):
        con = None
        try:
            while not bitti.wait(self.nabiz_sn):
                try:
                    if con is None or con.kopuk:
                        con = self.baglan()
                    nabiz(con, is_, self.kira_sn)
                except KiraKaybedildi:
                    kayip.set()
                    return
                except pg.PgHata:   # transient: try again at the next beat; if the lease runs out the job is given to somebody else
                    if con is not None and con.kopuk:
                        con = None
        finally:
            if con is not None:
                try:
                    con.kapat()
                except pg.PgHata:
                    pass

    def calis(self):
        """Runs until `durdur` is set. First gives back what a previous run of the same worker name left leased (crash recovery)."""
        try:
            while not self.durdur.is_set():
                try:
                    if not getattr(self, "_basladi", False):
                        isci_birak(self._baglanti(), self.isci, self.taban_s, self.tavan_s)
                        self._basladi = True
                    if self.bir_tur():
                        continue
                    self.durdur.wait(self.bekleme_suresi())
                except pg.PgHata as e:
                    _log.warning("queue worker: database error (%s); reconnecting", type(e).__name__)
                    self._kapat()
                    self.durdur.wait(self.hata_bekleme_s)
        finally:
            self._kapat()


def _kod_guvenli(kod):
    return kod if isinstance(kod, str) and _KOD.match(kod) else "hata"


# ----------------------------------------------------------------------------------------- Mode B admission

class _Posta:
    __slots__ = ("is_fn", "alindi", "bitti", "sonuc", "hata")

    def __init__(self, is_fn):
        self.is_fn, self.alindi, self.bitti, self.sonuc, self.hata = is_fn, threading.Event(), threading.Event(), None, None


class Kabul:
    """Admission control for the Mode B runner, on top of the queue.

    calistir(firma_id, istek_id, is_fn) enqueues a job that REFERENCES the request, keeps `is_fn` (a closure that holds the inputs, the
    customer's login secret included) only in this process's memory, waits for a worker thread of this process to pick the job in its
    fair turn, and returns is_fn()'s result (or raises its exception). The database sees ids only.
    A job whose in-memory inputs are gone (the process restarted) can never run: sahip_temizle() at start dead-letters such jobs.
    Single instance per `sahip` name."""

    def __init__(self, baglan, sahip, *, es_zamanli=2, firma_basina=1, kira_sn=180, nabiz_sn=None, bos_bekleme_s=0.5,
                 sira_bekleme_sn=60.0, calisma_sn=170.0, azami_bekleyen=20, firma_azami=3):
        if not callable(baglan):
            raise TypeError("baglan must be a callable returning a Baglanti")
        self.baglan, self.sahip = baglan, _ad(sahip, "sahip")
        _sayi(es_zamanli, "es_zamanli", 1, 64)
        self.es_zamanli, self.firma_basina = es_zamanli, firma_basina
        self.kira_sn, self.nabiz_sn, self.bos_bekleme_s = kira_sn, nabiz_sn, bos_bekleme_s
        self.sira_bekleme_sn, self.calisma_sn = float(sira_bekleme_sn), float(calisma_sn)
        self.azami_bekleyen, self.firma_azami = azami_bekleyen, firma_azami
        self._posta, self._kilit = {}, threading.Lock()
        self._durdur, self._is_parcaciklari = threading.Event(), []
        self._calisiyor = False

    def baslat(self):
        if self._calisiyor:
            return
        con = self.baglan()
        try:
            sahip_temizle(con, self.sahip)
        finally:
            con.kapat()
        self._durdur.clear()
        for i in range(self.es_zamanli):
            isci = Isci(self.baglan, "%s-%d" % (self.sahip, i), self._isle, sahip=self.sahip, kira_sn=self.kira_sn, nabiz_sn=self.nabiz_sn,
                        bos_bekleme_s=self.bos_bekleme_s, firma_basina=self.firma_basina, durdur=self._durdur)
            t = threading.Thread(target=isci.calis, name="alig-kuyruk-%d" % i, daemon=True)
            t.start()
            self._is_parcaciklari.append(t)
        self._calisiyor = True

    def durdur(self):
        self._durdur.set()
        for t in self._is_parcaciklari:
            t.join(timeout=10)
        self._is_parcaciklari, self._calisiyor = [], False

    def _isle(self, is_, kira_gecerli):
        with self._kilit:
            p = self._posta.pop(is_.istek_id, None)
        if p is None:
            raise Kalici("bellek_yok")   # inputs are not in this process: a retry could never succeed
        p.alindi.set()
        try:
            p.sonuc = p.is_fn()
        except BaseException as e:   # handed to the waiting request thread unchanged
            p.hata = e
            p.bitti.set()
            raise Kalici(_kod_guvenli(getattr(e, "kod", "hata")))
        p.bitti.set()

    def calistir(self, firma_id, istek_id, is_fn):
        if not self._calisiyor:
            raise KuyrukHatasi("the queue is not started")
        p = _Posta(is_fn)
        with self._kilit:
            if istek_id in self._posta:
                raise KuyrukHatasi("request %r is already waiting" % (istek_id,))
            self._posta[istek_id] = p
        con = None
        try:
            con = self.baglan()
            job = ekle(con, firma_id, istek_id, sahip=self.sahip, azami_deneme=1,
                       azami_bekleyen=self.azami_bekleyen, firma_azami=self.firma_azami)
        except BaseException:
            with self._kilit:
                self._posta.pop(istek_id, None)
            raise
        finally:
            if con is not None:
                con.kapat()
        if not p.alindi.wait(self.sira_bekleme_sn):
            con = self.baglan()
            try:
                vazgecildi = iptal(con, job)
            finally:
                con.kapat()
            if vazgecildi:
                with self._kilit:
                    self._posta.pop(istek_id, None)
                raise KuyrukZamanAsimi("not picked in time")
            p.alindi.wait(5)   # claimed just now: wait for the run below
        if not p.bitti.wait(self.calisma_sn):
            raise KuyrukZamanAsimi("did not finish in time")
        if p.hata is not None:
            raise p.hata
        return p.sonuc
