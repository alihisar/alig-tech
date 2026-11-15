"""SQLite (WAL) store and chained audit log (HMAC-SHA-256 if a key is set, otherwise SHA-256). Times are UTC.
Verification: python3 tarama/depo.py dogrula <db> [--bas file.json]; chain head: python3 tarama/depo.py bas <db>"""
import contextlib
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from tarama import saklama
except ImportError:  # when run directly with python3 tarama/depo.py
    import saklama

SAKLAMA_GUN = 30  # default; the actual period is read from tarama/saklama.py
SINIR_GUN = 30
SINIR_ADET = 2  # number of free scans: [doldurulacak: onay] (to be filled in: approval)
GOCLER = [
    """CREATE TABLE rapor(id INTEGER PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, olusturma_utc TEXT NOT NULL,
       bitis_utc TEXT NOT NULL, motor TEXT NOT NULL, dil TEXT NOT NULL, belge_json TEXT NOT NULL)""",
    """CREATE TABLE denetim(seq INTEGER PRIMARY KEY, zaman_utc TEXT NOT NULL, aktor TEXT NOT NULL, olay TEXT NOT NULL,
       onceki TEXT NOT NULL, ozet TEXT NOT NULL)""",
    """CREATE TABLE kullanim(id INTEGER PRIMARY KEY, anahtar_sha256 TEXT NOT NULL, zaman_utc TEXT NOT NULL)""",
    """CREATE INDEX kullanim_anahtar ON kullanim(anahtar_sha256, zaman_utc)""",
    """CREATE TABLE firma(id INTEGER PRIMARY KEY, anahtar TEXT NOT NULL UNIQUE, ad TEXT NOT NULL, eposta TEXT NOT NULL,
       durum TEXT NOT NULL DEFAULT 'aktif', kaynak TEXT NOT NULL, aciklama TEXT NOT NULL DEFAULT '',
       kayit_utc TEXT NOT NULL, son_utc TEXT NOT NULL)""",
    """ALTER TABLE rapor ADD COLUMN firma_id INTEGER""",
    """ALTER TABLE firma ADD COLUMN dogrudan_izin INTEGER NOT NULL DEFAULT 0""",
    # Mode B (direct connection) request. The password is NEVER stored; only the target and the ownership proof.
    """CREATE TABLE baglanti_istegi(id INTEGER PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, firma_id INTEGER NOT NULL,
       kanit TEXT NOT NULL, ad TEXT NOT NULL, ip TEXT NOT NULL, port INTEGER NOT NULL, veritabani TEXT NOT NULL,
       kullanici TEXT NOT NULL, maskele INTEGER NOT NULL DEFAULT 0, dil TEXT NOT NULL, olusturma_utc TEXT NOT NULL,
       bitis_utc TEXT NOT NULL, deneme INTEGER NOT NULL DEFAULT 0, durum TEXT NOT NULL DEFAULT 'bekliyor')""",
    # keyed audit chain: 0 = old SHA-256 record, 1 = HMAC-SHA-256 (ALIG_DENETIM_ANAHTARI)
    """ALTER TABLE denetim ADD COLUMN mod INTEGER NOT NULL DEFAULT 0""",
    # so the same file does not spend a second allowance: the digest of the document (content is not stored)
    """ALTER TABLE kullanim ADD COLUMN belge_sha256 TEXT""",
    # structured fields (company, target, result...): included in the digest, therefore cannot be altered
    """ALTER TABLE denetim ADD COLUMN alanlar TEXT NOT NULL DEFAULT ''""",
    # trace of a deleted company: so it is not recreated by itself from an old request (contact form). A digest is kept, not the plain key.
    """CREATE TABLE firma_silinen(anahtar_sha256 TEXT PRIMARY KEY, silinme_utc TEXT NOT NULL)""",
    # email verification (ALIG_EPOSTA_DOGRULAMA): uploader address on the report, unverified report hidden, company verification time
    """ALTER TABLE rapor ADD COLUMN eposta TEXT NOT NULL DEFAULT ''""",
    """ALTER TABLE rapor ADD COLUMN dogrulandi INTEGER NOT NULL DEFAULT 1""",
    """ALTER TABLE firma ADD COLUMN eposta_dogrulama_utc TEXT""",
    # outbox: the web process does not reach the network; a separate mail service sends; the text is deleted once sent
    """CREATE TABLE posta(id INTEGER PRIMARY KEY, alici TEXT NOT NULL, konu TEXT NOT NULL, metin TEXT NOT NULL,
       olusturma_utc TEXT NOT NULL, deneme INTEGER NOT NULL DEFAULT 0, durum TEXT NOT NULL DEFAULT 'bekliyor',
       son_hata TEXT NOT NULL DEFAULT '', gonderim_utc TEXT)""",
    """CREATE INDEX posta_alici ON posta(alici, olusturma_utc)""",
    # where the company sync from contact requests left off (so that only new requests are processed)
    """CREATE TABLE esitleme(ad TEXT PRIMARY KEY, deger TEXT NOT NULL)""",
    # company and report ids must not be reused after deletion (AUTOINCREMENT): "#N" in the audit always points to the same record.
    # SQLite needs a rebuild; the steps run in goc_uygula's single transaction, and if it stops halfway none are applied.
    """CREATE TABLE firma_yeni(id INTEGER PRIMARY KEY AUTOINCREMENT, anahtar TEXT NOT NULL UNIQUE, ad TEXT NOT NULL, eposta TEXT NOT NULL,
       durum TEXT NOT NULL DEFAULT 'aktif', kaynak TEXT NOT NULL, aciklama TEXT NOT NULL DEFAULT '', kayit_utc TEXT NOT NULL,
       son_utc TEXT NOT NULL, dogrudan_izin INTEGER NOT NULL DEFAULT 0, eposta_dogrulama_utc TEXT)""",
    """INSERT INTO firma_yeni(id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc, dogrudan_izin, eposta_dogrulama_utc)
       SELECT id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc, dogrudan_izin, eposta_dogrulama_utc FROM firma""",
    """DROP TABLE firma""",
    """ALTER TABLE firma_yeni RENAME TO firma""",
    """CREATE TABLE rapor_yeni(id INTEGER PRIMARY KEY AUTOINCREMENT, token_sha256 TEXT NOT NULL UNIQUE, olusturma_utc TEXT NOT NULL,
       bitis_utc TEXT NOT NULL, motor TEXT NOT NULL, dil TEXT NOT NULL, belge_json TEXT NOT NULL, firma_id INTEGER,
       eposta TEXT NOT NULL DEFAULT '', dogrulandi INTEGER NOT NULL DEFAULT 1)""",
    """INSERT INTO rapor_yeni(id, token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id, eposta, dogrulandi)
       SELECT id, token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id, eposta, dogrulandi FROM rapor""",
    """DROP TABLE rapor""",
    """ALTER TABLE rapor_yeni RENAME TO rapor""",
    # customer portal (ALIG_PORTAL): company user, email verification code, session, login attempt. Separate tables and a separate
    # identity from the platform administrator (yonetim.sqlite). A verified user has a company (CHECK); an unverified one does not.
    """CREATE TABLE portal_kullanici(id INTEGER PRIMARY KEY AUTOINCREMENT, firma_id INTEGER, eposta TEXT NOT NULL UNIQUE,
       parola TEXT NOT NULL, durum TEXT NOT NULL DEFAULT 'bekliyor', dil TEXT NOT NULL DEFAULT 'tr', sirket TEXT NOT NULL DEFAULT '',
       kayit_utc TEXT NOT NULL, dogrulama_utc TEXT, son_giris_utc TEXT,
       CHECK (durum IN ('bekliyor', 'aktif') AND (durum = 'bekliyor' OR firma_id IS NOT NULL)))""",
    """CREATE INDEX portal_kullanici_firma ON portal_kullanici(firma_id)""",
    """CREATE TABLE portal_kod(kod_sha256 TEXT PRIMARY KEY, kullanici_id INTEGER NOT NULL, bitis_utc TEXT NOT NULL)""",
    """CREATE TABLE portal_oturum(kod_sha256 TEXT PRIMARY KEY, kullanici_id INTEGER NOT NULL, csrf TEXT NOT NULL,
       olusturma_utc TEXT NOT NULL, son_erisim_utc TEXT NOT NULL)""",
    """CREATE TABLE portal_deneme(id INTEGER PRIMARY KEY, anahtar TEXT NOT NULL, zaman_utc TEXT NOT NULL)""",
    """CREATE INDEX portal_deneme_anahtar ON portal_deneme(anahtar, zaman_utc)""",
    # portal requests: service request (audit, support, other) and account/data deletion request (silme). A deletion request is only recorded;
    # identity verification and deletion are an administrator action (panel). One open deletion request per company.
    """CREATE TABLE portal_talep(id INTEGER PRIMARY KEY AUTOINCREMENT, firma_id INTEGER NOT NULL, kullanici_id INTEGER NOT NULL,
       tur TEXT NOT NULL CHECK (tur IN ('denetim', 'destek', 'diger', 'silme')), konu TEXT NOT NULL DEFAULT '', mesaj TEXT NOT NULL DEFAULT '',
       durum TEXT NOT NULL DEFAULT 'yeni' CHECK (durum IN ('yeni', 'inceleniyor', 'tamamlandi', 'reddedildi')),
       olusturma_utc TEXT NOT NULL, guncelleme_utc TEXT NOT NULL)""",
    """CREATE INDEX portal_talep_firma ON portal_talep(firma_id, olusturma_utc)""",
    """CREATE UNIQUE INDEX portal_talep_acik_silme ON portal_talep(firma_id) WHERE tur='silme' AND durum IN ('yeni', 'inceleniyor')""",
    # commercial process (admin panel): status and note per company. Only status and note; no price, amount or customer name.
    # Deleted together with the company row (firma_sil, saklama_uygula): the note may contain personal data.
    """ALTER TABLE firma ADD COLUMN surec TEXT NOT NULL DEFAULT 'aday'""",
    """ALTER TABLE firma ADD COLUMN surec_notu TEXT NOT NULL DEFAULT ''""",
    """ALTER TABLE firma ADD COLUMN surec_utc TEXT""",
]
ISTEK_DAKIKA = 30
BEKLEME_SAAT = 24      # a report not verified by email is deleted after this period
POSTA_DENEME = 5       # maximum attempts on a transient error
ISTEK_DENEME = 3
ISTEK_SAATLIK = 5
FIRMA_DURUMLARI = ("aktif", "pasif")
# commercial process: aday (lead) -> gorusuluyor (in talks) -> teklif (offer) -> musteri (customer); from any status -> kapandi (closed; kapandi is the final status)
SUREC_DURUMLARI = ("aday", "gorusuluyor", "teklif", "musteri", "kapandi")
SUREC_GECISLERI = {"aday": ("gorusuluyor", "kapandi"), "gorusuluyor": ("teklif", "kapandi"), "teklif": ("musteri", "kapandi"),
                   "musteri": ("kapandi",), "kapandi": ()}


class SurecHatasi(ValueError):
    """Invalid commercial process transition."""


def simdi():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def goc_uygula(con, gocler):
    """Forward-only migration. Several processes may start at the same time (scan, admin, maintenance; on a new release
    all restart): the migration runs under a single write lock and the version is re-read inside the lock."""
    if con.execute("PRAGMA user_version").fetchone()[0] >= len(gocler):
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        surum = con.execute("PRAGMA user_version").fetchone()[0]
        for i in range(surum, len(gocler)):
            con.execute(gocler[i])
            con.execute("PRAGMA user_version=%d" % (i + 1))
        con.commit()
    except BaseException:
        con.rollback()
        raise


class _IslemIcinde:
    """Connection wrapper that defers the commit for the duration of an outer transaction. Store functions call their own commits;
    the real commit happens once when the transaction ends, and on an exception everything is rolled back."""
    in_transaction = True

    def __init__(self, con):
        self._con = con

    def execute(self, *a, **k):
        return self._con.execute(*a, **k)

    def executemany(self, *a, **k):
        return self._con.executemany(*a, **k)

    def commit(self):
        pass

    def rollback(self):
        raise RuntimeError("rollback is not called inside a transaction: raise an exception")

    def __getattr__(self, ad):
        return getattr(self._con, ad)


@contextlib.contextmanager
def islem(con):
    """Business action and audit record in one transaction: either both are written or neither. The write lock is taken up front."""
    if isinstance(con, _IslemIcinde):
        yield con
        return
    if con.in_transaction:
        con.commit()
    con.execute("BEGIN IMMEDIATE")
    try:
        yield _IslemIcinde(con)
    except BaseException:
        con.rollback()
        raise
    con.commit()


def wal_ac(con, deneme=50):
    """Switching to WAL mode needs a brief exclusive lock on first open; on concurrent opens it waits until the lock is free."""
    for i in range(deneme):
        try:
            con.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as ex:
            if "locked" not in str(ex) or i == deneme - 1:
                raise
            time.sleep(0.1)


def baglan(yol):
    con = sqlite3.connect(yol, timeout=10)
    wal_ac(con)
    goc_uygula(con, GOCLER)
    return con


def token_ozeti(token):
    return hashlib.sha256(token.encode()).hexdigest()


ANAHTAR_ORTAM = "ALIG_DENETIM_ANAHTARI"
ANAHTAR_MIN = 32


class AnahtarHatasi(ValueError):
    pass


def denetim_anahtari(ortam=None):
    """The audit key (bytes) from the environment, or None if undefined. A short key is not silently accepted."""
    ham = (os.environ if ortam is None else ortam).get(ANAHTAR_ORTAM, "")
    if not ham:
        return None
    if len(ham) < ANAHTAR_MIN:
        raise AnahtarHatasi("%s must be at least %d characters" % (ANAHTAR_ORTAM, ANAHTAR_MIN))
    return ham.encode()


ALAN_ANAHTARLARI = ("firma", "hedef", "motor", "sonuc", "neden", "ip_ozeti", "yeni_ip", "rapor", "talep", "kullanici")
ALAN_UZUNLUK = 120


def alanlari_yaz(alanlar):
    """Converts structured fields to canonical JSON text: only allowed keys, short plain values. '' if empty."""
    if not alanlar:
        return ""
    temiz = {}
    for k in ALAN_ANAHTARLARI:
        if k in alanlar and alanlar[k] is not None:
            v = alanlar[k]
            temiz[k] = v if isinstance(v, int) and not isinstance(v, bool) else str(v)[:ALAN_UZUNLUK]
    return json.dumps(temiz, sort_keys=True, separators=(",", ":"), ensure_ascii=False) if temiz else ""


def ip_ozeti(ip, anahtar=None):
    """Shortened digest of the IP (the plain address is not written to the audit). With a key it is an HMAC: a dictionary attack is impossible without the key."""
    ham = ("ip|" + str(ip)).encode()
    if anahtar is None:
        anahtar = denetim_anahtari()
    d = hmac.new(anahtar, ham, hashlib.sha256) if anahtar else hashlib.sha256(ham)
    return d.hexdigest()[:16]


def ozet_hesapla(seq, aktor, olay, onceki, anahtar=None, alanlar=None):
    """SHA-256 without a key, HMAC-SHA-256 with one (separate prefix). If alanlar is None, the old (fieldless) form; if text, it is included in the digest."""
    parcalar = [str(seq), aktor, olay, onceki] + ([] if alanlar is None else [alanlar])
    if anahtar is None:
        return hashlib.sha256("|".join(parcalar).encode()).hexdigest()
    return hmac.new(anahtar, "|".join(["k"] + parcalar).encode(), hashlib.sha256).hexdigest()


def denetim_ekle(con, aktor, olay, alanlar=None):
    anahtar = denetim_anahtari()
    metin = alanlari_yaz(alanlar)
    # Reading the last record and appending must happen under the same write lock: the scan server, the admin panel and maintenance all write
    # to the same chain; with an unlocked read two writers get the same seq and one loses its record to an IntegrityError.
    # If a transaction is open the connection already holds the write lock (the transaction began with a write).
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    son = con.execute("SELECT seq, ozet FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()
    seq, onceki = (son[0] + 1, son[1]) if son else (1, "")
    # mode: bit0 = HMAC, bit1 = structured fields included in the digest
    con.execute("INSERT INTO denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) VALUES(?,?,?,?,?,?,?,?)",
                (seq, simdi(), aktor, olay, onceki, ozet_hesapla(seq, aktor, olay, onceki, anahtar, metin), (1 if anahtar else 0) | 2, metin))
    con.commit()


def denetim_durum(con, anahtar=None, bas=None):
    """Detailed state of the chain.
    bozuk: seq of the first broken record, or None. Breakage: broken link, digest mismatch, a keyless record after
      keyed records (downgrade), an HMAC mismatch while a key is present, or a missing exported chain head.
    dogrulanamayan: number of keyed records whose HMAC could not be checked because no key was given.
    bas: {"seq", "ozet"} (a previously exported chain head) or None."""
    onceki, anahtarli_goruldu, alanli_goruldu, kayit, dogrulanamayan, bozuk, son = "", False, False, 0, 0, None, None
    gorulen = {}
    for seq, aktor, olay, on, oz, mod, alanlar in con.execute("SELECT seq, aktor, olay, onceki, ozet, mod, alanlar FROM denetim ORDER BY seq"):
        kayit += 1
        gorulen[seq] = oz
        son = (seq, oz)
        if bozuk is not None:
            continue
        hmac_mi, alanli_mi = bool(mod & 1), bool(mod & 2)
        if on != onceki or mod not in (0, 1, 2, 3):
            bozuk = seq
        elif not alanli_mi and (alanli_goruldu or alanlar):  # downgrade: a record without fields, or one with the field but not included in the digest
            bozuk = seq
        elif hmac_mi:
            anahtarli_goruldu = True
            if anahtar is None:
                dogrulanamayan += 1
            elif not hmac.compare_digest(oz, ozet_hesapla(seq, aktor, olay, on, anahtar, alanlar if alanli_mi else None)):
                bozuk = seq
        elif anahtarli_goruldu or not hmac.compare_digest(oz, ozet_hesapla(seq, aktor, olay, on, None, alanlar if alanli_mi else None)):
            bozuk = seq
        alanli_goruldu = alanli_goruldu or alanli_mi
        onceki = oz
    if bozuk is None and bas is not None and gorulen.get(bas["seq"]) != bas["ozet"]:
        bozuk = bas["seq"]
    return {"bozuk": bozuk, "kayit": kayit, "dogrulanamayan": dogrulanamayan, "anahtarli": anahtarli_goruldu, "son": son}


def denetim_dogrula(con, anahtar=None):
    """seq of the first broken record, None if sound. If no key is given, the key from the environment is used."""
    return denetim_durum(con, anahtar if anahtar is not None else denetim_anahtari())["bozuk"]


def denetim_metni(durum):
    """One-line status for the panel and the CLI."""
    if durum["bozuk"] is not None:
        return "KIRIK: kayıt #%d" % durum["bozuk"]
    if durum["dogrulanamayan"]:
        return "bağlantı sağlam, ancak %d anahtarlı kayıt anahtar olmadan doğrulanamadı" % durum["dogrulanamayan"]
    return "sağlam (anahtarlı)" if durum["anahtarli"] else "sağlam (anahtarsız kayıtlar)"


def zincir_basi(con):
    """Chain head to be exported: seq and digest of the last record. None for an empty chain."""
    son = con.execute("SELECT seq, zaman_utc, ozet FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()
    return {"seq": son[0], "zaman_utc": son[1], "ozet": son[2]} if son else None


SERBEST_POSTA = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "yandex.com",
                 "icloud.com", "proton.me", "protonmail.com", "hotmail.com.tr", "yahoo.com.tr", "mynet.com"}
EPOSTA = re.compile(r"^[^@\s]{1,64}@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)$")


def firma_anahtari(eposta):
    """Plain key that identifies the company: the domain for a corporate address, the full address for a free mail provider. None if invalid."""
    m = EPOSTA.match(eposta.strip()) if isinstance(eposta, str) and len(eposta) <= 200 else None
    if not m:
        return None
    alan = m.group(1).lower()
    return eposta.strip().lower() if alan in SERBEST_POSTA else alan


def sirket_anahtari(eposta):
    """SHA-256 digest of the key, for rate counting. None if invalid."""
    ham = firma_anahtari(eposta)
    return hashlib.sha256(("sirket|" + ham).encode()).hexdigest() if ham else None


_FIRMA_KOLON = ("id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc, dogrudan_izin, eposta_dogrulama_utc, "
                "surec, surec_notu, surec_utc")


def _firma(r):
    return dict(zip(_FIRMA_KOLON.split(", "), r)) if r else None


def _iz_ozeti(anahtar):
    return hashlib.sha256(("silinen|" + anahtar).encode()).hexdigest()


def firma_kaydet(con, anahtar, ad, eposta, kaynak, zaman=None, guncelle=True):
    """Creates the company record or (if guncelle=True) refreshes its last activity. Returns the record.
    If zaman is given the event is in the past (sync from a contact request): if the company was deleted after this event the record
    is not recreated and None is returned."""
    if zaman is not None:
        iz = con.execute("SELECT silinme_utc FROM firma_silinen WHERE anahtar_sha256=?", (_iz_ozeti(anahtar),)).fetchone()
        if iz and zaman <= iz[0] and not con.execute("SELECT 1 FROM firma WHERE anahtar=?", (anahtar,)).fetchone():
            return None
    z = zaman or simdi()
    ad, eposta = (ad or "").strip()[:160], (eposta or "").strip().lower()[:200]
    con.execute("INSERT OR IGNORE INTO firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES(?,?,?,?,?,?)", (anahtar, ad, eposta, kaynak, z, z))
    if guncelle:  # the email does not change: so an unverified upload cannot take over the registered contact address
        con.execute("UPDATE firma SET son_utc=?, ad=CASE WHEN ad='' THEN ? ELSE ad END WHERE anahtar=?", (z, ad, anahtar))
    con.commit()
    return _firma(con.execute("SELECT %s FROM firma WHERE anahtar=?" % _FIRMA_KOLON, (anahtar,)).fetchone())


def firma_eposta_dogrula(con, fid, eposta):
    """The address verified through the link in the email becomes the company's contact address."""
    con.execute("UPDATE firma SET eposta=?, eposta_dogrulama_utc=? WHERE id=?", ((eposta or "").strip().lower()[:200], simdi(), fid))
    con.commit()


def esitleme_oku(con, ad):
    r = con.execute("SELECT deger FROM esitleme WHERE ad=?", (ad,)).fetchone()
    return r[0] if r else ""


def esitleme_yaz(con, ad, deger):
    con.execute("INSERT INTO esitleme(ad, deger) VALUES(?,?) ON CONFLICT(ad) DO UPDATE SET deger=excluded.deger", (ad, deger))
    con.commit()


def firma_getir(con, fid):
    return _firma(con.execute("SELECT %s FROM firma WHERE id=?" % _FIRMA_KOLON, (fid,)).fetchone())


def firma_listele(con):
    sayim = dict(con.execute("SELECT firma_id, count(*) FROM rapor WHERE firma_id IS NOT NULL GROUP BY firma_id").fetchall())
    out = []
    for r in con.execute("SELECT %s FROM firma ORDER BY son_utc DESC" % _FIRMA_KOLON):
        f = _firma(r)
        f["rapor_sayisi"] = sayim.get(f["id"], 0)
        out.append(f)
    return out


def firma_durum_yaz(con, fid, durum):
    if durum not in FIRMA_DURUMLARI:
        raise ValueError("status")
    n = con.execute("UPDATE firma SET durum=? WHERE id=?", (durum, fid)).rowcount
    con.commit()
    return n


def firma_surec_gecis(con, fid, yeni, aciklama=""):
    """Commercial process transition (state machine) and an optional note. Returns (old, new); None if the company does not exist.
    An invalid transition raises SurecHatasi and changes nothing. The note belongs to this transition (at most 500 characters);
    it is not written to the audit chain (it may contain personal data, and the chain cannot be deleted)."""
    r = con.execute("SELECT surec FROM firma WHERE id=?", (fid,)).fetchone()
    if not r:
        return None
    if yeni not in SUREC_GECISLERI.get(r[0], ()):
        raise SurecHatasi("%s -> %s" % (r[0], yeni))
    n = con.execute("UPDATE firma SET surec=?, surec_notu=?, surec_utc=? WHERE id=? AND surec=?", (yeni, (aciklama or "")[:500], simdi(), fid, r[0])).rowcount
    if n != 1:
        raise SurecHatasi("status changed in the meantime")
    con.commit()
    return r[0], yeni


def firma_izin_yaz(con, fid, izin):
    """Direct connection (Mode B) permission. Only an administrator grants it."""
    n = con.execute("UPDATE firma SET dogrudan_izin=? WHERE id=?", (1 if izin else 0, fid)).rowcount
    con.commit()
    return n


_ISTEK_KOLON = "id, firma_id, kanit, ad, ip, port, veritabani, kullanici, maskele, dil, olusturma_utc, bitis_utc, deneme, durum"


def istek_ekle(con, token, firma_id, kanit, ad, ip, port, veritabani, kullanici, maskele, dil):
    n = datetime.now(timezone.utc)
    con.execute("INSERT INTO baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, maskele, dil, olusturma_utc, bitis_utc)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (token_ozeti(token), firma_id, kanit, ad, ip, port, veritabani, kullanici, 1 if maskele else 0, dil,
                 n.strftime("%Y-%m-%dT%H:%M:%SZ"), (n + timedelta(minutes=ISTEK_DAKIKA)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    con.commit()


def istek_getir(con, token):
    """A pending request that has not expired; None if there is none."""
    r = con.execute("SELECT %s FROM baglanti_istegi WHERE token_sha256=? AND durum='bekliyor' AND bitis_utc > ?" % _ISTEK_KOLON,
                    (token_ozeti(token), simdi())).fetchone()
    return dict(zip(_ISTEK_KOLON.split(", "), r)) if r else None


def istek_deneme(con, iid):
    """Increments the attempt count by one and returns the new value."""
    con.execute("UPDATE baglanti_istegi SET deneme=deneme+1 WHERE id=?", (iid,))
    con.commit()
    return con.execute("SELECT deneme FROM baglanti_istegi WHERE id=?", (iid,)).fetchone()[0]


def istek_bitir(con, iid, durum):
    con.execute("UPDATE baglanti_istegi SET durum=? WHERE id=?", (durum, iid))
    con.commit()


ISTEK_DURUMLARI = ("bekliyor", "tamam", "iptal", "deneme")
_ISTEK_LISTE_KOLON = "i.id, i.firma_id, f.ad, i.ad, i.port, i.veritabani, i.kullanici, i.maskele, i.deneme, i.durum, i.olusturma_utc, i.bitis_utc"


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
    esik = (datetime.now(timezone.utc) - timedelta(minutes=dakika)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT count(*) FROM baglanti_istegi WHERE firma_id=? AND olusturma_utc > ?", (firma_id, esik)).fetchone()[0]


def firma_not_yaz(con, fid, aciklama):
    n = con.execute("UPDATE firma SET aciklama=? WHERE id=?", ((aciklama or "")[:500], fid)).rowcount
    con.commit()
    return n


def _firma_ozeti(f):
    return hashlib.sha256(("sirket|" + f["anahtar"]).encode()).hexdigest()


def firma_sinir_sifirla(con, fid):
    f = firma_getir(con, fid)
    if not f:
        return 0
    n = con.execute("DELETE FROM kullanim WHERE anahtar_sha256=?", (_firma_ozeti(f),)).rowcount
    con.commit()
    return n


def firma_sil(con, fid):
    """Deletes the company record, its reports, its portal users and its rate counts. Returns the number of deleted reports; None if the company does not exist."""
    f = firma_getir(con, fid)
    if not f:
        return None
    n = con.execute("DELETE FROM rapor WHERE firma_id=?", (fid,)).rowcount
    for tablo in ("portal_kod", "portal_oturum"):   # codes and sessions of the company's portal users
        con.execute("DELETE FROM %s WHERE kullanici_id IN (SELECT id FROM portal_kullanici WHERE firma_id=?)" % tablo, (fid,))
    con.execute("DELETE FROM portal_kullanici WHERE firma_id=?", (fid,))
    con.execute("DELETE FROM portal_talep WHERE firma_id=?", (fid,))
    con.execute("DELETE FROM kullanim WHERE anahtar_sha256=?", (_firma_ozeti(f),))
    con.execute("DELETE FROM baglanti_istegi WHERE firma_id=?", (fid,))
    con.execute("DELETE FROM firma WHERE id=?", (fid,))
    con.execute("INSERT INTO firma_silinen(anahtar_sha256, silinme_utc) VALUES(?,?) ON CONFLICT(anahtar_sha256) DO UPDATE SET silinme_utc=excluded.silinme_utc",
                (_iz_ozeti(f["anahtar"]), simdi()))
    con.commit()
    return n


def kullanim_say(con, anahtar, gun=SINIR_GUN):
    esik = (datetime.now(timezone.utc) - timedelta(days=gun)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT count(*) FROM kullanim WHERE anahtar_sha256=? AND zaman_utc>?", (anahtar, esik)).fetchone()[0]


def belge_ozeti(belge):
    return hashlib.sha256(json.dumps(belge, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def kullanim_tekrar(con, anahtar, ozet, gun=SINIR_GUN):
    """True if the same company already uploaded the same document within the rate window (no new allowance is spent)."""
    esik = (datetime.now(timezone.utc) - timedelta(days=gun)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT 1 FROM kullanim WHERE anahtar_sha256=? AND belge_sha256=? AND zaman_utc>? LIMIT 1", (anahtar, ozet, esik)).fetchone() is not None


def kullanim_ekle(con, anahtar, ozet=None):
    con.execute("INSERT INTO kullanim(anahtar_sha256, zaman_utc, belge_sha256) VALUES(?,?,?)", (anahtar, simdi(), ozet))
    con.commit()


def rapor_ekle(con, token, motor, dil, belge, firma_id=None, eposta="", dogrulandi=True):
    """dogrulandi=False: the report is hidden until verified through the link in the email and is deleted after BEKLEME_SAAT hours."""
    n = datetime.now(timezone.utc)
    bitis = n + (timedelta(days=saklama.gun("rapor")) if dogrulandi else timedelta(hours=BEKLEME_SAAT))
    con.execute("INSERT INTO rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id, eposta, dogrulandi)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (token_ozeti(token), n.strftime("%Y-%m-%dT%H:%M:%SZ"), bitis.strftime("%Y-%m-%dT%H:%M:%SZ"), motor, dil,
                 json.dumps(belge, sort_keys=True), firma_id, (eposta or "").strip().lower()[:200], 1 if dogrulandi else 0))
    con.commit()


def rapor_getir(con, token):
    """A verified, unexpired report; None if there is none."""
    r = _rapor(con.execute("SELECT %s FROM rapor WHERE token_sha256=? AND dogrulandi=1" % _RAPOR_KOLON, (token_ozeti(token),)).fetchone())
    return r if r and r["bitis_utc"] > simdi() else None


def rapor_bekleyen_getir(con, token):
    """A report awaiting email verification and not yet expired; None if there is none."""
    r = _rapor(con.execute("SELECT %s FROM rapor WHERE token_sha256=? AND dogrulandi=0" % _RAPOR_KOLON, (token_ozeti(token),)).fetchone())
    return r if r and r["bitis_utc"] > simdi() else None


def rapor_dogrula(con, rid):
    """Makes the report visible; the retention period starts at the moment of verification."""
    bitis = (datetime.now(timezone.utc) + timedelta(days=saklama.gun("rapor"))).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = con.execute("UPDATE rapor SET dogrulandi=1, bitis_utc=? WHERE id=? AND dogrulandi=0", (bitis, rid)).rowcount
    con.commit()
    return n


def bekleyen_say(con, firma_id, saat=BEKLEME_SAAT):
    esik = (datetime.now(timezone.utc) - timedelta(hours=saat)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT count(*) FROM rapor WHERE firma_id=? AND dogrulandi=0 AND olusturma_utc > ?", (firma_id, esik)).fetchone()[0]


def rapor_sil(con, token):
    n = con.execute("DELETE FROM rapor WHERE token_sha256=?", (token_ozeti(token),)).rowcount
    con.commit()
    return n


_RAPOR_KOLON = "id, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id, eposta, dogrulandi"


def _rapor(r):
    if not r:
        return None
    d = dict(zip(_RAPOR_KOLON.split(", "), r))
    d["belge"] = json.loads(d.pop("belge_json"))
    return d


def rapor_listele(con, limit=200, firma_id=None):
    kosul, arg = ("WHERE firma_id=?", (firma_id, limit)) if firma_id is not None else ("", (limit,))
    return [_rapor(r) for r in con.execute("SELECT %s FROM rapor %s ORDER BY id DESC LIMIT ?" % (_RAPOR_KOLON, kosul), arg)]


def onceki_rapor(con, rapor):
    """Previous report for comparison: the same company's, with the same database identity (tarama/gecmis.py), the newest
    verified and unexpired report made before this scan; None if there is none. The same scan time (the same file) does not count."""
    from tarama import gecmis
    k = gecmis.kimlik(rapor.get("belge")) if rapor.get("firma_id") is not None else None
    t = rapor["belge"].get("olusturma_utc") if k else None
    if not isinstance(t, str):
        return None
    en = None
    for satir in con.execute("SELECT %s FROM rapor WHERE firma_id=? AND id<>? AND dogrulandi=1 AND bitis_utc>?" % _RAPOR_KOLON,
                             (rapor["firma_id"], rapor.get("id", -1), simdi())):
        try:
            r = _rapor(satir)
        except ValueError:   # a corrupt record does not enter the comparison and does not prevent this report from opening
            continue
        rt = r["belge"].get("olusturma_utc") if isinstance(r["belge"], dict) else None
        if isinstance(rt, str) and rt < t and gecmis.kimlik(r["belge"]) == k and (en is None or rt > en["belge"]["olusturma_utc"]):
            en = r
    return en


def rapor_getir_id(con, rid):
    return _rapor(con.execute("SELECT %s FROM rapor WHERE id=?" % _RAPOR_KOLON, (rid,)).fetchone())


# --- portal requests (admin view; the company view is Kapsam in tarama/portal_depo.py) ---
TALEP_DURUMLARI = ("yeni", "inceleniyor", "tamamlandi", "reddedildi")


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
    n = con.execute("UPDATE portal_talep SET durum=?, guncelleme_utc=? WHERE id=?", (durum, simdi(), tid)).rowcount
    con.commit()
    return n


# --- outbox (sent by tarama/posta.py) ---
def posta_ekle(con, alici, konu, metin):
    con.execute("INSERT INTO posta(alici, konu, metin, olusturma_utc) VALUES(?,?,?,?)", (alici.strip().lower()[:200], konu, metin, simdi()))
    con.commit()


def posta_say(con, alici, saat=24):
    esik = (datetime.now(timezone.utc) - timedelta(hours=saat)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT count(*) FROM posta WHERE alici=? AND olusturma_utc > ?", ((alici or "").strip().lower(), esik)).fetchone()[0]


def posta_bekleyenler(con, en_cok=20):
    return con.execute("SELECT id, alici, konu, metin, deneme FROM posta WHERE durum='bekliyor' ORDER BY id LIMIT ?", (en_cok,)).fetchall()


def posta_sonuc(con, pid, hata=None, deneme_siniri=POSTA_DENEME):
    """If sent, the text is deleted (the link is secret). On failure the attempt count rises; at the limit it gives up and the text is still deleted."""
    if hata is None:
        con.execute("UPDATE posta SET durum='gonderildi', metin='', gonderim_utc=?, son_hata='' WHERE id=?", (simdi(), pid))
    else:
        con.execute("UPDATE posta SET deneme=deneme+1, son_hata=? WHERE id=?", (str(hata)[:200], pid))
        con.execute("UPDATE posta SET durum='basarisiz', metin='' WHERE id=? AND deneme >= ?", (pid, deneme_siniri))
    con.commit()


def rapor_sil_id(con, rid):
    n = con.execute("DELETE FROM rapor WHERE id=?", (rid,)).rowcount
    con.commit()
    return n


def saklama_uygula(con, simdi_=None):
    """Applies the company record retention period: if the period has passed since last activity and there is no active report, the company is deleted.
    Every deletion is written to the audit chain (the company name and email are not written). Returns the number of deleted companies."""
    g = saklama.gun("firma")
    if g is None:
        return 0
    esik = ((simdi_ or datetime.now(timezone.utc)) - timedelta(days=g)).strftime("%Y-%m-%dT%H:%M:%SZ")
    adaylar = con.execute("SELECT id FROM firma WHERE son_utc <= ? AND NOT EXISTS (SELECT 1 FROM rapor WHERE rapor.firma_id=firma.id AND rapor.bitis_utc > ?)",
                          (esik, simdi())).fetchall()
    for (fid,) in adaylar:
        with islem(con) as c:   # deletion and audit record together
            firma_sil(c, fid)
            denetim_ekle(c, "sistem", "saklama suresi doldu, firma #%d silindi" % fid)
    tg = saklama.gun("talep")
    if tg is not None:  # no request older than this date remains, so the trace is no longer needed either
        con.execute("DELETE FROM firma_silinen WHERE silinme_utc <= ?",
                    (((simdi_ or datetime.now(timezone.utc)) - timedelta(days=tg)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
        con.commit()
    return len(adaylar)


def suresi_dolanlari_sil(con):
    n = con.execute("DELETE FROM rapor WHERE bitis_utc <= ?", (simdi(),)).rowcount
    esik = (datetime.now(timezone.utc) - timedelta(days=SINIR_GUN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM kullanim WHERE zaman_utc <= ?", (esik,))
    gun = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM baglanti_istegi WHERE bitis_utc <= ?", (gun,))
    pg = (datetime.now(timezone.utc) - timedelta(days=saklama.gun("posta"))).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM posta WHERE olusturma_utc <= ? AND durum != 'bekliyor'", (pg,))
    con.commit()
    return n


def _komut(argv):
    """python3 tarama/depo.py dogrula <db> [--bas file.json] | bas <db>  (key: ALIG_DENETIM_ANAHTARI)"""
    if len(argv) >= 3 and argv[1] == "bas":
        bas = zincir_basi(baglan(argv[2]))
        if bas is None:
            print("chain is empty", file=sys.stderr)
            return 1
        print(json.dumps(bas, sort_keys=True))
        return 0
    if len(argv) in (3, 5) and argv[1] == "dogrula" and (len(argv) == 3 or argv[3] == "--bas"):
        try:
            anahtar = denetim_anahtari()
            bas = json.load(open(argv[4], encoding="utf-8")) if len(argv) == 5 else None
            durum = denetim_durum(baglan(argv[2]), anahtar, bas)
        except (AnahtarHatasi, OSError, ValueError, KeyError, TypeError) as ex:
            print("error: %s" % ex, file=sys.stderr)
            return 2
        print("denetim zinciri %s" % denetim_metni(durum))
        return 0 if durum["bozuk"] is None and not durum["dogrulanamayan"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_komut(sys.argv))
