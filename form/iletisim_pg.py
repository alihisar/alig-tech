"""PostgreSQL implementation of the contact form store (ALIG-DB-003e). Standard library only; uses ortak/pg.py.

The SQLite store in form/server.py stays the default. form/server.py dispatches to this module only when PostgreSQL is configured
(ortak/pg_ayar.py) and passes an IletisimPg object as `pg`; there is NO silent fallback to SQLite in that mode: a PostgreSQL failure
is a controlled 503 + Retry-After (docs/postgresql-gecis.md section 9).

- IletisimPg.kaydet(): one parameterised INSERT into alig.contact (the application role has INSERT/SELECT/DELETE there).
- IletisimPg.saglik(): readiness probe (a connection and a trivial query).
- FormSinir: the form's RateLimiter interface (allow(key)) on top of ortak.sinir_pg.SinirPg (atomic counter in PostgreSQL);
  tekrar_sn() gives the Retry-After seconds of the last rejection in the calling thread."""
import threading
from datetime import datetime, timezone

from ortak import pg
from ortak.pg_havuz import Havuz
from ortak.sinir_pg import SinirPg

__all__ = ["IletisimPg", "FormSinir"]

_EKLE = ("INSERT INTO alig.contact(created_utc, name, company, email, db, message, ip_hash) "
         "VALUES($1, $2, $3, $4, $5, $6, $7)")


class IletisimPg:
    def __init__(self, baglan):
        """baglan: a zero-argument callable returning a new ortak.pg.Baglanti (pooled)."""
        self._havuz = Havuz(baglan)

    def kaydet(self, veri, ip_ozeti):
        """Inserts one contact request (veri: the validated dict from form/server.py validate()). Raises pg.PgHata on failure."""
        with self._havuz.kullan() as b:
            b.sorgu(_EKLE, [datetime.now(timezone.utc), veri["name"], veri["company"], veri["email"], veri["db"],
                            veri["message"], ip_ozeti])

    def saglik(self):
        try:
            with self._havuz.kullan() as b:
                b.sorgu("SELECT 1")
            return True
        except pg.PgHata:
            return False

    def kapat(self):
        self._havuz.kapat()


class FormSinir:
    """RateLimiter-compatible (allow(key) -> bool) wrapper over the PostgreSQL counter, bucket 'iletisim'. Raises pg.PgHata if the
    database is unusable (form/server.py answers 503)."""

    def __init__(self, sinir, kova="iletisim"):
        if not isinstance(sinir, SinirPg):
            raise TypeError("sinir must be an ortak.sinir_pg.SinirPg")
        self.sinir, self.kova = sinir, kova
        self._yerel = threading.local()

    def allow(self, key):
        s = self.sinir.kontrol(self.kova, key)
        self._yerel.tekrar = s.tekrar_sn
        return s.izin

    def tekrar_sn(self):
        return max(1, getattr(self._yerel, "tekrar", 0) or 1)
