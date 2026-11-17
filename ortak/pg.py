"""The shared PostgreSQL connection layer: a narrow ctypes + system libpq wrapper (ALIG-DB-003b, decision DB-K1 = B).

Not wired into the application yet: SQLite is still the runtime; ALIG-DB-003c-e build on this module.

Public API (everything else is private)
---------------------------------------
Connection (one PGconn, never shared between threads):
    Baglanti.baglan(*, host, port=None, dbname, user, password, baglanti_zaman_asimi=10, statement_timeout_ms=30000,
                    lock_timeout_ms=5000, bosta_islem_zaman_asimi_ms=60000, uygulama_adi="alig",
                    sslmode=None, sslrootcert=None) -> Baglanti
        host is required (a Unix socket directory, or a network name). Over the network sslmode MUST be "verify-full"
        (Master Prompt v5.1 section 5, DB-K2); sslrootcert (a path or "system") is passed through to libpq. A violation raises
        ValueError before libpq is called. Unix socket: sslmode is optional. No retry; BaglantiHatasi on failure.
    b.sorgu(sql, parametreler=(), *, gizli=False) -> list[tuple]
        One statement, parameters bound server-side as $1, $2 (PQexecParams), never concatenated. gizli=True: the
        parameter values are also masked in any error text (server messages can echo a value, for example
        'invalid input syntax for type integer: "..."'). b.etkilenen = rows affected by the last command.
    b.islem(*, salt_okunur=False, izolasyon=None, statement_timeout_ms=None, lock_timeout_ms=None)
        Context manager: BEGIN [ISOLATION LEVEL ...] [READ ONLY]; COMMIT on a normal exit; ROLLBACK on any exception
        (re-raised unchanged). izolasyon: "read committed" | "repeatable read" | "serializable". The two timeouts are
        transaction-local (they revert at the end). Nesting is refused (PgHata).
    b.islemde, b.kopuk (broken), b.iptal() (PQcancel; the only call allowed from another thread), b.kapat(), "with".
Retry (the only retry in the layer):
    tekrarli_islem(kaynak, is_fn, *, salt_okunur=False, idempotency_anahtari=None, izolasyon=None,
                   azami_deneme=3, ilk_bekleme_s=0.05, azami_bekleme_s=1.0, yeniden_dene_baglanti=True) -> is_fn's result
        Runs is_fn(baglanti) inside b.islem(). kaynak is a Baglanti (then a connection loss is raised, not retried) or a
        zero-argument factory returning a Baglanti (then the helper owns the connections, reopens after a loss and closes
        them at the end). Allowed ONLY for a read-only transaction (salt_okunur=True) or a write that carries an
        idempotency key (a non-empty str that is_fn itself uses so that a replay is a no-op, for example
        INSERT ... ON CONFLICT (idempotency_key) DO NOTHING); otherwise ValueError and is_fn is not run. Retried:
        SerilestirmeHatasi (40001, 40P01) and, with a factory, BaglantiHatasi. Never retried: constraint, permission,
        timeout and every other error, and any non-database exception. Bounded: azami_deneme (1..10) attempts, equal-jitter
        exponential backoff capped at azami_bekleme_s, none after the last attempt; the last error is raised with
        .deneme_sayisi. is_fn must have no side effect outside the database that cannot be repeated.
Errors (all derive from PgHata; sorgu() never maps one class to another silently):
    PgHata
      KutuphaneHatasi                libpq missing or not thread safe
      EszamanliKullanimHatasi        connection used by two threads
      BaglantiHatasi                 could not connect / authentication failed / connection lost; .sonuc_belirsiz
        SonucBelirsizHatasi            lost while COMMIT (or a statement outside a transaction) was in flight: the outcome is
                                       UNKNOWN; reconcile with the idempotency record, never declare success or failure
      SorguHatasi(.sqlstate, .kisit)  the server rejected a statement
        ButunlukHatasi (23xxx) > BenzersizlikHatasi (23505)
        SerilestirmeHatasi (40001) > DeadlockHatasi (40P01)
        YetkiHatasi (42501)
        ZamanAsimiHatasi (57014, 55P03) > SorguIptalHatasi (57014; also a user cancel), KilitHatasi (55P03)
    Messages hold the SQLSTATE and the server's primary message only (no DETAIL, no SQL text, no parameters).
Helpers: kutuphane_yukle(), thread_guvenli().

Design rules:
- Python standard library only; libpq is loaded from the system (Linux: libpq.so.5, Windows: libpq.dll).
- Values are never concatenated into the query text: they are bound as $1, $2 with PQexecParams, in text format.
- Every PGresult is closed with PQclear and every PGconn with PQfinish (try/finally).
- Secrets: the password (plain and escaped), a conninfo-style "password=..." and, with gizli=True, the parameter values are
  masked in every exception message and every log record (logger "alig.pg"). The connection string is never kept,
  logged or put into a message; SQL text and parameters are never logged.
- No blind retry anywhere except tekrarli_islem. sorgu() and islem() send each statement at most once.
- A lost connection is released at once (PQfinish), marked broken (kopuk) and refuses further use with a clear error;
  there is no automatic reconnect and no half-open state. A transaction cut by a loss before COMMIT cannot have committed.
- No pool: one Baglanti per thread/job, opened by the caller (a pool needs its own tests and is not part of 003b).

Thread safety: libpq is checked with PQisthreadsafe(). A Baglanti object can be used by a single thread at a time
and is NOT SHARED between threads: if a second thread tries to use a busy connection it gets
EszamanliKullanimHatasi (it is not made to wait, not queued). An open transaction (islem()) belongs only to the
thread that started it. The only exception is iptal(): it may be called from another thread (PQcancel).
Each thread opens its own connection.

Parameter type: if the server cannot infer the type ($1 alone inside a SELECT) it raises an error; if needed write a type
cast such as $1::text. The result arrives in text format; only bool, int, float, numeric and timestamptz are converted to a Python type,
the others stay str; NULL is always None. A datetime without a time zone is rejected.
"""
import ctypes
import ctypes.util
import logging
import os
import random
import re
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

__all__ = [
    "PgHata", "KutuphaneHatasi", "BaglantiHatasi", "SonucBelirsizHatasi", "SorguHatasi", "ButunlukHatasi",
    "BenzersizlikHatasi", "ZamanAsimiHatasi", "SorguIptalHatasi", "KilitHatasi", "SerilestirmeHatasi",
    "DeadlockHatasi", "YetkiHatasi", "EszamanliKullanimHatasi",
    "Baglanti", "tekrarli_islem", "kutuphane_yukle", "thread_guvenli",
]

_gunluk = logging.getLogger("alig.pg")
_gunluk.addHandler(logging.NullHandler())  # library: the application configures logging


# --- error classes -------------------------------------------------------------------------------------------

class PgHata(Exception):
    """Base of all PostgreSQL layer errors."""


class KutuphaneHatasi(PgHata):
    """libpq was not found or is unusable (for example, not thread safe)."""


class BaglantiHatasi(PgHata):
    """The connection could not be made, authentication failed or the connection dropped. The operation is not repeated.

    sonuc_belirsiz: True if the loss happened while a statement that may have committed was in flight."""

    def __init__(self, mesaj, sonuc_belirsiz=False):
        super().__init__(mesaj)
        self.sonuc_belirsiz = sonuc_belirsiz


class SonucBelirsizHatasi(BaglantiHatasi):
    """The connection dropped during COMMIT (or a statement outside a transaction): whether it committed is unknown."""

    def __init__(self, mesaj):
        super().__init__(mesaj, sonuc_belirsiz=True)


class EszamanliKullanimHatasi(PgHata):
    """The connection is in use by another thread (a connection cannot be shared)."""


class SorguHatasi(PgHata):
    """The server rejected the query. sqlstate: the 5-character SQLSTATE; kisit: the constraint name, if any."""

    def __init__(self, mesaj, sqlstate=None, kisit=None):
        super().__init__(f"[{sqlstate}] {mesaj}" if sqlstate else mesaj)
        self.mesaj = mesaj
        self.sqlstate = sqlstate
        self.kisit = kisit


class ButunlukHatasi(SorguHatasi):
    """SQLSTATE class 23 (integrity constraint)."""


class BenzersizlikHatasi(ButunlukHatasi):
    """SQLSTATE 23505."""


class ZamanAsimiHatasi(SorguHatasi):
    """A timeout: statement_timeout / cancel (57014) or lock_timeout (55P03)."""


class SorguIptalHatasi(ZamanAsimiHatasi):
    """SQLSTATE 57014: statement_timeout expired or the query was cancelled (PQcancel/pg_cancel_backend look the same)."""


class KilitHatasi(ZamanAsimiHatasi):
    """SQLSTATE 55P03: lock_timeout expired or the lock could not be acquired."""


class SerilestirmeHatasi(SorguHatasi):
    """SQLSTATE 40001 (serialization failure). The transaction was rolled back; retry only via tekrarli_islem."""


class DeadlockHatasi(SerilestirmeHatasi):
    """SQLSTATE 40P01 (deadlock detected): this transaction was the victim and was rolled back."""


class YetkiHatasi(SorguHatasi):
    """SQLSTATE 42501 (permission denied)."""


_SINIFLAR = {
    "23505": BenzersizlikHatasi, "57014": SorguIptalHatasi, "55P03": KilitHatasi,
    "40001": SerilestirmeHatasi, "40P01": DeadlockHatasi, "42501": YetkiHatasi,
}


def _hata_sinifi(sqlstate):
    if sqlstate in _SINIFLAR:
        return _SINIFLAR[sqlstate]
    if sqlstate and sqlstate.startswith("23"):
        return ButunlukHatasi
    return SorguHatasi


# --- loading libpq -------------------------------------------------------------------------------------------

_yukleme_kilidi = threading.Lock()
_lib = None

CONNECTION_OK = 0
PGRES_EMPTY_QUERY, PGRES_COMMAND_OK, PGRES_TUPLES_OK = 0, 1, 2
PG_DIAG_SQLSTATE, PG_DIAG_MESSAGE_PRIMARY, PG_DIAG_CONSTRAINT_NAME = ord("C"), ord("M"), ord("n")

# OID -> converter (text format)
_OID_BOOL, _OID_INT8, _OID_INT2, _OID_INT4 = 16, 20, 21, 23
_OID_FLOAT4, _OID_FLOAT8, _OID_NUMERIC, _OID_TIMESTAMPTZ = 700, 701, 1700, 1184


def _aday_listesi():
    adaylar = []
    ozel = os.environ.get("ALIG_LIBPQ")
    if ozel:
        adaylar.append(ozel)
    bulunan = ctypes.util.find_library("pq")
    if bulunan:
        adaylar.append(bulunan)
    adaylar += ["libpq.so.5", "libpq.dll", "libpq.5.dylib"]
    return adaylar


def _imzalar(lib):
    vp, ci, cp = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
    tanim = {
        "PQconnectdb": (vp, [cp]),
        "PQstatus": (ci, [vp]),
        "PQerrorMessage": (cp, [vp]),
        "PQfinish": (None, [vp]),
        "PQexecParams": (vp, [vp, cp, ci, vp, ctypes.POINTER(cp), vp, vp, ci]),
        "PQresultStatus": (ci, [vp]),
        "PQresultErrorField": (cp, [vp, ci]),
        "PQresultErrorMessage": (cp, [vp]),
        "PQntuples": (ci, [vp]),
        "PQnfields": (ci, [vp]),
        "PQftype": (ctypes.c_uint, [vp, ci]),
        "PQgetvalue": (cp, [vp, ci, ci]),
        "PQgetisnull": (ci, [vp, ci]),
        "PQgetlength": (ci, [vp, ci, ci]),
        "PQcmdTuples": (cp, [vp]),
        "PQclear": (None, [vp]),
        "PQgetCancel": (vp, [vp]),
        "PQcancel": (ci, [vp, ctypes.c_char_p, ci]),
        "PQfreeCancel": (None, [vp]),
        "PQisthreadsafe": (ci, []),
        "PQlibVersion": (ci, []),
    }
    for ad, (donus, args) in tanim.items():
        f = getattr(lib, ad)
        f.restype = donus
        f.argtypes = args


def kutuphane_yukle(adaylar=None, onbellek=True):
    """Loads libpq. KutuphaneHatasi if it is not found or not thread safe (no silent fallback)."""
    global _lib
    with _yukleme_kilidi:
        if onbellek and adaylar is None and _lib is not None:
            return _lib
        denenen, son_hata = [], None
        for aday in (adaylar if adaylar is not None else _aday_listesi()):
            denenen.append(aday)
            try:
                lib = ctypes.CDLL(aday)
                _imzalar(lib)
            except (OSError, AttributeError) as e:
                son_hata = e
                continue
            if lib.PQisthreadsafe() != 1:
                raise KutuphaneHatasi(f"libpq is not thread safe ({aday}); not used")
            if onbellek and adaylar is None:
                _lib = lib
            return lib
        raise KutuphaneHatasi(
            "libpq not found (tried: " + ", ".join(denenen) + "). Linux: install the 'libpq5' package; "
            "Windows: put libpq.dll and its dependencies on PATH or give the path with ALIG_LIBPQ. "
            f"Last error: {son_hata}")


def thread_guvenli():
    return kutuphane_yukle().PQisthreadsafe() == 1


# --- helpers -------------------------------------------------------------------------------------------------

_PAROLA_DESENI = re.compile(r"(?i)(pass(?:word)?\s*=\s*)(?:'(?:\\.|[^'\\])*'|\S+)")


def _maskele(metin, sirlar):
    """Turns known secrets (plain and conninfo-escaped) and any conninfo-style password=... in the text into ***."""
    for s in sirlar:
        if s:
            for bicim in (s.replace("\\", "\\\\").replace("'", "\\'"), s):
                metin = metin.replace(bicim, "***")
    return _PAROLA_DESENI.sub(lambda m: m.group(1) + "'***'", metin)


def _kontrol_nul(deger, ad):
    if "\x00" in deger:
        raise ValueError(f"{ad}: cannot contain a NUL character")


_SSLMODLARI = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")


def _tls_denetle(host, sslmode, sslrootcert):
    """TLS policy (v5.1 section 5, DB-K2): a network host requires sslmode=verify-full; a Unix socket does not use TLS."""
    if not host:
        raise ValueError("host is required (a Unix socket directory or a server name); there is no environment fallback")
    if sslmode is not None and sslmode not in _SSLMODLARI:
        raise ValueError("unknown sslmode")
    for h in str(host).split(","):
        if not h.startswith("/") and sslmode != "verify-full":
            raise ValueError("a network connection requires sslmode='verify-full' (and sslrootcert for a private CA)")
    if sslrootcert is not None:
        _kontrol_nul(str(sslrootcert), "sslrootcert")


def _pozitif_tamsayi(deger, ad):
    if isinstance(deger, bool) or not isinstance(deger, int) or deger <= 0:
        raise ValueError(f"{ad}: must be a positive integer (milliseconds)")
    return deger


def _baglanti_dizgisi(ayarlar):
    """A key='value' string; \\ and ' are escaped in the value. None values are skipped."""
    parcalar = []
    for anahtar, deger in ayarlar.items():
        if deger is None:
            continue
        deger = str(deger)
        _kontrol_nul(deger, anahtar)
        kacisli = deger.replace("\\", "\\\\").replace("'", "\\'")
        parcalar.append(f"{anahtar}='{kacisli}'")
    return " ".join(parcalar)


def _parametre_metni(deger):
    """Converts a Python value to a text-format parameter (bytes); None -> NULL."""
    if deger is None:
        return None
    if isinstance(deger, bool):
        return b"true" if deger else b"false"
    if isinstance(deger, (int, float, Decimal)):
        return str(deger).encode("ascii")
    if isinstance(deger, datetime):
        if deger.tzinfo is None or deger.utcoffset() is None:
            raise ValueError("datetime without a time zone rejected (for timestamptz give UTC or an offset)")
        return deger.isoformat().encode("ascii")
    if isinstance(deger, date):
        return deger.isoformat().encode("ascii")
    if isinstance(deger, (bytes, bytearray)):
        return b"\\x" + bytes(deger).hex().encode("ascii")
    if isinstance(deger, str):
        _kontrol_nul(deger, "parametre")
        return deger.encode("utf-8")
    raise TypeError(f"unsupported parameter type: {type(deger).__name__}")


def _doniustur(oid, metin):
    if oid == _OID_BOOL:
        return metin == "t"
    if oid in (_OID_INT2, _OID_INT4, _OID_INT8):
        return int(metin)
    if oid in (_OID_FLOAT4, _OID_FLOAT8):
        return float(metin)
    if oid == _OID_NUMERIC:
        return Decimal(metin)
    if oid == _OID_TIMESTAMPTZ:
        try:
            return datetime.fromisoformat(metin)
        except ValueError:  # special values such as infinity
            return metin
    return metin


# --- connection ----------------------------------------------------------------------------------------------

_IZOLASYON = {"read committed": "READ COMMITTED", "repeatable read": "REPEATABLE READ", "serializable": "SERIALIZABLE"}


class Baglanti:
    """A single PGconn. Not shared between threads (see the module docstring). Create it with baglan(), not directly."""

    def __init__(self):
        raise TypeError("use Baglanti.baglan(...)")

    @classmethod
    def baglan(cls, *, host=None, port=None, dbname=None, user=None, password=None,
               baglanti_zaman_asimi=10, statement_timeout_ms=30000, lock_timeout_ms=5000,
               bosta_islem_zaman_asimi_ms=60000, uygulama_adi="alig", sslmode=None, sslrootcert=None):
        """Connects and sets the session timeouts. There is no retry; BaglantiHatasi on failure.

        ValueError (before libpq is called) for a bad argument or a TLS policy violation (see the module docstring)."""
        _tls_denetle(host, sslmode, sslrootcert)
        zamanlar = [(ad, int(v)) for ad, v in (("statement_timeout", statement_timeout_ms),
                                               ("lock_timeout", lock_timeout_ms),
                                               ("idle_in_transaction_session_timeout", bosta_islem_zaman_asimi_ms))]
        if any(v < 0 for _, v in zamanlar) or int(baglanti_zaman_asimi) <= 0:
            raise ValueError("timeouts must not be negative (connect timeout: positive)")
        lib = kutuphane_yukle()
        dizgi = _baglanti_dizgisi({
            "host": host, "port": port, "dbname": dbname, "user": user, "password": password,
            "connect_timeout": int(baglanti_zaman_asimi), "application_name": uygulama_adi,
            "client_encoding": "UTF8", "sslmode": sslmode, "sslrootcert": sslrootcert,
            # a silently dead peer (cable pulled, firewall drop) is noticed by the OS instead of hanging forever
            "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
        })
        self = object.__new__(cls)
        self._lib = lib
        self._sirlar = [password] if password else []
        self._conn = None
        self._iptal = None
        self._kopuk = False
        self._islemde = False
        self._islem_sahibi = None
        self.etkilenen = None
        self._mesgul = threading.Lock()      # held during a query; to refuse sharing
        self._iptal_kilidi = threading.Lock()  # between iptal() and kapat()
        conn = lib.PQconnectdb(dizgi.encode("utf-8"))
        del dizgi
        if not conn:
            raise BaglantiHatasi("could not create the connection object (memory)")
        if lib.PQstatus(conn) != CONNECTION_OK:
            mesaj = _maskele(self._metin(lib.PQerrorMessage(conn)) or "could not connect", self._sirlar)
            lib.PQfinish(conn)
            _gunluk.warning("connection could not be established: %s", mesaj)
            raise BaglantiHatasi(mesaj)
        self._conn = conn
        try:
            self._iptal = lib.PQgetCancel(conn)  # taken now so that iptal() can be used safely from another thread
            for ad, deger in zamanlar + [("TimeZone", "UTC")]:
                self.sorgu("SELECT set_config($1, $2, false)", [ad, str(deger)])
        except BaseException:
            self.kapat()
            raise
        return self

    # -- helpers
    @staticmethod
    def _metin(b):
        return b.decode("utf-8", "replace").strip() if b else ""

    def __repr__(self):
        durum = "kopuk" if self._kopuk else ("kapali" if self._conn is None else "acik")
        return f"<pg.Baglanti {durum}>"

    __str__ = __repr__

    @property
    def islemde(self):
        return self._islemde

    @property
    def kopuk(self):
        return self._kopuk

    # -- query
    def sorgu(self, sql, parametreler=(), *, gizli=False):
        """A single SQL statement; parameters with $1, $2 ... Returns a list of rows (tuples); an empty list for commands.

        gizli=True also masks the parameter values in any error text. Sent at most once: no retry."""
        if self._islemde and self._islem_sahibi != threading.get_ident():
            raise EszamanliKullanimHatasi("the transaction belongs to another thread")
        return self._komut(sql, parametreler, not self._islemde, gizli)

    def _komut(self, sql, parametreler, belirsiz, gizli=False):
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("the connection is in use by another thread; it cannot be shared")
        try:
            return self._calistir(sql, parametreler, belirsiz, gizli)
        finally:
            self._mesgul.release()

    def _calistir(self, sql, parametreler, belirsiz, gizli):
        if self._kopuk:
            raise BaglantiHatasi("connection is broken; open a new connection")
        if self._conn is None:
            raise BaglantiHatasi("connection is closed")
        lib = self._lib
        _kontrol_nul(sql, "sql")
        degerler = [_parametre_metni(p) for p in parametreler]
        sirlar = self._sirlar
        if gizli:
            sirlar = sirlar + [d.decode("utf-8", "replace") for d in degerler if d]
        n = len(degerler)
        dizi = (ctypes.c_char_p * n)(*degerler) if n else None
        res = lib.PQexecParams(self._conn, sql.encode("utf-8"), n, None, dizi, None, None, 0)
        if not res:
            self._kayip(self._metin(lib.PQerrorMessage(self._conn)) or "no result", sirlar, belirsiz, None)
        try:
            durum = lib.PQresultStatus(res)
            if durum in (PGRES_COMMAND_OK, PGRES_TUPLES_OK, PGRES_EMPTY_QUERY):
                return self._satirlar(res, durum)
            sqlstate = self._metin(lib.PQresultErrorField(res, PG_DIAG_SQLSTATE)) or None
            birincil = self._metin(lib.PQresultErrorField(res, PG_DIAG_MESSAGE_PRIMARY)) \
                or self._metin(lib.PQresultErrorMessage(res))
            kisit = self._metin(lib.PQresultErrorField(res, PG_DIAG_CONSTRAINT_NAME)) or None
        finally:
            lib.PQclear(res)
        # an error without SQLSTATE is a client-side error (including connection loss); 08xxx and 57P01-03 are connection/server shutdown
        if (lib.PQstatus(self._conn) != CONNECTION_OK or not sqlstate or sqlstate.startswith("08")
                or sqlstate in ("57P01", "57P02", "57P03")):
            self._kayip(birincil, sirlar, belirsiz, sqlstate)
        # the detail (DETAIL) is deliberately not added: it may contain row values
        raise _hata_sinifi(sqlstate)(_maskele(birincil, sirlar), sqlstate, kisit)

    def _kayip(self, birincil, sirlar, belirsiz, sqlstate):
        """The connection is gone: release libpq now (no half-open PGconn), mark broken, raise a clear error."""
        self._kopuk = True
        self._serbest_birak()
        mesaj = _maskele(birincil, sirlar)
        _gunluk.warning("connection lost (sqlstate=%s, outcome %s)", sqlstate or "none",
                        "unknown" if belirsiz else "not committed")
        if belirsiz:
            raise SonucBelirsizHatasi(f"connection dropped; whether the statement took effect is unknown: {mesaj}")
        raise BaglantiHatasi(f"connection dropped: {mesaj}")

    def _serbest_birak(self):
        with self._iptal_kilidi:
            if self._iptal is not None:
                self._lib.PQfreeCancel(self._iptal)
                self._iptal = None
            if self._conn is not None:
                self._lib.PQfinish(self._conn)
                self._conn = None
        self._islemde = False
        self._islem_sahibi = None

    def _satirlar(self, res, durum):
        lib = self._lib
        self.etkilenen = None
        sayi = self._metin(lib.PQcmdTuples(res))
        if sayi.isdigit():
            self.etkilenen = int(sayi)
        if durum != PGRES_TUPLES_OK:
            return []
        satir_sayisi, kolon_sayisi = lib.PQntuples(res), lib.PQnfields(res)
        tipler = [lib.PQftype(res, j) for j in range(kolon_sayisi)]
        sonuc = []
        for i in range(satir_sayisi):
            satir = []
            for j in range(kolon_sayisi):
                if lib.PQgetisnull(res, i, j):
                    satir.append(None)
                else:
                    ham = ctypes.string_at(lib.PQgetvalue(res, i, j), lib.PQgetlength(res, i, j))
                    satir.append(_doniustur(tipler[j], ham.decode("utf-8")))
            sonuc.append(tuple(satir))
        return sonuc

    # -- transaction
    @contextmanager
    def islem(self, *, salt_okunur=False, izolasyon=None, statement_timeout_ms=None, lock_timeout_ms=None):
        """with baglanti.islem(): BEGIN; COMMIT on exit; ROLLBACK on an exception and the exception is re-raised.

        salt_okunur=True: BEGIN READ ONLY (the server refuses writes, SQLSTATE 25006). izolasyon: one of
        "read committed", "repeatable read", "serializable". statement_timeout_ms / lock_timeout_ms apply to this
        transaction only. A connection lost before COMMIT raises BaglantiHatasi (cannot have committed); during COMMIT
        SonucBelirsizHatasi."""
        if self._islemde:
            raise PgHata("nested transactions are not supported")
        baslat = "BEGIN"
        if izolasyon is not None:
            duzey = _IZOLASYON.get(izolasyon.lower() if isinstance(izolasyon, str) else None)
            if duzey is None:
                raise ValueError("izolasyon must be one of: " + ", ".join(_IZOLASYON))
            baslat += " ISOLATION LEVEL " + duzey
        if salt_okunur:
            baslat += " READ ONLY"
        yerel = [(ad, str(_pozitif_tamsayi(v, ad))) for ad, v in
                 (("statement_timeout", statement_timeout_ms), ("lock_timeout", lock_timeout_ms)) if v is not None]
        self._komut(baslat, (), False)
        self._islemde = True
        self._islem_sahibi = threading.get_ident()
        try:
            for ad, deger in yerel:
                self.sorgu("SELECT set_config($1, $2, true)", [ad, deger])  # is_local: reverts at the end of the transaction
            yield self
        except BaseException:
            self._geri_al()
            raise
        try:
            self._komut("COMMIT", (), True)
        except BaseException:
            self._geri_al()
            raise
        finally:
            self._islemde = False
            self._islem_sahibi = None

    def _geri_al(self):
        try:
            if self._conn is not None and not self._kopuk:
                self._komut("ROLLBACK", (), False)
        except PgHata as e:
            _gunluk.warning("rollback failed: %s", type(e).__name__)  # the real error propagates anyway
        finally:
            self._islemde = False
            self._islem_sahibi = None

    # -- cancel and close
    def iptal(self):
        """Cancels the running query with PQcancel; may be called from another thread. The query gets SorguIptalHatasi."""
        with self._iptal_kilidi:
            if self._iptal is None:
                raise BaglantiHatasi("connection is closed")
            tampon = ctypes.create_string_buffer(256)
            if self._lib.PQcancel(self._iptal, tampon, 256) != 1:
                raise PgHata("cancel request could not be sent: " + _maskele(self._metin(tampon.value), self._sirlar))

    def kapat(self):
        """PQfinish; may be called more than once. Refuses if another thread is running a query."""
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("connection is in use; cannot be closed")
        try:
            self._serbest_birak()
        finally:
            self._mesgul.release()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.kapat()

    def __del__(self):
        try:
            if getattr(self, "_conn", None) is not None:
                self.kapat()
        except Exception:
            pass


# --- retry ---------------------------------------------------------------------------------------------------

def tekrarli_islem(kaynak, is_fn, *, salt_okunur=False, idempotency_anahtari=None, izolasyon=None,
                   azami_deneme=3, ilk_bekleme_s=0.05, azami_bekleme_s=1.0, uyku=time.sleep):
    """Runs is_fn(baglanti) in a transaction and retries ONLY where a retry is safe (see the module docstring).

    uyku is a test hook (the sleep function). Returns what is_fn returns."""
    anahtar_var = False
    if idempotency_anahtari is not None:
        if (not isinstance(idempotency_anahtari, str) or not idempotency_anahtari.strip()
                or len(idempotency_anahtari) > 255 or "\x00" in idempotency_anahtari):
            raise ValueError("idempotency_anahtari must be a non-empty string of at most 255 characters")
        anahtar_var = True
    if not (salt_okunur or anahtar_var):
        raise ValueError("retry is allowed only for a read-only transaction (salt_okunur=True) or a write that "
                         "carries an idempotency key (idempotency_anahtari)")
    if isinstance(azami_deneme, bool) or not isinstance(azami_deneme, int) or not 1 <= azami_deneme <= 10:
        raise ValueError("azami_deneme must be an integer from 1 to 10")
    if not (0 < ilk_bekleme_s <= azami_bekleme_s):
        raise ValueError("0 < ilk_bekleme_s <= azami_bekleme_s is required")
    if isinstance(kaynak, Baglanti):
        baglanti, fabrika = kaynak, None
    elif callable(kaynak):
        baglanti, fabrika = None, kaynak
    else:
        raise TypeError("kaynak must be a Baglanti or a factory returning one")
    try:
        for deneme in range(1, azami_deneme + 1):
            try:
                if baglanti is None:
                    baglanti = fabrika()
                    if not isinstance(baglanti, Baglanti):
                        raise TypeError("the factory must return a Baglanti")
                with baglanti.islem(salt_okunur=salt_okunur, izolasyon=izolasyon):
                    return is_fn(baglanti)
            except SerilestirmeHatasi as e:
                son = e
            except BaglantiHatasi as e:
                if fabrika is None:
                    e.deneme_sayisi = deneme
                    raise
                son = e
                if baglanti is not None:
                    try:
                        baglanti.kapat()
                    except PgHata:
                        pass
                    baglanti = None
            son.deneme_sayisi = deneme
            if deneme == azami_deneme:
                raise son
            tavan = min(azami_bekleme_s, ilk_bekleme_s * 2 ** (deneme - 1))
            bekleme = random.uniform(tavan / 2, tavan)
            _gunluk.info("retry %d of %d after %s (waiting %.3f s)", deneme, azami_deneme, type(son).__name__, bekleme)
            uyku(bekleme)
    finally:
        if fabrika is not None and baglanti is not None:
            try:
                baglanti.kapat()
            except PgHata:
                pass
