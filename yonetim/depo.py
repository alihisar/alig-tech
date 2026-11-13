"""Yonetim paneli deposu: kullanicilar, oturumlar, giris denemeleri, talep durumlari, denetim zinciri. SQLite WAL, UTC."""
import sqlite3
from datetime import datetime, timedelta, timezone

from tarama import depo as zincir  # denetim_ekle / denetim_dogrula ayni sema ile calisir
from yonetim import guvenlik

OTURUM_BOSTA_DK = 30
OTURUM_EN_COK_SAAT = 8
DENEME_PENCERE_DK = 15
DENEME_KULLANICI = 5
DENEME_IP = 10
DURUMLAR = ("yeni", "gorusuluyor", "kapandi")

GOCLER = [
    """CREATE TABLE kullanici(ad TEXT PRIMARY KEY, parola TEXT NOT NULL, totp TEXT NOT NULL, totp_sayac INTEGER NOT NULL DEFAULT 0,
       olusturma_utc TEXT NOT NULL)""",
    """CREATE TABLE oturum(kod_sha256 TEXT PRIMARY KEY, ad TEXT NOT NULL, csrf TEXT NOT NULL, olusturma_utc TEXT NOT NULL,
       son_erisim_utc TEXT NOT NULL)""",
    """CREATE TABLE giris_denemesi(id INTEGER PRIMARY KEY, anahtar TEXT NOT NULL, zaman_utc TEXT NOT NULL)""",
    """CREATE INDEX giris_anahtar ON giris_denemesi(anahtar, zaman_utc)""",
    """CREATE TABLE talep_durum(talep_id INTEGER PRIMARY KEY, durum TEXT NOT NULL, aciklama TEXT NOT NULL DEFAULT '',
       guncelleme_utc TEXT NOT NULL, guncelleyen TEXT NOT NULL)""",
    """CREATE TABLE denetim(seq INTEGER PRIMARY KEY, zaman_utc TEXT NOT NULL, aktor TEXT NOT NULL, olay TEXT NOT NULL,
       onceki TEXT NOT NULL, ozet TEXT NOT NULL)""",
    """ALTER TABLE denetim ADD COLUMN mod INTEGER NOT NULL DEFAULT 0""",
    """ALTER TABLE denetim ADD COLUMN alanlar TEXT NOT NULL DEFAULT ''""",
    # kullanicinin daha once giris yaptigi IP'ler (duz adres yok, ozet)
    """CREATE TABLE giris_ip(ad TEXT NOT NULL, ip_ozeti TEXT NOT NULL, ilk_utc TEXT NOT NULL, son_utc TEXT NOT NULL, PRIMARY KEY(ad, ip_ozeti))""",
]
BICIM = "%Y-%m-%dT%H:%M:%SZ"


def _simdi():
    return datetime.now(timezone.utc)


def _z(dt):
    return dt.strftime(BICIM)


def baglan(yol):
    con = sqlite3.connect(yol)
    zincir.wal_ac(con)
    zincir.goc_uygula(con, GOCLER)
    return con


denetim_ekle = zincir.denetim_ekle
denetim_dogrula = zincir.denetim_dogrula
denetim_durum = zincir.denetim_durum


# --- kullanicilar --- (her eylem ve denetim kaydi tek islemde: denetim yazilamazsa eylem de geri alinir)
def kullanici_ekle(con, ad, parola):
    gizli = guvenlik.totp_gizli()
    ozet = guvenlik.parola_ozetle(parola)   # yavas (scrypt): kilit disinda
    with zincir.islem(con) as c:
        c.execute("INSERT INTO kullanici(ad, parola, totp, olusturma_utc) VALUES(?,?,?,?)", (ad, ozet, gizli, _z(_simdi())))
        denetim_ekle(c, "cli", "kullanici eklendi: %s" % ad)
    return gizli


def kullanici_parola(con, ad, parola):
    ozet = guvenlik.parola_ozetle(parola)
    with zincir.islem(con) as c:
        n = c.execute("UPDATE kullanici SET parola=? WHERE ad=?", (ozet, ad)).rowcount
        c.execute("DELETE FROM oturum WHERE ad=?", (ad,))
        if n:
            denetim_ekle(c, "cli", "parola degisti, oturumlar kapatildi: %s" % ad)
    return n


def kullanici_totp_yenile(con, ad):
    gizli = guvenlik.totp_gizli()
    with zincir.islem(con) as c:
        n = c.execute("UPDATE kullanici SET totp=?, totp_sayac=0 WHERE ad=?", (gizli, ad)).rowcount
        c.execute("DELETE FROM oturum WHERE ad=?", (ad,))
        if n:
            denetim_ekle(c, "cli", "dogrulama kodu anahtari yenilendi: %s" % ad)
    return gizli if n else None


def kullanici_sil(con, ad):
    with zincir.islem(con) as c:
        n = c.execute("DELETE FROM kullanici WHERE ad=?", (ad,)).rowcount
        c.execute("DELETE FROM oturum WHERE ad=?", (ad,))
        c.execute("DELETE FROM giris_ip WHERE ad=?", (ad,))
        if n:
            denetim_ekle(c, "cli", "kullanici silindi: %s" % ad)
    return n


# --- giris ---
def _deneme_sayisi(con, anahtar):
    esik = _z(_simdi() - timedelta(minutes=DENEME_PENCERE_DK))
    return con.execute("SELECT count(*) FROM giris_denemesi WHERE anahtar=? AND zaman_utc>?", (anahtar, esik)).fetchone()[0]


def giris_engelli(con, ad, ip):
    return _deneme_sayisi(con, "k:" + ad) >= DENEME_KULLANICI or _deneme_sayisi(con, "ip:" + ip) >= DENEME_IP


def _basarisiz(c, ad, ip):
    z = _z(_simdi())
    c.executemany("INSERT INTO giris_denemesi(anahtar, zaman_utc) VALUES(?,?)", [("k:" + ad, z), ("ip:" + ip, z)])
    denetim_ekle(c, "sistem", "basarisiz giris: %s" % ad, {"kullanici": ad, "sonuc": "basarisiz", "ip_ozeti": zincir.ip_ozeti(ip), "neden": "hatali"})


def giris(con, ad, parola, kod, ip, simdi=None):
    """Basarili ise (oturum_kodu, None), degilse (None, neden). Neden kullaniciya gosterilmez, denetim icindir.
    Parola (yavas) kilit disinda denetlenir; dogrulama kodu ve sayac, ayni kodun es zamanli iki giriste
    iki kez kabul edilmemesi icin yazma kilidi altinda okunur ve guncellenir."""
    ad = (ad or "").strip()[:64]
    if giris_engelli(con, ad, ip):
        denetim_ekle(con, "sistem", "giris engellendi (cok fazla deneme): %s" % ad, {"kullanici": ad, "sonuc": "reddedildi", "ip_ozeti": zincir.ip_ozeti(ip), "neden": "engelli"})
        return None, "engelli"
    satir = con.execute("SELECT parola, totp FROM kullanici WHERE ad=?", (ad,)).fetchone()
    parola_ok = guvenlik.parola_dogrula(parola or "", satir[0] if satir else guvenlik.SAHTE_OZET)
    kod_ = guvenlik.rastgele_kod()
    with zincir.islem(con) as c:
        guncel = c.execute("SELECT totp, totp_sayac FROM kullanici WHERE ad=?", (ad,)).fetchone() if satir and parola_ok else None
        sayac = guvenlik.totp_dogrula(guncel[0], kod, guncel[1], simdi) if guncel else None
        if not sayac:
            _basarisiz(c, ad, ip)
            return None, "hatali"
        z = _z(_simdi())
        c.execute("UPDATE kullanici SET totp_sayac=? WHERE ad=?", (sayac, ad))
        c.execute("INSERT INTO oturum VALUES(?,?,?,?,?)", (guvenlik.ozet(kod_), ad, guvenlik.rastgele_kod(), z, z))
        c.execute("DELETE FROM giris_denemesi WHERE anahtar=?", ("k:" + ad,))
        ioz = zincir.ip_ozeti(ip)
        onceki_ip = c.execute("SELECT count(*) FROM giris_ip WHERE ad=?", (ad,)).fetchone()[0]
        var = c.execute("SELECT 1 FROM giris_ip WHERE ad=? AND ip_ozeti=?", (ad, ioz)).fetchone()
        if var:
            c.execute("UPDATE giris_ip SET son_utc=? WHERE ad=? AND ip_ozeti=?", (z, ad, ioz))
        else:
            c.execute("INSERT INTO giris_ip(ad, ip_ozeti, ilk_utc, son_utc) VALUES(?,?,?,?)", (ad, ioz, z, z))
        yeni_ip = bool(onceki_ip and not var)  # ilk giris yeni IP uyarisi sayilmaz
        denetim_ekle(c, ad, "giris yapildi" if not yeni_ip else "yeni IP'den giris yapildi",
                     {"kullanici": ad, "sonuc": "basarili", "ip_ozeti": ioz, "yeni_ip": 1 if yeni_ip else 0})
    return kod_, None


def oturum(con, kod):
    """{ad, csrf} ya da None. Bosta 30 dk, en cok 8 saat."""
    if not kod:
        return None
    oz = guvenlik.ozet(kod)
    s = con.execute("SELECT ad, csrf, olusturma_utc, son_erisim_utc FROM oturum WHERE kod_sha256=?", (oz,)).fetchone()
    if not s:
        return None
    n = _simdi()
    ilk = datetime.strptime(s[2], BICIM).replace(tzinfo=timezone.utc)
    son = datetime.strptime(s[3], BICIM).replace(tzinfo=timezone.utc)
    if n - son > timedelta(minutes=OTURUM_BOSTA_DK) or n - ilk > timedelta(hours=OTURUM_EN_COK_SAAT):
        con.execute("DELETE FROM oturum WHERE kod_sha256=?", (oz,))
        con.commit()
        return None
    con.execute("UPDATE oturum SET son_erisim_utc=? WHERE kod_sha256=?", (_z(n), oz))
    con.commit()
    return {"ad": s[0], "csrf": s[1]}


def cikis(con, kod):
    con.execute("DELETE FROM oturum WHERE kod_sha256=?", (guvenlik.ozet(kod or ""),))
    con.commit()


def temizle(con):
    con.execute("DELETE FROM giris_denemesi WHERE zaman_utc<?", (_z(_simdi() - timedelta(days=1)),))
    con.execute("DELETE FROM oturum WHERE olusturma_utc<?", (_z(_simdi() - timedelta(hours=OTURUM_EN_COK_SAAT)),))
    con.commit()


# --- talep durumlari ---
def talep_durumlari(con):
    return {r[0]: {"durum": r[1], "aciklama": r[2], "guncelleme_utc": r[3], "guncelleyen": r[4]}
            for r in con.execute("SELECT talep_id, durum, aciklama, guncelleme_utc, guncelleyen FROM talep_durum")}


def talep_durum_yaz(con, talep_id, durum, aciklama, kim):
    if durum not in DURUMLAR:
        raise ValueError("durum")
    with zincir.islem(con) as c:
        c.execute("INSERT INTO talep_durum VALUES(?,?,?,?,?) ON CONFLICT(talep_id) DO UPDATE SET durum=excluded.durum, "
                  "aciklama=excluded.aciklama, guncelleme_utc=excluded.guncelleme_utc, guncelleyen=excluded.guncelleyen",
                  (talep_id, durum, aciklama[:500], _z(_simdi()), kim))
        denetim_ekle(c, kim, "talep #%d durumu: %s" % (talep_id, durum))
