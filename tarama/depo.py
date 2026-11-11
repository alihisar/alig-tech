"""SQLite (WAL) deposu ve SHA-256 zincirli denetim kaydi. Zamanlar UTC.
Dogrulama: python3 tarama/depo.py dogrula <db>"""
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

SAKLAMA_GUN = 30
SINIR_GUN = 30
SINIR_ADET = 2  # ucretsiz tarama sayisi: [doldurulacak: onay]
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
    # Kip B (dogrudan baglanti) istegi. Parola ASLA saklanmaz; yalniz hedef ve sahiplik kaniti.
    """CREATE TABLE baglanti_istegi(id INTEGER PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, firma_id INTEGER NOT NULL,
       kanit TEXT NOT NULL, ad TEXT NOT NULL, ip TEXT NOT NULL, port INTEGER NOT NULL, veritabani TEXT NOT NULL,
       kullanici TEXT NOT NULL, maskele INTEGER NOT NULL DEFAULT 0, dil TEXT NOT NULL, olusturma_utc TEXT NOT NULL,
       bitis_utc TEXT NOT NULL, deneme INTEGER NOT NULL DEFAULT 0, durum TEXT NOT NULL DEFAULT 'bekliyor')""",
]
ISTEK_DAKIKA = 30
ISTEK_DENEME = 3
ISTEK_SAATLIK = 5
FIRMA_DURUMLARI = ("aktif", "pasif")


def simdi():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def baglan(yol):
    con = sqlite3.connect(yol)
    con.execute("PRAGMA journal_mode=WAL")
    surum = con.execute("PRAGMA user_version").fetchone()[0]
    for i in range(surum, len(GOCLER)):  # yalniz ileri yonlu
        con.execute(GOCLER[i])
        con.execute("PRAGMA user_version=%d" % (i + 1))
    con.commit()
    return con


def token_ozeti(token):
    return hashlib.sha256(token.encode()).hexdigest()


def ozet_hesapla(seq, aktor, olay, onceki):
    return hashlib.sha256("|".join([str(seq), aktor, olay, onceki]).encode()).hexdigest()


def denetim_ekle(con, aktor, olay):
    son = con.execute("SELECT seq, ozet FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()
    seq, onceki = (son[0] + 1, son[1]) if son else (1, "")
    con.execute("INSERT INTO denetim VALUES(?,?,?,?,?,?)", (seq, simdi(), aktor, olay, onceki, ozet_hesapla(seq, aktor, olay, onceki)))
    con.commit()


def denetim_dogrula(con):
    """Bozuk ilk kaydin seq'i, saglamsa None."""
    onceki = ""
    for seq, aktor, olay, on, oz in con.execute("SELECT seq, aktor, olay, onceki, ozet FROM denetim ORDER BY seq"):
        if on != onceki or oz != ozet_hesapla(seq, aktor, olay, on):
            return seq
        onceki = oz
    return None


SERBEST_POSTA = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "yandex.com",
                 "icloud.com", "proton.me", "protonmail.com", "hotmail.com.tr", "yahoo.com.tr", "mynet.com"}
EPOSTA = re.compile(r"^[^@\s]{1,64}@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)$")


def firma_anahtari(eposta):
    """Firmayi tanimlayan duz anahtar: kurumsal adreste alan adi, ucretsiz posta saglayicisinda tam adres. Gecersizse None."""
    m = EPOSTA.match(eposta.strip()) if isinstance(eposta, str) and len(eposta) <= 200 else None
    if not m:
        return None
    alan = m.group(1).lower()
    return eposta.strip().lower() if alan in SERBEST_POSTA else alan


def sirket_anahtari(eposta):
    """Sinir sayimi icin anahtarin SHA-256 ozeti. Gecersizse None."""
    ham = firma_anahtari(eposta)
    return hashlib.sha256(("sirket|" + ham).encode()).hexdigest() if ham else None


_FIRMA_KOLON = "id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc, dogrudan_izin"


def _firma(r):
    return dict(zip(("id", "anahtar", "ad", "eposta", "durum", "kaynak", "aciklama", "kayit_utc", "son_utc", "dogrudan_izin"), r)) if r else None


def firma_kaydet(con, anahtar, ad, eposta, kaynak, zaman=None, guncelle=True):
    """Firma kaydini olusturur ya da (guncelle=True ise) son etkinligini yeniler. Kaydi doner."""
    z = zaman or simdi()
    ad, eposta = (ad or "").strip()[:160], (eposta or "").strip().lower()[:200]
    con.execute("INSERT OR IGNORE INTO firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES(?,?,?,?,?,?)", (anahtar, ad, eposta, kaynak, z, z))
    if guncelle:
        con.execute("UPDATE firma SET son_utc=?, eposta=?, ad=CASE WHEN ad='' THEN ? ELSE ad END WHERE anahtar=?", (z, eposta, ad, anahtar))
    con.commit()
    return _firma(con.execute("SELECT %s FROM firma WHERE anahtar=?" % _FIRMA_KOLON, (anahtar,)).fetchone())


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
        raise ValueError("durum")
    n = con.execute("UPDATE firma SET durum=? WHERE id=?", (durum, fid)).rowcount
    con.commit()
    return n


def firma_izin_yaz(con, fid, izin):
    """Dogrudan baglanti (Kip B) izni. Yalniz yonetici verir."""
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
    """Suresi dolmamis ve bekleyen istek; yoksa None."""
    r = con.execute("SELECT %s FROM baglanti_istegi WHERE token_sha256=? AND durum='bekliyor' AND bitis_utc > ?" % _ISTEK_KOLON,
                    (token_ozeti(token), simdi())).fetchone()
    return dict(zip(_ISTEK_KOLON.split(", "), r)) if r else None


def istek_deneme(con, iid):
    """Deneme sayisini bir artirir ve yeni degeri doner."""
    con.execute("UPDATE baglanti_istegi SET deneme=deneme+1 WHERE id=?", (iid,))
    con.commit()
    return con.execute("SELECT deneme FROM baglanti_istegi WHERE id=?", (iid,)).fetchone()[0]


def istek_bitir(con, iid, durum):
    con.execute("UPDATE baglanti_istegi SET durum=? WHERE id=?", (durum, iid))
    con.commit()


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
    """Firma kaydini, raporlarini ve sinir sayimini siler. Silinen rapor sayisini doner; firma yoksa None."""
    f = firma_getir(con, fid)
    if not f:
        return None
    n = con.execute("DELETE FROM rapor WHERE firma_id=?", (fid,)).rowcount
    con.execute("DELETE FROM kullanim WHERE anahtar_sha256=?", (_firma_ozeti(f),))
    con.execute("DELETE FROM baglanti_istegi WHERE firma_id=?", (fid,))
    con.execute("DELETE FROM firma WHERE id=?", (fid,))
    con.commit()
    return n


def kullanim_say(con, anahtar, gun=SINIR_GUN):
    esik = (datetime.now(timezone.utc) - timedelta(days=gun)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT count(*) FROM kullanim WHERE anahtar_sha256=? AND zaman_utc>?", (anahtar, esik)).fetchone()[0]


def kullanim_ekle(con, anahtar):
    con.execute("INSERT INTO kullanim(anahtar_sha256, zaman_utc) VALUES(?,?)", (anahtar, simdi()))
    con.commit()


def rapor_ekle(con, token, motor, dil, belge, firma_id=None):
    n = datetime.now(timezone.utc)
    con.execute("INSERT INTO rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id) VALUES(?,?,?,?,?,?,?)",
                (token_ozeti(token), n.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 (n + timedelta(days=SAKLAMA_GUN)).strftime("%Y-%m-%dT%H:%M:%SZ"), motor, dil, json.dumps(belge, sort_keys=True), firma_id))
    con.commit()


def rapor_getir(con, token):
    satir = con.execute("SELECT id, olusturma_utc, bitis_utc, motor, dil, belge_json FROM rapor WHERE token_sha256=?",
                        (token_ozeti(token),)).fetchone()
    if not satir or satir[2] <= simdi():
        return None
    return {"id": satir[0], "olusturma_utc": satir[1], "bitis_utc": satir[2], "motor": satir[3], "dil": satir[4], "belge": json.loads(satir[5])}


def rapor_sil(con, token):
    n = con.execute("DELETE FROM rapor WHERE token_sha256=?", (token_ozeti(token),)).rowcount
    con.commit()
    return n


def _rapor(r):
    return {"id": r[0], "olusturma_utc": r[1], "bitis_utc": r[2], "motor": r[3], "dil": r[4], "belge": json.loads(r[5]), "firma_id": r[6]} if r else None


def rapor_listele(con, limit=200, firma_id=None):
    kosul, arg = ("WHERE firma_id=?", (firma_id, limit)) if firma_id is not None else ("", (limit,))
    return [_rapor(r) for r in con.execute(
        "SELECT id, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id FROM rapor %s ORDER BY id DESC LIMIT ?" % kosul, arg)]


def rapor_getir_id(con, rid):
    return _rapor(con.execute("SELECT id, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id FROM rapor WHERE id=?", (rid,)).fetchone())


def rapor_sil_id(con, rid):
    n = con.execute("DELETE FROM rapor WHERE id=?", (rid,)).rowcount
    con.commit()
    return n


def suresi_dolanlari_sil(con):
    n = con.execute("DELETE FROM rapor WHERE bitis_utc <= ?", (simdi(),)).rowcount
    esik = (datetime.now(timezone.utc) - timedelta(days=SINIR_GUN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM kullanim WHERE zaman_utc <= ?", (esik,))
    gun = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM baglanti_istegi WHERE bitis_utc <= ?", (gun,))
    con.commit()
    return n


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "dogrula":
        bozuk = denetim_dogrula(baglan(sys.argv[2]))
        print("denetim zinciri saglam" if bozuk is None else "denetim zinciri kirik: kayit #%d" % bozuk)
        sys.exit(0 if bozuk is None else 1)
    print(__doc__)
    sys.exit(2)
