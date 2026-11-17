"""ALIG-DB-003c, part 2: PostgreSQL-native tests of the scan and portal stores (tarama/depo_pg.py, tarama/portal_depo_pg.py).

Real concurrency (threads and forked processes, each with its OWN connection to a temporary PostgreSQL 16 cluster), real constraints,
real privileges (alig_app). Part 1 (tests/test_pg_depo.py) re-runs the existing SQLite-era test classes. SKIPPED without PG16 / libpq.
"""
import contextlib
import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_depo_yardimci as Y  # noqa: E402
import pg_yardimci  # noqa: E402
import test_portal  # noqa: E402
import test_tarama  # noqa: E402
from ortak import pg  # noqa: E402
from tarama import depo_pg as depo  # noqa: E402
from tarama import portal_depo_pg as portal_depo  # noqa: E402
from tarama import server as tserver  # noqa: E402
from tarama import yukleme  # noqa: E402

BICIM = "%Y-%m-%dT%H:%M:%SZ"
SINIR = depo.SINIR_ADET


def setUpModule():
    Y.kur()


def tearDownModule():
    Y.kapat()


def pg_sinifi(sinif):
    return pg_yardimci.pg_testi(Y.PG_VAR, Y.PG_NEDEN)(sinif)


class PgTaban(unittest.TestCase):
    """A fresh database for every test; app(): a connection as the application role, yonetici(): as the superuser (fixtures only)."""

    def setUp(self):
        Y.sifirla()

    def app(self):
        c = depo.baglan(Y.app_ayar())
        self.addCleanup(c.close)
        return c

    def yonetici(self):
        c = depo.baglan(Y.yonetici_ayar())
        c.execute("SET search_path = alig, pg_catalog")
        self.addCleanup(c.close)
        return c

    def sayim(self, tablo, kosul="", p=()):
        return Y.yonetici_sql("SELECT count(*) FROM alig.%s %s" % (tablo, kosul), p)[0][0]


def paralel(n, is_, *, bariyer=True):
    """Runs is_(i) in n threads that start at the same moment; returns the results in order. An exception in a thread is returned, not raised."""
    b = threading.Barrier(n) if bariyer else None

    def sar(i):
        try:
            if b:
                b.wait(30)
            return is_(i)
        except BaseException as ex:   # noqa: BLE001 - reported to the test
            return ex
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(sar, range(n)))


def kendi_baglantisiyla(f):
    """Opens a connection for the calling thread (a connection is never shared between threads), runs f(con), closes it."""
    c = depo.baglan(Y.app_ayar())
    try:
        return f(c)
    finally:
        c.close()


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgIslemTests(PgTaban):
    def test_ic_ice_islem_dis_islemle_birlikte_geri_alinir(self):
        c = self.app()
        with self.assertRaises(RuntimeError):
            with depo.islem(c):
                depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama")
                with depo.islem(c):   # nested: joins the outer transaction
                    depo.denetim_ekle(c, "sistem", "olay")
                self.assertTrue(c.in_transaction)
                raise RuntimeError("fail after both")
        self.assertFalse(c.in_transaction)
        self.assertEqual((self.sayim("firma"), self.sayim("denetim")), (0, 0))   # neither the company nor the audit record

    def test_basarili_islem_commit_eder_ve_baska_baglanti_gorur(self):
        c = self.app()
        with depo.islem(c):
            depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama")
            self.assertEqual(self.sayim("firma"), 0)   # not visible to others before the commit
        self.assertEqual(self.sayim("firma"), 1)

    def test_firma_sil_ve_denetim_tek_islemde_ya_ikisi_ya_hicbiri(self):
        c = self.app()
        f = depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama")
        depo.rapor_ekle(c, "t1", "postgresql", "tr", {"a": 1}, f["id"])
        with mock.patch.object(depo, "denetim_ekle", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                with depo.islem(c) as c2:
                    depo.firma_sil(c2, f["id"])
                    depo.denetim_ekle(c2, "yonetici", "firma silindi")
        self.assertEqual((self.sayim("firma"), self.sayim("rapor"), self.sayim("firma_silinen")), (1, 1, 0))   # the delete was rolled back

    def test_hata_sonrasi_baglanti_kullanilabilir(self):
        c = self.app()
        with self.assertRaises(pg.ButunlukHatasi):
            depo.firma_kaydet(c, "", "A", "x@a.com", "tarama")   # CHECK (anahtar <> '')
        self.assertFalse(c.in_transaction)
        self.assertIsNotNone(depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama"))

    def test_islem_ortasinda_baglanti_kopunca_basari_bildirilmez(self):
        c = self.app()
        pid = c.execute("SELECT pg_backend_pid()").fetchone()[0]
        with self.assertRaises(pg.BaglantiHatasi):
            with depo.islem(c):
                depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama")
                Y.yonetici_sql("SELECT pg_terminate_backend($1)", (pid,))
                time.sleep(0.3)
                depo.denetim_ekle(c, "sistem", "olay")
        self.assertEqual((self.sayim("firma"), self.sayim("denetim")), (0, 0))   # nothing half-written
        self.assertFalse(c.in_transaction)

    def test_ulasilamayan_sunucuda_baglan_hata_verir_sqlite_a_dusmez(self):
        ayar = dict(Y.app_ayar(), port=1)
        with self.assertRaises(pg.BaglantiHatasi):
            depo.baglan(ayar)
        with self.assertRaises(TypeError):
            depo.baglan("/tmp/tarama.sqlite")   # a file path is not accepted: the PostgreSQL store takes settings, never a SQLite path

    def test_parametre_sayisi_uyusmazligi_reddedilir_ve_enjeksiyon_deger_kalir(self):
        c = self.app()
        with self.assertRaises(ValueError):
            c.execute("SELECT ?, ?", (1,))
        f = depo.firma_kaydet(c, "a.com", "A'); DROP TABLE alig.firma; --", "x@a.com", "tarama")
        self.assertEqual(f["ad"], "A'); DROP TABLE alig.firma; --")
        self.assertEqual(self.sayim("firma"), 1)
        # a '?' inside a quoted literal is not a placeholder
        self.assertEqual(c.execute("SELECT '?' || ?", ("x",)).fetchone()[0], "?x")


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgKotaTests(PgTaban):
    """The quota is a sliding window (SINIR_ADET in SINIR_GUN days); lock + count + insert in one transaction."""
    ANAHTAR = depo.sirket_anahtari("ali@ornek.com.tr")

    def ozet(self, n):
        return hashlib.sha256(("belge%d" % n).encode()).hexdigest()

    def test_ardisik_pencere_semantigi(self):
        c = self.app()
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(1)), "yeni")
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(1)), "tekrar")     # the same document: nothing spent (idempotent)
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(2)), "yeni")
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(3)), "asildi")     # window full
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(2)), "tekrar")     # an old document is still a repeat when full
        self.assertEqual(self.sayim("kullanim"), SINIR)
        self.assertEqual(depo.kullanim_say(c, self.ANAHTAR), SINIR)
        self.assertEqual(depo.kota_al(c, depo.sirket_anahtari("x@baska.com"), self.ozet(9)), "yeni")   # another company is separate

    def test_pencere_kayar_eski_kayit_sayilmaz(self):
        c = self.app()
        depo.kota_al(c, self.ANAHTAR, self.ozet(1))
        depo.kota_al(c, self.ANAHTAR, self.ozet(2))
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(3)), "asildi")
        Y.yonetici_sql("UPDATE alig.kullanim SET zaman_utc = now() - interval '%d days 1 hour' WHERE belge_sha256=$1" % depo.SINIR_GUN, (self.ozet(1),))
        self.assertEqual(depo.kullanim_say(c, self.ANAHTAR), 1)
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(3)), "yeni")     # the oldest allowance came back
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(4)), "asildi")
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(1)), "asildi")   # the old document is outside the window: not a repeat, and the window is full

    def test_asildi_hicbir_sey_yazmaz_ve_hata_islemi_geri_alir(self):
        c = self.app()
        for i in range(SINIR):
            depo.kota_al(c, self.ANAHTAR, self.ozet(i))
        self.assertEqual(depo.kota_al(c, self.ANAHTAR, self.ozet(99)), "asildi")
        self.assertEqual(self.sayim("kullanim"), SINIR)
        with self.assertRaises(RuntimeError):   # the quota row and the report are in the caller's transaction: rolled back together
            with depo.islem(c):
                depo.kota_al(c, depo.sirket_anahtari("y@baska.com"), self.ozet(5))
                raise RuntimeError("report could not be saved")
        self.assertEqual(self.sayim("kullanim"), SINIR)

    def test_paralel_yuklemeler_siniri_asmaz_kota_al(self):
        """N concurrent uploads of ONE company: exactly SINIR_ADET win, the rest are refused, the table never exceeds the allowance."""
        n = 16
        for tur in range(4):
            Y.sifirla()
            sonuc = paralel(n, lambda i: kendi_baglantisiyla(lambda c: depo.kota_al(c, self.ANAHTAR, self.ozet(tur * 100 + i))))
            self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [], "round %d" % tur)
            self.assertEqual(sorted(sonuc).count("yeni"), SINIR, "round %d: %r" % (tur, sonuc))
            self.assertEqual(sorted(sonuc).count("asildi"), n - SINIR)
            self.assertEqual(self.sayim("kullanim"), SINIR)

    def test_paralel_ayni_belge_bir_kez_sayilir(self):
        n = 12
        sonuc = paralel(n, lambda i: kendi_baglantisiyla(lambda c: depo.kota_al(c, self.ANAHTAR, self.ozet(7))))
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(sorted(sonuc), ["tekrar"] * (n - 1) + ["yeni"])
        self.assertEqual(self.sayim("kullanim"), 1)

    def test_paralel_firmalar_birbirini_engellemez_ve_her_biri_sinirda_kalir(self):
        firmalar = [depo.sirket_anahtari("u@firma%d.com" % k) for k in range(4)]
        n = 8 * len(firmalar)
        sonuc = paralel(n, lambda i: (i % 4, kendi_baglantisiyla(lambda c: depo.kota_al(c, firmalar[i % 4], self.ozet(i)))))
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        for k in range(4):
            self.assertEqual([r for f, r in sonuc if f == k].count("yeni"), SINIR)
            self.assertEqual(self.sayim("kullanim", "WHERE anahtar_sha256=$1", (firmalar[k],)), SINIR)

    def test_paralel_surecler_siniri_asmaz(self):
        """Separate OS processes (not threads): the lock is in the database, not in Python."""
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        bariyer = ctx.Barrier(6)
        ayar = Y.app_ayar()

        def is_(i):
            try:
                c = depo.baglan(ayar)
                bariyer.wait(30)
                q.put(depo.kota_al(c, self.ANAHTAR, self.ozet(500 + i)))
                c.close()
            except BaseException as ex:   # noqa: BLE001
                q.put("HATA " + repr(ex))
        ps = [ctx.Process(target=is_, args=(i,)) for i in range(6)]
        [p.start() for p in ps]
        [p.join(60) for p in ps]
        sonuc = sorted(q.get(timeout=5) for _ in ps)
        self.assertEqual(sonuc, ["asildi"] * (6 - SINIR) + ["yeni"] * SINIR)
        self.assertEqual(self.sayim("kullanim"), SINIR)

    def test_kontrol_kilitsiz_kontrol_ekle_siniri_asar(self):
        """The test has teeth: the same race WITHOUT the lock exceeds the allowance (so a green result above means something)."""
        def kilitsiz(i):
            def is_(c):
                with depo.islem(c) as t:
                    sayi = t.execute("SELECT count(*) FROM kullanim WHERE anahtar_sha256=?", (self.ANAHTAR,)).fetchone()[0]
                    time.sleep(0.05)   # the window between the check and the write
                    if sayi < SINIR:
                        t.execute("INSERT INTO kullanim(anahtar_sha256, zaman_utc, belge_sha256) VALUES(?,?,?)", (self.ANAHTAR, depo.simdi(), self.ozet(i)))
                        return "yeni"
                    return "asildi"
            return kendi_baglantisiyla(is_)
        sonuc = paralel(8, kilitsiz)
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertGreater(self.sayim("kullanim"), SINIR)

    def test_sunucu_yukleme_yolu_paralel_atomik(self):
        """The real upload code (tarama/server.py _yukleme_isle: company, tekrar/say/ekle, report, audit in one transaction), 16 concurrent clients."""
        class Sahte:
            sirket_adet = SINIR
            eposta_dogrulama = False
            posta_adres_siniri = 3
            bekleyen_firma_siniri = 5
        eposta = "ali@ornek.com.tr"
        anahtar_s = depo.sirket_anahtari(eposta)

        def yukle(i):
            belge = yukleme.coz(test_tarama.farkli_belge(i), ("postgresql",))

            def is_(c):
                with depo.islem(c) as t:
                    return tserver.H._yukleme_isle(Sahte(), t, "tok%02d" % i, anahtar_s, eposta, eposta, "Ornek AS", "tr", belge)
            return kendi_baglantisiyla(is_)
        with mock.patch.object(tserver, "depo", depo):
            sonuc = paralel(16, yukle)
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(sorted(s[0] for s in sonuc), ["hata"] * (16 - SINIR) + ["rapor"] * SINIR)
        self.assertTrue(all(s[1] == 429 and s[2] == "sinir" for s in sonuc if s[0] == "hata"))
        self.assertEqual((self.sayim("kullanim"), self.sayim("rapor"), self.sayim("firma")), (SINIR, SINIR, 1))
        self.assertEqual(self.sayim("denetim"), 16)    # one audit record per request, accepted or refused
        self.assertIsNone(depo.denetim_dogrula(self.yonetici()))

    def test_firma_sil_ve_yuklemeler_kilitlenmez(self):
        """Company deletion and uploads of the same company take the locks in the same order: no deadlock, a valid chain."""
        class Sahte:
            sirket_adet = SINIR
            eposta_dogrulama = False
            posta_adres_siniri = 3
            bekleyen_firma_siniri = 5
        eposta = "ali@ornek.com.tr"
        anahtar_s = depo.sirket_anahtari(eposta)
        c0 = self.app()
        depo.firma_kaydet(c0, depo.firma_anahtari(eposta), "Ornek", eposta, "tarama")

        def is_(i):
            def f(c):
                if i % 3 == 0:
                    fr = depo.firma_getir(c, 1)
                    if fr:
                        with depo.islem(c) as t:
                            depo.firma_sil(t, 1)
                            depo.denetim_ekle(t, "yonetici", "firma silindi")
                        return "sil"
                    return "yok"
                belge = yukleme.coz(test_tarama.farkli_belge(i), ("postgresql",))
                with depo.islem(c) as t:
                    return tserver.H._yukleme_isle(Sahte(), t, "tok%02d" % i, anahtar_s, eposta, eposta, "Ornek AS", "tr", belge)[0]
            return kendi_baglantisiyla(f)
        with mock.patch.object(tserver, "depo", depo):
            sonuc = paralel(18, is_)
        hatalar = [s for s in sonuc if isinstance(s, BaseException)]
        self.assertEqual(hatalar, [], "deadlock or lock timeout: %r" % hatalar)
        self.assertIsNone(depo.denetim_dogrula(self.yonetici()))

    def test_sinir_sifirla_kilitli_ve_firma_silinince_kullanim_silinir(self):
        c = self.app()
        f = depo.firma_kaydet(c, "ornek.com.tr", "O", "ali@ornek.com.tr", "tarama")
        anahtar = depo.sirket_anahtari("ali@ornek.com.tr")
        depo.kota_al(c, anahtar, self.ozet(1))
        depo.kota_al(c, anahtar, self.ozet(2))
        self.assertEqual(depo.firma_sinir_sifirla(c, f["id"]), 2)
        self.assertEqual(depo.kota_al(c, anahtar, self.ozet(3)), "yeni")
        depo.firma_sil(c, f["id"])
        self.assertEqual(self.sayim("kullanim"), 0)

    def test_kilit_zaman_asimi_kontrollu_hata_verir(self):
        """A holder that never commits does not hang the others: lock_timeout turns into KilitHatasi, nothing is written."""
        tutan = self.app()
        bekleyen = depo.baglan(dict(Y.app_ayar(), lock_timeout_ms=300))
        self.addCleanup(bekleyen.close)
        with depo.islem(tutan):
            depo.kullanim_say(tutan, self.ANAHTAR)   # takes the quota lock and keeps the transaction open
            with self.assertRaises(pg.KilitHatasi):
                depo.kota_al(bekleyen, self.ANAHTAR, self.ozet(1))
        self.assertEqual(self.sayim("kullanim"), 0)
        self.assertEqual(depo.kota_al(bekleyen, self.ANAHTAR, self.ozet(1)), "yeni")   # usable afterwards


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgIdempotencyTests(PgTaban):
    def test_ayni_anahtar_ayni_icerik_tekrar_ayni_sonuc_farkli_icerik_reddedilir(self):
        c = self.app()
        a, b = "a" * 64, "b" * 64
        self.assertEqual(depo.idempotency_kaydet(c, "yukle-1", a, "rapor-7"), ("yeni", ""))
        self.assertEqual(depo.idempotency_kaydet(c, "yukle-1", a, "baska"), ("ayni", "rapor-7"))    # repeat: the stored result, not a new action
        self.assertEqual(depo.idempotency_kaydet(c, "yukle-1", b, "x"), ("celisiyor", ""))          # same key, different content
        self.assertEqual(self.sayim("idempotency_anahtari"), 1)

    def test_gecersiz_anahtar(self):
        c = self.app()
        for k in ("", None, "x" * 201, 5):
            with self.assertRaises(ValueError):
                depo.idempotency_kaydet(c, k, "a" * 64)
        with self.assertRaises(pg.ButunlukHatasi):
            depo.idempotency_kaydet(c, "k", "kisa")   # istek_ozeti must be a 64-hex digest

    def test_paralel_ayni_anahtar_tek_yeni(self):
        sonuc = paralel(12, lambda i: kendi_baglantisiyla(lambda c: depo.idempotency_kaydet(c, "yukle-9", "c" * 64, "r")))
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(sorted(s[0] for s in sonuc), ["ayni"] * 11 + ["yeni"])

    def test_kayit_is_verisiyle_ayni_islemde_geri_alinir(self):
        c = self.app()
        with self.assertRaises(RuntimeError):
            with depo.islem(c):
                depo.idempotency_kaydet(c, "yukle-2", "d" * 64)
                raise RuntimeError("business step failed")
        self.assertEqual(self.sayim("idempotency_anahtari"), 0)    # a failed attempt can be retried with the same key


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgZincirTests(PgTaban):
    """Audit chain on PostgreSQL: the canonical digest format is unchanged; writers are ordered by an advisory lock."""

    def test_zincir_saglam_kirik_ve_silinen_kayit(self):
        c = self.app()
        for i in range(4):
            depo.denetim_ekle(c, "musteri", "olay %d" % i)
        self.assertIsNone(depo.denetim_dogrula(c))
        y = self.yonetici()
        y.execute("UPDATE denetim SET olay='degistirildi' WHERE seq=2")
        self.assertEqual(depo.denetim_dogrula(c), 2)
        y.execute("UPDATE denetim SET olay='olay 1' WHERE seq=2")
        self.assertIsNone(depo.denetim_dogrula(c))
        # PostgreSQL itself refuses a hole in the chain from the application: deleting needs the superuser
        y.execute("DELETE FROM denetim WHERE seq=3")
        self.assertIsNotNone(depo.denetim_dogrula(c))

    def test_uygulama_rolu_zinciri_degistiremez_silemez(self):
        c = self.app()
        depo.denetim_ekle(c, "a", "bir")
        for sql in ("UPDATE denetim SET olay='x'", "DELETE FROM denetim", "TRUNCATE alig.denetim"):
            with self.assertRaises(pg.SorguHatasi) as e:
                c.execute(sql)
            self.assertEqual(e.exception.sqlstate, "42501", sql)    # insufficient_privilege
        self.assertEqual(self.sayim("denetim"), 1)

    def test_anahtarli_zincir_ve_eski_kayitlar(self):
        c = self.app()
        y = self.yonetici()
        y.execute("INSERT INTO denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod) VALUES(1,'2026-01-01T00:00:00Z','a','eski','',?,0)",
                  (depo.ozet_hesapla(1, "a", "eski", ""),))     # a pre-version record (no fields, no key)
        anahtar = "k" * 40
        with mock.patch.dict(os.environ, {depo.ANAHTAR_ORTAM: anahtar}):
            depo.denetim_ekle(c, "a", "yeni")
            depo.denetim_ekle(c, "a", "yeni2")
            self.assertIsNone(depo.denetim_dogrula(c))
            self.assertTrue(depo.denetim_durum(c, anahtar.encode())["anahtarli"])
        self.assertEqual(c.execute("SELECT mod FROM denetim ORDER BY seq").fetchall(), [(0,), (3,), (3,)])
        d = depo.denetim_durum(c)
        self.assertIsNone(d["bozuk"])
        self.assertEqual(d["dogrulanamayan"], 2)

    def test_yapisal_alanlar_ve_surume_dusurme(self):
        c = self.app()
        y = self.yonetici()
        depo.denetim_ekle(c, "sistem", "x", {"firma": 3, "sonuc": "reddedildi", "neden": None, "serbest": "yok", "hedef": "h" * 500})
        ham = c.execute("SELECT alanlar FROM denetim").fetchone()[0]
        al = json.loads(ham)
        self.assertEqual(set(al), {"firma", "sonuc", "hedef"})
        self.assertEqual(len(al["hedef"]), depo.ALAN_UZUNLUK)
        y.execute("UPDATE denetim SET alanlar=? WHERE seq=1", (json.dumps({"firma": 4, "sonuc": "reddedildi", "hedef": al["hedef"]}),))
        self.assertEqual(depo.denetim_dogrula(c), 1)    # a changed field breaks the chain
        y.execute("UPDATE denetim SET alanlar=? WHERE seq=1", (ham,))
        self.assertIsNone(depo.denetim_dogrula(c))
        y.execute("INSERT INTO denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod) VALUES(2,'2026-01-01T00:00:00Z','a','iki',(SELECT ozet FROM denetim WHERE seq=1),?,0)",
                  (depo.ozet_hesapla(2, "a", "iki", c.execute("SELECT ozet FROM denetim WHERE seq=1").fetchone()[0]),))
        self.assertEqual(depo.denetim_dogrula(c), 2)    # a record without fields cannot follow a structured one

    def test_anahtarsiz_yeniden_uretilen_zincir_yakalanir(self):
        c = self.app()
        y = self.yonetici()
        anahtar = ("k" * 40).encode()
        with mock.patch.dict(os.environ, {depo.ANAHTAR_ORTAM: anahtar.decode()}):
            for i in range(3):
                depo.denetim_ekle(c, "a", "o%d" % i)
        # the attacker changes record 2 and regenerates the chain from the start with plain SHA-256, leaving mod=1
        y.execute("UPDATE denetim SET olay='sahte' WHERE seq=2")
        onceki = ""
        for seq, aktor, olay in y.execute("SELECT seq, aktor, olay FROM denetim ORDER BY seq").fetchall():
            oz = depo.ozet_hesapla(seq, aktor, olay, onceki)
            y.execute("UPDATE denetim SET onceki=?, ozet=? WHERE seq=?", (onceki, oz, seq))
            onceki = oz
        self.assertEqual(depo.denetim_dogrula(c, anahtar), 1)

    def test_zincir_basi_disa_aktarilir_ve_kesilme_yakalanir(self):
        c = self.app()
        y = self.yonetici()
        for i in range(3):
            depo.denetim_ekle(c, "a", "o%d" % i)
        bas = depo.zincir_basi(c)
        self.assertEqual(bas["seq"], 3)
        self.assertRegex(bas["zaman_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsNone(depo.denetim_durum(c, None, bas)["bozuk"])
        y.execute("DELETE FROM denetim WHERE seq=3")
        self.assertEqual(depo.denetim_durum(c, None, bas)["bozuk"], 3)

    def test_eszamanli_yazarlar_zinciri_bozmaz_kayit_kaybetmez(self):
        """Threads and processes writing to the same chain with their own connections: no lost record, no branch, chain verifies."""
        def yaz(i):
            def f(c):
                for j in range(15):
                    depo.denetim_ekle(c, "t%d" % i, "olay %d" % j)
            return kendi_baglantisiyla(f)
        sonuc = paralel(6, yaz)
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        ayar = Y.app_ayar()

        def surec(i):
            try:
                c = depo.baglan(ayar)
                for j in range(15):
                    depo.denetim_ekle(c, "p%d" % i, "olay %d" % j)
                c.close()
                q.put(0)
            except BaseException as ex:   # noqa: BLE001
                q.put(repr(ex))
        ps = [ctx.Process(target=surec, args=(i,)) for i in range(3)]
        [p.start() for p in ps]
        [p.join(60) for p in ps]
        self.assertEqual([q.get(timeout=5) for _ in ps], [0, 0, 0])
        self.assertEqual(self.sayim("denetim"), 6 * 15 + 3 * 15)
        self.assertEqual(Y.yonetici_sql("SELECT count(DISTINCT seq), max(seq) FROM alig.denetim")[0], (135, 135))
        self.assertIsNone(depo.denetim_dogrula(self.yonetici()))

    def test_cli_bas_ve_dogrula(self):
        c = self.app()
        with mock.patch.dict(os.environ, {depo.ANAHTAR_ORTAM: "k" * 40}):
            depo.denetim_ekle(c, "a", "bir")
        e = {k: v for k, v in os.environ.items() if not k.startswith(("ALIG_", "PG"))}
        e.update(ALIG_DB_HOST=Y.Ortam.kume.soket, ALIG_DB_PORT=str(Y.Ortam.kume.port), ALIG_DB_NAME=Y.DB, ALIG_DB_USER="alig_app",
                 ALIG_DENETIM_ANAHTARI="k" * 40, PYTHONPATH=str(ROOT))
        calis = lambda env, *a: subprocess.run([sys.executable, "-m", "tarama.depo_pg", *a], capture_output=True, text=True, env=env, cwd=str(ROOT))  # noqa: E731
        r = calis(e, "bas")
        self.assertEqual(r.returncode, 0, r.stderr)
        dosya = Path(Y.Ortam.kume.dizin) / "bas.json"
        dosya.write_text(r.stdout, encoding="utf-8")
        self.assertEqual(calis(e, "dogrula", "--bas", str(dosya)).returncode, 0)
        e2 = {k: v for k, v in e.items() if k != depo.ANAHTAR_ORTAM}
        self.assertEqual(calis(e2, "dogrula").returncode, 1)     # a keyed record cannot be verified without the key
        e3 = {k: v for k, v in e.items() if not k.startswith("ALIG_DB_")}
        r3 = calis(e3, "bas")
        self.assertEqual(r3.returncode, 2)
        self.assertIn("not configured", r3.stderr)


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgKisitTests(PgTaban):
    """What the SQLite tests checked with sqlite3.IntegrityError is a PostgreSQL constraint here (ButunlukHatasi)."""

    def test_portal_kullanici_dogrulanmis_firmasiz_olamaz_ve_durum_kumesi(self):
        kid, fid = test_portal.hesap_ac(self.yonetici_test_baglantisi(), "ali@ornek.com.tr")
        y = self.yonetici()
        with self.assertRaises(pg.ButunlukHatasi):
            y.execute("UPDATE portal_kullanici SET firma_id=NULL WHERE id=?", (kid,))
        with self.assertRaises(pg.ButunlukHatasi):
            y.execute("UPDATE portal_kullanici SET durum='yonetici' WHERE id=?", (kid,))

    def yonetici_test_baglantisi(self):
        """test_portal.hesap_ac uses test_portal's globals; point them at the PostgreSQL stores for the call."""
        for ad, deger in (("depo", depo), ("portal_depo", portal_depo)):
            p = mock.patch.object(test_portal, ad, deger)
            p.start()
            self.addCleanup(p.stop)
        return self.yonetici()

    def test_bozuk_belge_json_kabul_edilmez(self):
        c = self.app()
        f = depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama")
        depo.rapor_ekle(c, "t1", "postgresql", "tr", {"a": 1}, f["id"])
        with self.assertRaises(pg.ButunlukHatasi):
            self.yonetici().execute("UPDATE rapor SET belge_json='{bozuk' WHERE id=1")
        with self.assertRaises(pg.ButunlukHatasi):
            depo.rapor_ekle(c, "t2", "postgresql", "xx", {"a": 1}, f["id"])   # dil CHECK
        with self.assertRaises(pg.BenzersizlikHatasi):
            depo.rapor_ekle(c, "t1", "postgresql", "tr", {"a": 1}, f["id"])   # token digest unique

    def test_silme_talebi_tek_acik_kisit_veritabaninda(self):
        y = self.yonetici_test_baglantisi()
        _, fa = test_portal.hesap_ac(y, "ali@firma-a.com.tr")
        ks = test_portal.oturum(y, "ali@firma-a.com.tr")
        tid, yeni = ks.silme_talebi_ekle()
        self.assertTrue(yeni)
        with self.assertRaises(pg.BenzersizlikHatasi):
            y.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) VALUES(?,1,'silme',now(),now())", (fa,))
        with self.assertRaises(pg.ButunlukHatasi):
            y.execute("UPDATE portal_talep SET tur='yonetici' WHERE id=?", (tid,))
        self.assertEqual(ks.silme_talebi_ekle(), (tid, False))

    def test_belge_ozeti_ve_token_ozeti_bicim_kisiti(self):
        c = self.app()
        with self.assertRaises(pg.ButunlukHatasi):
            depo.kullanim_ekle(c, "kisa-anahtar")      # anahtar_sha256 must be a 64-hex digest
        with self.assertRaises(pg.ButunlukHatasi):
            depo.kullanim_ekle(c, "a" * 64, "belge")   # belge_sha256 too


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgPortalYerelTests(PgTaban):
    def setUp(self):
        super().setUp()
        for ad, deger in (("depo", depo), ("portal_depo", portal_depo)):
            p = mock.patch.object(test_portal, ad, deger)
            p.start()
            self.addCleanup(p.stop)

    def test_paralel_kayit_ayni_adres_tek_hesap(self):
        def kayit(i):
            return kendi_baglantisiyla(lambda c: portal_depo.kayit(c, "ali@ornek.com.tr", test_portal.PAROLA + str(i), "Ornek AS", "tr"))
        sonuc = paralel(8, kayit)
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(self.sayim("portal_kullanici"), 1)
        self.assertEqual(self.sayim("portal_kod"), 1)    # each registration replaces the previous code; one live code remains

    def test_paralel_dogrulama_kodu_tek_kullanimlik(self):
        c = self.app()
        durum, kod = portal_depo.kayit(c, "ali@ornek.com.tr", test_portal.PAROLA, "Ornek AS", "tr")
        sonuc = paralel(8, lambda i: kendi_baglantisiyla(lambda x: portal_depo.dogrula(x, kod)[0]))
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(sorted(sonuc), ["tamam"] + ["yok"] * 7)
        self.assertEqual((self.sayim("firma"), self.sayim("portal_kullanici", "WHERE durum='aktif'")), (1, 1))

    def test_paralel_silme_talebi_tek_yeni(self):
        c = self.app()
        _, fid = test_portal.hesap_ac(c, "ali@ornek.com.tr")
        kod, _ = portal_depo.giris(c, "ali@ornek.com.tr", test_portal.PAROLA, test_portal.IP)
        sonuc = paralel(8, lambda i: kendi_baglantisiyla(lambda x: portal_depo.kapsam(x, kod).silme_talebi_ekle()))
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(sorted(s[1] for s in sonuc), [False] * 7 + [True])
        self.assertEqual(len({s[0] for s in sonuc}), 1)
        self.assertEqual(self.sayim("portal_talep", "WHERE tur='silme'"), 1)
        self.assertEqual(self.sayim("denetim", "WHERE olay LIKE 'portal veri silme talebi%'"), 1)

    def test_paralel_talep_gunluk_sinir_asilmaz(self):
        c = self.app()
        test_portal.hesap_ac(c, "ali@ornek.com.tr")
        kod, _ = portal_depo.giris(c, "ali@ornek.com.tr", test_portal.PAROLA, test_portal.IP)
        sonuc = paralel(12, lambda i: kendi_baglantisiyla(lambda x: portal_depo.kapsam(x, kod).talep_ekle("destek", "Konu %d" % i, "Mesaj")))
        self.assertEqual([s for s in sonuc if isinstance(s, BaseException)], [])
        self.assertEqual(sum(1 for s in sonuc if s[1] is None), portal_depo.TALEP_GUNLUK)
        self.assertEqual(self.sayim("portal_talep"), portal_depo.TALEP_GUNLUK)

    def test_kapsam_sorgulari_firma_kosulu_tasir_pg_kaynagi(self):
        """Static guard for the PostgreSQL portal layer, like the SQLite one: every report query carries the company condition."""
        import re
        kaynak = (ROOT / "tarama" / "portal_depo_pg.py").read_text(encoding="utf-8")
        sorgular = re.findall(r'"(SELECT [^"]*FROM rapor[^"]*)"', kaynak)
        self.assertGreaterEqual(len(sorgular), 2)
        for sorgu in sorgular:
            self.assertIn("firma_id=?", sorgu, sorgu)
        for sorgu in re.findall(r'"(DELETE FROM rapor[^"]*)"', kaynak):
            self.assertIn("firma_id=?", sorgu, sorgu)

    def test_asiri_buyuk_kimlik_bulunamaz_hata_vermez(self):
        c = self.app()
        test_portal.hesap_ac(c, "ali@ornek.com.tr")
        ks = test_portal.oturum(c, "ali@ornek.com.tr")
        self.assertIsNone(ks.rapor(10 ** 30))
        self.assertEqual(ks.rapor_sil(10 ** 30), 0)


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgUygulamaRoluTests(PgTaban):
    """Every store function works with the least-privileged application role alig_app (DML only, no DDL, no UPDATE on append-only tables)."""

    def setUp(self):
        super().setUp()
        for ad, deger in (("depo", depo), ("portal_depo", portal_depo)):
            p = mock.patch.object(test_portal, ad, deger)
            p.start()
            self.addCleanup(p.stop)

    def test_tum_is_akisi(self):
        c = self.app()
        bos = c.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        self.assertEqual(bos, (False, False, False, False))
        # companies, reports, quota, outbox, requests
        f = depo.firma_kaydet(c, "ornek.com.tr", "Ornek", "ali@ornek.com.tr", "tarama")
        depo.firma_eposta_dogrula(c, f["id"], "ali@ornek.com.tr")
        depo.firma_izin_yaz(c, f["id"], True)
        depo.firma_durum_yaz(c, f["id"], "aktif")
        depo.firma_not_yaz(c, f["id"], "not")
        self.assertEqual(depo.firma_surec_gecis(c, f["id"], "gorusuluyor", "arandi"), ("aday", "gorusuluyor"))
        with self.assertRaises(depo.SurecHatasi):
            depo.firma_surec_gecis(c, f["id"], "musteri")
        depo.esitleme_yaz(c, "contact", "5")
        self.assertEqual(depo.esitleme_oku(c, "contact"), "5")
        b = test_tarama.temiz_belge()
        depo.rapor_ekle(c, "tok1", "postgresql", "tr", b, f["id"], "ali@ornek.com.tr")
        depo.rapor_ekle(c, "tok2", "postgresql", "tr", b, f["id"], "ali@ornek.com.tr", dogrulandi=False)
        self.assertIsNotNone(depo.rapor_getir(c, "tok1"))
        self.assertIsNotNone(depo.rapor_bekleyen_getir(c, "tok2"))
        self.assertEqual(depo.rapor_dogrula(c, depo.rapor_bekleyen_getir(c, "tok2")["id"]), 1)
        self.assertEqual(depo.bekleyen_say(c, f["id"]), 0)
        self.assertEqual(len(depo.rapor_listele(c)), 2)
        self.assertEqual(depo.kota_al(c, depo.sirket_anahtari("ali@ornek.com.tr"), depo.belge_ozeti(b)), "yeni")
        depo.posta_ekle(c, "ali@ornek.com.tr", "k", "m")
        self.assertEqual(depo.posta_say(c, "ali@ornek.com.tr"), 1)
        pid = depo.posta_bekleyenler(c)[0][0]
        depo.posta_sonuc(c, pid, hata="OSError")
        depo.posta_sonuc(c, pid)
        depo.istek_ekle(c, "tok", f["id"], "kanit", "h.example", "192.0.2.1", 5432, "postgres", "alig_hc", True, "tr")
        i = depo.istek_getir(c, "tok")
        self.assertEqual(depo.istek_deneme(c, i["id"]), 1)
        depo.istek_bitir(c, i["id"], "tamam")
        self.assertEqual(depo.istek_listele(c)[1], 1)
        self.assertEqual(depo.istek_say(c, f["id"]), 1)
        # portal
        kid, fid = test_portal.hesap_ac(c, "veli@firma-b.com.tr", "Firma B")
        ks = test_portal.oturum(c, "veli@firma-b.com.tr")
        self.assertEqual(ks.talep_ekle("destek", "Konu", "Mesaj")[1], None)
        self.assertTrue(ks.silme_talebi_ekle()[1])
        self.assertEqual(len(ks.talepler()), 2)
        self.assertEqual(ks.kullanim(2)["kullanilan"], 0)
        self.assertEqual(depo.portal_talep_durum_yaz(c, ks.talepler()[0]["id"], "inceleniyor"), 1)
        self.assertEqual(len(depo.portal_talep_listele(c)), 2)
        portal_depo.cikis(c, "yok")
        portal_depo.temizle(c)
        # retention and company deletion (deletes quota rows through the application role: DELETE is granted, UPDATE is not needed)
        self.assertEqual(depo.suresi_dolanlari_sil(c), 0)
        self.assertEqual(depo.firma_sinir_sifirla(c, f["id"]), 1)
        self.assertEqual(depo.firma_sil(c, fid), 0)
        Y.yonetici_sql("UPDATE alig.firma SET son_utc = now() - interval '9999 days'")
        Y.yonetici_sql("UPDATE alig.rapor SET bitis_utc = now() - interval '1 day'")
        self.assertGreaterEqual(depo.saklama_uygula(c), 1)
        self.assertIsNone(depo.denetim_dogrula(c))
        self.assertGreater(self.sayim("denetim"), 3)

    def test_yetki_sinirlari(self):
        c = self.app()
        for sql, durum in (("UPDATE kullanim SET zaman_utc=now()", "42501"), ("UPDATE portal_kod SET bitis_utc=now()", "42501"),
                           ("CREATE TABLE alig.x(a int)", "42501"), ("DROP TABLE alig.firma", "42501"),
                           ("ALTER TABLE alig.firma ADD COLUMN z int", "42501"), ("TRUNCATE alig.rapor", "42501"),
                           ("UPDATE schema_migrations SET surum='x'", "42501"), ("CREATE ROLE evil", "42501")):
            with self.assertRaises(pg.SorguHatasi, msg=sql) as e:
                c.execute(sql)
            self.assertEqual(e.exception.sqlstate, durum, sql)

    def test_kullanici_ve_oturum_ayari(self):
        c = self.app()
        self.assertEqual(c.execute("SELECT current_user, current_setting('TimeZone'), current_setting('search_path')").fetchone(),
                         ("alig_app", "UTC", "alig, pg_catalog"))


# ---------------------------------------------------------------------------------------------------------------------
@pg_sinifi
class PgSunucuSecimiTests(PgTaban):
    """The PostgreSQL store is selected only by explicit configuration; a configured but unusable PostgreSQL is a startup error."""

    def ortam(self, **ek):
        e = {"ALIG_DB_HOST": Y.Ortam.kume.soket, "ALIG_DB_PORT": str(Y.Ortam.kume.port), "ALIG_DB_NAME": Y.DB, "ALIG_DB_USER": "alig_app"}
        e.update(ek)
        return e

    @contextlib.contextmanager
    def korunan_modul(self):
        from tarama import portal as tportal
        eski = (tserver.depo, tportal.depo, tportal.portal_depo)
        try:
            yield tportal
        finally:
            tserver.depo, tportal.depo, tportal.portal_depo = eski

    def test_ayar_yoksa_sqlite_kalir(self):
        H = type("H", (tserver.H,), {})
        with self.korunan_modul() as tportal:
            eski, yol = tserver.depo, H.db_yolu
            self.assertIsNone(tserver.pg_ayarla({}, H))
            self.assertIs(tserver.depo, eski)
            self.assertEqual(H.db_yolu, yol)      # still the SQLite path (other tests may have set the class attribute)
            self.assertIsInstance(H.db_yolu, str)

    def test_ayar_varsa_pg_modulleri_baglanir(self):
        H = type("H", (tserver.H,), {})
        with self.korunan_modul() as tportal:
            ayar = tserver.pg_ayarla(self.ortam(), H)
            self.assertIs(tserver.depo, depo)
            self.assertIs(tportal.portal_depo, portal_depo)
            self.assertEqual(H.db_yolu, ayar)
            self.assertEqual(ayar["user"], "alig_app")
            tserver.depo.baglan(H.db_yolu).close()

    def test_eksik_ayar_hata_sqlite_a_dusmez(self):
        H = type("H", (tserver.H,), {})
        with self.korunan_modul():
            eski = tserver.depo
            with self.assertRaises(ValueError):
                tserver.pg_ayarla({"ALIG_DB_NAME": "x"}, H)     # HOST missing
            self.assertIs(tserver.depo, eski)

    def test_baslangicta_ulasilamayan_pg_acik_hata_ile_durur(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("ALIG_", "PG"))}
        e.update(self.ortam(ALIG_DB_PORT="1"), PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-m", "tarama.server", "--port", "0"], capture_output=True, text=True, env=e, cwd=str(ROOT), timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PostgreSQL is configured but cannot be used", r.stderr)
        self.assertNotIn("listening", r.stdout)
        e.pop("ALIG_DB_HOST")
        r = subprocess.run([sys.executable, "-m", "tarama.server", "--port", "0"], capture_output=True, text=True, env=e, cwd=str(ROOT), timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ALIG_DB_HOST is required", r.stderr)

    def test_posta_hizmeti_pg_ayariyla_postgresql_kutusunu_bosaltir(self):
        from tarama import posta
        c = self.app()
        depo.posta_ekle(c, "ali@firma.com", "Konu", "gizli baglanti")
        e = {k: v for k, v in os.environ.items() if not k.startswith(("ALIG_", "PG"))}
        dizin = Path(Y.Ortam.kume.dizin) / "eml"
        e.update(self.ortam(), ALIG_POSTA_DIZINI=str(dizin), PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-m", "tarama.posta"], capture_output=True, text=True, env=e, cwd=str(ROOT), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(c.execute("SELECT durum, metin FROM posta").fetchall(), [("gonderildi", "")])
        self.assertEqual(len(list(dizin.glob("*.eml"))), 1)


if __name__ == "__main__":
    unittest.main()
