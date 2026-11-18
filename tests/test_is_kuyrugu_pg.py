"""Roadmap item 21: PostgreSQL job queue for Mode B (ortak/is_kuyrugu_pg.py, db/sema/0008_is_kuyrugu.sql).
Real concurrency: threads with their own connections and a separate OS process killed with SIGKILL, against a temporary PostgreSQL 16
cluster with the real schema. SKIPped (never PASS) when PostgreSQL 16 or libpq is missing."""
import hashlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_sema_kume  # noqa: E402
import pg_yardimci  # noqa: E402
from ortak import is_kuyrugu_pg as k  # noqa: E402
from ortak import pg  # noqa: E402
from tarama import baglanti, calistirici, hedef  # noqa: E402

KANIT = "ab" * 16
GIZLI = "cok-gizli-musteri-degeri-93241"


class BirimTests(unittest.TestCase):
    """No server needed."""

    def test_gecersiz_argumanlar_baglanmadan_reddedilir(self):
        def yasak(*a, **kw):
            raise AssertionError("must not use the connection")
        with self.assertRaises(ValueError):
            k.al(yasak, "bad name!")
        with self.assertRaises(ValueError):
            k.al(yasak, "w1", kira_sn=0)
        with self.assertRaises(ValueError):
            k.al(yasak, "w1", firma_basina=0)
        with self.assertRaises(ValueError):
            k.basarisiz(yasak, k.Is(1, 1, 1, "t", None, "w", 1, 1, 1), "an error text with spaces")
        with self.assertRaises(ValueError):
            k.ekle(yasak, 1, 1, azami_deneme=0)
        with self.assertRaises(ValueError):
            k.ekle(yasak, 1, 1, tur="Bad Type")
        with self.assertRaises(ValueError):
            k.ekle(yasak, 1, 1, sahip="a b")

    def test_isci_yapilandirmasi(self):
        with self.assertRaises(ValueError):
            k.Isci(lambda: None, "w", lambda i, g: None, kira_sn=10, nabiz_sn=10)   # the beat must be shorter than the lease
        with self.assertRaises(TypeError):
            k.Isci("x", "w", lambda i, g: None)

    def test_bos_yoklama_araligi_titresimli_ve_sinirli(self):
        w = k.Isci(lambda: None, "w", lambda i, g: None, bos_bekleme_s=2.0)
        degerler = {round(w.bekleme_suresi(), 6) for _ in range(200)}
        self.assertGreater(len(degerler), 50)   # not a fixed period
        self.assertTrue(all(1.0 <= d <= 3.0 for d in degerler))

    def test_kod_guvenli(self):
        self.assertEqual(k._kod_guvenli("baglanti"), "baglanti")
        self.assertEqual(k._kod_guvenli("has spaces and a secret"), "hata")
        self.assertEqual(k._kod_guvenli(None), "hata")


CALISAN = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from ortak import pg, is_kuyrugu_pg as k
ayar = dict(host=sys.argv[2], port=int(sys.argv[3]), dbname=sys.argv[4], user="alig_app")
def isle(is_, gecerli):
    print("ALINDI", is_.id, flush=True)
    time.sleep(600)
k.Isci(lambda: pg.Baglanti.baglan(**ayar), sys.argv[5], isle, kira_sn=2, nabiz_sn=0.5, bos_bekleme_s=0.05).calis()
"""


@pg_yardimci.pg_testi(pg_sema_kume.PG_VAR, pg_sema_kume.PG_NEDEN)
class KuyrukTests(pg_sema_kume.SemaKumesi, unittest.TestCase):
    def setUp(self):
        self.sql("TRUNCATE alig.is_kuyrugu, alig.is_kuyrugu_sira, alig.baglanti_istegi, alig.firma CASCADE")
        self.con = self.baglan()
        self.n = 0

    # ---- helpers
    def firma(self, ad="f"):
        self.n += 1
        return self.con.sorgu("INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES ($1, $2, 'x@example.com', 'test', now(), now()) "
                              "RETURNING id", ("a%s%d" % (ad, self.n), ad))[0][0]

    def istek(self, firma_id):
        self.n += 1
        return self.con.sorgu(
            "INSERT INTO alig.baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, dil, olusturma_utc, bitis_utc) "
            "VALUES ($1, $2, 'k', 'db.example.com', '93.184.216.34', 5432, 'postgres', 'alig_hc', 'tr', now(), now() + interval '1 hour') RETURNING id",
            (hashlib.sha256(str(self.n).encode()).hexdigest(), firma_id))[0][0]

    def is_ekle(self, firma_id, adet=1, **kw):
        return [k.ekle(self.con, firma_id, self.istek(firma_id), **kw) for _ in range(adet)]

    def yeni_baglanti(self):
        b = pg.Baglanti.baglan(**self.app_ayar())
        self.addCleanup(b.kapat)
        return b

    def satir(self, id_):
        r = self.con.sorgu("SELECT durum, deneme, kira_no, son_hata, isci, uygun_utc > clock_timestamp() FROM alig.is_kuyrugu WHERE id = $1", (id_,))
        return r[0]

    def paralel(self, hedefler):
        sonuc, hatalar = [None] * len(hedefler), []

        def sar(i, f):
            try:
                sonuc[i] = f()
            except BaseException as e:   # noqa: BLE001 - reported below
                hatalar.append(e)
        ts = [threading.Thread(target=sar, args=(i, f)) for i, f in enumerate(hedefler)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        self.assertEqual(hatalar, [])
        return sonuc

    # ---- basic life cycle
    def test_ekle_idempotent_ve_al_tamam(self):
        f = self.firma()
        i = self.istek(f)
        a = k.ekle(self.con, f, i)
        self.assertEqual(k.ekle(self.con, f, i), a)   # the same request is the same job
        self.assertEqual(self.sql("SELECT count(*) FROM alig.is_kuyrugu"), "1")
        is_ = k.al(self.con, "w1")
        self.assertEqual((is_.id, is_.firma_id, is_.istek_id, is_.kira_no, is_.deneme), (a, f, i, 1, 1))
        self.assertIsNone(k.al(self.con, "w2"))   # nothing else to claim
        self.assertEqual(k.tamam(self.con, is_), "tamam")
        self.assertEqual(self.satir(a)[:2], ("tamam", 1))
        self.assertEqual(k.durum_say(self.con), {"tamam": 1})

    def test_ekle_sinirlari_yumusak_ama_calisir(self):
        f = self.firma()
        self.is_ekle(f, 2, firma_azami=2)
        with self.assertRaises(k.KuyrukDolu):
            k.ekle(self.con, f, self.istek(f), firma_azami=2)
        g = self.firma()
        with self.assertRaises(k.KuyrukDolu):
            k.ekle(self.con, g, self.istek(g), azami_bekleyen=2)
        self.assertEqual(len(self.is_ekle(g, 1, firma_azami=2)), 1)   # another company is unaffected by the per-company limit

    def test_gelecekteki_is_alinmaz_ve_sirasi(self):
        f = self.firma()
        a, b = self.is_ekle(f, 2)
        self.sql("UPDATE alig.is_kuyrugu SET uygun_utc = now() + interval '1 hour' WHERE id = %d" % a)
        self.assertEqual(k.al(self.con, "w", firma_basina=5).id, b)
        self.assertIsNone(k.al(self.con, "w", firma_basina=5))

    # ---- no job claimed twice
    def test_hicbir_is_iki_kez_alinmaz_es_zamanli(self):
        firmalar = [self.firma() for _ in range(5)]
        ids = [j for f in firmalar for j in self.is_ekle(f, 40)]
        alinan, kilit = [], threading.Lock()

        def isci(ad):
            b = self.yeni_baglanti()
            bos = 0
            while bos < 3:
                j = k.al(b, ad, firma_basina=3)
                if j is None:
                    bos += 1
                    time.sleep(0.01)
                    continue
                bos = 0
                with kilit:
                    alinan.append(j.id)
                self.assertEqual(k.tamam(b, j), "tamam")
        self.paralel([lambda ad="w%d" % n: isci(ad) for n in range(8)])
        self.assertEqual(len(alinan), len(set(alinan)), "a job was claimed twice")
        self.assertEqual(sorted(alinan), sorted(ids))
        self.assertEqual(k.durum_say(self.con), {"tamam": 200})
        self.assertEqual(self.sql("SELECT count(*) FROM alig.is_kuyrugu WHERE deneme <> 1 OR kira_no <> 1"), "0")

    def test_hicbir_is_iki_kez_alinmaz_ayri_surecler(self):
        f = self.firma()
        ids = self.is_ekle(f, 60)
        betik = ("import sys\nsys.path.insert(0, sys.argv[1])\nfrom ortak import pg, is_kuyrugu_pg as k\n"
                 "b = pg.Baglanti.baglan(host=sys.argv[2], port=int(sys.argv[3]), dbname=sys.argv[4], user='alig_app')\n"
                 "bos = 0\nwhile bos < 3:\n j = k.al(b, sys.argv[5], firma_basina=4)\n if j is None:\n  bos += 1\n  continue\n"
                 " bos = 0\n print(j.id, flush=True)\n k.tamam(b, j)\n")
        surecler = [subprocess.Popen([sys.executable, "-c", betik, str(ROOT), self.kume.soket, str(self.kume.port), self.DB, "p%d" % n],
                                     stdout=subprocess.PIPE, text=True) for n in range(4)]
        alinan = []
        for s in surecler:
            cikti, _ = s.communicate(timeout=120)
            self.assertEqual(s.returncode, 0)
            alinan += [int(x) for x in cikti.split()]
        self.assertEqual(sorted(alinan), sorted(ids))   # every job exactly once across 4 processes

    # ---- fairness
    def test_firmalar_arasinda_adil_sira(self):
        a, b, c = self.firma("a"), self.firma("b"), self.firma("c")
        self.is_ekle(a, 30)
        self.is_ekle(b, 3)
        self.is_ekle(c, 3)
        sira = []
        for _ in range(9):
            j = k.al(self.con, "w", firma_basina=100)   # no per-company cap: only the order is tested
            sira.append(j.firma_id)
            k.tamam(self.con, j)
        self.assertEqual(sira[:3], [a, b, c])   # never served first, in id order
        self.assertEqual(sira, [a, b, c] * 3)   # then strictly round robin: the big queue of `a` does not run ahead
        self.assertEqual(Counter(sira), {a: 3, b: 3, c: 3})

    def test_bir_firma_tum_iscileri_tutamaz(self):
        a, b = self.firma("a"), self.firma("b")
        self.is_ekle(a, 20)
        self.is_ekle(b, 1)
        j1 = k.al(self.con, "w1", firma_basina=1)
        self.assertEqual(j1.firma_id, a)
        j2 = k.al(self.con, "w2", firma_basina=1)   # a is at its cap: the worker serves b
        self.assertEqual(j2.firma_id, b)
        self.assertIsNone(k.al(self.con, "w3", firma_basina=1))   # a is still at its cap and b has nothing else: the third worker stays free
        k.tamam(self.con, j1)
        self.assertEqual(k.al(self.con, "w3", firma_basina=1).firma_id, a)   # the slot is available again

    def test_firma_basina_sinir_yaris_altinda_asilmaz(self):
        a, b = self.firma("a"), self.firma("b")
        self.is_ekle(a, 12)
        self.is_ekle(b, 12)
        baglantilar = [self.yeni_baglanti() for _ in range(8)]
        for tur in range(10):
            bariyer = threading.Barrier(len(baglantilar))

            def al(i):
                bariyer.wait()
                return k.al(baglantilar[i], "w%d" % i, firma_basina=1)
            alinan = [j for j in self.paralel([lambda i=i: al(i) for i in range(len(baglantilar))]) if j is not None]
            self.assertEqual(Counter(j.firma_id for j in alinan), {a: 1, b: 1}, "round %d: a company ran above its cap" % tur)
            for j in alinan:
                k.tamam(self.con, j)

    # ---- lease, heartbeat, reclaim
    def test_kira_dolunca_baska_isci_alir_eski_kira_reddedilir(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        eski = k.al(self.con, "w1", kira_sn=1)
        time.sleep(1.4)
        yeni = k.al(self.yeni_baglanti(), "w2", kira_sn=30, taban_s=0, tavan_s=0)
        self.assertIsNotNone(yeni)
        self.assertEqual((yeni.id, yeni.kira_no, yeni.deneme), (a, 2, 2))
        with self.assertRaises(k.KiraKaybedildi):
            k.tamam(self.con, eski)   # stale lease cannot complete
        with self.assertRaises(k.KiraKaybedildi):
            k.nabiz(self.con, eski)
        with self.assertRaises(k.KiraKaybedildi):
            k.basarisiz(self.con, eski, "x")
        self.assertEqual(self.satir(a)[0], "calisiyor")   # the stale attempts changed nothing
        self.assertEqual(k.tamam(self.con, yeni), "tamam")

    def test_nabiz_kirayi_uzatir(self):
        f = self.firma()
        self.is_ekle(f)
        j = k.al(self.con, "w1", kira_sn=1.0)
        for _ in range(5):
            time.sleep(0.4)
            k.nabiz(self.con, j, 1.0)
        self.assertIsNone(k.al(self.yeni_baglanti(), "w2", kira_sn=1.0, taban_s=0, tavan_s=0))   # 2 s later the lease is still ours
        self.assertEqual(k.tamam(self.con, j), "tamam")

    def test_suresi_dolan_kira_en_cok_azami_deneme_kez_denenir(self):
        f = self.firma()
        (a,) = self.is_ekle(f, azami_deneme=2)
        for beklenen in (1, 2):
            j = k.al(self.con, "w", kira_sn=0.2, taban_s=0, tavan_s=0)
            self.assertEqual(j.deneme, beklenen)
            time.sleep(0.4)
        self.assertEqual(k.birak_suresi_dolan(self.con), 1)
        self.assertEqual(self.satir(a)[:4], ("olu", 2, 2, "kira_doldu"))
        self.assertIsNone(k.al(self.con, "w"))   # a dead letter is never claimed again

    # ---- retry, back-off, dead letter
    def test_geri_cekilme_ve_olu_mektup(self):
        f = self.firma()
        (a,) = self.is_ekle(f, azami_deneme=3)
        j = k.al(self.con, "w", taban_s=30, tavan_s=300)
        self.assertEqual(k.basarisiz(self.con, j, "gecici_hata", taban_s=30, tavan_s=300), "bekliyor")
        durum, deneme, _, hata, _, gelecekte = self.satir(a)
        self.assertEqual((durum, deneme, hata, gelecekte), ("bekliyor", 1, "gecici_hata", True))
        bekleme = float(self.sql("SELECT extract(epoch FROM uygun_utc - clock_timestamp()) FROM alig.is_kuyrugu WHERE id = %d" % a))
        self.assertTrue(14 <= bekleme <= 30.5, bekleme)   # 30 s x [0.5, 1]
        self.assertIsNone(k.al(self.con, "w"))   # not yet due
        for beklenen_deneme in (2, 3):
            self.sql("UPDATE alig.is_kuyrugu SET uygun_utc = now() WHERE id = %d" % a)
            j = k.al(self.con, "w", taban_s=0, tavan_s=0)
            self.assertEqual(j.deneme, beklenen_deneme)
            sonuc = k.basarisiz(self.con, j, "gecici_hata", taban_s=0, tavan_s=0)
        self.assertEqual(sonuc, "olu")   # the third attempt failed: dead letter
        self.assertEqual(self.satir(a)[:4], ("olu", 3, 3, "gecici_hata"))
        self.assertEqual(self.sql("SELECT bitis_utc IS NOT NULL FROM alig.is_kuyrugu WHERE id = %d" % a), "t")
        self.sql("UPDATE alig.is_kuyrugu SET uygun_utc = now() WHERE id = %d" % a)
        self.assertIsNone(k.al(self.con, "w"))

    def test_geri_cekilme_ustel_ve_sinirli(self):
        f = self.firma()
        (a,) = self.is_ekle(f, azami_deneme=8)
        bekler = []
        for _ in range(5):
            self.sql("UPDATE alig.is_kuyrugu SET uygun_utc = now() WHERE id = %d" % a)
            j = k.al(self.con, "w", taban_s=2, tavan_s=10)
            k.basarisiz(self.con, j, "e", taban_s=2, tavan_s=10)
            bekler.append(float(self.sql("SELECT extract(epoch FROM uygun_utc - clock_timestamp()) FROM alig.is_kuyrugu WHERE id = %d" % a)))
        ust = [2, 4, 8, 10, 10]   # 2 * 2**(n-1) capped at 10
        for b, u in zip(bekler, ust):
            self.assertTrue(u * 0.5 - 0.3 <= b <= u + 0.1, (bekler, ust))

    def test_kalici_hata_hemen_olu(self):
        f = self.firma()
        (a,) = self.is_ekle(f, azami_deneme=5)
        j = k.al(self.con, "w")
        self.assertEqual(k.basarisiz(self.con, j, "kalici_hata", yeniden_dene=False), "olu")
        self.assertEqual(self.satir(a)[:2], ("olu", 1))

    def test_hata_metni_saklanamaz(self):
        f = self.firma()
        self.is_ekle(f)
        j = k.al(self.con, "w")
        with self.assertRaises(pg.ButunlukHatasi):   # the table itself refuses anything but a short code (here: spaces and a value)
            self.con.sorgu("UPDATE alig.is_kuyrugu SET son_hata = $1 WHERE id = $2", ("login failed for " + GIZLI, j.id))

    # ---- idempotent transitions
    def test_ikinci_tamam_zaten_ve_degistirmez(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        j = k.al(self.con, "w")
        self.assertEqual(k.tamam(self.con, j), "tamam")
        bitis = self.sql("SELECT bitis_utc FROM alig.is_kuyrugu WHERE id = %d" % a)
        self.assertEqual(k.tamam(self.con, j), "zaten")
        self.assertEqual(self.sql("SELECT bitis_utc FROM alig.is_kuyrugu WHERE id = %d" % a), bitis)
        with self.assertRaises(k.KiraKaybedildi):   # a finished job cannot be failed afterwards
            k.basarisiz(self.con, j, "e")
        self.assertEqual(self.satir(a)[0], "tamam")

    def test_es_zamanli_tamam_tek_gecis(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        j = k.al(self.con, "w")
        baglantilar = [self.yeni_baglanti() for _ in range(8)]
        bariyer = threading.Barrier(8)

        def tamamla(b):
            bariyer.wait()
            return k.tamam(b, j)
        sonuc = self.paralel([lambda b=b: tamamla(b) for b in baglantilar])
        self.assertEqual(Counter(sonuc), {"tamam": 1, "zaten": 7})
        self.assertEqual(self.satir(a)[:2], ("tamam", 1))

    def test_ikinci_basarisiz_zaten_ve_sayac_artmaz(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        j = k.al(self.con, "w")
        self.assertEqual(k.basarisiz(self.con, j, "e", taban_s=30, tavan_s=30), "bekliyor")
        self.assertEqual(k.basarisiz(self.con, j, "e", taban_s=30, tavan_s=30), "zaten")
        with self.assertRaises(k.KiraKaybedildi):   # nor can a failed attempt be completed late
            k.tamam(self.con, j)
        self.assertEqual(self.satir(a)[:3], ("bekliyor", 1, 1))

    def test_iptal_yalniz_bekleyen_is(self):
        f = self.firma()
        a, b = self.is_ekle(f, 2)
        j = k.al(self.con, "w")
        self.assertFalse(k.iptal(self.con, j.id))   # already leased
        other = b if j.id == a else a
        self.assertTrue(k.iptal(self.con, other))
        self.assertFalse(k.iptal(self.con, other))
        self.assertEqual(self.satir(other)[:4], ("olu", 0, 0, "iptal"))

    # ---- restart recovery
    def test_isci_yeniden_baslayinca_ayni_adin_kirasi_hemen_serbest(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        k.al(self.con, "w1", kira_sn=300)   # a "crashed" worker: the lease would hold for 5 minutes
        self.assertIsNone(k.al(self.yeni_baglanti(), "w2", kira_sn=300))
        self.assertEqual(k.isci_birak(self.con, "w1", taban_s=0, tavan_s=0), 1)
        self.assertEqual(self.satir(a)[:4], ("bekliyor", 1, 1, "isci_yeniden_basladi"))
        self.assertEqual(k.al(self.con, "w1", kira_sn=300).kira_no, 2)

    def test_sigkill_ile_olen_surecten_kurtarma(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        p = subprocess.Popen([sys.executable, "-c", CALISAN, str(ROOT), self.kume.soket, str(self.kume.port), self.DB, "olen"],
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.kill)
        self.assertEqual(p.stdout.readline().split(), ["ALINDI", str(a)])
        self.assertEqual(self.satir(a)[:3], ("calisiyor", 1, 1))
        os.kill(p.pid, signal.SIGKILL)
        p.wait(10)
        # the same worker name restarts: it takes the job back at once (the lease of 2 s has not necessarily run out)
        islenen = []
        w = k.Isci(lambda: self.yeni_baglanti(), "olen", lambda is_, g: islenen.append(is_), kira_sn=30, bos_bekleme_s=0.05, taban_s=0, tavan_s=0)
        t = threading.Thread(target=w.calis)
        t.start()
        for _ in range(100):
            if islenen:
                break
            time.sleep(0.05)
        w.durdur.set()
        t.join(10)
        self.assertEqual([x.id for x in islenen], [a])
        self.assertEqual(islenen[0].deneme, 2)
        self.assertEqual(self.satir(a)[:2], ("tamam", 2))

    def test_baska_adli_isci_kira_dolunca_kurtarir(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        p = subprocess.Popen([sys.executable, "-c", CALISAN, str(ROOT), self.kume.soket, str(self.kume.port), self.DB, "olen2"],
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.kill)
        self.assertEqual(p.stdout.readline().split()[0], "ALINDI")
        os.kill(p.pid, signal.SIGKILL)
        p.wait(10)
        islenen = []
        w = k.Isci(lambda: self.yeni_baglanti(), "baska", lambda is_, g: islenen.append(is_), kira_sn=30, bos_bekleme_s=0.05, taban_s=0, tavan_s=0)
        t = threading.Thread(target=w.calis)
        t.start()
        for _ in range(200):   # the dead worker's 2 s lease runs out, then the job is reclaimed
            if islenen:
                break
            time.sleep(0.05)
        w.durdur.set()
        t.join(10)
        self.assertEqual([x.id for x in islenen], [a])
        self.assertEqual(self.satir(a)[:2], ("tamam", 2))

    # ---- worker loop
    def kos(self, isleyici, sure=3.0, **kw):
        w = k.Isci(lambda: self.yeni_baglanti(), kw.pop("isci", "wk"), isleyici, kira_sn=kw.pop("kira_sn", 30), bos_bekleme_s=0.05,
                   taban_s=0, tavan_s=0, **kw)
        t = threading.Thread(target=w.calis)
        t.start()
        self.addCleanup(t.join, 10)
        self.addCleanup(w.durdur.set)
        return w

    def bekle(self, kosul, sn=15):
        son = time.time() + sn
        while time.time() < son:
            if kosul():
                return True
            time.sleep(0.05)
        return False

    def test_isci_dongusu_hata_turleri(self):
        f = self.firma()
        ok, gecici, kalici, patla = self.is_ekle(f, 4, azami_deneme=2)
        istekler = {r[0]: r[1] for r in self.con.sorgu("SELECT id, istek_id FROM alig.is_kuyrugu")}
        sayac = Counter()

        def isle(is_, gecerli):
            sayac[is_.id] += 1
            if is_.id == gecici:
                raise k.Gecici("gecici_kod")
            if is_.id == kalici:
                raise k.Kalici("kalici_kod")
            if is_.id == patla:
                raise RuntimeError("login failed for " + GIZLI)
        self.kos(isle, firma_basina=4)
        self.assertTrue(self.bekle(lambda: self.con.sorgu("SELECT count(*) FROM alig.is_kuyrugu WHERE durum IN ('tamam','olu')")[0][0] == 4))
        self.assertEqual(self.satir(ok)[:4], ("tamam", 1, 1, ""))
        self.assertEqual(self.satir(gecici)[:2], ("olu", 2))   # retried once, then dead (azami_deneme=2)
        self.assertEqual(self.satir(gecici)[3], "gecici_kod")
        self.assertEqual(self.satir(kalici)[:4], ("olu", 1, 1, "kalici_kod"))
        self.assertEqual(self.satir(patla)[:2], ("olu", 2))
        self.assertEqual(self.satir(patla)[3], "hata")   # the exception text (which echoed an input) is not stored
        self.assertNotIn(GIZLI, self.sql("SELECT row_to_json(t) FROM alig.is_kuyrugu t"))
        self.assertEqual((sayac[ok], sayac[gecici], sayac[kalici], sayac[patla]), (1, 2, 1, 2))

    def test_uzun_is_nabiz_ile_kirayi_korur_ve_baskasi_alamaz(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        basladi, birak = threading.Event(), threading.Event()

        def isle(is_, gecerli):
            basladi.set()
            birak.wait(10)   # runs 2.5x longer than its lease; the heartbeat has to keep it
        w = k.Isci(lambda: self.yeni_baglanti(), "uzun", isle, kira_sn=1.0, nabiz_sn=0.3, bos_bekleme_s=0.05)
        t = threading.Thread(target=w.calis)
        t.start()
        self.addCleanup(t.join, 10)
        self.addCleanup(w.durdur.set)
        self.assertTrue(basladi.wait(10))
        time.sleep(2.5)
        self.assertIsNone(k.al(self.yeni_baglanti(), "diger", kira_sn=30))
        self.assertEqual(self.satir(a)[:2], ("calisiyor", 1))
        birak.set()
        self.assertTrue(self.bekle(lambda: self.satir(a)[0] == "tamam"))

    def test_kira_kaybolursa_isleyici_gecerli_degil_gorur_ve_sonuc_yazilmaz(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        gordu = []

        def isle(is_, gecerli):
            self.sql("UPDATE alig.is_kuyrugu SET kira_no = kira_no + 1 WHERE id = %d" % a)   # somebody else took the job over
            for _ in range(100):
                if not gecerli():
                    break
                time.sleep(0.05)
            gordu.append(gecerli())
        w = k.Isci(lambda: self.yeni_baglanti(), "w", isle, kira_sn=1.0, nabiz_sn=0.2, bos_bekleme_s=0.05)
        t = threading.Thread(target=w.calis)
        t.start()
        self.addCleanup(t.join, 10)
        self.addCleanup(w.durdur.set)
        self.assertTrue(self.bekle(lambda: gordu))
        self.assertEqual(gordu, [False])
        self.assertEqual(self.satir(a)[0], "calisiyor")   # the stale worker recorded nothing

    # ---- no payload: the queue cannot carry a secret
    def test_tabloda_yuk_kolonu_yok_ve_metin_kolonlari_kisitli(self):
        kolonlar = self.sql("SELECT string_agg(column_name || ':' || data_type, ' ' ORDER BY ordinal_position) FROM information_schema.columns "
                            "WHERE table_schema = 'alig' AND table_name = 'is_kuyrugu'").split()
        self.assertEqual([c for c in kolonlar if c.endswith(":jsonb") or c.endswith(":json") or c.endswith(":bytea")], [])
        metin = [c.split(":")[0] for c in kolonlar if c.endswith(":text")]
        self.assertEqual(sorted(metin), ["durum", "isci", "sahip", "son_hata", "tur"])
        for ad in ("tur", "sahip", "isci", "son_hata"):
            with self.assertRaises(pg.ButunlukHatasi):
                f = self.firma()
                i = self.istek(f)
                self.con.sorgu("INSERT INTO alig.is_kuyrugu(tur, firma_id, istek_id, sahip, isci, son_hata, uygun_utc, olusturma_utc) "
                               "VALUES ($1, $2, $3, $4, $5, $6, now(), now())",
                               ("t" if ad != "tur" else "x " + GIZLI, f, i, "s" if ad != "sahip" else "x " + GIZLI, "i" if ad != "isci" else "x " + GIZLI,
                                "" if ad != "son_hata" else "x " + GIZLI))

    def test_yetkiler_uygulama_silemez_okuma_rolu_kisitli(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        with self.assertRaises(pg.YetkiHatasi):
            self.con.sorgu("DELETE FROM alig.is_kuyrugu WHERE id = $1", (a,))
        with self.assertRaises(pg.YetkiHatasi):
            self.con.sorgu("TRUNCATE alig.is_kuyrugu")
        with self.assertRaises(pg.YetkiHatasi):
            self.con.sorgu("DROP TABLE alig.is_kuyrugu")
        ro = self.baglan("alig_readonly")
        self.assertEqual(ro.sorgu("SELECT durum FROM alig.is_kuyrugu")[0][0], "bekliyor")
        with self.assertRaises(pg.YetkiHatasi):
            ro.sorgu("SELECT isci FROM alig.is_kuyrugu")
        with self.assertRaises(pg.YetkiHatasi):
            ro.sorgu("UPDATE alig.is_kuyrugu SET durum = 'tamam'")

    def test_istek_silinince_is_de_gider(self):
        f = self.firma()
        (a,) = self.is_ekle(f)
        self.sql("DELETE FROM alig.baglanti_istegi")
        self.assertEqual(self.sql("SELECT count(*) FROM alig.is_kuyrugu"), "0")
        self.assertEqual(a > 0, True)


@pg_yardimci.pg_testi(pg_sema_kume.PG_VAR, pg_sema_kume.PG_NEDEN)
class KabulTests(pg_sema_kume.SemaKumesi, unittest.TestCase):
    """The Mode B admission (Kabul) and its narrow dispatch in tarama/calistirici.py."""

    def setUp(self):
        self.sql("TRUNCATE alig.is_kuyrugu, alig.is_kuyrugu_sira, alig.baglanti_istegi, alig.firma CASCADE")
        self.con = self.baglan()
        self.n = 0

    def firma(self):
        self.n += 1
        return self.con.sorgu("INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES ($1, 'f', 'x@example.com', 'test', now(), now()) "
                              "RETURNING id", ("kabul%d" % self.n,))[0][0]

    def istek(self, firma_id):
        self.n += 1
        return self.con.sorgu(
            "INSERT INTO alig.baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, dil, olusturma_utc, bitis_utc) "
            "VALUES ($1, $2, 'k', 'db.example.com', '93.184.216.34', 5432, 'postgres', 'alig_hc', 'tr', now(), now() + interval '1 hour') RETURNING id",
            (hashlib.sha256(("kabul%d" % self.n).encode()).hexdigest(), firma_id))[0][0]

    def kabul(self, **kw):
        kw.setdefault("bos_bekleme_s", 0.05)
        kw.setdefault("kira_sn", 30)
        kb = k.Kabul(lambda: pg.Baglanti.baglan(**self.app_ayar()), "calistirici-t", **kw)
        kb.baslat()
        self.addCleanup(kb.durdur)
        return kb

    def test_sonuc_ve_hata_istek_parcacigina_doner_veritabani_yalniz_kimlik_gorur(self):
        kb = self.kabul()
        f = self.firma()
        i1, i2 = self.istek(f), self.istek(f)
        gizli = "p-" + GIZLI
        self.assertEqual(kb.calistir(f, i1, lambda: ("belge", gizli)), ("belge", gizli))
        with self.assertRaises(baglanti.BaglantiHatasi) as e:
            kb.calistir(f, i2, lambda: (_ for _ in ()).throw(baglanti.BaglantiHatasi("kanit")))
        self.assertEqual(e.exception.kod, "kanit")
        tum = self.sql("SELECT string_agg(row_to_json(t)::text, ' ') FROM alig.is_kuyrugu t")
        self.assertNotIn(gizli, tum)
        self.assertNotIn(GIZLI, tum)
        self.assertEqual(self.sql("SELECT string_agg(durum || ':' || son_hata, ',' ORDER BY id) FROM alig.is_kuyrugu"), "tamam:,olu:kanit")

    def test_es_zamanli_sinir_ve_firma_adaleti_gercek_is_parcaciklari(self):
        kb = self.kabul(es_zamanli=2, firma_basina=1)
        a, b = self.firma(), self.firma()
        calisan, tepe, kilit = Counter(), Counter(), threading.Lock()
        sira = []

        def is_(firma):
            def f():
                with kilit:
                    calisan[firma] += 1
                    tepe[firma] = max(tepe[firma], calisan[firma])
                    sira.append(firma)
                time.sleep(0.15)
                with kilit:
                    calisan[firma] -= 1
                return firma
            return f
        sonuc, hatalar = [], []

        def gonder(firma, istek):
            try:
                sonuc.append(kb.calistir(firma, istek, is_(firma)))
            except Exception as e:   # noqa: BLE001
                hatalar.append(e)
        ts = ([threading.Thread(target=gonder, args=(a, self.istek(a))) for _ in range(3)]
              + [threading.Thread(target=gonder, args=(b, self.istek(b)))])
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        self.assertEqual(hatalar, [])
        self.assertEqual(Counter(sonuc), {a: 3, b: 1})
        self.assertEqual(tepe, {a: 1, b: 1})   # never two scans of one company at once
        self.assertIn(b, sira[:2])   # the small company is not queued behind all of the big one's jobs

    def test_kuyruk_dolu_mesgul_ve_zaman_asimi_iptal(self):
        kb = self.kabul(es_zamanli=1, azami_bekleyen=1, sira_bekleme_sn=0.5)
        f, g, h = self.firma(), self.firma(), self.firma()
        tut, basladi = threading.Event(), threading.Event()

        def uzun():
            basladi.set()
            tut.wait(20)
        t = threading.Thread(target=lambda: kb.calistir(f, self.istek(f), uzun))
        t.start()
        self.addCleanup(t.join, 20)
        self.addCleanup(tut.set)
        self.assertTrue(basladi.wait(10))
        i = self.istek(g)
        with self.assertRaises(k.KuyrukZamanAsimi):   # the only worker is busy: not picked within 0.5 s
            kb.calistir(g, i, lambda: "x")
        self.assertEqual(self.sql("SELECT son_hata FROM alig.is_kuyrugu WHERE istek_id = %d" % i), "iptal")   # given up, dead-lettered
        self.assertNotIn(i, kb._posta)   # and its in-memory inputs are gone
        # fill the single waiting slot, then the next request is refused
        bekleyen = threading.Thread(target=lambda: self._yut(lambda: kb.calistir(g, self.istek(g), lambda: "y")))
        bekleyen.start()
        self.addCleanup(bekleyen.join, 20)
        for _ in range(100):
            if self.sql("SELECT count(*) FROM alig.is_kuyrugu WHERE durum = 'bekliyor'") == "1":
                break
            time.sleep(0.02)
        with self.assertRaises(k.KuyrukDolu):
            kb.calistir(h, self.istek(h), lambda: "z")

    @staticmethod
    def _yut(f):
        try:
            f()
        except k.KuyrukHatasi:
            pass

    def test_yeniden_baslatma_bellekteki_girdileri_olmayan_isleri_olu_yapar(self):
        f = self.firma()
        i = self.istek(f)
        k.ekle(self.con, f, i, sahip="calistirici-t", azami_deneme=1)   # left behind by a runner that died
        kb = self.kabul()   # start: sahip_temizle
        self.assertEqual(self.sql("SELECT durum || ':' || son_hata FROM alig.is_kuyrugu"), "olu:yeniden_basladi")
        self.assertEqual(kb.calistir(f, self.istek(f), lambda: 1), 1)

    def test_baska_sahibin_isi_alinmaz(self):
        kb = self.kabul()
        f = self.firma()
        k.ekle(self.con, f, self.istek(f), sahip="baska-calistirici", azami_deneme=1)
        k.ekle(self.con, f, self.istek(f))   # an unowned job is not for the runner either
        time.sleep(0.5)
        self.assertEqual(self.sql("SELECT string_agg(durum, ',') FROM alig.is_kuyrugu"), "bekliyor,bekliyor")
        self.assertEqual(kb.calistir(f, self.istek(f), lambda: 7), 7)

    # ---- the runner socket (narrow dispatch)
    def test_calistirici_soketi_kuyruk_uzerinden_calisir_parola_veritabanina_girmez(self):
        d = Path(tempfile.mkdtemp())
        soket = str(d / "c.sock")
        cagrilar = []

        def sahte(h, **arg):
            cagrilar.append(arg)
            return {"ok": True}
        kb = self.kabul()
        srv = calistirici.Sunucu(soket, tara=sahte, kuyruk=kb)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        f = self.firma()
        i = self.istek(f)
        # the validated-document step of the web side needs a real document; talk to the runner at the frame level instead
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(soket)
        s.sendall(calistirici.paketle({"ad": "db.example.com", "ip": "93.184.216.34", "port": 5432, "veritabani": "postgres", "kullanici": "alig_hc",
                                       "parola": GIZLI, "kanit": KANIT, "maskele": False, "firma_id": f, "istek_id": i}))
        yanit = calistirici.cerceve_al(s, 1 << 20)
        s.close()
        self.assertEqual(yanit, {"belge": {"ok": True}})
        self.assertEqual(cagrilar[0]["parola"], GIZLI)   # the scan got it, from memory
        self.assertEqual(self.sql("SELECT durum FROM alig.is_kuyrugu"), "tamam")
        for tablo in ("alig.is_kuyrugu", "alig.is_kuyrugu_sira", "alig.baglanti_istegi"):
            self.assertNotIn(GIZLI, self.sql("SELECT string_agg(row_to_json(t)::text, ' ') FROM %s t" % tablo))

    def test_calistirici_kuyruk_acikken_kimlik_alani_zorunlu(self):
        d = Path(tempfile.mkdtemp())
        soket = str(d / "c.sock")
        srv = calistirici.Sunucu(soket, tara=lambda h, **a: {"ok": True}, kuyruk=self.kabul())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        for ek in ({}, {"firma_id": 1}, {"firma_id": 0, "istek_id": 1}, {"firma_id": "1", "istek_id": 1}, {"firma_id": True, "istek_id": 1}):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect(soket)
            istek = {"ad": "db.example.com", "ip": "93.184.216.34", "port": 5432, "veritabani": "postgres", "kullanici": "alig_hc",
                     "parola": GIZLI, "kanit": KANIT, "maskele": False}
            istek.update(ek)
            s.sendall(calistirici.paketle(istek))
            self.assertEqual(calistirici.cerceve_al(s, 1 << 20), {"hata": "bicim"}, ek)
            s.close()


if __name__ == "__main__":
    unittest.main()
