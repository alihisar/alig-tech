"""Musteri portali veri katmani. Yalnizca standart kutuphane.

Firma izolasyonu BURADA, veri erisim katmaninda saglanir, sayfa koduna birakilmaz:
  * Portal sayfalari tarama.sqlite'a yalniz Kapsam uzerinden okur. Kapsam gecerli bir oturumdan olusur ve firma kimligini
    oturumdaki kullanicinin kaydindan alir; istekten (adres, form, cerez icerigi) firma kimligi ALINMAZ.
  * Kapsam'in her sorgusu "firma_id = <kapsamin firmasi>" kosulunu tasir. Baska firmanin raporu, tahmin edilen kimlikle
    istense de bulunamaz: sonuc "yok" ile ayni, "yetkisiz" degil (kaydin varligi da sizmaz).
  * Kullanici dogrulanmadan firmasi yoktur: dogrulanmamis hesap hicbir veriye erisemez (CHECK kisiti + kapsam kosulu).
  * Firma pasifse ya da silindiyse oturum gecersizdir.
Platform yoneticisi ile firma kullanicisi ayri kimliklerdir: yonetim.sqlite ile hicbir ortak tablo ya da oturum yoktur.

Giris: e-posta + parola (scrypt, en az 12 karakter). E-posta, tek kullanimlik ve sureli kodla dogrulanir; dogrulanmadan
hesap acilmaz. Hesap varligi ekrandan sizmaz (kayit her zaman ayni yaniti verir). Basarisiz girisler e-posta ve IP basina
sayilir ve kisa sure engellenir. Oturum bosta 30 dakika, en cok 8 saat.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from tarama import depo
from yonetim import guvenlik   # parola ozeti ve rastgele kod: tek yerde

PAROLA_EN_AZ = guvenlik.PAROLA_EN_AZ
PAROLA_EN_COK = 200
KOD_SAAT = 24
OTURUM_BOSTA_DK = 30
OTURUM_EN_COK_SAAT = 8
DENEME_PENCERE_DK = 15
DENEME_EPOSTA = 5
DENEME_IP = 10
BICIM = "%Y-%m-%dT%H:%M:%SZ"
HIZMET_TURLERI = ("denetim", "destek", "diger")
KONU_EN_COK = 120
MESAJ_EN_COK = 2000
TALEP_GUNLUK = 5


class PortalHata(ValueError):
    """kod: eposta | parola | sirket"""

    def __init__(self, kod):
        super().__init__(kod)
        self.kod = kod


def _simdi():
    return datetime.now(timezone.utc)


def _z(dt):
    return dt.strftime(BICIM)


def _eposta(deger):
    """Normallestirilmis e-posta ya da None. Firma anahtari kurallariyla ayni dogrulama (depo.firma_anahtari)."""
    if not isinstance(deger, str) or depo.firma_anahtari(deger) is None:
        return None
    return deger.strip().lower()


def _ozet(kod):
    """Kodun ozeti; metin olmayan deger hicbir kayitla eslesmeyen bos kodun ozetidir."""
    return guvenlik.ozet(kod if isinstance(kod, str) else "")


def _eposta_ozeti(eposta):
    return hashlib.sha256(("portal|" + eposta).encode()).hexdigest()


# ---- kayit ve e-posta dogrulama ----

def kayit(con, eposta, parola, sirket, dil):
    """Hesap isteginin sonucu: ("yeni", kod) dogrulama baglantisi gonderilmeli; ("var", None) adreste etkin hesap var
    (yeni hesap acilmaz, kullaniciya ayni yanit gosterilir). Gecersiz girdide PortalHata. Firma bu asamada olusmaz:
    firma, adresin sahibi dogrulama kodunu kullaninca olusur. Dogrulanmamis eski istek yenisiyle degistirilir
    (adresin sahibi olmayan biri baskasinin adresine parola yerlestirip kalici hak kazanamaz)."""
    eposta_n = _eposta(eposta)
    if eposta_n is None:
        raise PortalHata("eposta")
    if not isinstance(parola, str) or not PAROLA_EN_AZ <= len(parola) <= PAROLA_EN_COK:
        raise PortalHata("parola")
    sirket = (sirket or "").strip() if isinstance(sirket, str) else ""
    if not sirket or len(sirket) > 160 or any(ord(c) < 32 or ord(c) == 127 for c in sirket):
        raise PortalHata("sirket")
    dil = dil if dil in ("tr", "en") else "tr"
    ozet = guvenlik.parola_ozetle(parola)   # yavas islem: yazma kilidi disinda
    with depo.islem(con) as c:
        var = c.execute("SELECT id, durum FROM portal_kullanici WHERE eposta=?", (eposta_n,)).fetchone()
        if var and var[1] == "aktif":
            return "var", None
        z = depo.simdi()
        if var:
            kid = var[0]
            c.execute("UPDATE portal_kullanici SET parola=?, dil=?, sirket=?, kayit_utc=? WHERE id=?", (ozet, dil, sirket, z, kid))
            c.execute("DELETE FROM portal_kod WHERE kullanici_id=?", (kid,))
        else:
            kid = c.execute("INSERT INTO portal_kullanici(eposta, parola, dil, sirket, kayit_utc) VALUES(?,?,?,?,?)",
                            (eposta_n, ozet, dil, sirket, z)).lastrowid
        kod = guvenlik.rastgele_kod()
        c.execute("INSERT INTO portal_kod(kod_sha256, kullanici_id, bitis_utc) VALUES(?,?,?)",
                  (guvenlik.ozet(kod), kid, _z(_simdi() + timedelta(hours=KOD_SAAT))))
        return "yeni", kod


def kod_bekleyen(con, kod):
    """Dogrulama bekleyen kullanicinin dili, yoksa None. Okuma: hicbir sey degistirmez (GET icin)."""
    s = con.execute("SELECT u.dil FROM portal_kod k JOIN portal_kullanici u ON u.id=k.kullanici_id "
                    "WHERE k.kod_sha256=? AND k.bitis_utc>? AND u.durum='bekliyor'", (_ozet(kod), depo.simdi())).fetchone()
    return s[0] if s else None


def dogrula(con, kod):
    """Kodu tek seferlik kullanir: hesap etkinlesir, firma olusur ya da mevcut firmaya baglanir, firma e-postasi dogrulanir.
    ("tamam", kullanici_id, firma_id) | ("pasif", ...) firma pasifse hesap etkinlesmez | ("yok", None, None)."""
    with depo.islem(con) as c:
        oz = _ozet(kod)
        s = c.execute("SELECT k.kullanici_id, u.eposta, u.sirket, u.durum FROM portal_kod k JOIN portal_kullanici u ON u.id=k.kullanici_id "
                      "WHERE k.kod_sha256=? AND k.bitis_utc>?", (oz, depo.simdi())).fetchone()
        if not s or c.execute("DELETE FROM portal_kod WHERE kod_sha256=?", (oz,)).rowcount != 1:
            return "yok", None, None
        kid, eposta, sirket, durum = s
        if durum != "bekliyor":
            return "yok", None, None
        firma = depo.firma_kaydet(c, depo.firma_anahtari(eposta), sirket, eposta, "portal")
        if firma["durum"] != "aktif":
            depo.denetim_ekle(c, "sistem", "pasif firma portal hesabi reddedildi, firma #%d" % firma["id"],
                              {"firma": firma["id"], "sonuc": "reddedildi", "neden": "pasif"})
            return "pasif", None, None
        z = depo.simdi()
        c.execute("UPDATE portal_kullanici SET durum='aktif', firma_id=?, dogrulama_utc=?, sirket='' WHERE id=?", (firma["id"], z, kid))
        if not firma["eposta_dogrulama_utc"]:
            depo.firma_eposta_dogrula(c, firma["id"], eposta)
        depo.denetim_ekle(c, "musteri", "portal hesabi dogrulandi, firma #%d" % firma["id"], {"firma": firma["id"], "kullanici": kid, "sonuc": "basarili"})
        return "tamam", kid, firma["id"]


# ---- giris, oturum ----

def _deneme_say(con, anahtar):
    esik = _z(_simdi() - timedelta(minutes=DENEME_PENCERE_DK))
    return con.execute("SELECT count(*) FROM portal_deneme WHERE anahtar=? AND zaman_utc>?", (anahtar, esik)).fetchone()[0]


def giris_engelli(con, eposta_n, ip):
    return _deneme_say(con, "e:" + _eposta_ozeti(eposta_n)) >= DENEME_EPOSTA or _deneme_say(con, "ip:" + depo.ip_ozeti(ip)) >= DENEME_IP


def giris(con, eposta, parola, ip):
    """(oturum_kodu, None) ya da (None, neden): hatali | engelli | pasif. Neden denetim icindir; ekranda 'hatali' ve
    'engelli' disindaki ayrim yalniz dogru parola verildiyse gosterilir (hesap varligi sizmasin)."""
    eposta_n = _eposta(eposta) or "?"
    ioz = depo.ip_ozeti(ip)
    if giris_engelli(con, eposta_n, ip):
        depo.denetim_ekle(con, "sistem", "portal girisi engellendi (cok fazla deneme)", {"sonuc": "reddedildi", "neden": "engelli", "ip_ozeti": ioz})
        return None, "engelli"
    satir = con.execute("SELECT id, parola, firma_id, durum FROM portal_kullanici WHERE eposta=?", (eposta_n,)).fetchone()
    # Kullanici yokken de ayni sure harcanir: zamanlama ile hesap varligi anlasilmasin
    ok = guvenlik.parola_dogrula(parola if isinstance(parola, str) and len(parola) <= PAROLA_EN_COK else "", satir[1] if satir else guvenlik.SAHTE_OZET)
    if not (satir and ok and satir[3] == "aktif"):
        with depo.islem(con) as c:
            z = _z(_simdi())
            c.executemany("INSERT INTO portal_deneme(anahtar, zaman_utc) VALUES(?,?)", [("e:" + _eposta_ozeti(eposta_n), z), ("ip:" + ioz, z)])
            depo.denetim_ekle(c, "sistem", "basarisiz portal girisi", {"sonuc": "basarisiz", "neden": "hatali", "ip_ozeti": ioz})
        return None, "hatali"
    with depo.islem(con) as c:
        f = depo.firma_getir(c, satir[2])
        if not f or f["durum"] != "aktif":
            depo.denetim_ekle(c, "sistem", "pasif firma portal girisi reddedildi, firma #%d" % satir[2], {"firma": satir[2], "kullanici": satir[0], "sonuc": "reddedildi", "neden": "pasif"})
            return None, "pasif"
        kod = guvenlik.rastgele_kod()
        z = _z(_simdi())
        c.execute("INSERT INTO portal_oturum VALUES(?,?,?,?,?)", (guvenlik.ozet(kod), satir[0], guvenlik.rastgele_kod(), z, z))
        c.execute("UPDATE portal_kullanici SET son_giris_utc=? WHERE id=?", (z, satir[0]))
        c.execute("DELETE FROM portal_deneme WHERE anahtar=?", ("e:" + _eposta_ozeti(eposta_n),))
        depo.denetim_ekle(c, "portal:%d" % satir[0], "portal girisi yapildi", {"firma": satir[2], "kullanici": satir[0], "sonuc": "basarili", "ip_ozeti": ioz})
        return kod, None


def cikis(con, kod):
    con.execute("DELETE FROM portal_oturum WHERE kod_sha256=?", (_ozet(kod),))
    con.commit()


def temizle(con):
    """Suresi dolan kod, oturum ve deneme kayitlari; 24 saatte dogrulanmayan hesap istekleri."""
    n = _simdi()
    con.execute("DELETE FROM portal_kod WHERE bitis_utc<=?", (depo.simdi(),))
    con.execute("DELETE FROM portal_oturum WHERE son_erisim_utc<? OR olusturma_utc<?",
                (_z(n - timedelta(minutes=OTURUM_BOSTA_DK)), _z(n - timedelta(hours=OTURUM_EN_COK_SAAT))))
    con.execute("DELETE FROM portal_deneme WHERE zaman_utc<?", (_z(n - timedelta(days=1)),))
    con.execute("DELETE FROM portal_kullanici WHERE durum='bekliyor' AND NOT EXISTS (SELECT 1 FROM portal_kod WHERE portal_kod.kullanici_id=portal_kullanici.id)")
    con.commit()


class Kapsam:
    """Bir firmanin verisine tek erisim yolu. Yalniz kapsam() olusturur. firma_id yalniz okunur."""
    __slots__ = ("_con", "_firma_id", "kullanici_id", "eposta", "dil", "firma_ad", "csrf")

    def __init__(self, con, firma_id, kullanici_id, eposta, dil, firma_ad, csrf, _izin=None):
        if _izin is not _KAPSAM_IZNI:
            raise TypeError("Kapsam yalniz portal_depo.kapsam() ile olusturulur")
        self._con, self._firma_id, self.kullanici_id, self.eposta, self.dil, self.firma_ad, self.csrf = con, firma_id, kullanici_id, eposta, dil, firma_ad, csrf

    @property
    def firma_id(self):
        return self._firma_id

    def raporlar(self, limit=100):
        """Firmanin dogrulanmis ve suresi dolmamis raporlari, yeniden eskiye."""
        return [depo._rapor(r) for r in self._con.execute(
            "SELECT %s FROM rapor WHERE firma_id=? AND dogrulandi=1 AND bitis_utc>? ORDER BY id DESC LIMIT ?" % depo._RAPOR_KOLON,
            (self._firma_id, depo.simdi(), int(limit)))]

    def rapor(self, rid):
        """Firmanin raporu; baska firmanin, silinmis, suresi dolmus ya da dogrulanmamis raporu icin None (varligi da sizmaz)."""
        if not isinstance(rid, int) or isinstance(rid, bool):
            return None
        return depo._rapor(self._con.execute(
            "SELECT %s FROM rapor WHERE id=? AND firma_id=? AND dogrulandi=1 AND bitis_utc>?" % depo._RAPOR_KOLON,
            (rid, self._firma_id, depo.simdi())).fetchone())

    def onceki(self, rapor):
        """rapor() ile alinmis raporun karsilastirma raporu (ayni firma ve sunucu kimligi); yoksa None."""
        if rapor is None or rapor.get("firma_id") != self._firma_id:
            return None
        return depo.onceki_rapor(self._con, rapor)

    def profil(self):
        return {"firma": self.firma_ad, "eposta": self.eposta, "dil": self.dil}

    def rapor_sil(self, rid):
        """Firmanin raporunu siler. Silinen sayi: baska firmanin ya da olmayan rapor icin 0 (varligi sizmaz)."""
        if not isinstance(rid, int) or isinstance(rid, bool):
            return 0
        with depo.islem(self._con) as c:
            n = c.execute("DELETE FROM rapor WHERE id=? AND firma_id=? AND dogrulandi=1", (rid, self._firma_id)).rowcount
            if n:
                depo.denetim_ekle(c, "portal:%d" % self.kullanici_id, "portal raporu silindi #%d" % rid,
                                  {"firma": self._firma_id, "rapor": rid, "kullanici": self.kullanici_id, "sonuc": "basarili"})
            return n

    def kullanim(self, sinir):
        """Ucretsiz tarama hakki: {sinir, kullanilan, kalan, gun, yenilenme_utc}. yenilenme_utc: en eski hakkin dondugu an
        (kullanilan 0 ise None). Sayim depo.kullanim_say ile ayni anahtar ve pencereyi kullanir."""
        f = depo.firma_getir(self._con, self._firma_id)
        anahtar = depo._firma_ozeti(f)
        esik = (datetime.now(timezone.utc) - timedelta(days=depo.SINIR_GUN)).strftime(BICIM)
        zamanlar = [r[0] for r in self._con.execute("SELECT zaman_utc FROM kullanim WHERE anahtar_sha256=? AND zaman_utc>? ORDER BY zaman_utc", (anahtar, esik))]
        yenilenme = None
        if zamanlar:
            yenilenme = _z(datetime.strptime(zamanlar[0], BICIM).replace(tzinfo=timezone.utc) + timedelta(days=depo.SINIR_GUN))
        return {"sinir": sinir, "kullanilan": len(zamanlar), "kalan": max(0, sinir - len(zamanlar)), "gun": depo.SINIR_GUN, "yenilenme_utc": yenilenme}

    def talepler(self, limit=100):
        """Firmanin talepleri, yeniden eskiye: [{id, tur, konu, mesaj, durum, olusturma_utc}]."""
        return [dict(zip(("id", "tur", "konu", "mesaj", "durum", "olusturma_utc"), r)) for r in self._con.execute(
            "SELECT id, tur, konu, mesaj, durum, olusturma_utc FROM portal_talep WHERE firma_id=? ORDER BY id DESC LIMIT ?", (self._firma_id, int(limit)))]

    def talep_ekle(self, tur, konu, mesaj):
        """Hizmet talebi: (id, None) ya da (None, neden): tur | konu | mesaj | sinir. Firma basina 24 saatte en cok TALEP_GUNLUK."""
        if tur not in HIZMET_TURLERI:
            return None, "tur"
        konu = konu.strip() if isinstance(konu, str) else ""
        mesaj = mesaj.strip() if isinstance(mesaj, str) else ""
        if not konu or len(konu) > KONU_EN_COK or any(ord(c) < 32 or ord(c) == 127 for c in konu):
            return None, "konu"
        if not mesaj or len(mesaj) > MESAJ_EN_COK or any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in mesaj):
            return None, "mesaj"
        with depo.islem(self._con) as c:
            esik = _z(_simdi() - timedelta(hours=24))
            if c.execute("SELECT count(*) FROM portal_talep WHERE firma_id=? AND tur!='silme' AND olusturma_utc>?", (self._firma_id, esik)).fetchone()[0] >= TALEP_GUNLUK:
                return None, "sinir"
            z = depo.simdi()
            tid = c.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, konu, mesaj, olusturma_utc, guncelleme_utc) VALUES(?,?,?,?,?,?,?)",
                            (self._firma_id, self.kullanici_id, tur, konu, mesaj, z, z)).lastrowid
            depo.denetim_ekle(c, "portal:%d" % self.kullanici_id, "portal hizmet talebi #%d (%s)" % (tid, tur),
                              {"firma": self._firma_id, "talep": tid, "kullanici": self.kullanici_id, "sonuc": "basarili"})
            return tid, None

    def silme_talebi_ekle(self):
        """Hesap ve verilerin silinmesi talebi: (id, True) yeni, (id, False) zaten acik talep var. Silme yonetici islemidir."""
        with depo.islem(self._con) as c:
            var = c.execute("SELECT id FROM portal_talep WHERE firma_id=? AND tur='silme' AND durum IN ('yeni', 'inceleniyor')", (self._firma_id,)).fetchone()
            if var:
                return var[0], False
            z = depo.simdi()
            tid = c.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) VALUES(?,?,'silme',?,?)",
                            (self._firma_id, self.kullanici_id, z, z)).lastrowid
            depo.denetim_ekle(c, "portal:%d" % self.kullanici_id, "portal veri silme talebi #%d" % tid,
                              {"firma": self._firma_id, "talep": tid, "kullanici": self.kullanici_id, "sonuc": "bekliyor"})
            return tid, True


_KAPSAM_IZNI = object()


def kapsam(con, kod):
    """Gecerli oturumdan Kapsam, yoksa None. Bosta 30 dk, en cok 8 saat; kullanici etkin, firma etkin olmali.
    Firma kimligi kullanici kaydindan okunur: oturum satirinda firma bilgisi tutulmaz (eskiyip yanlis kalamaz)."""
    if not isinstance(kod, str) or not kod:
        return None
    oz = guvenlik.ozet(kod)
    s = con.execute("SELECT o.csrf, o.olusturma_utc, o.son_erisim_utc, u.id, u.eposta, u.dil, u.durum, f.id, f.ad, f.durum "
                    "FROM portal_oturum o JOIN portal_kullanici u ON u.id=o.kullanici_id JOIN firma f ON f.id=u.firma_id "
                    "WHERE o.kod_sha256=?", (oz,)).fetchone()
    if not s:
        return None
    n = _simdi()
    ilk = datetime.strptime(s[1], BICIM).replace(tzinfo=timezone.utc)
    son = datetime.strptime(s[2], BICIM).replace(tzinfo=timezone.utc)
    if n - son > timedelta(minutes=OTURUM_BOSTA_DK) or n - ilk > timedelta(hours=OTURUM_EN_COK_SAAT) or s[6] != "aktif" or s[9] != "aktif":
        con.execute("DELETE FROM portal_oturum WHERE kod_sha256=?", (oz,))
        con.commit()
        return None
    con.execute("UPDATE portal_oturum SET son_erisim_utc=? WHERE kod_sha256=?", (_z(n), oz))
    con.commit()
    return Kapsam(con, s[7], s[3], s[4], s[5], s[8], s[0], _izin=_KAPSAM_IZNI)


def csrf_dogru(kapsam_, gelen):
    return isinstance(gelen, str) and hmac.compare_digest(kapsam_.csrf, gelen)
