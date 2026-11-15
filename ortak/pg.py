"""A narrow ctypes + libpq wrapper for PostgreSQL (ALIG-DB-002 EVALUATION prototype).

Not wired into the application; no module imports it. Produces evidence for decision DB-K1 (docs/postgresql-gecis.md section 2).

Design rules:
- Python standard library only; libpq is loaded from the system (Linux: libpq.so.5, Windows: libpq.dll).
- Values are never concatenated into the query text: values are bound as $1, $2 with PQexecParams, in text format.
- Every PGresult is closed with PQclear and every PGconn with PQfinish (try/finally).
- The password is not written to error messages, repr or the log; possible traces are masked.
- No blind retry: when the connection drops BaglantiHatasi is raised, the operation is not repeated.

Thread safety: libpq is checked with PQisthreadsafe(). A Baglanti object can be used by a single thread at a time
and is NOT SHARED between threads: if a second thread tries to use a busy connection it gets
EszamanliKullanimHatasi (it is not made to wait, not queued). An open transaction (islem()) belongs only to the
thread that started it. The only exception is iptal(): it may be called from another thread (PQcancel).
Each thread opens its own connection.

Parameter type: if the server cannot infer the type ($1 alone inside a SELECT) it raises an error; if needed write a type
cast such as $1::text. The result arrives in text format; only bool, int, float, numeric and timestamptz are converted to a Python type,
the others stay str; NULL is always None.
"""
import ctypes
import ctypes.util
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

__all__ = [
    "PgHata", "KutuphaneHatasi", "BaglantiHatasi", "SorguHatasi", "ButunlukHatasi", "BenzersizlikHatasi",
    "SorguIptalHatasi", "KilitHatasi", "SerilestirmeHatasi", "EszamanliKullanimHatasi",
    "Baglanti", "kutuphane_yukle", "thread_guvenli",
]


# --- error classes -------------------------------------------------------------------------------------------

class PgHata(Exception):
    """Base of all PostgreSQL layer errors."""


class KutuphaneHatasi(PgHata):
    """libpq was not found or is unusable (for example, not thread safe)."""


class BaglantiHatasi(PgHata):
    """The connection could not be made, authentication failed or the connection dropped. The operation is not repeated."""


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


class SorguIptalHatasi(SorguHatasi):
    """SQLSTATE 57014: if statement_timeout expired or it was cancelled with PQcancel."""


class KilitHatasi(SorguHatasi):
    """SQLSTATE 55P03: lock_timeout expired or the lock could not be acquired."""


class SerilestirmeHatasi(SorguHatasi):
    """SQLSTATE 40001 / 40P01: serialization or deadlock. The decision to retry belongs to the caller."""


def _hata_sinifi(sqlstate):
    if sqlstate == "23505":
        return BenzersizlikHatasi
    if sqlstate and sqlstate.startswith("23"):
        return ButunlukHatasi
    if sqlstate == "57014":
        return SorguIptalHatasi
    if sqlstate == "55P03":
        return KilitHatasi
    if sqlstate in ("40001", "40P01"):
        return SerilestirmeHatasi
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

def _maskele(metin, sirlar):
    """Turns known secrets in the text into ***."""
    for s in sirlar:
        if s:
            metin = metin.replace(s, "***")
    return metin


def _kontrol_nul(deger, ad):
    if "\x00" in deger:
        raise ValueError(f"{ad}: cannot contain a NUL character")


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

class Baglanti:
    """A single PGconn. Not shared between threads (see the module docstring). Create it with baglan(), not directly."""

    def __init__(self):
        raise TypeError("use Baglanti.baglan(...)")

    @classmethod
    def baglan(cls, *, host=None, port=None, dbname=None, user=None, password=None,
               baglanti_zaman_asimi=10, statement_timeout_ms=30000, lock_timeout_ms=5000,
               bosta_islem_zaman_asimi_ms=60000, uygulama_adi="alig", sslmode=None):
        """Connects and sets the session timeouts. There is no retry; BaglantiHatasi on failure."""
        lib = kutuphane_yukle()
        dizgi = _baglanti_dizgisi({
            "host": host, "port": port, "dbname": dbname, "user": user, "password": password,
            "connect_timeout": int(baglanti_zaman_asimi), "application_name": uygulama_adi,
            "client_encoding": "UTF8", "sslmode": sslmode,
        })
        self = object.__new__(cls)
        self._lib = lib
        self._sirlar = [password]
        self._conn = None
        self._iptal = None
        self._kopuk = False
        self._islemde = False
        self._islem_sahibi = None
        self._mesgul = threading.Lock()      # held during a query; to refuse sharing
        self._iptal_kilidi = threading.Lock()  # between iptal() and kapat()
        conn = lib.PQconnectdb(dizgi.encode("utf-8"))
        del dizgi
        if not conn:
            raise BaglantiHatasi("could not create the connection object (memory)")
        if lib.PQstatus(conn) != CONNECTION_OK:
            mesaj = self._metin(lib.PQerrorMessage(conn))
            lib.PQfinish(conn)
            raise BaglantiHatasi(_maskele(mesaj or "could not connect", self._sirlar))
        self._conn = conn
        try:
            self._iptal = lib.PQgetCancel(conn)  # taken now so that iptal() can be used safely from another thread
            for ad, deger in (("statement_timeout", statement_timeout_ms), ("lock_timeout", lock_timeout_ms),
                              ("idle_in_transaction_session_timeout", bosta_islem_zaman_asimi_ms),
                              ("TimeZone", "UTC")):
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
        durum = "kapali" if self._conn is None else ("kopuk" if self._kopuk else "acik")
        return f"<pg.Baglanti {durum}>"

    __str__ = __repr__

    @property
    def islemde(self):
        return self._islemde

    @property
    def kopuk(self):
        return self._kopuk

    # -- query
    def sorgu(self, sql, parametreler=()):
        """A single SQL statement; parameters with $1, $2 ... Returns a list of rows (tuples); an empty list for commands."""
        if self._islemde and self._islem_sahibi != threading.get_ident():
            raise EszamanliKullanimHatasi("the transaction belongs to another thread")
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("the connection is in use by another thread; it cannot be shared")
        try:
            return self._calistir(sql, parametreler)
        finally:
            self._mesgul.release()

    def _calistir(self, sql, parametreler):
        if self._conn is None:
            raise BaglantiHatasi("connection is closed")
        if self._kopuk:
            raise BaglantiHatasi("connection is broken; open a new connection")
        lib = self._lib
        _kontrol_nul(sql, "sql")
        degerler = [_parametre_metni(p) for p in parametreler]
        n = len(degerler)
        dizi = (ctypes.c_char_p * n)(*degerler) if n else None
        res = lib.PQexecParams(self._conn, sql.encode("utf-8"), n, None, dizi, None, None, 0)
        if not res:
            return self._bos_sonuc_hatasi()
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
            self._kopuk = True
            raise BaglantiHatasi(_maskele(f"connection dropped: {birincil}", self._sirlar))
        # the detail (DETAIL) is deliberately not added: it may contain row values
        raise _hata_sinifi(sqlstate)(_maskele(birincil, self._sirlar), sqlstate, kisit)

    def _bos_sonuc_hatasi(self):
        self._kopuk = self._kopuk or self._lib.PQstatus(self._conn) != CONNECTION_OK
        mesaj = self._metin(self._lib.PQerrorMessage(self._conn)) or "sonuc alinamadi"
        raise BaglantiHatasi(_maskele(mesaj, self._sirlar))

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
    def islem(self):
        """with baglanti.islem(): BEGIN; COMMIT on exit; ROLLBACK on an exception and the exception is re-raised."""
        if self._islemde:
            raise PgHata("nested transactions are not supported")
        self.sorgu("BEGIN")
        self._islemde = True
        self._islem_sahibi = threading.get_ident()
        try:
            yield self
        except BaseException:
            self._geri_al()
            raise
        try:
            self._calistir_islem_sonu("COMMIT")
        except BaseException:
            self._geri_al()
            raise
        finally:
            self._islemde = False
            self._islem_sahibi = None

    def _calistir_islem_sonu(self, komut):
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("the connection is in use by another thread")
        try:
            self._calistir(komut, ())
        finally:
            self._mesgul.release()

    def _geri_al(self):
        try:
            if self._conn is not None and not self._kopuk:
                self._calistir_islem_sonu("ROLLBACK")
        except PgHata:
            pass  # the real error propagates anyway; the connection is marked broken if needed
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
            with self._iptal_kilidi:
                if self._iptal is not None:
                    self._lib.PQfreeCancel(self._iptal)
                    self._iptal = None
                if self._conn is not None:
                    self._lib.PQfinish(self._conn)
                    self._conn = None
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
