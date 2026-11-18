"""PostgreSQL implementation of the scan store (ALIG-DB-003c). The SQLite store tarama/depo.py stays the default runtime;
this module has the SAME public function names and signatures and is selected explicitly (tarama/server.py: ALIG_DB_* settings,
ortak/pg_ayar.py). Standard library + ortak/pg.py (ctypes libpq).

How it fits the existing callers
* baglan(ayar) takes the dict from ortak.pg_ayar.yukle() and returns PgCon, a small connection object with the part of the sqlite3
  connection surface the store code uses: execute / executemany / commit / close / in_transaction. SQL is written with "?" placeholders;
  PgCon renames them to $1, $2 ... and runs the statement with PQexecParams (server-side binding; no value is ever put into the
  SQL text). Times go in and come out as the same "%Y-%m-%dT%H:%M:%SZ" strings the SQLite store used (columns are timestamptz, UTC).
* Outside islem() every statement is its own transaction (autocommit). Functions that write more than one row open islem() themselves
  and nest transparently, so they are atomic whether or not the caller already opened a transaction.
* A PostgreSQL connection failure raises ortak.pg.BaglantiHatasi. There is never a fallback to SQLite (docs section 9).

Locks (advisory, transaction scoped, so they are released by COMMIT/ROLLBACK or a dropped connection)
* quota:  pg_advisory_xact_lock(KILIT_KOTA, hashtext(company key digest)). kullanim_say / kullanim_tekrar / kullanim_ekle /
  kota_al take it when called inside a transaction, BEFORE counting. The lock is a separate statement from the count, so under
  READ COMMITTED the count sees every usage row committed by the previous holder. Lock + count + insert are one transaction:
  N concurrent uploads of one company can never exceed SINIR_ADET in SINIR_GUN days. (Not "remaining - 1": the model is a sliding window.)
* audit chain: pg_advisory_xact_lock(KILIT_ZINCIR, ZINCIR_TARAMA) around "read the last record + insert the next". The admin chain
  (yonetim, ALIG-DB-003d) must use the same class with objid ZINCIR_YONETIM.
Lock order used everywhere: company row -> quota -> (e-mail registration) -> audit chain. Keep it.

Not done here: the canonical audit digest format is unchanged (ozet_hesapla is imported from tarama/depo.py); pure helpers are shared
with the SQLite store until that store is removed (then they move to a shared module).
"""
import contextlib
import inspect
import json
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

from ortak import pg, pg_ayar
from tarama import saklama
from tarama import depo as _sq   # pure helpers and constants only; no SQLite connection is opened from here
from tarama.depo import token_ozeti  # noqa: F401  (imported by name: the secret scan flags 'token... = ...' assignments)

# ---- shared constants, errors and pure helpers (same objects as the SQLite store: callers' except clauses keep working) ----
SAKLAMA_GUN = _sq.SAKLAMA_GUN
SINIR_GUN = _sq.SINIR_GUN
SINIR_ADET = _sq.SINIR_ADET
ISTEK_DAKIKA = _sq.ISTEK_DAKIKA
BEKLEME_SAAT = _sq.BEKLEME_SAAT
POSTA_DENEME = _sq.POSTA_DENEME
ISTEK_DENEME = _sq.ISTEK_DENEME
ISTEK_SAATLIK = _sq.ISTEK_SAATLIK
FIRMA_DURUMLARI = _sq.FIRMA_DURUMLARI
SUREC_DURUMLARI = _sq.SUREC_DURUMLARI
SUREC_GECISLERI = _sq.SUREC_GECISLERI
ISTEK_DURUMLARI = _sq.ISTEK_DURUMLARI
TALEP_DURUMLARI = _sq.TALEP_DURUMLARI
ANAHTAR_ORTAM = _sq.ANAHTAR_ORTAM
ANAHTAR_MIN = _sq.ANAHTAR_MIN
ALAN_ANAHTARLARI = _sq.ALAN_ANAHTARLARI
ALAN_UZUNLUK = _sq.ALAN_UZUNLUK
SERBEST_POSTA = _sq.SERBEST_POSTA
EPOSTA = _sq.EPOSTA
SurecHatasi = _sq.SurecHatasi
AnahtarHatasi = _sq.AnahtarHatasi
simdi = _sq.simdi
denetim_anahtari = _sq.denetim_anahtari
alanlari_yaz = _sq.alanlari_yaz
ip_ozeti = _sq.ip_ozeti
ozet_hesapla = _sq.ozet_hesapla
denetim_metni = _sq.denetim_metni
firma_anahtari = _sq.firma_anahtari
sirket_anahtari = _sq.sirket_anahtari
belge_ozeti = _sq.belge_ozeti
_firma_ozeti = _sq._firma_ozeti
_iz_ozeti = _sq._iz_ozeti
_FIRMA_KOLON = _sq._FIRMA_KOLON
_RAPOR_KOLON = _sq._RAPOR_KOLON
_ISTEK_KOLON = _sq._ISTEK_KOLON
_ISTEK_LISTE_KOLON = _sq._ISTEK_LISTE_KOLON
_firma = _sq._firma
_rapor = _sq._rapor

BICIM = "%Y-%m-%dT%H:%M:%SZ"
KILIT_KOTA = 7431      # advisory lock class: per-company quota (objid = hashtext of the company key digest)
KILIT_ZINCIR = 7432    # advisory lock class: audit chain tails
ZINCIR_TARAMA = 1
ZINCIR_YONETIM = 2     # reserved for yonetim/depo_pg.py (ALIG-DB-003d)
KILIT_KAYIT = 7433     # advisory lock class: portal registration per e-mail address
PgHata = pg.PgHata
MESAJ_ANAHTARI = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


# ---- connection --------------------------------------------------------------------------------------------------

def _soru_isaretlerini_cevir(sql):
    """'?' placeholders (outside single-quoted literals) -> $1, $2 ... The values still travel separately."""
    cikti, n, tirnak = [], 0, False
    for ch in sql:
        if ch == "'":
            tirnak = not tirnak
        if ch == "?" and not tirnak:
            n += 1
            cikti.append("$%d" % n)
        else:
            cikti.append(ch)
    return "".join(cikti), n


_CEVIRI = {}


def _cevir(sql):
    r = _CEVIRI.get(sql)
    if r is None:
        if len(_CEVIRI) > 2000:
            _CEVIRI.clear()
        r = _CEVIRI[sql] = _soru_isaretlerini_cevir(sql)
    return r


def _deger(v):
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).strftime(BICIM)
    return v


class Sonuc:
    """What execute() returns: fetchone / fetchall / iteration / rowcount, like a sqlite3 cursor."""
    __slots__ = ("_satirlar", "rowcount", "_i")

    def __init__(self, satirlar, etkilenen):
        self._satirlar = [tuple(_deger(v) for v in r) for r in satirlar]
        self.rowcount = etkilenen if etkilenen is not None else -1
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._satirlar):
            return None
        r = self._satirlar[self._i]
        self._i += 1
        return r

    def fetchall(self):
        r = self._satirlar[self._i:]
        self._i = len(self._satirlar)
        return r

    def __iter__(self):
        while True:
            r = self.fetchone()
            if r is None:
                return
            yield r


class PgCon:
    """One PostgreSQL connection (ortak.pg.Baglanti) with the sqlite3-like surface the store code uses. One thread at a time."""

    def __init__(self, baglanti):
        self._b = baglanti
        self._islemde = False

    @property
    def in_transaction(self):
        return self._islemde

    def execute(self, sql, parametreler=()):
        metin, n = _cevir(sql)
        if n != len(parametreler):
            raise ValueError("placeholder count %d does not match parameter count %d" % (n, len(parametreler)))
        satirlar = self._b.sorgu(metin, list(parametreler))
        return Sonuc(satirlar, self._b.etkilenen)

    def executemany(self, sql, dizi):
        with islem(self):
            for p in dizi:
                self.execute(sql, p)

    def commit(self):
        """Kept so that store code written for SQLite keeps working: statements autocommit outside islem(), and islem() commits at its end."""

    def rollback(self):
        if self._islemde:
            raise RuntimeError("rollback is not called inside a transaction: raise an exception")

    def close(self):
        self._b.kapat()

    def baglanti(self):
        return self._b


def baglan(ayar):
    """ayar: dict from ortak.pg_ayar.yukle(). ortak.pg.BaglantiHatasi if PostgreSQL cannot be reached (no fallback to SQLite)."""
    if not isinstance(ayar, dict):
        raise TypeError("baglan() takes the settings dict of ortak.pg_ayar.yukle(), not a file path (got %s)" % type(ayar).__name__)
    kw = dict(ayar)
    kabul = inspect.signature(pg.Baglanti.baglan).parameters
    eksik = [k for k in kw if k not in kabul and kw[k] is not None]
    if eksik:
        raise pg_ayar.PgAyarHatasi("ortak/pg.py does not support the setting(s): %s" % ", ".join(sorted(eksik)))
    return PgCon(pg.Baglanti.baglan(**kw))


@contextlib.contextmanager
def islem(con):
    """Business action and audit record in one transaction: either both are written or neither. Nested use joins the outer transaction."""
    if con.in_transaction:
        yield con
        return
    with con._b.islem():
        con._islemde = True
        try:
            yield con
        finally:
            con._islemde = False


def _kilit_kota(con, anahtar):
    con.execute("SELECT pg_advisory_xact_lock(?, hashtext(?))", (KILIT_KOTA, anahtar))


# ---- audit chain -------------------------------------------------------------------------------------------------

def denetim_ekle(con, aktor, olay, alanlar=None):
    anahtar = denetim_anahtari()
    metin = alanlari_yaz(alanlar)
    # The last-record read and the insert happen under one advisory lock: the scan server, the admin panel and maintenance write
    # to the same chain, and an unlocked read would give two writers the same seq.
    with islem(con) as c:
        c.execute("SELECT pg_advisory_xact_lock(?, ?)", (KILIT_ZINCIR, ZINCIR_TARAMA))
        son = c.execute("SELECT seq, ozet FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()
        seq, onceki = (son[0] + 1, son[1]) if son else (1, "")
        c.execute("INSERT INTO denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) VALUES(?,?,?,?,?,?,?,?)",
                  (seq, simdi(), aktor, olay, onceki, ozet_hesapla(seq, aktor, olay, onceki, anahtar, metin), (1 if anahtar else 0) | 2, metin))


# read-only verification: plain SELECTs that run unchanged through PgCon
denetim_durum = _sq.denetim_durum
denetim_dogrula = _sq.denetim_dogrula
zincir_basi = _sq.zincir_basi


# ---- company -----------------------------------------------------------------------------------------------------

def firma_kaydet(con, anahtar, ad, eposta, kaynak, zaman=None, guncelle=True):
    """Creates the company record or (if guncelle=True) refreshes its last activity. Returns the record.
    If zaman is given the event is in the past (sync from a contact request): if the company was deleted after this event the record
    is not recreated and None is returned."""
    with islem(con) as c:
        if zaman is not None:
            iz = c.execute("SELECT silinme_utc FROM firma_silinen WHERE anahtar_sha256=?", (_iz_ozeti(anahtar),)).fetchone()
            if iz and zaman <= iz[0] and not c.execute("SELECT 1 FROM firma WHERE anahtar=?", (anahtar,)).fetchone():
                return None
        z = zaman or simdi()
        ad, eposta = (ad or "").strip()[:160], (eposta or "").strip().lower()[:200]
        # ONE atomic upsert: with "DO NOTHING + UPDATE + SELECT" a concurrent deletion of the company between the statements would
        # leave nothing to return. ON CONFLICT DO UPDATE either inserts or updates the live row (and locks it: the company row is the first
        # lock of every upload).
        if guncelle:  # the email does not change: so an unverified upload cannot take over the registered contact address
            etki = "son_utc=excluded.son_utc, ad=CASE WHEN firma.ad='' THEN excluded.ad ELSE firma.ad END"
        else:
            etki = "anahtar=firma.anahtar"
        return _firma(c.execute("INSERT INTO firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES(?,?,?,?,?,?) "
                                "ON CONFLICT (anahtar) DO UPDATE SET %s RETURNING %s" % (etki, _FIRMA_KOLON),
                                (anahtar, ad, eposta, kaynak, z, z)).fetchone())


def firma_eposta_dogrula(con, fid, eposta):
    """The address verified through the link in the email becomes the company's contact address."""
    con.execute("UPDATE firma SET eposta=?, eposta_dogrulama_utc=? WHERE id=?", ((eposta or "").strip().lower()[:200], simdi(), fid))


def esitleme_oku(con, ad):
    r = con.execute("SELECT deger FROM esitleme WHERE ad=?", (ad,)).fetchone()
    return r[0] if r else ""


def esitleme_yaz(con, ad, deger):
    con.execute("INSERT INTO esitleme(ad, deger) VALUES(?,?) ON CONFLICT(ad) DO UPDATE SET deger=excluded.deger", (ad, deger))


def firma_getir(con, fid):
    return _firma(con.execute("SELECT %s FROM firma WHERE id=?" % _FIRMA_KOLON, (fid,)).fetchone())


def firma_listele(con):
    sayim = dict(con.execute("SELECT firma_id, count(*) FROM rapor WHERE firma_id IS NOT NULL GROUP BY firma_id").fetchall())
    out = []
    for r in con.execute("SELECT %s FROM firma ORDER BY son_utc DESC, id DESC" % _FIRMA_KOLON):
        f = _firma(r)
        f["rapor_sayisi"] = sayim.get(f["id"], 0)
        out.append(f)
    return out


def firma_durum_yaz(con, fid, durum):
    if durum not in FIRMA_DURUMLARI:
        raise ValueError("status")
    return con.execute("UPDATE firma SET durum=? WHERE id=?", (durum, fid)).rowcount


def firma_surec_gecis(con, fid, yeni, aciklama=""):
    """Commercial process transition (state machine) and an optional note. Returns (old, new); None if the company does not exist.
    An invalid transition raises SurecHatasi and changes nothing. The note belongs to this transition (at most 500 characters);
    it is not written to the audit chain (it may contain personal data, and the chain cannot be deleted)."""
    with islem(con) as c:
        r = c.execute("SELECT surec FROM firma WHERE id=? FOR UPDATE", (fid,)).fetchone()   # row lock: two admins cannot both pass the same transition
        if not r:
            return None
        if yeni not in SUREC_GECISLERI.get(r[0], ()):
            raise SurecHatasi("%s -> %s" % (r[0], yeni))
        n = c.execute("UPDATE firma SET surec=?, surec_notu=?, surec_utc=? WHERE id=? AND surec=?", (yeni, (aciklama or "")[:500], simdi(), fid, r[0])).rowcount
        if n != 1:
            raise SurecHatasi("status changed in the meantime")
        return r[0], yeni


def firma_izin_yaz(con, fid, izin):
    """Direct connection (Mode B) permission. Only an administrator grants it."""
    return con.execute("UPDATE firma SET dogrudan_izin=? WHERE id=?", (bool(izin), fid)).rowcount


def firma_not_yaz(con, fid, aciklama):
    return con.execute("UPDATE firma SET aciklama=? WHERE id=?", ((aciklama or "")[:500], fid)).rowcount


def firma_sinir_sifirla(con, fid):
    with islem(con) as c:
        f = firma_getir(c, fid)
        if not f:
            return 0
        anahtar = _firma_ozeti(f)
        _kilit_kota(c, anahtar)
        return c.execute("DELETE FROM kullanim WHERE anahtar_sha256=?", (anahtar,)).rowcount


def firma_sil(con, fid):
    """Deletes the company record, its reports, its portal users and its rate counts. Returns the number of deleted reports; None if the company does not exist."""
    with islem(con) as c:
        r = c.execute("SELECT %s FROM firma WHERE id=? FOR UPDATE" % _FIRMA_KOLON, (fid,)).fetchone()   # company row first, then quota (lock order)
        f = _firma(r)
        if not f:
            return None
        anahtar = _firma_ozeti(f)
        _kilit_kota(c, anahtar)
        n = c.execute("DELETE FROM rapor WHERE firma_id=?", (fid,)).rowcount
        for tablo in ("portal_kod", "portal_oturum"):   # codes and sessions of the company's portal users
            c.execute("DELETE FROM %s WHERE kullanici_id IN (SELECT id FROM portal_kullanici WHERE firma_id=?)" % tablo, (fid,))
        c.execute("DELETE FROM portal_kullanici WHERE firma_id=?", (fid,))
        c.execute("DELETE FROM portal_talep WHERE firma_id=?", (fid,))
        c.execute("DELETE FROM kullanim WHERE anahtar_sha256=?", (anahtar,))
        c.execute("DELETE FROM baglanti_istegi WHERE firma_id=?", (fid,))
        c.execute("DELETE FROM firma WHERE id=?", (fid,))
        c.execute("INSERT INTO firma_silinen(anahtar_sha256, silinme_utc) VALUES(?,?) ON CONFLICT(anahtar_sha256) DO UPDATE SET silinme_utc=excluded.silinme_utc",
                  (_iz_ozeti(f["anahtar"]), simdi()))
        return n


# ---- Mode B requests ---------------------------------------------------------------------------------------------

def istek_ekle(con, token, firma_id, kanit, ad, ip, port, veritabani, kullanici, maskele, dil):
    n = datetime.now(timezone.utc)
    con.execute("INSERT INTO baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, maskele, dil, olusturma_utc, bitis_utc)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (token_ozeti(token), firma_id, kanit, ad, ip, port, veritabani, kullanici, bool(maskele), dil,
                 n.strftime(BICIM), (n + timedelta(minutes=ISTEK_DAKIKA)).strftime(BICIM)))


def istek_getir(con, token):
    """A pending request that has not expired; None if there is none."""
    r = con.execute("SELECT %s FROM baglanti_istegi WHERE token_sha256=? AND durum='bekliyor' AND bitis_utc > ?" % _ISTEK_KOLON,
                    (token_ozeti(token), simdi())).fetchone()
    return dict(zip(_ISTEK_KOLON.split(", "), r)) if r else None


def istek_deneme(con, iid):
    """Increments the attempt count by one (atomically) and returns the new value."""
    r = con.execute("UPDATE baglanti_istegi SET deneme=deneme+1 WHERE id=? RETURNING deneme", (iid,)).fetchone()
    return r[0] if r else None


def istek_bitir(con, iid, durum):
    con.execute("UPDATE baglanti_istegi SET durum=? WHERE id=?", (durum, iid))


def istek_listele(con, firma_id=None, durum=None, limit=25, offset=0):
    """Read-only for the admin panel: (rows, total). The token digest, ownership proof and IP are deliberately NOT returned; the password is not stored anyway."""
    kosul, arg = [], []
    if isinstance(firma_id, int) and not isinstance(firma_id, bool):
        kosul.append("i.firma_id=?")
        arg.append(firma_id)
    if durum in ISTEK_DURUMLARI:
        kosul.append("i.durum=?")
        arg.append(durum)
    nere = (" WHERE " + " AND ".join(kosul)) if kosul else ""
    toplam = con.execute("SELECT count(*) FROM baglanti_istegi i" + nere, arg).fetchone()[0]
    anahtarlar = ("id", "firma_id", "firma_ad", "ad", "port", "veritabani", "kullanici", "maskele", "deneme", "durum", "olusturma_utc", "bitis_utc")
    satirlar = [dict(zip(anahtarlar, r)) for r in con.execute(
        "SELECT %s FROM baglanti_istegi i LEFT JOIN firma f ON f.id=i.firma_id%s ORDER BY i.id DESC LIMIT ? OFFSET ?" % (_ISTEK_LISTE_KOLON, nere),
        arg + [max(1, min(int(limit), 200)), max(0, int(offset))])]
    return satirlar, toplam


def istek_say(con, firma_id, dakika=60):
    esik = (datetime.now(timezone.utc) - timedelta(minutes=dakika)).strftime(BICIM)
    return con.execute("SELECT count(*) FROM baglanti_istegi WHERE firma_id=? AND olusturma_utc > ?", (firma_id, esik)).fetchone()[0]


# ---- quota: sliding window ---------------------------------------------------------------------------------------

def _pencere_esigi(gun):
    return (datetime.now(timezone.utc) - timedelta(days=SINIR_GUN if gun is None else gun)).strftime(BICIM)


def kullanim_say(con, anahtar, gun=None):
    """Usage records of the key in the window. Inside a transaction it first takes the key's quota lock, so a following
    kullanim_ekle() in the same transaction is decided on a count nobody else can change."""
    if con.in_transaction:
        _kilit_kota(con, anahtar)
    return con.execute("SELECT count(*) FROM kullanim WHERE anahtar_sha256=? AND zaman_utc>?", (anahtar, _pencere_esigi(gun))).fetchone()[0]


def kullanim_tekrar(con, anahtar, ozet, gun=None):
    """True if the same company already uploaded the same document within the rate window (no new allowance is spent)."""
    if con.in_transaction:
        _kilit_kota(con, anahtar)
    return con.execute("SELECT 1 FROM kullanim WHERE anahtar_sha256=? AND belge_sha256=? AND zaman_utc>? LIMIT 1",
                       (anahtar, ozet, _pencere_esigi(gun))).fetchone() is not None


def kullanim_ekle(con, anahtar, ozet=None):
    if con.in_transaction:
        _kilit_kota(con, anahtar)
    con.execute("INSERT INTO kullanim(anahtar_sha256, zaman_utc, belge_sha256) VALUES(?,?,?)", (anahtar, simdi(), ozet))


def kota_al(con, anahtar, ozet=None, adet=None, gun=None):
    """Spends one free scan in ONE transaction: lock, count, insert. Returns "yeni" (spent), "tekrar" (the same document was
    already counted in the window: nothing is spent) or "asildi" (the window is full: nothing is written).
    adet / gun default to SINIR_ADET / SINIR_GUN of this module (read at call time)."""
    adet = SINIR_ADET if adet is None else adet
    with islem(con) as c:
        _kilit_kota(c, anahtar)
        if ozet is not None and kullanim_tekrar(c, anahtar, ozet, gun):
            return "tekrar"
        if kullanim_say(c, anahtar, gun) >= adet:
            return "asildi"
        kullanim_ekle(c, anahtar, ozet)
        return "yeni"


def idempotency_kaydet(con, anahtar, istek_ozeti, sonuc=""):
    """Idempotency key of an upload / scan start. Returns ("yeni", "") first time, ("ayni", stored result) for the same key with the
    same request digest (repeat: do not run the action again), ("celisiyor", "") for the same key with DIFFERENT content (reject).
    Write it in the same transaction as the business data and the audit record."""
    if not isinstance(anahtar, str) or not 1 <= len(anahtar) <= 200:
        raise ValueError("idempotency key must be 1-200 characters")
    with islem(con) as c:
        r = c.execute("INSERT INTO idempotency_anahtari(anahtar, istek_ozeti, sonuc) VALUES(?,?,?) ON CONFLICT (anahtar) DO NOTHING RETURNING anahtar",
                      (anahtar, istek_ozeti, sonuc)).fetchone()
        if r:
            return "yeni", ""
        eski = c.execute("SELECT istek_ozeti, sonuc FROM idempotency_anahtari WHERE anahtar=?", (anahtar,)).fetchone()
        if eski is None:   # deleted between the two statements
            return idempotency_kaydet(c, anahtar, istek_ozeti, sonuc)
        return ("ayni", eski[1]) if eski[0] == istek_ozeti else ("celisiyor", "")


# ---- reports -----------------------------------------------------------------------------------------------------

def rapor_ekle(con, token, motor, dil, belge, firma_id=None, eposta="", dogrulandi=True):
    """dogrulandi=False: the report is hidden until verified through the link in the email and is deleted after BEKLEME_SAAT hours."""
    n = datetime.now(timezone.utc)
    bitis = n + (timedelta(days=saklama.gun("rapor")) if dogrulandi else timedelta(hours=BEKLEME_SAAT))
    con.execute("INSERT INTO rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id, eposta, dogrulandi)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (token_ozeti(token), n.strftime(BICIM), bitis.strftime(BICIM), motor, dil,
                 json.dumps(belge, sort_keys=True), firma_id, (eposta or "").strip().lower()[:200], bool(dogrulandi)))


def rapor_getir(con, token):
    """A verified, unexpired report; None if there is none."""
    r = _rapor(con.execute("SELECT %s FROM rapor WHERE token_sha256=? AND dogrulandi" % _RAPOR_KOLON, (token_ozeti(token),)).fetchone())
    return r if r and r["bitis_utc"] > simdi() else None


def rapor_bekleyen_getir(con, token):
    """A report awaiting email verification and not yet expired; None if there is none."""
    r = _rapor(con.execute("SELECT %s FROM rapor WHERE token_sha256=? AND NOT dogrulandi" % _RAPOR_KOLON, (token_ozeti(token),)).fetchone())
    return r if r and r["bitis_utc"] > simdi() else None


def rapor_dogrula(con, rid):
    """Makes the report visible; the retention period starts at the moment of verification. 0 if it was already verified (atomic: one winner)."""
    bitis = (datetime.now(timezone.utc) + timedelta(days=saklama.gun("rapor"))).strftime(BICIM)
    return con.execute("UPDATE rapor SET dogrulandi=true, bitis_utc=? WHERE id=? AND NOT dogrulandi", (bitis, rid)).rowcount


def bekleyen_say(con, firma_id, saat=BEKLEME_SAAT):
    esik = (datetime.now(timezone.utc) - timedelta(hours=saat)).strftime(BICIM)
    return con.execute("SELECT count(*) FROM rapor WHERE firma_id=? AND NOT dogrulandi AND olusturma_utc > ?", (firma_id, esik)).fetchone()[0]


def rapor_sil(con, token):
    return con.execute("DELETE FROM rapor WHERE token_sha256=?", (token_ozeti(token),)).rowcount


def rapor_sil_id(con, rid):
    return con.execute("DELETE FROM rapor WHERE id=?", (rid,)).rowcount


def rapor_listele(con, limit=200, firma_id=None):
    kosul, arg = ("WHERE firma_id=?", (firma_id, limit)) if firma_id is not None else ("", (limit,))
    return [_rapor(r) for r in con.execute("SELECT %s FROM rapor %s ORDER BY id DESC LIMIT ?" % (_RAPOR_KOLON, kosul), arg)]


def rapor_getir_id(con, rid):
    return _rapor(con.execute("SELECT %s FROM rapor WHERE id=?" % _RAPOR_KOLON, (rid,)).fetchone())


def onceki_rapor(con, rapor):
    """Previous report for comparison: the same company's, with the same database identity (tarama/gecmis.py), the newest
    verified and unexpired report made before this scan; None if there is none. The same scan time (the same file) does not count."""
    from tarama import gecmis
    k = gecmis.kimlik(rapor.get("belge")) if rapor.get("firma_id") is not None else None
    t = rapor["belge"].get("olusturma_utc") if k else None
    if not isinstance(t, str):
        return None
    en = None
    for satir in con.execute("SELECT %s FROM rapor WHERE firma_id=? AND id<>? AND dogrulandi AND bitis_utc>?" % _RAPOR_KOLON,
                             (rapor["firma_id"], rapor.get("id", -1), simdi())).fetchall():
        try:
            r = _rapor(satir)
        except ValueError:   # a corrupt record does not enter the comparison and does not prevent this report from opening
            continue
        rt = r["belge"].get("olusturma_utc") if isinstance(r["belge"], dict) else None
        if isinstance(rt, str) and rt < t and gecmis.kimlik(r["belge"]) == k and (en is None or rt > en["belge"]["olusturma_utc"]):
            en = r
    return en


# ---- portal requests (admin view; the company view is Kapsam in tarama/portal_depo_pg.py) ------------------------

def portal_talep_listele(con, durum=None, limit=200):
    """Portal requests of all companies (admin panel only): [{id, firma_id, firma_ad, tur, konu, mesaj, durum, olusturma_utc}]."""
    kosul, arg = ("WHERE t.durum=?", (durum, int(limit))) if durum in TALEP_DURUMLARI else ("", (int(limit),))
    return [dict(zip(("id", "firma_id", "firma_ad", "tur", "konu", "mesaj", "durum", "olusturma_utc"), r)) for r in con.execute(
        "SELECT t.id, t.firma_id, f.ad, t.tur, t.konu, t.mesaj, t.durum, t.olusturma_utc FROM portal_talep t LEFT JOIN firma f ON f.id=t.firma_id "
        "%s ORDER BY t.id DESC LIMIT ?" % kosul, arg)]


def portal_talep_durum_yaz(con, tid, durum):
    """Number of affected rows (0: no such request). ValueError on an invalid status."""
    if durum not in TALEP_DURUMLARI:
        raise ValueError("invalid status")
    return con.execute("UPDATE portal_talep SET durum=?, guncelleme_utc=? WHERE id=?", (durum, simdi(), tid)).rowcount


# ---- outbox (sent by tarama/posta.py) ----------------------------------------------------------------------------

def posta_ekle(con, alici, konu, metin, anahtar=None):
    """Writes the intent to send. The row is part of the CALLER'S transaction: call it on the connection that is inside islem() together with
    the business change, and it commits or rolls back with it (outside islem() it is its own transaction). Nothing is sent here; the
    worker (tarama/posta_pg.py) sends after commit.
    anahtar: idempotency key of the message (letters, digits . _ -, up to 100). Enqueueing the same key again stores nothing and returns
    None; without a key a random one is generated. The key travels to the receiver in the message headers. Returns the new message id."""
    anahtar = secrets.token_hex(16) if anahtar is None else anahtar
    if not isinstance(anahtar, str) or not MESAJ_ANAHTARI.match(anahtar):
        raise ValueError("invalid message key")
    r = con.execute("INSERT INTO posta(alici, konu, metin, olusturma_utc, mesaj_anahtari) VALUES(?,?,?,?,?) "
                    "ON CONFLICT (mesaj_anahtari) DO NOTHING RETURNING id", (alici.strip().lower()[:200], konu, metin, simdi(), anahtar)).fetchone()
    return r[0] if r else None


def posta_say(con, alici, saat=24):
    esik = (datetime.now(timezone.utc) - timedelta(hours=saat)).strftime(BICIM)
    return con.execute("SELECT count(*) FROM posta WHERE alici=? AND olusturma_utc > ?", ((alici or "").strip().lower(), esik)).fetchone()[0]


def posta_bekleyenler(con, en_cok=20):
    return con.execute("SELECT id, alici, konu, metin, deneme FROM posta WHERE durum='bekliyor' ORDER BY id LIMIT ?", (en_cok,)).fetchall()


def posta_sonuc(con, pid, hata=None, deneme_siniri=POSTA_DENEME):
    """If sent, the text is deleted (the link is secret). On failure the attempt count rises; at the limit it gives up and the text is still deleted."""
    with islem(con) as c:
        if hata is None:
            c.execute("UPDATE posta SET durum='gonderildi', metin='', gonderim_utc=?, son_hata='' WHERE id=?", (simdi(), pid))
        else:
            c.execute("UPDATE posta SET deneme=deneme+1, son_hata=? WHERE id=?", (str(hata)[:200], pid))
            c.execute("UPDATE posta SET durum='basarisiz', metin='' WHERE id=? AND deneme >= ?", (pid, deneme_siniri))


# ---- retention ---------------------------------------------------------------------------------------------------

def saklama_uygula(con, simdi_=None):
    """Applies the company record retention period: if the period has passed since last activity and there is no active report, the company is deleted.
    Every deletion is written to the audit chain (the company name and email are not written). Returns the number of deleted companies."""
    g = saklama.gun("firma")
    if g is None:
        return 0
    esik = ((simdi_ or datetime.now(timezone.utc)) - timedelta(days=g)).strftime(BICIM)
    adaylar = con.execute("SELECT id FROM firma WHERE son_utc <= ? AND NOT EXISTS (SELECT 1 FROM rapor WHERE rapor.firma_id=firma.id AND rapor.bitis_utc > ?)",
                          (esik, simdi())).fetchall()
    for (fid,) in adaylar:
        with islem(con) as c:   # deletion and audit record together
            firma_sil(c, fid)
            denetim_ekle(c, "sistem", "saklama suresi doldu, firma #%d silindi" % fid)
    tg = saklama.gun("talep")
    if tg is not None:  # no request older than this date remains, so the trace is no longer needed either
        con.execute("DELETE FROM firma_silinen WHERE silinme_utc <= ?", (((simdi_ or datetime.now(timezone.utc)) - timedelta(days=tg)).strftime(BICIM),))
    return len(adaylar)


def suresi_dolanlari_sil(con):
    with islem(con) as c:
        n = c.execute("DELETE FROM rapor WHERE bitis_utc <= ?", (simdi(),)).rowcount
        c.execute("DELETE FROM kullanim WHERE zaman_utc <= ?", (_pencere_esigi(None),))
        c.execute("DELETE FROM baglanti_istegi WHERE bitis_utc <= ?", ((datetime.now(timezone.utc) - timedelta(days=1)).strftime(BICIM),))
        pg_ = (datetime.now(timezone.utc) - timedelta(days=saklama.gun("posta"))).strftime(BICIM)
        c.execute("DELETE FROM posta WHERE olusturma_utc <= ? AND durum IN ('gonderildi', 'basarisiz')", (pg_,))
        return n


# ---- command line: chain verification against PostgreSQL ---------------------------------------------------------

def _komut(argv):
    """python3 -m tarama.depo_pg dogrula [--bas file.json] | bas   (connection: ALIG_DB_*; key: ALIG_DENETIM_ANAHTARI)"""
    try:
        ayar = pg_ayar.yukle()
        if ayar is None:
            print("error: PostgreSQL is not configured (ALIG_DB_HOST ...)", file=sys.stderr)
            return 2
        con = baglan(ayar)
    except (pg_ayar.PgAyarHatasi, pg.PgHata) as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 2
    try:
        if argv[1:] == ["bas"]:
            bas = zincir_basi(con)
            if bas is None:
                print("chain is empty", file=sys.stderr)
                return 1
            print(json.dumps(bas, sort_keys=True))
            return 0
        if argv[1:2] == ["dogrula"] and (len(argv) == 2 or (len(argv) == 4 and argv[2] == "--bas")):
            try:
                bas = json.load(open(argv[3], encoding="utf-8")) if len(argv) == 4 else None
                durum = denetim_durum(con, denetim_anahtari(), bas)
            except (AnahtarHatasi, OSError, ValueError, KeyError, TypeError) as ex:
                print("error: %s" % ex, file=sys.stderr)
                return 2
            print("denetim zinciri %s" % denetim_metni(durum))
            return 0 if durum["bozuk"] is None and not durum["dogrulanamayan"] else 1
        print(_komut.__doc__)
        return 2
    finally:
        con.close()


if __name__ == "__main__":   # python3 -m tarama.depo_pg ...
    sys.exit(_komut(sys.argv))
