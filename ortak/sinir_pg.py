"""Atomic rate limiter on PostgreSQL (ALIG-DB-003e). Standard library only; uses ortak/pg.py.

A fixed window counter per (bucket, client digest). The check and the increment are ONE statement:

    INSERT INTO alig.sinir_sayac ... ON CONFLICT (kova, anahtar_sha256, pencere_utc)
    DO UPDATE SET adet = adet + 1 WHERE adet < limit RETURNING adet

The row lock taken by ON CONFLICT DO UPDATE serialises concurrent requests for the same key, and the WHERE clause is re-evaluated
on the latest row version, so the counter NEVER goes above the limit, however many connections or application servers race.
A rejected request returns no row and writes nothing (no churn under a flood). The window boundaries and the clock are the
database's (clock_timestamp()), so several application processes agree on the window.

- The key is hashed (HMAC-SHA-256 with the optional salt `tuz`): no plain IP address or account name is stored (KVKK).
- Expired windows are deleted by `temizle()`; `kontrol()` calls it opportunistically at most once per `temizlik_araligi` seconds per process.
- No in-memory fallback: if PostgreSQL fails, `kontrol()` raises ortak.pg.PgHata and the caller answers 503 + Retry-After
  (docs/postgresql-gecis.md section 9). Failing open would disable the protection; failing closed with a quiet 429 would hide an outage.
- Connections come from a small bounded pool (ortak/pg_havuz.py; ortak/pg.py connections are not shared between threads, and the HTTP
  servers start a thread per request). A dropped connection is discarded and reopened by the next call. A failed statement is not
  retried (it may or may not have been counted).

Usage:
    sn = SinirPg(lambda: pg.Baglanti.baglan(**ayar), tuz="...")
    s = sn.kontrol("iletisim", ip)            # limits from SINIRLAR["iletisim"]
    if not s.izin:
        return 429, s.baslik()                # (("Retry-After", "1234"),)
"""
import hashlib
import hmac
import threading
import time
from collections import namedtuple

from ortak import pg
from ortak.pg_havuz import Havuz

__all__ = ["SinirPg", "Sonuc", "SINIRLAR", "Politika"]

Politika = namedtuple("Politika", "limit pencere_sn")

# Per-endpoint policy (bucket name -> limit per window). "existing" values are the ones the SQLite runtime enforces today
# (tarama/server.py RateLimiter 5/hour/IP, yonetim/portal attempt windows 15 min); the others are the v5.1 section 16 extras.
SINIRLAR = {
    "iletisim": Politika(5, 3600),               # contact form (existing: form/server.py)
    "yukle": Politika(5, 3600),                  # upload (existing: tarama/server.py, shared 5/hour/IP)
    "tarama_baslat": Politika(5, 3600),          # scan start, Mode B request page POST (existing: same limiter)
    "yonetim_giris": Politika(10, 900),          # admin login per IP (existing: yonetim/depo.py DENEME_IP / DENEME_PENCERE_DK)
    "yonetim_giris_kullanici": Politika(5, 900),  # admin login per account (existing: DENEME_KULLANICI)
    "rapor_dogrulama": Politika(10, 3600),       # report verification link (new)
    "rapor_goruntule": Politika(120, 60),        # report viewing (new, v5.1 section 16)
    "tarama_baglan": Politika(30, 3600),         # /api/tarama/baglan page (new, v5.1 section 16)
    "tarama_baglan_token": Politika(20, 900),    # /api/tarama/baglan/<token> (new, v5.1 section 16)
    "portal_kayit": Politika(5, 3600),           # portal registration (existing: shared 5/hour/IP)
    "portal_giris": Politika(10, 900),           # portal login per IP (existing: portal_depo.py DENEME_IP)
    "portal_giris_eposta": Politika(5, 900),     # portal login per e-mail (existing: DENEME_EPOSTA)
}

TEMIZLIK_ARALIGI = 60
TEMIZLIK_ARTIK_SN = 60      # a window is deleted this long after it ended

_KONTROL_SQL = (
    "WITH p AS (SELECT to_timestamp(floor(extract(epoch FROM clock_timestamp()) / $3::int) * $3::int) AS bas) "
    "INSERT INTO alig.sinir_sayac AS s (kova, anahtar_sha256, pencere_utc, bitis_utc, adet) "
    "SELECT $1::text, $2::text, p.bas, p.bas + make_interval(secs => $3::int), 1 FROM p "
    "ON CONFLICT (kova, anahtar_sha256, pencere_utc) DO UPDATE SET adet = s.adet + 1 WHERE s.adet < $4::int "
    "RETURNING s.adet"
)
_TEKRAR_SQL = "SELECT ceil($1::int - mod(extract(epoch FROM clock_timestamp())::numeric, $1::int))::int"
_TEMIZLE_SQL = "DELETE FROM alig.sinir_sayac WHERE bitis_utc < clock_timestamp() - make_interval(secs => $1::int)"


class Sonuc(namedtuple("Sonuc", "izin adet limit kalan tekrar_sn")):
    """izin: whether the request may proceed. adet: the counter after this call (== limit when rejected).
    kalan: requests left in the window. tekrar_sn: seconds until the window ends (0 when allowed)."""
    __slots__ = ()

    def baslik(self):
        """Extra response headers for a 429: (("Retry-After", "<seconds>"),). Empty when allowed."""
        return () if self.izin else (("Retry-After", str(max(1, self.tekrar_sn))),)


class SinirPg:
    def __init__(self, baglan, tuz="", politikalar=None, temizlik_araligi=TEMIZLIK_ARALIGI, saat=time.monotonic, azami_baglanti=8):
        """baglan: a zero-argument callable returning a new ortak.pg.Baglanti (pooled, at most azami_baglanti open)."""
        self._tuz = tuz.encode("utf-8") if isinstance(tuz, str) else bytes(tuz)
        self.politikalar = dict(SINIRLAR if politikalar is None else politikalar)
        self._havuz = Havuz(baglan, azami_baglanti)
        self._aralik, self._saat = temizlik_araligi, saat
        self._son_temizlik = saat()
        self._kilit = threading.Lock()

    def kapat(self):
        """Closes every connection this limiter opened (call after the worker threads have stopped)."""
        self._havuz.kapat()

    # --- the check ---
    def _ozet(self, kova, anahtar):
        ham = ("%s|%s" % (kova, anahtar)).encode("utf-8")
        return hmac.new(self._tuz, ham, hashlib.sha256).hexdigest() if self._tuz else hashlib.sha256(ham).hexdigest()

    def kontrol(self, kova, anahtar, limit=None, pencere_sn=None):
        """Counts one request for (kova, anahtar). limit/pencere_sn default to self.politikalar[kova].
        Raises ortak.pg.PgHata if PostgreSQL cannot be used (the caller answers 503)."""
        if limit is None or pencere_sn is None:
            p = self.politikalar[kova]
            limit = p.limit if limit is None else limit
            pencere_sn = p.pencere_sn if pencere_sn is None else pencere_sn
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be an integer >= 1")
        if not isinstance(pencere_sn, int) or isinstance(pencere_sn, bool) or pencere_sn < 1:
            raise ValueError("pencere_sn must be an integer >= 1")
        if not kova or not str(anahtar):
            raise ValueError("kova and anahtar are required")
        with self._havuz.kullan() as b:
            satirlar = b.sorgu(_KONTROL_SQL, [kova, self._ozet(kova, anahtar), pencere_sn, limit])
            if satirlar:
                sonuc = Sonuc(True, satirlar[0][0], limit, limit - satirlar[0][0], 0)
            else:
                tekrar = b.sorgu(_TEKRAR_SQL, [pencere_sn])[0][0]
                sonuc = Sonuc(False, limit, limit, 0, int(tekrar))
            self._temizlik_gerekirse(b)
        return sonuc

    def _temizlik_gerekirse(self, b):
        simdi = self._saat()
        with self._kilit:
            if simdi - self._son_temizlik < self._aralik:
                return
            self._son_temizlik = simdi
        try:
            self.temizle(b)
        except pg.PgHata:
            pass   # cleanup is housekeeping: it must not fail the request that triggered it

    def temizle(self, baglanti=None):
        """Deletes windows that ended more than TEMIZLIK_ARTIK_SN seconds ago. Returns the number of deleted rows."""
        if baglanti is not None:
            baglanti.sorgu(_TEMIZLE_SQL, [TEMIZLIK_ARTIK_SN])
            return baglanti.etkilenen
        with self._havuz.kullan() as b:
            b.sorgu(_TEMIZLE_SQL, [TEMIZLIK_ARTIK_SN])
            return b.etkilenen
