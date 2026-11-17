"""A small bounded connection pool for ortak/pg.py (ALIG-DB-003e). Standard library only.

ortak/pg.py connections are not shared between threads at the same time, and ThreadingHTTPServer starts a NEW thread for every request, so
a per-thread connection would reconnect on every request and leak. Havuz checks a connection out for the duration of a `with` block (one
thread at a time), puts it back afterwards and keeps at most `azami` connections open: more concurrent users wait up to `bekleme_sn` and then
get BaglantiHatasi (the caller answers 503). A connection that is broken, or that raised a connection error, is closed and not returned.
A statement is never retried here."""
import threading
from contextlib import contextmanager

from ortak import pg

__all__ = ["Havuz"]


class Havuz:
    def __init__(self, baglan, azami=8, bekleme_sn=10.0):
        """baglan: a zero-argument callable returning a new ortak.pg.Baglanti."""
        if not callable(baglan):
            raise TypeError("baglan must be a callable returning a Baglanti")
        if azami < 1:
            raise ValueError("azami must be >= 1")
        self._baglan, self._bekleme = baglan, bekleme_sn
        self._yer = threading.BoundedSemaphore(azami)
        self._kilit = threading.Lock()
        self._bosta = []
        self._kapali = False

    @contextmanager
    def kullan(self):
        if not self._yer.acquire(timeout=self._bekleme):
            raise pg.BaglantiHatasi("connection pool exhausted")
        b = None
        try:
            with self._kilit:
                if self._kapali:
                    raise pg.BaglantiHatasi("connection pool is closed")
                while self._bosta and b is None:
                    c = self._bosta.pop()
                    if c.kopuk:
                        self._kapat(c)
                    else:
                        b = c
            if b is None:
                b = self._baglan()
            try:
                yield b
            except pg.BaglantiHatasi:
                self._kapat(b)
                b = None
                raise
        finally:
            if b is not None:
                if b.kopuk or b.islemde:
                    self._kapat(b)
                else:
                    with self._kilit:
                        kapali = self._kapali
                        if not kapali:
                            self._bosta.append(b)
                    if kapali:
                        self._kapat(b)
            self._yer.release()

    @staticmethod
    def _kapat(b):
        try:
            b.kapat()
        except pg.PgHata:
            pass

    def kapat(self):
        """Closes the idle connections and refuses new checkouts (connections still checked out are closed when they come back)."""
        with self._kilit:
            self._kapali = True
            bosta, self._bosta = self._bosta, []
        for b in bosta:
            self._kapat(b)
