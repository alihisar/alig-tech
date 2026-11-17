"""Admin panel store on PostgreSQL (ALIG-DB-003d): users, sessions, login attempts, request statuses, audit chains.

The second implementation of yonetim/depo.py. Function names and meanings are the same; `con` is an ortak.pg.Baglanti
(not a sqlite3 connection). Selected explicitly by configuration; there is NO fallback to SQLite: if PostgreSQL is configured
but unreachable, BaglantiHatasi propagates (docs/postgresql-gecis.md section 9, degraded mode).

Audit chain rules:
- The canonical format is NOT re-implemented: the digest comes from tarama.depo.ozet_hesapla / alanlari_yaz / denetim_anahtari and the
  verification runs the very same tarama.depo.denetim_durum over the rows read from PostgreSQL. A chain written by SQLite
  verifies here and vice versa (tests/test_yonetim_pg.py cross-checks identical inputs).
- Writers are ordered with a transaction-level advisory lock per chain (pg_advisory_xact_lock(KILIT_SINIFI, chain no)):
  the tail record is read only after the lock is held, so two concurrent writers cannot read the same tail and fork the chain.
  The lock is released at COMMIT/ROLLBACK, so a rolled-back business action leaves no gap. PRIMARY KEY (seq) and UNIQUE (onceki) in the
  schema are a second line of defence. A transaction that writes BOTH chains must take them in the order yonetim, then tarama.
- The application role has INSERT and SELECT only on the chain tables (db/sema/0005); nothing here updates or deletes audit rows.
"""
import os
from datetime import datetime, timedelta, timezone

from ortak import pg
from tarama import depo as zincir  # canonical format, digest and verifier shared with SQLite
from yonetim import guvenlik
from yonetim.depo import (BICIM, DENEME_IP, DENEME_KULLANICI, DENEME_PENCERE_DK, DURUMLAR,  # noqa: F401
                          OTURUM_BOSTA_DK, OTURUM_EN_COK_SAAT)

KILIT_SINIFI = 7430032   # first key of pg_advisory_xact_lock(int, int); db/uygula.py uses the bigint form with 7430031
# chain name -> (table, second advisory key)
ZINCIRLER = {"yonetim": ("yonetim_denetim", 1), "tarama": ("denetim", 2)}
_SORGU = "SELECT seq, aktor, olay, onceki, ozet, mod, alanlar FROM denetim ORDER BY seq"


class YapilandirmaHatasi(RuntimeError):
    """PostgreSQL is selected but not configured or the configuration parser is missing: a startup error, never a SQLite fallback."""


def _simdi():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _z(dt):
    return dt.astimezone(timezone.utc).strftime(BICIM) if isinstance(dt, datetime) else dt


def baglan(ortam=None, **ek):
    """Opens a connection from the settings parsed by ortak/pg_ayar.py (yukle(ortam) -> kwargs or None). Raises
    YapilandirmaHatasi when PostgreSQL is not configured. The schema is NOT created here: the application role never runs DDL
    (db/uygula.py does it with the migrator role)."""
    try:
        from ortak import pg_ayar
    except ImportError as ex:
        raise YapilandirmaHatasi("ortak/pg_ayar.py is missing: cannot read the PostgreSQL settings") from ex
    ayar = pg_ayar.yukle(os.environ if ortam is None else ortam)
    if ayar is None:
        raise YapilandirmaHatasi("PostgreSQL is not configured; this store does not fall back to SQLite")
    return pg.Baglanti.baglan(**ayar, **ek)


def _tablo(ad):
    try:
        return ZINCIRLER[ad]
    except KeyError:
        raise ValueError("unknown chain: %r" % (ad,)) from None


def _islem(con):
    """Joins the open transaction or starts one (the PostgreSQL counterpart of tarama.depo.islem)."""
    if con.islemde:
        return _Mevcut(con)
    return con.islem()


class _Mevcut:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *a):
        return False


# --- audit chain ---
def denetim_ekle(con, aktor, olay, alanlar=None, zincir_ad="yonetim"):
    """Appends one record. Inside an open transaction it joins it (commit/rollback belongs to the caller); otherwise it is its own
    transaction. The tail is read only after the chain lock is held."""
    tablo, no = _tablo(zincir_ad)
    anahtar = zincir.denetim_anahtari()
    metin = zincir.alanlari_yaz(alanlar)
    with _islem(con) as c:
        c.sorgu("SELECT pg_advisory_xact_lock($1::int, $2::int)", [KILIT_SINIFI, no])
        son = c.sorgu("SELECT seq, ozet FROM alig.%s ORDER BY seq DESC LIMIT 1" % tablo)
        seq, onceki = (son[0][0] + 1, son[0][1]) if son else (1, "")
        # mode: bit0 = HMAC, bit1 = structured fields included in the digest (same as SQLite)
        c.sorgu("INSERT INTO alig.%s(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8)" % tablo,
                [seq, _simdi(), aktor, olay, onceki, zincir.ozet_hesapla(seq, aktor, olay, onceki, anahtar, metin),
                 (1 if anahtar else 0) | 2, metin])


class _Satirlar:
    """Makes the PostgreSQL rows look like the sqlite3 connection the shared verifier expects. It answers only the verifier's
    own query; if the verifier's query ever changes this fails loudly instead of verifying something else."""

    def __init__(self, con, tablo):
        self.con, self.tablo = con, tablo

    def execute(self, sorgu, arg=()):
        if sorgu != _SORGU or arg:
            raise AssertionError("the shared chain verifier changed its query; update yonetim/depo_pg.py")
        return iter(self.con.sorgu("SELECT seq, aktor, olay, onceki, ozet, mod, alanlar FROM alig.%s ORDER BY seq" % self.tablo))


def denetim_durum(con, anahtar=None, bas=None, zincir_ad="yonetim"):
    """Same result dict as tarama.depo.denetim_durum (it IS that function, run over PostgreSQL rows)."""
    return zincir.denetim_durum(_Satirlar(con, _tablo(zincir_ad)[0]), anahtar, bas)


def denetim_dogrula(con, anahtar=None, zincir_ad="yonetim"):
    return denetim_durum(con, anahtar if anahtar is not None else zincir.denetim_anahtari(), zincir_ad=zincir_ad)["bozuk"]


def zincir_basi(con, zincir_ad="yonetim"):
    son = con.sorgu("SELECT seq, zaman_utc, ozet FROM alig.%s ORDER BY seq DESC LIMIT 1" % _tablo(zincir_ad)[0])
    return {"seq": son[0][0], "zaman_utc": _z(son[0][1]), "ozet": son[0][2]} if son else None


def denetim_say(con, zincir_ad="yonetim"):
    return con.sorgu("SELECT count(*) FROM alig.%s" % _tablo(zincir_ad)[0])[0][0]


def denetim_listele(con, zincir_ad="yonetim", limit=50, offset=0):
    """Newest first: (seq, zaman_utc text, aktor, olay, ozet, alanlar), like the panel's chain page query."""
    return [(r[0], _z(r[1]), r[2], r[3], r[4], r[5]) for r in con.sorgu(
        "SELECT seq, zaman_utc, aktor, olay, ozet, alanlar FROM alig.%s ORDER BY seq DESC LIMIT $1 OFFSET $2" % _tablo(zincir_ad)[0],
        [int(limit), int(offset)])]


# --- users --- (each action and its audit record in one transaction)
def kullanici_ekle(con, ad, parola):
    gizli = guvenlik.totp_gizli()
    ozet = guvenlik.parola_ozetle(parola)   # slow (scrypt): outside the transaction and the lock
    with con.islem() as c:
        c.sorgu("INSERT INTO alig.kullanici(ad, parola, totp, olusturma_utc) VALUES($1,$2,$3,$4)", [ad, ozet, gizli, _simdi()])
        denetim_ekle(c, "cli", "kullanici eklendi: %s" % ad)
    return gizli


def kullanici_parola(con, ad, parola):
    ozet = guvenlik.parola_ozetle(parola)
    with con.islem() as c:
        c.sorgu("UPDATE alig.kullanici SET parola=$1 WHERE ad=$2", [ozet, ad])
        n = c.etkilenen
        c.sorgu("DELETE FROM alig.oturum WHERE ad=$1", [ad])
        if n:
            denetim_ekle(c, "cli", "parola degisti, oturumlar kapatildi: %s" % ad)
    return n


def kullanici_totp_yenile(con, ad):
    gizli = guvenlik.totp_gizli()
    with con.islem() as c:
        c.sorgu("UPDATE alig.kullanici SET totp=$1, totp_sayac=0 WHERE ad=$2", [gizli, ad])
        n = c.etkilenen
        c.sorgu("DELETE FROM alig.oturum WHERE ad=$1", [ad])
        if n:
            denetim_ekle(c, "cli", "dogrulama kodu anahtari yenilendi: %s" % ad)
    return gizli if n else None


def kullanici_sil(con, ad):
    with con.islem() as c:
        c.sorgu("DELETE FROM alig.kullanici WHERE ad=$1", [ad])
        n = c.etkilenen
        c.sorgu("DELETE FROM alig.oturum WHERE ad=$1", [ad])     # also gone through ON DELETE CASCADE; explicit like SQLite
        c.sorgu("DELETE FROM alig.giris_ip WHERE ad=$1", [ad])
        if n:
            denetim_ekle(c, "cli", "kullanici silindi: %s" % ad)
    return n


def kullanici_listele(con):
    return [(r[0], _z(r[1])) for r in con.sorgu("SELECT ad, olusturma_utc FROM alig.kullanici ORDER BY ad")]


def kullanici_var(con, ad):
    return bool(con.sorgu("SELECT 1 FROM alig.kullanici WHERE ad=$1", [ad]))


# --- login ---
def _deneme_sayisi(con, anahtar):
    esik = _simdi() - timedelta(minutes=DENEME_PENCERE_DK)
    return con.sorgu("SELECT count(*) FROM alig.giris_denemesi WHERE anahtar=$1 AND zaman_utc>$2", [anahtar, esik])[0][0]


def giris_engelli(con, ad, ip):
    return _deneme_sayisi(con, "k:" + ad) >= DENEME_KULLANICI or _deneme_sayisi(con, "ip:" + ip) >= DENEME_IP


def _basarisiz(c, ad, ip):
    z = _simdi()
    for a in ("k:" + ad, "ip:" + ip):
        c.sorgu("INSERT INTO alig.giris_denemesi(anahtar, zaman_utc) VALUES($1,$2)", [a, z])
    denetim_ekle(c, "sistem", "basarisiz giris: %s" % ad,
                 {"kullanici": ad, "sonuc": "basarisiz", "ip_ozeti": zincir.ip_ozeti(ip), "neden": "hatali"})


def giris(con, ad, parola, kod, ip, simdi=None):
    """On success (session_code, None), otherwise (None, reason). Same contract as the SQLite store. The password (slow) is
    checked outside the transaction; the verification code and counter are read with FOR UPDATE in the transaction, so the same
    code cannot be accepted twice by two concurrent logins (the second waits for the first and sees the new counter)."""
    ad = (ad or "").strip()[:64]
    if giris_engelli(con, ad, ip):
        denetim_ekle(con, "sistem", "giris engellendi (cok fazla deneme): %s" % ad,
                     {"kullanici": ad, "sonuc": "reddedildi", "ip_ozeti": zincir.ip_ozeti(ip), "neden": "engelli"})
        return None, "engelli"
    satir = con.sorgu("SELECT parola, totp FROM alig.kullanici WHERE ad=$1", [ad])
    parola_ok = guvenlik.parola_dogrula(parola or "", satir[0][0] if satir else guvenlik.SAHTE_OZET)
    kod_ = guvenlik.rastgele_kod()
    with con.islem() as c:
        guncel = None
        if satir and parola_ok:
            g = c.sorgu("SELECT totp, totp_sayac FROM alig.kullanici WHERE ad=$1 FOR UPDATE", [ad])
            guncel = g[0] if g else None
        sayac = guvenlik.totp_dogrula(guncel[0], kod, guncel[1], simdi) if guncel else None
        if not sayac:
            _basarisiz(c, ad, ip)
            return None, "hatali"
        z = _simdi()
        c.sorgu("UPDATE alig.kullanici SET totp_sayac=$1 WHERE ad=$2", [sayac, ad])
        c.sorgu("INSERT INTO alig.oturum(kod_sha256, ad, csrf, olusturma_utc, son_erisim_utc) VALUES($1,$2,$3,$4,$5)",
                [guvenlik.ozet(kod_), ad, guvenlik.rastgele_kod(), z, z])
        c.sorgu("DELETE FROM alig.giris_denemesi WHERE anahtar=$1", ["k:" + ad])
        ioz = zincir.ip_ozeti(ip)
        onceki_ip = c.sorgu("SELECT count(*) FROM alig.giris_ip WHERE ad=$1", [ad])[0][0]
        var = c.sorgu("SELECT 1 FROM alig.giris_ip WHERE ad=$1 AND ip_ozeti=$2", [ad, ioz])
        if var:
            c.sorgu("UPDATE alig.giris_ip SET son_utc=$1 WHERE ad=$2 AND ip_ozeti=$3", [z, ad, ioz])
        else:
            c.sorgu("INSERT INTO alig.giris_ip(ad, ip_ozeti, ilk_utc, son_utc) VALUES($1,$2,$3,$4)", [ad, ioz, z, z])
        yeni_ip = bool(onceki_ip and not var)  # a first login does not count as a new-IP warning
        denetim_ekle(c, ad, "giris yapildi" if not yeni_ip else "yeni IP'den giris yapildi",
                     {"kullanici": ad, "sonuc": "basarili", "ip_ozeti": ioz, "yeni_ip": 1 if yeni_ip else 0})
    return kod_, None


def oturum(con, kod):
    """{ad, csrf} or None. 30 min idle, 8 hours at most."""
    if not kod:
        return None
    oz = guvenlik.ozet(kod)
    s = con.sorgu("SELECT ad, csrf, olusturma_utc, son_erisim_utc FROM alig.oturum WHERE kod_sha256=$1", [oz])
    if not s:
        return None
    ad, csrf, ilk, son = s[0]
    n = _simdi()
    if n - son > timedelta(minutes=OTURUM_BOSTA_DK) or n - ilk > timedelta(hours=OTURUM_EN_COK_SAAT):
        con.sorgu("DELETE FROM alig.oturum WHERE kod_sha256=$1", [oz])
        return None
    con.sorgu("UPDATE alig.oturum SET son_erisim_utc=$1 WHERE kod_sha256=$2", [n, oz])
    return {"ad": ad, "csrf": csrf}


def cikis(con, kod):
    con.sorgu("DELETE FROM alig.oturum WHERE kod_sha256=$1", [guvenlik.ozet(kod or "")])


def oturum_listele(con):
    """(ad, olusturma_utc text, son_erisim_utc text), most recently used first (the panel's session table)."""
    return [(r[0], _z(r[1]), _z(r[2])) for r in con.sorgu(
        "SELECT ad, olusturma_utc, son_erisim_utc FROM alig.oturum ORDER BY son_erisim_utc DESC")]


def temizle(con, denetle=False):
    """Deletes old login attempts and expired sessions, in one transaction. With denetle=True (daily maintenance) a 'sistem' audit
    record with the number of sessions goes in the same transaction; nothing is recorded when none expired. The admin-login call keeps the
    default (no audit record). Returns the number of sessions deleted."""
    with con.islem() as c:
        c.sorgu("DELETE FROM alig.giris_denemesi WHERE zaman_utc<$1", [_simdi() - timedelta(days=1)])
        c.sorgu("DELETE FROM alig.oturum WHERE olusturma_utc<$1", [_simdi() - timedelta(hours=OTURUM_EN_COK_SAAT)])
        n = c.etkilenen
        if denetle and n:
            denetim_ekle(c, "sistem", "suresi dolan %d yonetim oturumu silindi" % n)
    return n


# --- request statuses ---
def talep_durumlari(con):
    return {r[0]: {"durum": r[1], "aciklama": r[2], "guncelleme_utc": _z(r[3]), "guncelleyen": r[4]}
            for r in con.sorgu("SELECT talep_id, durum, aciklama, guncelleme_utc, guncelleyen FROM alig.talep_durum")}


def talep_durum_yaz(con, talep_id, durum, aciklama, kim):
    if durum not in DURUMLAR:
        raise ValueError("durum")
    with con.islem() as c:
        c.sorgu("INSERT INTO alig.talep_durum(talep_id, durum, aciklama, guncelleme_utc, guncelleyen) VALUES($1,$2,$3,$4,$5) "
                "ON CONFLICT(talep_id) DO UPDATE SET durum=EXCLUDED.durum, aciklama=EXCLUDED.aciklama, "
                "guncelleme_utc=EXCLUDED.guncelleme_utc, guncelleyen=EXCLUDED.guncelleyen",
                [talep_id, durum, aciklama[:500], _simdi(), kim])
        denetim_ekle(c, kim, "talep #%d durumu: %s" % (talep_id, durum))


# --- indicators (panel summary): read-only. An unreadable count returns None; it is never confused with 0 ---
def _say(con, sorgu, arg=()):
    """Single count query; None if the table is missing, a privilege is missing or the query fails. A lost connection is NOT
    turned into None: BaglantiHatasi propagates (degraded mode)."""
    try:
        return con.sorgu(sorgu, list(arg))[0][0]
    except pg.BaglantiHatasi:
        raise
    except pg.PgHata:
        return None


def gosterge(con, simdi=None):
    """Panel summary counts, same keys as the SQLite store (tarama_7, tarama_30, firma_aktif, firma_pasif, iletisim_acik,
    portal_acik, kipb_bekleyen, posta_bekleyen; zincir_tarama, zincir_yonetim). All data is in one database now, so there are no
    separate scan and form file arguments. Nothing is written."""
    n = simdi or _simdi()
    g = {}
    for ad, gun in (("tarama_7", 7), ("tarama_30", 30)):
        g[ad] = _say(con, "SELECT count(*) FROM alig.rapor WHERE olusturma_utc>=$1", [n - timedelta(days=gun)])
    g["firma_aktif"] = _say(con, "SELECT count(*) FROM alig.firma WHERE durum='aktif'")
    g["firma_pasif"] = _say(con, "SELECT count(*) FROM alig.firma WHERE durum='pasif'")
    g["portal_acik"] = _say(con, "SELECT count(*) FROM alig.portal_talep WHERE durum IN ('yeni','inceleniyor')")
    g["kipb_bekleyen"] = _say(con, "SELECT count(*) FROM alig.baglanti_istegi WHERE durum='bekliyor' AND bitis_utc>$1", [n])
    g["posta_bekleyen"] = _say(con, "SELECT count(*) FROM alig.posta WHERE durum='bekliyor'")
    g["iletisim_acik"] = _say(con, "SELECT count(*) FROM alig.contact c WHERE NOT EXISTS "
                                   "(SELECT 1 FROM alig.talep_durum t WHERE t.talep_id=c.id AND t.durum='kapandi')")
    g["zincir_tarama"] = None
    try:
        g["zincir_tarama"] = denetim_durum(con, zincir.denetim_anahtari(), zincir_ad="tarama")
    except pg.BaglantiHatasi:
        raise
    except pg.PgHata:
        pass
    g["zincir_yonetim"] = denetim_durum(con, zincir.denetim_anahtari(), zincir_ad="yonetim")
    return g
