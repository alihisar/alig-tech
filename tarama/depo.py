"""SQLite (WAL) deposu ve zincirli denetim kaydi (anahtar varsa HMAC-SHA-256, yoksa SHA-256). Zamanlar UTC.
Dogrulama: python3 tarama/depo.py dogrula <db> [--bas dosya.json]; zincir basi: python3 tarama/depo.py bas <db>"""
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
except ImportError:  # python3 tarama/depo.py ile dogrudan calisirken
    import saklama

SAKLAMA_GUN = 30  # varsayilan; gercek sure tarama/saklama.py'den okunur
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
    # anahtarli denetim zinciri: 0 = eski SHA-256 kaydi, 1 = HMAC-SHA-256 (ALIG_DENETIM_ANAHTARI)
    """ALTER TABLE denetim ADD COLUMN mod INTEGER NOT NULL DEFAULT 0""",
    # ayni dosya ikinci hak harcamasin: belgenin ozeti (icerik saklanmaz)
    """ALTER TABLE kullanim ADD COLUMN belge_sha256 TEXT""",
    # yapisal alanlar (firma, hedef, sonuc...): ozete dahil edilir, bu yuzden degistirilemez
    """ALTER TABLE denetim ADD COLUMN alanlar TEXT NOT NULL DEFAULT ''""",
    # silinen firmanin izi: eski bir talepten (iletisim formu) kendiliginden geri olusmasin. Duz anahtar degil ozet tutulur.
    """CREATE TABLE firma_silinen(anahtar_sha256 TEXT PRIMARY KEY, silinme_utc TEXT NOT NULL)""",
    # e-posta dogrulamasi (ALIG_EPOSTA_DOGRULAMA): raporda yukleyen adres, dogrulanmamis rapor gizli, firma dogrulama zamani
    """ALTER TABLE rapor ADD COLUMN eposta TEXT NOT NULL DEFAULT ''""",
    """ALTER TABLE rapor ADD COLUMN dogrulandi INTEGER NOT NULL DEFAULT 1""",
    """ALTER TABLE firma ADD COLUMN eposta_dogrulama_utc TEXT""",
    # giden kutusu: web sureci aga cikmaz, ayri posta servisi gonderir; metin gonderilince silinir
    """CREATE TABLE posta(id INTEGER PRIMARY KEY, alici TEXT NOT NULL, konu TEXT NOT NULL, metin TEXT NOT NULL,
       olusturma_utc TEXT NOT NULL, deneme INTEGER NOT NULL DEFAULT 0, durum TEXT NOT NULL DEFAULT 'bekliyor',
       son_hata TEXT NOT NULL DEFAULT '', gonderim_utc TEXT)""",
    """CREATE INDEX posta_alici ON posta(alici, olusturma_utc)""",
    # iletisim taleplerinden firma esitlemesinin nerede kaldigi (yalniz yeni talepler islensin)
    """CREATE TABLE esitleme(ad TEXT PRIMARY KEY, deger TEXT NOT NULL)""",
    # firma ve rapor kimligi silmeden sonra yeniden kullanilmasin (AUTOINCREMENT): denetimdeki "#N" hep ayni kaydi gosterir.
    # SQLite'ta yeniden kurma gerekir; adimlar goc_uygula'nin tek islemi icinde, yarida kalirsa hicbiri uygulanmaz.
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
    # musteri portali (ALIG_PORTAL): firma kullanicisi, e-posta dogrulama kodu, oturum, giris denemesi. Platform yoneticisinden
    # ayri tablolar ve ayri kimlik (yonetim.sqlite). Dogrulanmis kullanicinin firmasi vardir (CHECK); dogrulanmamisin yoktur.
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
    # portal talepleri: hizmet talebi (denetim, destek, diger) ve hesap/veri silme talebi (silme). Silme talebi yalniz kaydedilir;
    # kimlik dogrulamasi ve silme yonetici islemidir (panel). Firma basina tek acik silme talebi.
    """CREATE TABLE portal_talep(id INTEGER PRIMARY KEY AUTOINCREMENT, firma_id INTEGER NOT NULL, kullanici_id INTEGER NOT NULL,
       tur TEXT NOT NULL CHECK (tur IN ('denetim', 'destek', 'diger', 'silme')), konu TEXT NOT NULL DEFAULT '', mesaj TEXT NOT NULL DEFAULT '',
       durum TEXT NOT NULL DEFAULT 'yeni' CHECK (durum IN ('yeni', 'inceleniyor', 'tamamlandi', 'reddedildi')),
       olusturma_utc TEXT NOT NULL, guncelleme_utc TEXT NOT NULL)""",
    """CREATE INDEX portal_talep_firma ON portal_talep(firma_id, olusturma_utc)""",
    """CREATE UNIQUE INDEX portal_talep_acik_silme ON portal_talep(firma_id) WHERE tur='silme' AND durum IN ('yeni', 'inceleniyor')""",
]
ISTEK_DAKIKA = 30
BEKLEME_SAAT = 24      # e-postayla dogrulanmamis rapor bu sure sonunda silinir
POSTA_DENEME = 5       # gecici hatada en cok deneme
ISTEK_DENEME = 3
ISTEK_SAATLIK = 5
FIRMA_DURUMLARI = ("aktif", "pasif")


def simdi():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def goc_uygula(con, gocler):
    """Yalniz ileri yonlu goc. Birden cok surec ayni anda acabilir (tarama, yonetim, bakim; yeni surum dagitiminda
    hepsi yeniden baslar): goc tek yazma kilidi altinda yapilir ve surum kilit icinde yeniden okunur."""
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
    """Dis islem suresince commit'i erteleyen baglanti sarmalayicisi. Depo fonksiyonlari kendi commit'lerini cagirir;
    gercek commit islem bitince bir kez yapilir, istisnada hepsi geri alinir."""
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
        raise RuntimeError("islem icinde rollback cagrilmaz: istisna firlatin")

    def __getattr__(self, ad):
        return getattr(self._con, ad)


@contextlib.contextmanager
def islem(con):
    """Is eylemi ve denetim kaydi tek islemde: ya ikisi birlikte yazilir ya hicbiri. Yazma kilidi bastan alinir."""
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
    """WAL kipine gecis ilk acilista kisa sure ozel kilit ister; es zamanli acilista kilit bosalana kadar bekler."""
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
    """Ortamdaki denetim anahtari (bytes) ya da tanimsizsa None. Kisa anahtar sessizce kabul edilmez."""
    ham = (os.environ if ortam is None else ortam).get(ANAHTAR_ORTAM, "")
    if not ham:
        return None
    if len(ham) < ANAHTAR_MIN:
        raise AnahtarHatasi("%s en az %d karakter olmali" % (ANAHTAR_ORTAM, ANAHTAR_MIN))
    return ham.encode()


ALAN_ANAHTARLARI = ("firma", "hedef", "motor", "sonuc", "neden", "ip_ozeti", "yeni_ip", "rapor", "talep", "kullanici")
ALAN_UZUNLUK = 120


def alanlari_yaz(alanlar):
    """Yapisal alanlari kanonik JSON metnine cevirir: yalniz izinli anahtarlar, kisa duz degerler. Bos ise ''."""
    if not alanlar:
        return ""
    temiz = {}
    for k in ALAN_ANAHTARLARI:
        if k in alanlar and alanlar[k] is not None:
            v = alanlar[k]
            temiz[k] = v if isinstance(v, int) and not isinstance(v, bool) else str(v)[:ALAN_UZUNLUK]
    return json.dumps(temiz, sort_keys=True, separators=(",", ":"), ensure_ascii=False) if temiz else ""


def ip_ozeti(ip, anahtar=None):
    """IP'nin kisaltilmis ozeti (duz adres denetime yazilmaz). Anahtar varsa HMAC: sozluk saldirisi anahtarsiz yapilamaz."""
    ham = ("ip|" + str(ip)).encode()
    if anahtar is None:
        anahtar = denetim_anahtari()
    d = hmac.new(anahtar, ham, hashlib.sha256) if anahtar else hashlib.sha256(ham)
    return d.hexdigest()[:16]


def ozet_hesapla(seq, aktor, olay, onceki, anahtar=None, alanlar=None):
    """anahtar yoksa SHA-256, varsa HMAC-SHA-256 (ayri onek). alanlar None ise eski (alansiz) bicim; metin ise ozete dahil edilir."""
    parcalar = [str(seq), aktor, olay, onceki] + ([] if alanlar is None else [alanlar])
    if anahtar is None:
        return hashlib.sha256("|".join(parcalar).encode()).hexdigest()
    return hmac.new(anahtar, "|".join(["k"] + parcalar).encode(), hashlib.sha256).hexdigest()


def denetim_ekle(con, aktor, olay, alanlar=None):
    anahtar = denetim_anahtari()
    metin = alanlari_yaz(alanlar)
    # Son kaydi okuma ile ekleme ayni yazma kilidi altinda olmali: tarama sunucusu, yonetim paneli ve bakim ayni
    # zincire yazar; kilitsiz okumada iki yazici ayni seq'i alir ve biri IntegrityError ile kaydi kaybeder.
    # Acik islem varsa baglanti zaten yazma kilidini tutar (islem bir yazmayla baslamistir).
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    son = con.execute("SELECT seq, ozet FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()
    seq, onceki = (son[0] + 1, son[1]) if son else (1, "")
    # mod: bit0 = HMAC, bit1 = yapisal alanlar ozete dahil
    con.execute("INSERT INTO denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) VALUES(?,?,?,?,?,?,?,?)",
                (seq, simdi(), aktor, olay, onceki, ozet_hesapla(seq, aktor, olay, onceki, anahtar, metin), (1 if anahtar else 0) | 2, metin))
    con.commit()


def denetim_durum(con, anahtar=None, bas=None):
    """Zincirin ayrintili durumu.
    bozuk: ilk bozuk kaydin seq'i ya da None. Bozukluk: baglanti kopuklugu, ozet uyusmazligi, anahtarli kayitlardan sonra
      anahtarsiz kayit (surum dusurme), anahtar varken HMAC uyusmazligi ya da disa aktarilmis zincir basinin bulunmamasi.
    dogrulanamayan: anahtar verilmediginden HMAC'i denetlenemeyen anahtarli kayit sayisi.
    bas: {"seq", "ozet"} (daha once disa aktarilmis zincir basi) ya da None."""
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
        elif not alanli_mi and (alanli_goruldu or alanlar):  # surum dusurme: alansiz kayit, ya da alani olup ozete dahil olmayan
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
    """Bozuk ilk kaydin seq'i, saglamsa None. Anahtar verilmezse ortamdaki anahtar kullanilir."""
    return denetim_durum(con, anahtar if anahtar is not None else denetim_anahtari())["bozuk"]


def denetim_metni(durum):
    """Panel ve CLI icin tek satirlik durum."""
    if durum["bozuk"] is not None:
        return "KIRIK: kayıt #%d" % durum["bozuk"]
    if durum["dogrulanamayan"]:
        return "bağlantı sağlam, ancak %d anahtarlı kayıt anahtar olmadan doğrulanamadı" % durum["dogrulanamayan"]
    return "sağlam (anahtarlı)" if durum["anahtarli"] else "sağlam (anahtarsız kayıtlar)"


def zincir_basi(con):
    """Disa aktarilacak zincir basi: son kaydin seq'i ve ozeti. Bos zincirde None."""
    son = con.execute("SELECT seq, zaman_utc, ozet FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()
    return {"seq": son[0], "zaman_utc": son[1], "ozet": son[2]} if son else None


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


_FIRMA_KOLON = "id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc, dogrudan_izin, eposta_dogrulama_utc"


def _firma(r):
    return dict(zip(_FIRMA_KOLON.split(", "), r)) if r else None


def _iz_ozeti(anahtar):
    return hashlib.sha256(("silinen|" + anahtar).encode()).hexdigest()


def firma_kaydet(con, anahtar, ad, eposta, kaynak, zaman=None, guncelle=True):
    """Firma kaydini olusturur ya da (guncelle=True ise) son etkinligini yeniler. Kaydi doner.
    zaman verilmisse olay gecmistir (iletisim talebinden esitleme): firma bu olaydan sonra silinmisse kayit
    yeniden olusturulmaz ve None doner."""
    if zaman is not None:
        iz = con.execute("SELECT silinme_utc FROM firma_silinen WHERE anahtar_sha256=?", (_iz_ozeti(anahtar),)).fetchone()
        if iz and zaman <= iz[0] and not con.execute("SELECT 1 FROM firma WHERE anahtar=?", (anahtar,)).fetchone():
            return None
    z = zaman or simdi()
    ad, eposta = (ad or "").strip()[:160], (eposta or "").strip().lower()[:200]
    con.execute("INSERT OR IGNORE INTO firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES(?,?,?,?,?,?)", (anahtar, ad, eposta, kaynak, z, z))
    if guncelle:  # e-posta degismez: dogrulanmamis bir yukleme kayitli iletisim adresini ele geciremesin
        con.execute("UPDATE firma SET son_utc=?, ad=CASE WHEN ad='' THEN ? ELSE ad END WHERE anahtar=?", (z, ad, anahtar))
    con.commit()
    return _firma(con.execute("SELECT %s FROM firma WHERE anahtar=?" % _FIRMA_KOLON, (anahtar,)).fetchone())


def firma_eposta_dogrula(con, fid, eposta):
    """E-postadaki baglantiyla dogrulanan adres firmanin iletisim adresi olur."""
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
    """Firma kaydini, raporlarini, portal kullanicilarini ve sinir sayimini siler. Silinen rapor sayisini doner; firma yoksa None."""
    f = firma_getir(con, fid)
    if not f:
        return None
    n = con.execute("DELETE FROM rapor WHERE firma_id=?", (fid,)).rowcount
    for tablo in ("portal_kod", "portal_oturum"):   # firmanin portal kullanicilarinin kodlari ve oturumlari
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
    """Ayni sirket ayni belgeyi sinir penceresi icinde zaten yuklediyse True (yeni hak harcanmaz)."""
    esik = (datetime.now(timezone.utc) - timedelta(days=gun)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT 1 FROM kullanim WHERE anahtar_sha256=? AND belge_sha256=? AND zaman_utc>? LIMIT 1", (anahtar, ozet, esik)).fetchone() is not None


def kullanim_ekle(con, anahtar, ozet=None):
    con.execute("INSERT INTO kullanim(anahtar_sha256, zaman_utc, belge_sha256) VALUES(?,?,?)", (anahtar, simdi(), ozet))
    con.commit()


def rapor_ekle(con, token, motor, dil, belge, firma_id=None, eposta="", dogrulandi=True):
    """dogrulandi=False: rapor e-postadaki baglantiyla dogrulanana kadar gizlidir ve BEKLEME_SAAT sonra silinir."""
    n = datetime.now(timezone.utc)
    bitis = n + (timedelta(days=saklama.gun("rapor")) if dogrulandi else timedelta(hours=BEKLEME_SAAT))
    con.execute("INSERT INTO rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id, eposta, dogrulandi)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (token_ozeti(token), n.strftime("%Y-%m-%dT%H:%M:%SZ"), bitis.strftime("%Y-%m-%dT%H:%M:%SZ"), motor, dil,
                 json.dumps(belge, sort_keys=True), firma_id, (eposta or "").strip().lower()[:200], 1 if dogrulandi else 0))
    con.commit()


def rapor_getir(con, token):
    """Dogrulanmis ve suresi dolmamis rapor; yoksa None."""
    r = _rapor(con.execute("SELECT %s FROM rapor WHERE token_sha256=? AND dogrulandi=1" % _RAPOR_KOLON, (token_ozeti(token),)).fetchone())
    return r if r and r["bitis_utc"] > simdi() else None


def rapor_bekleyen_getir(con, token):
    """E-posta dogrulamasi bekleyen ve suresi dolmamis rapor; yoksa None."""
    r = _rapor(con.execute("SELECT %s FROM rapor WHERE token_sha256=? AND dogrulandi=0" % _RAPOR_KOLON, (token_ozeti(token),)).fetchone())
    return r if r and r["bitis_utc"] > simdi() else None


def rapor_dogrula(con, rid):
    """Raporu gorunur yapar; saklama suresi dogrulama aninda baslar."""
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
    """Karsilastirma icin onceki rapor: ayni firmanin, ayni veritabani kimligine ait (tarama/gecmis.py), bu taramadan once
    yapilmis en yeni dogrulanmis ve suresi dolmamis rapor; yoksa None. Ayni tarama zamani (ayni dosya) sayilmaz."""
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
        except ValueError:   # bozuk kayit karsilastirmaya girmez, bu raporun acilmasini engellemez
            continue
        rt = r["belge"].get("olusturma_utc") if isinstance(r["belge"], dict) else None
        if isinstance(rt, str) and rt < t and gecmis.kimlik(r["belge"]) == k and (en is None or rt > en["belge"]["olusturma_utc"]):
            en = r
    return en


def rapor_getir_id(con, rid):
    return _rapor(con.execute("SELECT %s FROM rapor WHERE id=?" % _RAPOR_KOLON, (rid,)).fetchone())


# --- portal talepleri (yonetici gorunumu; firma gorunumu tarama/portal_depo.py Kapsam) ---
TALEP_DURUMLARI = ("yeni", "inceleniyor", "tamamlandi", "reddedildi")


def portal_talep_listele(con, durum=None, limit=200):
    """Tum firmalarin portal talepleri (yalniz yonetici paneli): [{id, firma_id, firma_ad, tur, konu, mesaj, durum, olusturma_utc}]."""
    kosul, arg = ("WHERE t.durum=?", (durum, int(limit))) if durum in TALEP_DURUMLARI else ("", (int(limit),))
    return [dict(zip(("id", "firma_id", "firma_ad", "tur", "konu", "mesaj", "durum", "olusturma_utc"), r)) for r in con.execute(
        "SELECT t.id, t.firma_id, f.ad, t.tur, t.konu, t.mesaj, t.durum, t.olusturma_utc FROM portal_talep t LEFT JOIN firma f ON f.id=t.firma_id "
        "%s ORDER BY t.id DESC LIMIT ?" % kosul, arg)]


def portal_talep_durum_yaz(con, tid, durum):
    """Etkilenen satir sayisi (0: talep yok). Gecersiz durumda ValueError."""
    if durum not in TALEP_DURUMLARI:
        raise ValueError("gecersiz durum")
    n = con.execute("UPDATE portal_talep SET durum=?, guncelleme_utc=? WHERE id=?", (durum, simdi(), tid)).rowcount
    con.commit()
    return n


# --- giden kutusu (tarama/posta.py gonderir) ---
def posta_ekle(con, alici, konu, metin):
    con.execute("INSERT INTO posta(alici, konu, metin, olusturma_utc) VALUES(?,?,?,?)", (alici.strip().lower()[:200], konu, metin, simdi()))
    con.commit()


def posta_say(con, alici, saat=24):
    esik = (datetime.now(timezone.utc) - timedelta(hours=saat)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return con.execute("SELECT count(*) FROM posta WHERE alici=? AND olusturma_utc > ?", ((alici or "").strip().lower(), esik)).fetchone()[0]


def posta_bekleyenler(con, en_cok=20):
    return con.execute("SELECT id, alici, konu, metin, deneme FROM posta WHERE durum='bekliyor' ORDER BY id LIMIT ?", (en_cok,)).fetchall()


def posta_sonuc(con, pid, hata=None, deneme_siniri=POSTA_DENEME):
    """Gonderildiyse metin silinir (baglanti gizlidir). Hatada deneme artar; sinirda vazgecilir ve metin yine silinir."""
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
    """Firma kaydi saklama suresini uygular: son etkinlikten bu yana sure gectiyse ve etkin raporu yoksa firma silinir.
    Her silme denetim zincirine yazilir (firma adi ve e-postasi yazilmaz). Silinen firma sayisini doner."""
    g = saklama.gun("firma")
    if g is None:
        return 0
    esik = ((simdi_ or datetime.now(timezone.utc)) - timedelta(days=g)).strftime("%Y-%m-%dT%H:%M:%SZ")
    adaylar = con.execute("SELECT id FROM firma WHERE son_utc <= ? AND NOT EXISTS (SELECT 1 FROM rapor WHERE rapor.firma_id=firma.id AND rapor.bitis_utc > ?)",
                          (esik, simdi())).fetchall()
    for (fid,) in adaylar:
        with islem(con) as c:   # silme ve denetim kaydi birlikte
            firma_sil(c, fid)
            denetim_ekle(c, "sistem", "saklama suresi doldu, firma #%d silindi" % fid)
    tg = saklama.gun("talep")
    if tg is not None:  # bu tarihten eski talep kalmadigi icin iz de gerekmez
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
    """python3 tarama/depo.py dogrula <db> [--bas dosya.json] | bas <db>  (anahtar: ALIG_DENETIM_ANAHTARI)"""
    if len(argv) >= 3 and argv[1] == "bas":
        bas = zincir_basi(baglan(argv[2]))
        if bas is None:
            print("zincir bos", file=sys.stderr)
            return 1
        print(json.dumps(bas, sort_keys=True))
        return 0
    if len(argv) in (3, 5) and argv[1] == "dogrula" and (len(argv) == 3 or argv[3] == "--bas"):
        try:
            anahtar = denetim_anahtari()
            bas = json.load(open(argv[4], encoding="utf-8")) if len(argv) == 5 else None
            durum = denetim_durum(baglan(argv[2]), anahtar, bas)
        except (AnahtarHatasi, OSError, ValueError, KeyError, TypeError) as ex:
            print("hata: %s" % ex, file=sys.stderr)
            return 2
        print("denetim zinciri %s" % denetim_metni(durum))
        return 0 if durum["bozuk"] is None and not durum["dogrulanamayan"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_komut(sys.argv))
