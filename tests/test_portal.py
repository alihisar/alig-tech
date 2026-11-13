"""Musteri portali (tarama/portal_depo.py, tarama/portal.py): giris, e-posta dogrulama, firma izolasyonu.
Izolasyon veri erisim katmaninda sinanir: baska firmanin kaydina tahmin edilen kimlikle erisilemez."""
import http.client
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import depo, portal_depo, posta  # noqa: E402
from tarama import server as tserver  # noqa: E402
import test_tarama  # noqa: E402

PAROLA = "dogru-at-pil-9-sap"
IP = "192.0.2.10"


def yeni_db():
    con = depo.baglan(str(Path(tempfile.mkdtemp()) / "p.sqlite"))
    return con


def hesap_ac(con, eposta, sirket="Ornek AS", parola=PAROLA, dil="tr"):
    """Kayit ve dogrulama: (kullanici_id, firma_id)."""
    durum, kod = portal_depo.kayit(con, eposta, parola, sirket, dil)
    assert durum == "yeni", durum
    d, kid, fid = portal_depo.dogrula(con, kod)
    assert d == "tamam", d
    return kid, fid


def rapor_ekle(con, firma_id, zaman, token=None, **kw):
    b = test_tarama.temiz_belge()
    b["olusturma_utc"] = zaman
    depo.rapor_ekle(con, token or "t-%s-%s" % (firma_id, zaman), "postgresql", "tr", b, firma_id, **kw)
    return con.execute("SELECT max(id) FROM rapor").fetchone()[0]


def oturum(con, eposta, parola=PAROLA):
    kod, neden = portal_depo.giris(con, eposta, parola, IP)
    assert kod, neden
    return portal_depo.kapsam(con, kod)


class KayitTests(unittest.TestCase):
    def setUp(self):
        self.con = yeni_db()

    def test_gecersiz_girdi(self):
        for eposta, parola, sirket, kod in (
                ("yok", PAROLA, "A", "eposta"), ("", PAROLA, "A", "eposta"), (None, PAROLA, "A", "eposta"), ("a@b", PAROLA, "A", "eposta"),
                ("ali@ornek.com.tr", "kisa", "A", "parola"), ("ali@ornek.com.tr", "x" * 201, "A", "parola"), ("ali@ornek.com.tr", None, "A", "parola"),
                ("ali@ornek.com.tr", 12345678901234, "A", "parola"),
                ("ali@ornek.com.tr", PAROLA, "", "sirket"), ("ali@ornek.com.tr", PAROLA, "   ", "sirket"), ("ali@ornek.com.tr", PAROLA, "A" * 161, "sirket"),
                ("ali@ornek.com.tr", PAROLA, "A\nB", "sirket"), ("ali@ornek.com.tr", PAROLA, None, "sirket")):
            with self.assertRaises(portal_depo.PortalHata, msg=repr((eposta, parola, sirket))) as c:
                portal_depo.kayit(self.con, eposta, parola, sirket, "tr")
            self.assertEqual(c.exception.kod, kod)
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_kullanici").fetchone()[0], 0)

    def test_kayit_firma_olusturmaz_dogrulama_olusturur(self):
        durum, kod = portal_depo.kayit(self.con, "Ali@Ornek.com.tr", PAROLA, "Ornek AS", "tr")
        self.assertEqual(durum, "yeni")
        self.assertEqual(self.con.execute("SELECT count(*) FROM firma").fetchone()[0], 0)   # sahipligi kanitlanmadan firma yok
        self.assertEqual(self.con.execute("SELECT durum, firma_id, eposta FROM portal_kullanici").fetchone(), ("bekliyor", None, "ali@ornek.com.tr"))
        self.assertIsNone(portal_depo.kapsam(self.con, kod))
        d, kid, fid = portal_depo.dogrula(self.con, kod)
        self.assertEqual(d, "tamam")
        f = depo.firma_getir(self.con, fid)
        self.assertEqual((f["anahtar"], f["ad"], f["kaynak"]), ("ornek.com.tr", "Ornek AS", "portal"))
        self.assertTrue(f["eposta_dogrulama_utc"])
        self.assertEqual(self.con.execute("SELECT durum, firma_id, sirket FROM portal_kullanici").fetchone(), ("aktif", fid, ""))

    def test_kod_tek_kullanimlik_ve_sureli(self):
        _, kod = portal_depo.kayit(self.con, "ali@ornek.com.tr", PAROLA, "A", "tr")
        self.assertEqual(portal_depo.dogrula(self.con, kod)[0], "tamam")
        self.assertEqual(portal_depo.dogrula(self.con, kod), ("yok", None, None))
        _, kod2 = portal_depo.kayit(self.con, "veli@baska.com.tr", PAROLA, "B", "tr")
        self.con.execute("UPDATE portal_kod SET bitis_utc='2000-01-01T00:00:00Z'")
        self.assertEqual(portal_depo.dogrula(self.con, kod2), ("yok", None, None))
        self.assertIsNone(portal_depo.kod_bekleyen(self.con, kod2))
        for kotu in (None, "", "x", 5, "A" * 43):
            self.assertEqual(portal_depo.dogrula(self.con, kotu), ("yok", None, None), repr(kotu))

    def test_kod_ham_saklanmaz(self):
        _, kod = portal_depo.kayit(self.con, "ali@ornek.com.tr", PAROLA, "A", "tr")
        ham = json.dumps(self.con.execute("SELECT * FROM portal_kod").fetchall())
        self.assertNotIn(kod, ham)
        self.assertNotIn(PAROLA, json.dumps(self.con.execute("SELECT * FROM portal_kullanici").fetchall()))

    def test_okuma_hicbir_sey_degistirmez(self):
        _, kod = portal_depo.kayit(self.con, "ali@ornek.com.tr", PAROLA, "A", "en")
        self.assertEqual(portal_depo.kod_bekleyen(self.con, kod), "en")
        self.assertEqual(portal_depo.kod_bekleyen(self.con, kod), "en")   # tekrar: hala gecerli
        self.assertEqual(self.con.execute("SELECT durum FROM portal_kullanici").fetchone()[0], "bekliyor")

    def test_etkin_hesap_varken_yeni_hesap_acilmaz_parola_degismez(self):
        hesap_ac(self.con, "ali@ornek.com.tr")
        onceki = self.con.execute("SELECT parola FROM portal_kullanici").fetchone()[0]
        durum, kod = portal_depo.kayit(self.con, "ali@ornek.com.tr", "baska-bir-parola-123", "X", "tr")
        self.assertEqual((durum, kod), ("var", None))
        self.assertEqual(self.con.execute("SELECT parola FROM portal_kullanici").fetchone()[0], onceki)
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_kod").fetchone()[0], 0)
        self.assertTrue(oturum(self.con, "ali@ornek.com.tr"))   # eski parola gecerli

    def test_baskasinin_adresine_parola_yerlestirme(self):
        """Saldirgan kurbanin adresiyle kendi parolasini kaydeder; adresin sahibi dogrulama baglantisini acmadikca hesap yok.
        Kurban kendi istegini yapinca saldirganin parolasi ve kodu gecersiz olur."""
        _, kod_saldirgan = portal_depo.kayit(self.con, "kurban@kurum.com.tr", "saldirgan-parola-1", "Kurum", "tr")
        self.assertIsNone(portal_depo.giris(self.con, "kurban@kurum.com.tr", "saldirgan-parola-1", IP)[0])   # dogrulanmadan giris yok
        _, kod_kurban = portal_depo.kayit(self.con, "kurban@kurum.com.tr", "kurbanin-parolasi-2", "Kurum", "tr")
        self.assertEqual(portal_depo.dogrula(self.con, kod_saldirgan), ("yok", None, None))
        self.assertEqual(portal_depo.dogrula(self.con, kod_kurban)[0], "tamam")
        self.assertIsNone(portal_depo.giris(self.con, "kurban@kurum.com.tr", "saldirgan-parola-1", IP)[0])
        self.assertTrue(portal_depo.giris(self.con, "kurban@kurum.com.tr", "kurbanin-parolasi-2", IP)[0])
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_kullanici").fetchone()[0], 1)

    def test_pasif_firmaya_hesap_etkinlesmez(self):
        f = depo.firma_kaydet(self.con, "kurum.com.tr", "Kurum", "x@kurum.com.tr", "tarama")
        depo.firma_durum_yaz(self.con, f["id"], "pasif")
        _, kod = portal_depo.kayit(self.con, "ali@kurum.com.tr", PAROLA, "Kurum", "tr")
        self.assertEqual(portal_depo.dogrula(self.con, kod)[0], "pasif")
        self.assertIsNone(portal_depo.giris(self.con, "ali@kurum.com.tr", PAROLA, IP)[0])

    def test_ayni_kurumsal_alan_ayni_firma_serbest_posta_ayri(self):
        _, f1 = hesap_ac(self.con, "ali@kurum.com.tr", "Kurum")
        _, f2 = hesap_ac(self.con, "veli@kurum.com.tr", "Kurum")
        _, f3 = hesap_ac(self.con, "ali@gmail.com", "Ali")
        _, f4 = hesap_ac(self.con, "veli@gmail.com", "Veli")
        self.assertEqual(f1, f2)
        self.assertEqual(len({f1, f3, f4}), 3)


class GirisTests(unittest.TestCase):
    def setUp(self):
        self.con = yeni_db()
        self.kid, self.fid = hesap_ac(self.con, "ali@ornek.com.tr")

    def test_basarili_giris_ve_kapsam(self):
        ks = oturum(self.con, "Ali@Ornek.com.tr")
        self.assertEqual((ks.kullanici_id, ks.firma_id, ks.firma_ad, ks.eposta), (self.kid, self.fid, "Ornek AS", "ali@ornek.com.tr"))
        self.assertTrue(ks.csrf)
        self.assertEqual(ks.profil(), {"firma": "Ornek AS", "eposta": "ali@ornek.com.tr", "dil": "tr"})

    def test_hatali_giris_nedenleri_ayirt_edilmez(self):
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", "yanlis-parola-123", IP), (None, "hatali"))
        self.assertEqual(portal_depo.giris(self.con, "yok@ornek.com.tr", PAROLA, IP), (None, "hatali"))
        for kotu in (None, "", 5, ["x"]):
            self.assertEqual(portal_depo.giris(self.con, kotu, kotu, IP)[0], None)
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", "x" * 10000, IP), (None, "hatali"))

    def test_dogrulanmamis_hesapla_giris_yok(self):
        portal_depo.kayit(self.con, "yeni@ornek.com.tr", PAROLA, "A", "tr")
        self.assertEqual(portal_depo.giris(self.con, "yeni@ornek.com.tr", PAROLA, IP), (None, "hatali"))

    def test_eposta_basina_engel_dogru_parola_da_reddedilir(self):
        for _ in range(portal_depo.DENEME_EPOSTA):
            self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", "yanlis-parola-123", IP)[1], "hatali")
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP), (None, "engelli"))
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, "198.51.100.7"), (None, "engelli"))   # baska IP'den de

    def test_ip_basina_engel(self):
        for i in range(portal_depo.DENEME_IP):
            portal_depo.giris(self.con, "kisi%d@ornek.com.tr" % i, "yanlis-parola-123", IP)
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP), (None, "engelli"))
        self.assertTrue(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, "198.51.100.7")[0])

    def test_basarili_giris_sayaci_sifirlar(self):
        for _ in range(portal_depo.DENEME_EPOSTA - 1):
            portal_depo.giris(self.con, "ali@ornek.com.tr", "yanlis-parola-123", IP)
        self.assertTrue(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, "198.51.100.7")[0])
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_deneme WHERE anahtar LIKE 'e:%'").fetchone()[0], 0)

    def test_eski_denemeler_engellemez(self):
        for _ in range(portal_depo.DENEME_EPOSTA):
            portal_depo.giris(self.con, "ali@ornek.com.tr", "yanlis-parola-123", IP)
        eski = (datetime.now(timezone.utc) - timedelta(minutes=portal_depo.DENEME_PENCERE_DK + 1)).strftime(portal_depo.BICIM)
        self.con.execute("UPDATE portal_deneme SET zaman_utc=?", (eski,))
        self.assertTrue(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)[0])

    def test_oturum_bosta_ve_toplam_sure(self):
        kod, _ = portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)
        self.assertTrue(portal_depo.kapsam(self.con, kod))
        z = lambda **k: (datetime.now(timezone.utc) - timedelta(**k)).strftime(portal_depo.BICIM)   # noqa: E731
        self.con.execute("UPDATE portal_oturum SET son_erisim_utc=?", (z(minutes=portal_depo.OTURUM_BOSTA_DK + 1),))
        self.assertIsNone(portal_depo.kapsam(self.con, kod))
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_oturum").fetchone()[0], 0)
        kod, _ = portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)
        self.con.execute("UPDATE portal_oturum SET olusturma_utc=?", (z(hours=portal_depo.OTURUM_EN_COK_SAAT, minutes=1),))
        self.assertIsNone(portal_depo.kapsam(self.con, kod))

    def test_oturum_kodu_ham_saklanmaz_ve_cikis_siler(self):
        kod, _ = portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)
        self.assertNotIn(kod, json.dumps(self.con.execute("SELECT * FROM portal_oturum").fetchall()))
        portal_depo.cikis(self.con, kod)
        self.assertIsNone(portal_depo.kapsam(self.con, kod))
        for kotu in (None, "", "x", 5, "A" * 43):
            self.assertIsNone(portal_depo.kapsam(self.con, kotu), repr(kotu))

    def test_pasif_firma_oturumu_ve_girisi_gecersiz(self):
        kod, _ = portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)
        depo.firma_durum_yaz(self.con, self.fid, "pasif")
        self.assertIsNone(portal_depo.kapsam(self.con, kod))
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP), (None, "pasif"))
        depo.firma_durum_yaz(self.con, self.fid, "aktif")
        self.assertTrue(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)[0])

    def test_firma_silinince_kullanici_ve_oturum_gider(self):
        kod, _ = portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)
        portal_depo.kayit(self.con, "bekleyen@ornek.com.tr", PAROLA, "A", "tr")   # ayni firmaya bagli degil (henuz firmasiz)
        depo.firma_sil(self.con, self.fid)
        self.assertIsNone(portal_depo.kapsam(self.con, kod))
        self.assertEqual(portal_depo.giris(self.con, "ali@ornek.com.tr", PAROLA, IP)[0], None)
        for tablo in ("portal_oturum", "portal_kod"):
            self.assertEqual(self.con.execute("SELECT count(*) FROM %s WHERE kullanici_id=?" % tablo, (self.kid,)).fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_kullanici WHERE firma_id=?", (self.fid,)).fetchone()[0], 0)

    def test_dogrulanmis_kullanicinin_firmasi_zorunlu(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE portal_kullanici SET firma_id=NULL WHERE id=?", (self.kid,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE portal_kullanici SET durum='yonetici' WHERE id=?", (self.kid,))

    def test_temizle(self):
        portal_depo.kayit(self.con, "bekleyen@ornek.com.tr", PAROLA, "A", "tr")
        self.con.execute("UPDATE portal_kod SET bitis_utc='2000-01-01T00:00:00Z'")
        portal_depo.temizle(self.con)
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_kullanici WHERE durum='bekliyor'").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM portal_kullanici WHERE durum='aktif'").fetchone()[0], 1)


class IzolasyonTests(unittest.TestCase):
    """Firma A kullanicisi, firma B'nin verisine hicbir yoldan erisemez."""

    def setUp(self):
        self.con = yeni_db()
        _, self.fa = hesap_ac(self.con, "ali@firma-a.com.tr", "Firma A")
        _, self.fb = hesap_ac(self.con, "veli@firma-b.com.tr", "Firma B")
        self.a = rapor_ekle(self.con, self.fa, "2026-11-01T10:00:00Z")
        self.a2 = rapor_ekle(self.con, self.fa, "2026-11-05T10:00:00Z")
        self.b = rapor_ekle(self.con, self.fb, "2026-11-02T10:00:00Z")
        self.b2 = rapor_ekle(self.con, self.fb, "2026-11-06T10:00:00Z")
        self.ks_a = oturum(self.con, "ali@firma-a.com.tr")
        self.ks_b = oturum(self.con, "veli@firma-b.com.tr")

    def test_liste_yalniz_kendi_firmasi(self):
        self.assertEqual([r["id"] for r in self.ks_a.raporlar()], [self.a2, self.a])
        self.assertEqual([r["id"] for r in self.ks_b.raporlar()], [self.b2, self.b])
        self.assertTrue(all(r["firma_id"] == self.fa for r in self.ks_a.raporlar()))

    def test_baska_firmanin_raporu_tahmin_edilen_kimlikle_bulunamaz(self):
        for rid in (self.b, self.b2):
            self.assertIsNone(self.ks_a.rapor(rid))
        for rid in (self.a, self.a2):
            self.assertIsNone(self.ks_b.rapor(rid))
            self.assertEqual(self.ks_a.rapor(rid)["id"], rid)

    def test_var_olmayan_kimlik_ile_baska_firma_ayni_yanit(self):
        self.assertIsNone(self.ks_a.rapor(self.b))
        self.assertIsNone(self.ks_a.rapor(99999))   # kaydin varligi sizmaz: ikisi de None

    def test_butun_kimlikler_taranir(self):
        """Veritabanindaki her rapor kimligi icin yalniz sahibi bulur."""
        sahip = {self.a: self.ks_a, self.a2: self.ks_a, self.b: self.ks_b, self.b2: self.ks_b}
        for rid in range(0, 50):
            for ks in (self.ks_a, self.ks_b):
                r = ks.rapor(rid)
                self.assertEqual(r is not None, sahip.get(rid) is ks, "rapor %d, firma %d" % (rid, ks.firma_id))

    def test_kotu_kimlik_turleri(self):
        for kotu in ("1", "1 OR 1=1", "1; DROP TABLE rapor", None, True, False, 1.0, -1, 0, [self.b], {"id": self.b}, b"1", 10 ** 30):
            try:
                r = self.ks_a.rapor(kotu)
            except OverflowError:
                continue   # sqlite tamsayi siniri: veri donmez
            self.assertIsNone(r if kotu not in (self.a, self.a2) else None, repr(kotu))
        self.assertEqual(self.con.execute("SELECT count(*) FROM rapor").fetchone()[0], 4)

    def test_dogrulanmamis_suresi_dolmus_rapor_gorunmez(self):
        bekleyen = rapor_ekle(self.con, self.fa, "2026-11-07T10:00:00Z", dogrulandi=False)
        self.assertIsNone(self.ks_a.rapor(bekleyen))
        self.assertNotIn(bekleyen, [r["id"] for r in self.ks_a.raporlar()])
        self.con.execute("UPDATE rapor SET bitis_utc='2000-01-01T00:00:00Z' WHERE id=?", (self.a,))
        self.assertIsNone(self.ks_a.rapor(self.a))
        self.assertNotIn(self.a, [r["id"] for r in self.ks_a.raporlar()])

    def test_onceki_rapor_baska_firmadan_gelmez(self):
        import test_gecmis
        con = yeni_db()
        _, fa = hesap_ac(con, "ali@firma-a.com.tr", "A")
        _, fb = hesap_ac(con, "veli@firma-b.com.tr", "B")
        for fid, zaman in ((fb, "2026-11-01T00:00:00Z"), (fa, "2026-11-02T00:00:00Z"), (fa, "2026-11-05T00:00:00Z"), (fb, "2026-11-06T00:00:00Z")):
            depo.rapor_ekle(con, "t%s%s" % (fid, zaman), "postgresql", "tr", test_gecmis.belge(zaman=zaman), fid)
        ids = [r[0] for r in con.execute("SELECT id FROM rapor ORDER BY id")]
        ks = oturum(con, "ali@firma-a.com.tr")
        yeni = ks.rapor(ids[2])
        self.assertEqual(ks.onceki(yeni)["id"], ids[1])   # firma B'nin daha eski raporu degil
        self.assertIsNone(ks.onceki(ks.rapor(ids[1])))    # A'nin kendi onceki raporu yok; B'ninki sayilmaz
        yabanci = depo.rapor_getir_id(con, ids[3])         # B'nin, kendi eski raporu olan kaydi
        self.assertEqual(depo.onceki_rapor(con, yabanci)["id"], ids[0])
        self.assertIsNone(ks.onceki(yabanci))              # ama A'nin kapsami onu karsilastirmaz

    def test_kapsam_disaridan_uretilemez_firma_degistirilemez(self):
        with self.assertRaises(TypeError):
            portal_depo.Kapsam(self.con, self.fb, 1, "x", "tr", "B", "c")
        with self.assertRaises(TypeError):
            portal_depo.Kapsam(self.con, self.fb, 1, "x", "tr", "B", "c", _izin=object())
        with self.assertRaises(AttributeError):
            self.ks_a.firma_id = self.fb
        with self.assertRaises(AttributeError):
            self.ks_a.yeni_alan = 1   # __slots__
        self.assertEqual(self.ks_a.firma_id, self.fa)

    def test_oturum_baska_kullanicinin_kapsamini_vermez(self):
        kod_a, _ = portal_depo.giris(self.con, "ali@firma-a.com.tr", PAROLA, IP)
        self.assertEqual(portal_depo.kapsam(self.con, kod_a).firma_id, self.fa)
        # oturum satirinin sahibi degistirilirse (veri bozulmasi) kapsam yine kullanici kaydindan gelir, istekten degil
        self.con.execute("UPDATE portal_oturum SET kullanici_id=(SELECT id FROM portal_kullanici WHERE eposta='veli@firma-b.com.tr')")
        self.assertEqual(portal_depo.kapsam(self.con, kod_a).firma_id, self.fb)

    def test_ayni_firmanin_iki_kullanicisi_ayni_raporlari_gorur(self):
        hesap_ac(self.con, "ayse@firma-a.com.tr", "Firma A")
        ks2 = oturum(self.con, "ayse@firma-a.com.tr")
        self.assertEqual([r["id"] for r in ks2.raporlar()], [r["id"] for r in self.ks_a.raporlar()])
        self.assertEqual(ks2.firma_id, self.fa)

    def test_katman_kaynak_kodu_firma_kosulunu_tasir(self):
        """Statik koruma: portal_depo'daki her rapor sorgusu firma kosulu tasir; portal.py rapor tablosuna dogrudan erismez."""
        kaynak = (ROOT / "tarama" / "portal_depo.py").read_text(encoding="utf-8")
        for sorgu in re.findall(r'"(SELECT [^"]*FROM rapor[^"]*)"', kaynak):
            self.assertIn("firma_id=?", sorgu, sorgu)
        sayfa = (ROOT / "tarama" / "portal.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"depo\.(rapor_getir|rapor_getir_id|rapor_listele|rapor_bekleyen_getir|onceki_rapor|rapor_sil|rapor_sil_id)", sayfa))
        self.assertNotIn("FROM rapor", sayfa)
        self.assertNotIn("firma_id", re.sub(r"\{\"firma\": ks\.firma_id.*", "", sayfa).replace("ks.firma_id", ""))   # firma kimligi istekten okunmaz


class HttpTaban(test_tarama._SunucuTaban):
    H_EK = {"eposta_dogrulama": True, "site_adresi": "https://alig.test", "portal": True, "portal_cerez_guvenli": False}

    def istek(self, yontem, yol, form=None, cerez=None, origin=True, ek=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        from urllib.parse import urlencode
        h = dict(ek or {})
        govde = None
        if form is not None:
            govde = urlencode(form)
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if cerez:
            h["Cookie"] = "alig_portal=%s" % cerez
        if origin is True:
            h["Origin"] = "http://127.0.0.1:%d" % self.srv.server_port
        elif origin:
            h["Origin"] = origin
        c.request(yontem, yol, body=govde, headers=h)
        r = c.getresponse()
        r.govde = r.read().decode("utf-8", "replace")
        return r

    def con(self):
        return depo.baglan(self.db)

    def posta_baglantisi(self, alici):
        satirlar = self.con().execute("SELECT metin FROM posta WHERE alici=? ORDER BY id DESC", (alici,)).fetchall()
        m = re.search(r"https://alig\.test(/portal/dogrula/[A-Za-z0-9_\-]{43})", satirlar[0][0]) if satirlar else None
        return m.group(1) if m else None

    def hesap(self, eposta="ali@ornek.com.tr", sirket="Ornek AS", parola=PAROLA):
        r = self.istek("POST", "/portal/kayit", {"eposta": eposta, "parola": parola, "sirket": sirket, "dil": "tr"})
        self.assertEqual(r.status, 200, r.govde[:300])
        yol = self.posta_baglantisi(eposta)
        self.assertTrue(yol)
        self.assertEqual(self.istek("POST", yol, {"dil": "tr"}).status, 200)

    def giris(self, eposta="ali@ornek.com.tr", parola=PAROLA):
        r = self.istek("POST", "/portal/giris", {"eposta": eposta, "parola": parola, "dil": "tr"})
        m = re.search(r"alig_portal=([^;]+)", r.getheader("Set-Cookie") or "")
        return r, (m.group(1) if m else None)


class KapaliTests(test_tarama._SunucuTaban):
    def test_varsayilan_kapali(self):
        for yol in ("/portal/", "/portal", "/portal/kayit", "/portal/rapor/1/"):
            c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
            c.request("GET", yol)
            r = c.getresponse()
            self.assertIn(r.status, (301, 404), yol)
            if r.status == 301:
                c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
                c.request("GET", "/portal/")
                self.assertEqual(c.getresponse().status, 404)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/portal/giris", body="a=b", headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(c.getresponse().status, 404)

    def test_portal_ayarla_yalniz_dogrulamayla(self):
        H = type("H", (tserver.H,), {})
        self.assertFalse(tserver.portal_ayarla({}, H))
        self.assertFalse(H.portal)
        with self.assertRaises(ValueError):
            tserver.portal_ayarla({"ALIG_PORTAL": "1"}, H)   # e-posta dogrulamasi kapali: acilmaz
        self.assertFalse(H.portal)
        tserver.eposta_ayarla({"ALIG_EPOSTA_DOGRULAMA": "1", "ALIG_SITE_ADRESI": "https://alig.test"}, H)
        self.assertFalse(tserver.portal_ayarla({"ALIG_PORTAL": "0"}, H))
        self.assertTrue(tserver.portal_ayarla({"ALIG_PORTAL": "1"}, H))
        self.assertTrue(H.portal and H.portal_cerez_guvenli)


class SunucuTests(HttpTaban):
    def test_kayit_dogrulama_giris_ve_panel(self):
        r = self.istek("POST", "/portal/kayit", {"eposta": "ali@ornek.com.tr", "parola": PAROLA, "sirket": "Ornek AS", "dil": "tr"})
        self.assertEqual(r.status, 200)
        self.assertIn("İstek alındı", r.govde)
        yol = self.posta_baglantisi("ali@ornek.com.tr")
        self.assertTrue(yol)
        # GET hicbir sey degistirmez
        g = self.istek("GET", yol)
        self.assertEqual(g.status, 200)
        self.assertIn("Hesabı etkinleştir", g.govde)
        self.assertEqual(self.con().execute("SELECT durum FROM portal_kullanici").fetchone()[0], "bekliyor")
        self.assertEqual(self.giris()[0].status, 401)   # henuz giris yok
        p = self.istek("POST", yol, {"dil": "tr"})
        self.assertIn("Hesabınız etkinleştirildi", p.govde)
        self.assertEqual(self.istek("POST", yol, {"dil": "tr"}).status, 404)   # tek kullanimlik
        g, kod = self.giris()
        self.assertEqual((g.status, g.getheader("Location")), (303, "/portal/"))
        cerez = g.getheader("Set-Cookie")
        for parca in ("HttpOnly", "SameSite=Strict", "Path=/portal"):
            self.assertIn(parca, cerez)
        self.assertNotIn("Secure", cerez)   # bu testte portal_cerez_guvenli=False
        panel = self.istek("GET", "/portal/", cerez=kod)
        self.assertIn("Ornek AS", panel.govde)
        self.assertIn("Henüz raporunuz yok", panel.govde)
        self.assertNotIn("alig.test", panel.govde)

    def test_https_kurulumunda_cerez_secure(self):
        self.H.portal_cerez_guvenli = True
        self.hesap()
        g, _ = self.giris()
        self.assertIn("; Secure", g.getheader("Set-Cookie"))

    def test_guvenlik_basliklari(self):
        for yol in ("/portal/", "/portal/kayit"):
            r = self.istek("GET", yol)
            self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
            self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            self.assertNotIn("<script", r.govde)

    def test_hesap_varligi_ekrandan_anlasilmaz(self):
        self.hesap()
        yeni = self.istek("POST", "/portal/kayit", {"eposta": "yeni@ornek.com.tr", "parola": PAROLA, "sirket": "X", "dil": "tr"})
        var = self.istek("POST", "/portal/kayit", {"eposta": "ali@ornek.com.tr", "parola": PAROLA, "sirket": "X", "dil": "tr"})
        self.assertEqual((yeni.status, yeni.govde), (var.status, var.govde))
        konu = self.con().execute("SELECT konu FROM posta WHERE alici='ali@ornek.com.tr' ORDER BY id DESC").fetchone()[0]
        self.assertIn("zaten var", konu)   # bilgi yalniz adresin sahibine gider
        yanlis = self.giris("ali@ornek.com.tr", "yanlis-parola-123")[0]
        yok = self.giris("yok@ornek.com.tr", "yanlis-parola-123")[0]
        self.assertEqual((yanlis.status, yanlis.govde), (yok.status, yok.govde))

    def test_kayit_ayni_adrese_posta_siniri(self):
        for _ in range(5):
            r = self.istek("POST", "/portal/kayit", {"eposta": "ali@ornek.com.tr", "parola": PAROLA, "sirket": "X", "dil": "tr"})
            self.assertEqual(r.status, 200)
        self.assertEqual(self.con().execute("SELECT count(*) FROM posta WHERE alici='ali@ornek.com.tr'").fetchone()[0], self.H.posta_adres_siniri)

    def test_kayit_dogrulama_hatalari(self):
        for form, metin in (({"eposta": "x", "parola": PAROLA, "sirket": "A"}, "Geçerli bir e-posta"),
                            ({"eposta": "a@ornek.com.tr", "parola": "kisa", "sirket": "A"}, "Parola 12 ile 200"),
                            ({"eposta": "a@ornek.com.tr", "parola": PAROLA, "sirket": ""}, "Firma adını girin")):
            r = self.istek("POST", "/portal/kayit", dict(form, dil="tr"))
            self.assertEqual(r.status, 422)
            self.assertIn(metin, r.govde)
        self.assertEqual(self.con().execute("SELECT count(*) FROM posta").fetchone()[0], 0)

    def test_baska_kaynaktan_ya_da_kaynaksiz_post_reddedilir(self):
        form = {"eposta": "ali@ornek.com.tr", "parola": PAROLA, "sirket": "A", "dil": "tr"}
        for origin in ("https://kotu.example", "http://127.0.0.1:1", False, "null"):
            self.assertEqual(self.istek("POST", "/portal/kayit", form, origin=origin).status, 403, repr(origin))
        self.assertEqual(self.con().execute("SELECT count(*) FROM portal_kullanici").fetchone()[0], 0)
        self.hesap()
        g, kod = self.giris()
        self.assertEqual(self.istek("POST", "/portal/giris", {"eposta": "ali@ornek.com.tr", "parola": PAROLA}, origin="https://kotu.example").status, 403)
        ks = portal_depo.kapsam(self.con(), kod)
        r = self.istek("POST", "/portal/cikis", {"csrf": ks.csrf}, cerez=kod, origin="https://kotu.example")
        self.assertEqual(r.status, 403)
        self.assertTrue(portal_depo.kapsam(self.con(), kod))   # oturum duruyor

    def test_cikis_csrf_ister(self):
        self.hesap()
        _, kod = self.giris()
        self.assertEqual(self.istek("POST", "/portal/cikis", {"csrf": "yanlis"}, cerez=kod).status, 303)
        self.assertTrue(portal_depo.kapsam(self.con(), kod))   # yanlis csrf: oturum kapanmaz
        csrf = portal_depo.kapsam(self.con(), kod).csrf
        r = self.istek("POST", "/portal/cikis", {"csrf": csrf}, cerez=kod)
        self.assertEqual(r.status, 303)
        self.assertIn("Max-Age=0", r.getheader("Set-Cookie"))
        self.assertIsNone(portal_depo.kapsam(self.con(), kod))

    def test_panel_formunda_csrf_var(self):
        self.hesap()
        _, kod = self.giris()
        panel = self.istek("GET", "/portal/", cerez=kod).govde
        csrf = portal_depo.kapsam(self.con(), kod).csrf
        self.assertIn('name="csrf" value="%s"' % csrf, panel)

    def test_giris_engeli_http(self):
        self.hesap()
        for _ in range(portal_depo.DENEME_EPOSTA):
            self.assertEqual(self.giris(parola="yanlis-parola-123")[0].status, 401)
        r, kod = self.giris()
        self.assertEqual(r.status, 429)
        self.assertIsNone(kod)
        self.assertTrue(r.getheader("Retry-After"))

    def test_rapor_izolasyonu_http(self):
        self.hesap("ali@firma-a.com.tr", "Firma A")
        self.hesap("veli@firma-b.com.tr", "Firma B")
        con = self.con()
        fa = depo.firma_getir(con, 1)["id"]
        fb = [f for f in depo.firma_listele(con) if f["id"] != fa][0]["id"]
        a = rapor_ekle(con, fa, "2026-11-01T10:00:00Z")
        b = rapor_ekle(con, fb, "2026-11-02T10:00:00Z")
        _, kod_a = self.giris("ali@firma-a.com.tr")
        _, kod_b = self.giris("veli@firma-b.com.tr")
        # kendi raporu: iki gorunum
        own = self.istek("GET", "/portal/rapor/%d/" % a, cerez=kod_a)
        self.assertEqual(own.status, 200)
        self.assertIn("Denetim sonuçları", own.govde)
        self.assertIn("Genel durum", self.istek("GET", "/portal/rapor/%d/?gorunum=yonetici" % a, cerez=kod_a).govde)
        self.assertNotIn("/sil", own.govde)   # silme bu dilimde yok; token yok
        # baska firmanin raporu: var olmayan kimlikle ayni yanit
        yabanci = self.istek("GET", "/portal/rapor/%d/" % b, cerez=kod_a)
        yok = self.istek("GET", "/portal/rapor/99999/", cerez=kod_a)
        self.assertEqual((yabanci.status, yabanci.govde), (404, yok.govde))
        self.assertEqual(self.istek("GET", "/portal/rapor/%d/" % a, cerez=kod_b).status, 404)
        # liste
        self.assertIn('href="/portal/rapor/%d/"' % a, self.istek("GET", "/portal/", cerez=kod_a).govde)
        self.assertNotIn('href="/portal/rapor/%d/"' % b, self.istek("GET", "/portal/", cerez=kod_a).govde)
        # oturumsuz
        for yol in ("/portal/rapor/%d/" % a, "/portal/rapor/%d/" % b):
            r = self.istek("GET", yol)
            self.assertEqual((r.status, r.getheader("Location")), (303, "/portal/"))
        # sahte cerez
        self.assertEqual(self.istek("GET", "/portal/rapor/%d/" % a, cerez="x" * 43).status, 303)

    def test_rapor_kimligi_yolu_katidir(self):
        self.hesap()
        _, kod = self.giris()
        for yol in ("/portal/rapor/abc/", "/portal/rapor/1/../2/", "/portal/rapor/-1/", "/portal/rapor/", "/portal/rapor/99999999999999999999/",
                    "/portal/rapor/1/sil", "/portal/dogrula/kisa", "/portal/baska"):
            self.assertIn(self.istek("GET", yol, cerez=kod).status, (404,), yol)

    def test_denetim_zinciri_ve_gizli_veri(self):
        self.hesap()
        con = self.con()
        fid = depo.firma_listele(con)[0]["id"]
        rid = rapor_ekle(con, fid, "2026-11-01T10:00:00Z")
        self.giris(parola="yanlis-parola-123")
        _, kod = self.giris()
        self.istek("GET", "/portal/rapor/%d/" % rid, cerez=kod)
        self.istek("POST", "/portal/cikis", {"csrf": portal_depo.kapsam(self.con(), kod).csrf}, cerez=kod)
        con = self.con()
        self.assertIsNone(depo.denetim_dogrula(con))
        olaylar = [x[0] for x in con.execute("SELECT olay FROM denetim")]
        for beklenen in ("portal hesabi dogrulandi", "basarisiz portal girisi", "portal girisi yapildi", "portal raporu goruntulendi #%d" % rid, "portal cikisi yapildi"):
            self.assertTrue(any(beklenen in o for o in olaylar), beklenen)
        ham = json.dumps(con.execute("SELECT aktor, olay, alanlar FROM denetim").fetchall())
        for gizli in (PAROLA, "yanlis-parola-123", "ali@ornek.com.tr", kod, IP, "127.0.0.1"):
            self.assertNotIn(gizli, ham)

    def test_tokenli_rapor_baglantisi_etkilenmez(self):
        con = self.con()
        f = depo.firma_kaydet(con, "kurum.com.tr", "Kurum", "x@kurum.com.tr", "tarama")
        depo.rapor_ekle(con, "T" * 43, "postgresql", "tr", test_tarama.temiz_belge(), f["id"])
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("GET", "/rapor/%s/" % ("T" * 43))
        self.assertEqual(c.getresponse().status, 200)

    def test_ingilizce(self):
        r = self.istek("GET", "/portal/?dil=en")
        self.assertIn("Sign in", r.govde)
        self.assertIn('lang="en"', r.govde)
        self.assertIn("Request an account", self.istek("GET", "/portal/kayit?dil=en").govde)
        self.assertIn("Girş" if False else "Giriş yap", self.istek("GET", "/portal/?dil=xx").govde)   # gecersiz dil: Turkce

    def test_xss(self):
        self.hesap("ali@ornek.com.tr", "<script>alert(1)</script>")
        _, kod = self.giris()
        panel = self.istek("GET", "/portal/", cerez=kod).govde
        self.assertNotIn("<script>alert(1)", panel)
        self.assertIn("&lt;script&gt;", panel)


if __name__ == "__main__":
    unittest.main()
