"""ALIG-DB-006: transactional outbox on PostgreSQL (tarama/posta_pg.py, depo_pg.posta_ekle, db/sema/0009_outbox.sql).

Real PostgreSQL 16 (temporary cluster, application role alig_app), real concurrency (threads, each with its own connection), a fake
sender. No mail is sent anywhere (WEB-K1 is undecided). SKIPPED without PG16 / libpq; SKIPPED is not PASS.
"""
import os
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_depo_yardimci as Y  # noqa: E402
import test_pg_depo_yerel as T  # noqa: E402
import test_tarama  # noqa: E402
import smtplib  # noqa: E402
from ortak import pg  # noqa: E402
from tarama import depo_pg as depo  # noqa: E402
from tarama import posta, posta_pg  # noqa: E402
from tarama import server as tserver  # noqa: E402
from tarama import yukleme  # noqa: E402

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)


def setUpModule():
    Y.kur()


def tearDownModule():
    Y.kapat()


class SahteGonderici:
    """Records deliveries (alici, anahtar). hata: exception instance to raise; kac: raise only for the first N calls; bekle: seconds per send."""

    def __init__(self, hata=None, kac=None, bekle=0.0, once=None):
        self.hata, self.kac, self.bekle, self.once = hata, kac, bekle, once
        self.teslim, self.cagri, self.kilit = [], 0, threading.Lock()

    def gonder(self, alici, konu, metin, anahtar=None):
        with self.kilit:
            self.cagri += 1
            n = self.cagri
        if self.once:
            self.once(alici, anahtar)
        if self.bekle:
            time.sleep(self.bekle)
        if self.hata is not None and (self.kac is None or n <= self.kac):
            raise self.hata
        with self.kilit:
            self.teslim.append((alici, anahtar))


class Taban(T.PgTaban):
    def satir(self, pid=1):
        return Y.yonetici_sql("SELECT durum, deneme, metin, son_hata, mesaj_anahtari, kilit_utc IS NOT NULL FROM alig.posta WHERE id=$1", (pid,))[0]

    def ekle(self, c, anahtar=None, alici="ali@firma.com", metin="gizli baglanti"):
        return depo.posta_ekle(c, alici, "Konu", metin, anahtar)

    def sessiz(self, **ek):
        return dict(log=lambda *a: None, **ek)


@T.pg_sinifi
class PgPostaYazmaTests(Taban):
    """The intent is written in the caller's transaction."""

    def test_niyet_is_islemiyle_birlikte_geri_alinir(self):
        c = self.app()
        with self.assertRaises(RuntimeError):
            with depo.islem(c):
                depo.firma_kaydet(c, "a.com", "A", "x@a.com", "tarama")
                self.ekle(c)
                self.assertEqual(self.sayim("posta"), 0)    # not visible to anyone else before the commit
                raise RuntimeError("business step failed")
        self.assertEqual((self.sayim("posta"), self.sayim("firma")), (0, 0))   # no message for a change that never happened

    def test_niyet_commit_ile_gorunur_ve_hicbir_sey_gonderilmez(self):
        c = self.app()
        g = SahteGonderici()
        with depo.islem(c):
            self.ekle(c, "k1")
            self.assertEqual(g.teslim, [])
        self.assertEqual(self.satir(), ("bekliyor", 0, "gizli baglanti", "", "k1", False))
        self.assertEqual(g.teslim, [])

    def test_ayni_anahtar_tek_mesaj(self):
        c = self.app()
        self.assertIsNotNone(self.ekle(c, "olay-1"))
        self.assertIsNone(self.ekle(c, "olay-1", alici="baska@firma.com"))
        self.assertEqual(self.sayim("posta"), 1)
        a, b = self.ekle(c), self.ekle(c)            # no key: a random one each time
        self.assertNotEqual(self.satir(a)[4], self.satir(b)[4])

    def test_gecersiz_anahtar_ve_tablo_kisitlari(self):
        c = self.app()
        with self.assertRaises(ValueError):
            self.ekle(c, "bosluk var")
        with self.assertRaises(ValueError):
            self.ekle(c, "x" * 101)
        with self.assertRaises(pg.ButunlukHatasi):   # a claimed row without a lease is not a valid state
            c.execute("INSERT INTO posta(alici, konu, metin, olusturma_utc, mesaj_anahtari, durum) VALUES('a','k','m',?,'z','gonderiliyor')", (depo.simdi(),))
        with self.assertRaises(pg.ButunlukHatasi):
            c.execute("INSERT INTO posta(alici, konu, metin, olusturma_utc, mesaj_anahtari, durum) VALUES('a','k','m',?,'z','x')", (depo.simdi(),))

    def test_gercek_yukleme_islemi_geri_alininca_posta_da_yok_olur(self):
        class Sahte:
            sirket_adet = depo.SINIR_ADET
            eposta_dogrulama = True
            posta_adres_siniri = 3
            bekleyen_firma_siniri = 5
            site_adresi = "https://alig.tech"
        eposta = "ali@ornek.com.tr"
        anahtar_s = depo.sirket_anahtari(eposta)
        belge = yukleme.coz(test_tarama.farkli_belge(1), ("postgresql",))
        c = self.app()
        with mock.patch.object(tserver, "depo", depo):
            with mock.patch.object(depo, "denetim_ekle", side_effect=RuntimeError("audit down")):
                with self.assertRaises(RuntimeError):
                    with depo.islem(c) as t:
                        tserver.H._yukleme_isle(Sahte(), t, "tok01", anahtar_s, eposta, eposta, "Ornek AS", "tr", belge)
            self.assertEqual((self.sayim("posta"), self.sayim("rapor"), self.sayim("firma")), (0, 0, 0))
            with depo.islem(c) as t:
                self.assertEqual(tserver.H._yukleme_isle(Sahte(), t, "tok01", anahtar_s, eposta, eposta, "Ornek AS", "tr", belge), ("bekliyor",))
        self.assertEqual((self.sayim("posta"), self.sayim("rapor"), self.sayim("denetim")), (1, 1, 1))
        pid = Y.yonetici_sql("SELECT id FROM alig.posta")[0][0]
        self.assertEqual(self.satir(pid)[0], "bekliyor")


@T.pg_sinifi
class PgPostaIsciTests(Taban):
    def test_gonderim_commit_sonrasi_kilitsiz_ve_basarida_metin_silinir(self):
        c = self.app()
        self.ekle(c, "k1")
        gozlem = []

        def once(alici, anahtar):
            gozlem.append(c.in_transaction)       # no open transaction on the worker connection while sending
            gozlem.append(self.satir()[0])        # the claim is already committed and visible to others
            d = self.app()
            with depo.islem(d):                   # and no row lock is held: NOWAIT would fail otherwise
                d.execute("SELECT id FROM posta WHERE id=1 FOR UPDATE NOWAIT")
        g = SahteGonderici(once=once)
        s = posta_pg.isle(c, g, **self.sessiz())
        self.assertEqual((s.gonderilen, s.yeniden, s.olu, s.yitik), (1, 0, 0, 0))
        self.assertEqual(gozlem, [False, "gonderiliyor"])
        self.assertEqual(g.teslim, [("ali@firma.com", "k1")])
        self.assertEqual(self.satir(), ("gonderildi", 1, "", "", "k1", False))     # the text (secret link) is gone
        self.assertEqual(posta_pg.isle(c, g, **self.sessiz()).gonderilen, 0)       # not sent a second time
        self.assertEqual(len(g.teslim), 1)

    def test_talep_acik_islemde_reddedilir(self):
        c = self.app()
        with depo.islem(c):
            with self.assertRaises(RuntimeError):
                posta_pg.talep_et(c)

    def test_gecici_hata_geri_cekilmeyle_yeniden_denenir_sinirda_olur(self):
        c = self.app()
        self.ekle(c, "k1")
        g = SahteGonderici(hata=OSError("ag yok"))
        t = T0
        for deneme in range(1, posta_pg.DENEME_EN_COK):
            s = posta_pg.isle(c, g, simdi_=t, **self.sessiz())
            self.assertEqual((s.gonderilen, s.yeniden, s.olu), (0, 1, 0), deneme)
            self.assertEqual(self.satir()[:4], ("bekliyor", deneme, "gizli baglanti", "OSError"))
            bekle = posta_pg.geri_cekilme(deneme)
            self.assertEqual(posta_pg.isle(c, g, simdi_=t + timedelta(seconds=bekle - 1), **self.sessiz()), (0, 0, 0, 0, 0))   # backoff not over
            t = t + timedelta(seconds=bekle + 1)
        s = posta_pg.isle(c, g, simdi_=t, **self.sessiz())
        self.assertEqual((s.yeniden, s.olu), (0, 1))
        self.assertEqual(self.satir()[:4], ("basarisiz", posta_pg.DENEME_EN_COK, "", "OSError"))   # dead, text wiped
        self.assertEqual(posta_pg.isle(c, g, simdi_=t + timedelta(days=9), **self.sessiz()), (0, 0, 0, 0, 0))
        self.assertEqual(g.cagri, posta_pg.DENEME_EN_COK)

    def test_geri_cekilme_ustel_ve_sinirli(self):
        self.assertEqual([posta_pg.geri_cekilme(n) for n in (1, 2, 3, 4)], [30, 60, 120, 240])
        self.assertEqual(posta_pg.geri_cekilme(30), posta_pg.GERI_CEKILME_TAVAN)

    def test_kalici_ret_hemen_olur(self):
        c = self.app()
        self.ekle(c, "k1")
        ex = smtplib.SMTPRecipientsRefused({"ali@firma.com": (550, b"no such user")})
        s = posta_pg.isle(c, SahteGonderici(hata=ex), simdi_=T0, **self.sessiz())
        self.assertEqual((s.yeniden, s.olu), (0, 1))
        self.assertEqual(self.satir()[:2], ("basarisiz", 1))
        self.assertFalse(posta_pg.kalici_hata_mi(smtplib.SMTPRecipientsRefused({"a": (450, b"try later")})))
        self.assertFalse(posta_pg.kalici_hata_mi(smtplib.SMTPAuthenticationError(535, b"bad credentials")))   # configuration problem, not a bad message
        self.assertFalse(posta_pg.kalici_hata_mi(OSError("x")))

    def test_gonderici_istisnasi_satiri_kilitli_birakmaz(self):
        c = self.app()
        self.ekle(c, "k1")
        s = posta_pg.isle(c, SahteGonderici(hata=KeyError("bug")), simdi_=T0, **self.sessiz())
        self.assertEqual(s.yeniden, 1)
        self.assertEqual(self.satir()[0], "bekliyor")

    def test_hata_metni_alici_ve_metin_icermez(self):
        c = self.app()
        self.ekle(c, "k1")
        gunluk = []
        posta_pg.isle(c, SahteGonderici(hata=OSError("ali@firma.com gizli baglanti")), simdi_=T0, log=gunluk.append)
        self.assertEqual(self.satir()[3], "OSError")
        self.assertTrue(gunluk and all("ali@firma.com" not in x and "gizli" not in x for x in gunluk))

    def test_gonderimden_once_cokme_kiralama_sonrasi_yeniden_alinir_eski_isaretleme_etkisiz(self):
        c1, c2 = self.app(), self.app()
        self.ekle(c1, "k1")
        (a,) = posta_pg.talep_et(c1, kilit_saniye=100, simdi_=T0)               # worker 1 claims, then "dies"
        self.assertEqual((a.deneme, a.anahtar), (1, "k1"))
        self.assertEqual(posta_pg.talep_et(c2, kilit_saniye=100, simdi_=T0 + timedelta(seconds=99)), [])   # lease still valid
        (b,) = posta_pg.talep_et(c2, kilit_saniye=100, simdi_=T0 + timedelta(seconds=101))
        self.assertEqual((b.id, b.deneme), (a.id, 2))                           # the crash counted as an attempt
        self.assertFalse(posta_pg.gonderildi(c1, a))                            # the zombie's mark does not match attempt 2
        self.assertEqual(posta_pg.hatali(c1, a, "OSError"), "yitik")
        self.assertEqual(self.satir()[:2], ("gonderiliyor", 2))
        self.assertTrue(posta_pg.gonderildi(c2, b))
        self.assertEqual(self.satir()[0], "gonderildi")

    def test_son_denemede_cokme_olu_duruma_gider_sonsuz_dongu_yok(self):
        c = self.app()
        self.ekle(c, "k1")
        t = T0
        for n in range(posta_pg.DENEME_EN_COK):
            (i,) = posta_pg.talep_et(c, kilit_saniye=10, simdi_=t)
            self.assertEqual(i.deneme, n + 1)                                   # claimed, never marked: the worker keeps dying
            t += timedelta(seconds=11)
        self.assertEqual(posta_pg.talep_et(c, kilit_saniye=10, simdi_=t), [])
        self.assertEqual(self.satir()[:3], ("basarisiz", posta_pg.DENEME_EN_COK, ""))

    def test_gonderim_sonrasi_isaretleme_oncesi_cokme_en_cok_bir_kez_daha_gonderir_ayni_anahtarla(self):
        c1, c2 = self.app(), self.app()
        self.ekle(c1, "k1")
        g = SahteGonderici()
        with mock.patch.object(posta_pg, "gonderildi", side_effect=pg.BaglantiHatasi("connection lost after the send")):
            with self.assertRaises(pg.BaglantiHatasi):
                posta_pg.isle(c1, g, kilit_saniye=100, simdi_=T0, **self.sessiz())
        self.assertEqual(len(g.teslim), 1)                                      # delivered, but not recorded
        self.assertEqual(self.satir()[:2], ("gonderiliyor", 1))
        s = posta_pg.isle(c2, g, kilit_saniye=100, simdi_=T0 + timedelta(seconds=101), **self.sessiz())
        self.assertEqual(s.gonderilen, 1)
        self.assertEqual(g.teslim, [("ali@firma.com", "k1")] * 2)               # the honest at-least-once case: twice, the same key
        self.assertEqual(posta_pg.isle(c2, g, simdi_=T0 + timedelta(days=1), **self.sessiz()).gonderilen, 0)
        self.assertEqual(len(g.teslim), 2)

    def test_kiralama_bitmek_uzereyken_gonderim_baslamaz_ve_deneme_sayilmaz(self):
        c = self.app()
        self.ekle(c, "k1")
        self.ekle(c, "k2")
        sayac = iter([0.0, 0.0, 95.0, 95.0, 95.0, 95.0])    # monotonic clock: the 2nd message starts 95 s into a 100 s lease
        g = SahteGonderici()
        s = posta_pg.isle(c, g, kilit_saniye=100, saat=lambda: next(sayac), simdi_=T0, **self.sessiz())
        self.assertEqual((s.gonderilen, s.birakilan), (1, 1))
        self.assertEqual(g.teslim, [("ali@firma.com", "k1")])
        self.assertEqual(self.satir(2)[:2], ("bekliyor", 0))                    # given back untouched

    def test_koruma_silme_gonderilmekte_olan_iletiyi_silmez(self):
        c = self.app()
        self.ekle(c, "k1")
        self.ekle(c, "k2")
        posta_pg.talep_et(c, en_cok=1, kilit_saniye=100)
        Y.yonetici_sql("UPDATE alig.posta SET olusturma_utc = '2000-01-01T00:00:00Z'")
        depo.suresi_dolanlari_sil(c)
        self.assertEqual(self.sayim("posta"), 2)                                # in-flight and waiting rows survive retention


@T.pg_sinifi
class PgPostaEszamanliTests(Taban):
    def test_esizamanli_isciler_hic_cift_gondermez(self):
        c = self.app()
        N = 60
        with depo.islem(c):
            for i in range(N):
                self.ekle(c, "olay-%d" % i, alici="u%d@firma.com" % i)
        g = SahteGonderici(bekle=0.004)

        def isci(i):
            def is_(con):
                toplam = 0
                for _ in range(40):
                    s = posta_pg.isle(con, g, en_cok=3, **self.sessiz())
                    toplam += s.gonderilen
                    if s == (0, 0, 0, 0, 0):
                        break
                return toplam
            return T.kendi_baglantisiyla(is_)
        sonuc = T.paralel(8, isci)
        self.assertEqual([x for x in sonuc if isinstance(x, BaseException)], [])
        self.assertEqual(sum(sonuc), N)
        self.assertEqual(sorted(a for _, a in g.teslim), sorted("olay-%d" % i for i in range(N)))    # every key exactly once
        self.assertEqual(self.sayim("posta", "WHERE durum='gonderildi' AND metin='' AND deneme=1"), N)
        self.assertGreater(sum(1 for x in sonuc if x), 1)                       # the work really was shared between workers

    def test_esizamanli_talep_ayni_satiri_iki_kez_vermez(self):
        c = self.app()
        with depo.islem(c):
            for i in range(30):
                self.ekle(c, "q-%d" % i)

        def talep(i):
            return T.kendi_baglantisiyla(lambda con: [x.id for x in posta_pg.talep_et(con, en_cok=30)])
        sonuc = T.paralel(8, talep)
        self.assertEqual([x for x in sonuc if isinstance(x, BaseException)], [])
        hepsi = [i for r in sonuc for i in r]
        self.assertEqual(sorted(hepsi), list(range(1, 31)))                    # a partition: no row claimed twice, none lost

    def test_kontrol_talepsiz_okuma_ayni_satiri_birden_cok_isciye_verir(self):
        """The test has teeth: workers that only SELECT the pending rows (no claim) all get the same rows, i.e. would all send them."""
        c = self.app()
        with depo.islem(c):
            for i in range(10):
                self.ekle(c, "c-%d" % i)

        def oku(i):
            return T.kendi_baglantisiyla(lambda con: [r[0] for r in con.execute("SELECT id FROM posta WHERE durum='bekliyor' ORDER BY id LIMIT 10").fetchall()])
        hepsi = [i for r in T.paralel(4, oku) for i in r]
        self.assertGreater(len(hepsi), 10)

    def test_ayni_anahtarla_es_zamanli_ekleme_tek_mesaj(self):
        def ekle(i):
            def is_(con):
                with depo.islem(con):
                    return depo.posta_ekle(con, "a@firma.com", "K", "m", "ayni-olay")
            return T.kendi_baglantisiyla(is_)
        sonuc = T.paralel(8, ekle)
        self.assertEqual([x for x in sonuc if isinstance(x, BaseException)], [])
        self.assertEqual(len([x for x in sonuc if x is not None]), 1)
        self.assertEqual(self.sayim("posta"), 1)


class IletiBasliklariTests(unittest.TestCase):
    """The receiver-side dedupe key is in the message headers (no database needed)."""

    def test_anahtar_message_id_ve_ozel_baslikta_ve_denemeler_arasi_sabit(self):
        a = bytes(posta._ileti("tarama@alig.tech", "ali@firma.com", "K", "m", "olay-7"))
        b = bytes(posta._ileti("tarama@alig.tech", "ali@firma.com", "K", "m", "olay-7"))
        ma, mb = message_from_bytes(a), message_from_bytes(b)
        self.assertEqual(ma["Message-ID"], "<alig-olay-7@alig.tech>")
        self.assertEqual(ma["Message-ID"], mb["Message-ID"])
        self.assertEqual(ma["X-Alig-Idempotency-Key"], "olay-7")
        self.assertIsNone(message_from_bytes(bytes(posta._ileti("t@alig.tech", "a@b.c", "K", "m")))["X-Alig-Idempotency-Key"])

    def test_gondericiler_anahtar_kabul_eder(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        posta.DosyaGonderici(d).gonder("ali@firma.com", "K", "m", anahtar="olay-9")
        self.assertIn(b"X-Alig-Idempotency-Key: olay-9", next(d.iterdir()).read_bytes())


@T.pg_sinifi
class PgPostaHizmetiTests(Taban):
    def test_hizmet_pg_modunda_transaksiyonel_isciyi_kullanir_ve_basligi_yazar(self):
        c = self.app()
        with depo.islem(c):
            self.ekle(c, "olay-1")
        e = {k: v for k, v in os.environ.items() if not k.startswith(("ALIG_", "PG"))}
        dizin = Path(Y.Ortam.kume.dizin) / "eml-outbox"
        e.update({"ALIG_DB_HOST": Y.Ortam.kume.soket, "ALIG_DB_PORT": str(Y.Ortam.kume.port), "ALIG_DB_NAME": Y.DB, "ALIG_DB_USER": "alig_app",
                  "ALIG_POSTA_DIZINI": str(dizin), "PYTHONPATH": str(ROOT)})
        r = subprocess.run([sys.executable, "-m", "tarama.posta"], capture_output=True, text=True, env=e, cwd=str(ROOT), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.satir()[:3], ("gonderildi", 1, ""))
        (f,) = list(dizin.glob("*.eml"))
        m = message_from_bytes(f.read_bytes())
        self.assertEqual((m["X-Alig-Idempotency-Key"], m["Message-ID"].startswith("<alig-olay-1@")), ("olay-1", True))


if __name__ == "__main__":
    unittest.main()
