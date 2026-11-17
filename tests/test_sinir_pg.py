"""ALIG-DB-003e: atomic rate limiter on PostgreSQL (ortak/sinir_pg.py, db/sema/0007_sinir_sayac.sql).
Real concurrency: threads with their own connections and separate OS processes against a temporary PostgreSQL 16 cluster.
SKIPped (never PASS) when PostgreSQL 16 or libpq is missing."""
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_sema_kume  # noqa: E402
import pg_yardimci  # noqa: E402
from ortak import pg  # noqa: E402
from ortak import sinir_pg  # noqa: E402
from ortak.pg_havuz import Havuz  # noqa: E402


class BirimTests(unittest.TestCase):
    """No server needed."""

    def test_politika_tablosu_gerekli_uclari_kapsar(self):
        for ad in ("iletisim", "yukle", "yonetim_giris", "rapor_dogrulama", "tarama_baslat", "rapor_goruntule",
                   "tarama_baglan", "tarama_baglan_token", "portal_kayit", "portal_giris"):
            self.assertIn(ad, sinir_pg.SINIRLAR)
        for ad, p in sinir_pg.SINIRLAR.items():
            self.assertGreaterEqual(p.limit, 1, ad)
            self.assertGreaterEqual(p.pencere_sn, 1, ad)
            self.assertRegex(ad, r"^[a-z0-9_]{1,40}$")   # the table CHECK on kova

    def test_mevcut_sinirlar_korunur(self):
        self.assertEqual(sinir_pg.SINIRLAR["iletisim"], sinir_pg.Politika(5, 3600))
        self.assertEqual(sinir_pg.SINIRLAR["yukle"], sinir_pg.Politika(5, 3600))
        self.assertEqual(sinir_pg.SINIRLAR["yonetim_giris"], sinir_pg.Politika(10, 900))
        self.assertEqual(sinir_pg.SINIRLAR["yonetim_giris_kullanici"], sinir_pg.Politika(5, 900))

    def test_baslik(self):
        self.assertEqual(sinir_pg.Sonuc(True, 1, 5, 4, 0).baslik(), ())
        self.assertEqual(sinir_pg.Sonuc(False, 5, 5, 0, 42).baslik(), (("Retry-After", "42"),))
        self.assertEqual(sinir_pg.Sonuc(False, 5, 5, 0, 0).baslik(), (("Retry-After", "1"),))

    def test_gecersiz_argumanlar_baglanmadan_reddedilir(self):
        def yasak():
            raise AssertionError("must not connect")
        sn = sinir_pg.SinirPg(yasak)
        for kw in ({"limit": 0}, {"limit": -1}, {"limit": True}, {"pencere_sn": 0}, {"limit": 1.5}):
            with self.assertRaises(ValueError):
                sn.kontrol("iletisim", "1.2.3.4", **{"limit": 5, "pencere_sn": 60, **kw})
        with self.assertRaises(ValueError):
            sn.kontrol("iletisim", "", 5, 60)
        with self.assertRaises(TypeError):
            sinir_pg.SinirPg("not callable")

    def test_ozet_sabit_ve_tuzlu(self):
        a, b = sinir_pg.SinirPg(lambda: None, tuz="t1"), sinir_pg.SinirPg(lambda: None, tuz="t2")
        self.assertEqual(a._ozet("iletisim", "1.2.3.4"), a._ozet("iletisim", "1.2.3.4"))
        self.assertNotEqual(a._ozet("iletisim", "1.2.3.4"), b._ozet("iletisim", "1.2.3.4"))
        self.assertNotEqual(a._ozet("iletisim", "1.2.3.4"), a._ozet("yukle", "1.2.3.4"))
        self.assertNotIn("1.2.3.4", a._ozet("iletisim", "1.2.3.4"))

    def test_veritabani_yoksa_hata_verir_sessizce_izin_vermez(self):
        sn = sinir_pg.SinirPg(lambda: pg.Baglanti.baglan(host="/nonexistent-alig-dir", port=1, dbname="x", user="x", baglanti_zaman_asimi=2))
        with self.assertRaises(pg.BaglantiHatasi):
            sn.kontrol("iletisim", "1.2.3.4")


class SahteBaglanti:
    acilan = 0

    def __init__(self):
        SahteBaglanti.acilan += 1
        self.kopuk, self.islemde, self.kapali = False, False, False

    def kapat(self):
        self.kapali = True


class HavuzTests(unittest.TestCase):
    def setUp(self):
        SahteBaglanti.acilan = 0

    def test_baglanti_yeniden_kullanilir(self):
        h = Havuz(SahteBaglanti, azami=2)
        with h.kullan() as a:
            pass
        with h.kullan() as b:
            self.assertIs(a, b)
        self.assertEqual(SahteBaglanti.acilan, 1)

    def test_azami_asilinca_bekler_sonra_hata_verir(self):
        h = Havuz(SahteBaglanti, azami=1, bekleme_sn=0.2)
        with h.kullan():
            with self.assertRaises(pg.BaglantiHatasi):
                with h.kullan():
                    pass

    def test_kopuk_ve_islemde_kalan_baglanti_havuza_donmez(self):
        h = Havuz(SahteBaglanti, azami=2)
        with h.kullan() as a:
            a.kopuk = True
        with h.kullan() as b:
            b.islemde = True
        self.assertTrue(a.kapali and b.kapali)
        with h.kullan() as c:
            self.assertFalse(c.kapali)
        self.assertEqual(SahteBaglanti.acilan, 3)

    def test_baglanti_hatasinda_kapatilir_ve_yer_serbest_kalir(self):
        h = Havuz(SahteBaglanti, azami=1, bekleme_sn=0.2)
        with self.assertRaises(pg.BaglantiHatasi):
            with h.kullan() as a:
                raise pg.BaglantiHatasi("x")
        self.assertTrue(a.kapali)
        with h.kullan() as b:   # the slot was released
            self.assertIsNot(a, b)

    def test_baglan_hata_verirse_yer_serbest_kalir(self):
        def kotu():
            raise pg.BaglantiHatasi("no")
        h = Havuz(kotu, azami=1, bekleme_sn=0.2)
        for _ in range(3):
            with self.assertRaises(pg.BaglantiHatasi):
                with h.kullan():
                    pass

    def test_kapatilinca_yeni_odunc_verilmez(self):
        h = Havuz(SahteBaglanti)
        with h.kullan() as a:
            pass
        h.kapat()
        self.assertTrue(a.kapali)
        with self.assertRaises(pg.BaglantiHatasi):
            with h.kullan():
                pass


CALISAN = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from ortak import pg, sinir_pg
ayar = dict(host=sys.argv[2], port=int(sys.argv[3]), dbname=sys.argv[4], user="alig_app")
sn = sinir_pg.SinirPg(lambda: pg.Baglanti.baglan(**ayar))
bas = float(sys.argv[7])
while time.time() < bas:
    time.sleep(0.001)
izinli = 0
for _ in range(int(sys.argv[5])):
    if sn.kontrol("surec_testi", "ortak-anahtar", int(sys.argv[6]), 3600).izin:
        izinli += 1
sn.kapat()
print(izinli)
"""


@pg_yardimci.pg_testi(pg_sema_kume.PG_VAR, pg_sema_kume.PG_NEDEN)
class PgSinirTests(pg_sema_kume.SemaKumesi, unittest.TestCase):
    def setUp(self):
        self.sql("TRUNCATE alig.sinir_sayac")
        self.sn = sinir_pg.SinirPg(lambda: self.baglan(), tuz="tuz")
        self.addCleanup(self.sn.kapat)

    def satirlar(self):
        out = self.sql("SELECT kova || ' ' || adet FROM alig.sinir_sayac ORDER BY 1")
        return out.split("\n") if out else []

    def test_sirali_sinir_ve_retry_after(self):
        sonuclar = [self.sn.kontrol("iletisim", "1.2.3.4", 3, 3600) for _ in range(5)]
        self.assertEqual([s.izin for s in sonuclar], [True, True, True, False, False])
        self.assertEqual([s.kalan for s in sonuclar[:3]], [2, 1, 0])
        red = sonuclar[3]
        self.assertTrue(1 <= red.tekrar_sn <= 3600, red)
        self.assertEqual(red.baslik(), (("Retry-After", str(red.tekrar_sn)),))
        self.assertEqual(self.satirlar(), ["iletisim 3"])   # rejected requests are not counted: the counter stops at the limit

    def test_anahtar_ve_kova_bagimsiz(self):
        for _ in range(2):
            self.assertTrue(self.sn.kontrol("iletisim", "a", 2, 3600).izin)
        self.assertFalse(self.sn.kontrol("iletisim", "a", 2, 3600).izin)
        self.assertTrue(self.sn.kontrol("iletisim", "b", 2, 3600).izin)
        self.assertTrue(self.sn.kontrol("yukle", "a", 2, 3600).izin)

    def test_politika_tablosundan_okur(self):
        p = sinir_pg.SINIRLAR["iletisim"]
        sonuclar = [self.sn.kontrol("iletisim", "x").izin for _ in range(p.limit + 2)]
        self.assertEqual(sonuclar, [True] * p.limit + [False] * 2)

    def test_her_politika_kovasi_tabloya_yazilabilir(self):
        for kova in sinir_pg.SINIRLAR:
            self.assertTrue(self.sn.kontrol(kova, "k").izin, kova)

    def test_duz_adres_saklanmaz(self):
        self.sn.kontrol("iletisim", "203.0.113.77", 5, 60)
        self.assertEqual(self.sql("SELECT count(*) FROM alig.sinir_sayac WHERE anahtar_sha256 LIKE '%203.0.113.77%'"), "0")
        self.assertRegex(self.sql("SELECT anahtar_sha256 FROM alig.sinir_sayac"), r"^[0-9a-f]{64}$")

    def test_pencere_dolunca_yeniden_izin_verir(self):
        self.assertTrue(self.sn.kontrol("iletisim", "w", 1, 1).izin)
        # a 1 second fixed window ends within 1 s; the database clock decides
        bitis = time.monotonic() + 5
        izin = False
        while time.monotonic() < bitis and not izin:
            time.sleep(0.2)
            izin = self.sn.kontrol("iletisim", "w", 1, 1).izin
        self.assertTrue(izin)

    def test_es_zamanli_thread_siniri_asmaz(self):
        """60 threads, each with its own connection, released together: exactly `limit` pass and the stored counter equals limit."""
        limit, n = 7, 60
        b, izinli, hatalar = threading.Barrier(n), [], []

        def is_():
            try:
                b.wait(10)
                izinli.append(self.sn.kontrol("iletisim", "yaris", limit, 3600).izin)
            except Exception as e:   # noqa: BLE001
                hatalar.append(repr(e))
        ts = [threading.Thread(target=is_) for _ in range(n)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        self.assertEqual(hatalar, [])
        self.assertEqual(len(izinli), n)
        self.assertEqual(sum(izinli), limit)
        self.assertEqual(self.satirlar(), ["iletisim %d" % limit])

    def test_es_zamanli_surecler_siniri_asmaz(self):
        """6 separate OS processes (each its own connection and limiter object), 25 attempts each, limit 20: exactly 20 pass."""
        limit, surec, deneme = 20, 6, 25
        bas = time.time() + 3
        ps = [subprocess.Popen([sys.executable, "-I", "-c", CALISAN, str(ROOT), str(self.kume.soket), str(self.kume.port), self.DB,
                                str(deneme), str(limit), repr(bas)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
              for _ in range(surec)]
        toplam = 0
        for p in ps:
            out, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err)
            toplam += int(out.strip())
        self.assertEqual(toplam, limit)
        self.assertEqual(self.satirlar(), ["surec_testi %d" % limit])

    def test_suresi_dolmus_pencereler_temizlenir(self):
        self.sql("INSERT INTO alig.sinir_sayac(kova, anahtar_sha256, pencere_utc, bitis_utc, adet) "
                 "VALUES('eski', repeat('a', 64), now() - interval '2 hours', now() - interval '1 hour', 3)")
        self.sql("INSERT INTO alig.sinir_sayac(kova, anahtar_sha256, pencere_utc, bitis_utc, adet) "
                 "VALUES('sicak', repeat('b', 64), now() - interval '10 seconds', now() + interval '1 hour', 3)")
        self.assertEqual(self.sn.temizle(), 1)
        self.assertEqual(self.satirlar(), ["sicak 3"])

    def test_temizlik_kontrol_icinde_kendiliginden_calisir(self):
        self.sql("INSERT INTO alig.sinir_sayac(kova, anahtar_sha256, pencere_utc, bitis_utc, adet) "
                 "VALUES('eski', repeat('a', 64), now() - interval '2 hours', now() - interval '1 hour', 3)")
        sn = sinir_pg.SinirPg(lambda: self.baglan(), temizlik_araligi=0)
        self.addCleanup(sn.kapat)
        sn.kontrol("iletisim", "z", 5, 60)
        self.assertEqual(self.satirlar(), ["iletisim 1"])

    def test_uygulama_rolu_yalniz_gerekli_hakka_sahip_salt_okunur_rol_yok(self):
        b = self.baglan("alig_app")
        b.sorgu("SELECT count(*) FROM alig.sinir_sayac")
        with self.assertRaises(pg.SorguHatasi) as c:
            b.sorgu("DROP TABLE alig.sinir_sayac")
        self.assertEqual(c.exception.sqlstate, "42501")
        r = self.baglan("alig_readonly")
        with self.assertRaises(pg.SorguHatasi) as c:
            r.sorgu("SELECT count(*) FROM alig.sinir_sayac")
        self.assertEqual(c.exception.sqlstate, "42501")

    def test_tablo_kisitlari_duz_deger_ve_gecersiz_kovayi_reddeder(self):
        b = self.baglan("alig_app")
        with self.assertRaises(pg.ButunlukHatasi):
            b.sorgu("INSERT INTO alig.sinir_sayac VALUES('Bad Name', repeat('a', 64), now(), now() + interval '1 minute', 1)")
        with self.assertRaises(pg.ButunlukHatasi):
            b.sorgu("INSERT INTO alig.sinir_sayac VALUES('ok', '1.2.3.4', now(), now() + interval '1 minute', 1)")

    def test_baglanti_dusunce_hata_verir_sonra_yeniden_baglanir(self):
        self.assertTrue(self.sn.kontrol("iletisim", "d", 5, 60).izin)
        self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'alig_app' AND pid <> pg_backend_pid()")
        with self.assertRaises(pg.BaglantiHatasi):
            self.sn.kontrol("iletisim", "d", 5, 60)   # not retried: it may or may not have been counted
        self.assertTrue(self.sn.kontrol("iletisim", "d", 5, 60).izin)   # the next call reconnects


if __name__ == "__main__":
    unittest.main()
