"""ALIG-CI-001: tests/pg_yardimci.py (ortak gecici PostgreSQL kumesi) ve ci/pg_adimi.py (CI ozeti).
Kume gerektiren testler PostgreSQL yoksa SKIP olur; digerleri her yerde kosar."""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ci"))

import pg_adimi  # noqa: E402
import pg_yardimci  # noqa: E402

BULGU = pg_yardimci.pg_bul()


class BulmaTests(unittest.TestCase):
    def test_olmayan_dizin_acik_yok_nedeni_verir(self):
        b = pg_yardimci.pg_bul(adaylar=["/yok/boyle/bir/dizin"], ortam={})
        self.assertFalse(b.var)
        self.assertIsNone(b.dizin)
        self.assertIn("/yok/boyle/bir/dizin", b.neden)
        self.assertIn("initdb", b.neden)

    def test_eksik_ikili_nedene_yazilir(self):
        d = tempfile.mkdtemp()
        try:
            Path(d, "initdb").write_text("#!/bin/sh\n")
            b = pg_yardimci.pg_bul(adaylar=[d], ortam={})
            self.assertFalse(b.var)
            self.assertIn("pg_ctl", b.neden)
        finally:
            shutil.rmtree(d)

    def test_ortam_degiskeni_adaydan_once_denenir(self):
        b = pg_yardimci.pg_bul(adaylar=[], ortam={"ALIG_TEST_PG_BIN": "/yok/ortam/dizini"})
        self.assertFalse(b.var)
        self.assertIn("/yok/ortam/dizini", b.neden)

    def test_kume_olmadan_baslatma_acik_hata(self):
        with self.assertRaises(pg_yardimci.PgYok) as c:
            pg_yardimci.GeciciKume(bulgu=pg_yardimci.pg_bul(adaylar=["/yok"], ortam={})).baslat()
        self.assertIn("/yok", str(c.exception))

    def test_dis_hedef_ortam_degiskeninden_gelir(self):
        env = {"ALIG_TEST_PG_HOST": "/soket", "ALIG_TEST_PG_PORT": "6543", "ALIG_TEST_PG_USER": "u1"}
        h = pg_yardimci.dis_hedef(env)
        self.assertEqual((h.host, h.port, h.kullanici), ("/soket", "6543", "u1"))
        self.assertIsNone(pg_yardimci.dis_hedef({}))
        h2 = pg_yardimci.dis_hedef({"ALIG_TEST_PG_HOST": "x"})
        self.assertEqual((h2.port, h2.kullanici), ("5432", "alig_hc"))


@pg_yardimci.pg_testi(BULGU.var, BULGU.neden)
class KumeTests(unittest.TestCase):
    def test_baslat_rol_veritabani_ve_scram(self):
        k = pg_yardimci.GeciciKume()
        k.baslat()
        dizin = k.dizin
        try:
            self.assertTrue(Path(dizin).is_dir())
            k.rol_olustur("deneme_app", parola="Deneme-Parola-12345")
            k.veritabani_olustur("denemedb", sahip="deneme_app")
            k.kimlik_dogrulama("scram-sha-256")
            self.assertEqual(k.sql("SELECT current_database()", db="denemedb", kullanici="deneme_app",
                                   parola="Deneme-Parola-12345"), "denemedb")
            with self.assertRaises(subprocess.CalledProcessError):
                k.sql("SELECT 1", db="denemedb", kullanici="deneme_app", parola="yanlis-parola-1")
            self.assertRegex(k.surum, r"^\d+(\.\d+)?")
        finally:
            k.durdur()
        self.assertFalse(os.path.exists(dizin))
        k.durdur()   # ikinci durdurma zararsiz

    def test_sunucu_durdurma_sonrasi_dizin_kalir_silme_ayridir(self):
        k = pg_yardimci.GeciciKume()
        k.baslat()
        try:
            k.sunucuyu_durdur()
            self.assertTrue(Path(k.dizin).is_dir())
        finally:
            k.durdur()
        self.assertFalse(os.path.exists(k.dizin))

    def test_surec_cokerse_artik_dizin_kalmaz(self):
        kod = (
            "import sys, time\n"
            "sys.path.insert(0, %r)\n"
            "import pg_yardimci\n"
            "k = pg_yardimci.GeciciKume(); k.baslat()\n"
            "print(k.dizin, flush=True)\n"
            "time.sleep(300)\n" % str(ROOT / "tests")
        )
        p = subprocess.Popen([sys.executable, "-c", kod], stdout=subprocess.PIPE, text=True)
        try:
            dizin = p.stdout.readline().strip()
            self.assertTrue(Path(dizin).is_dir(), dizin)
            p.send_signal(signal.SIGKILL)   # temizlik kodu calisamaz: yalniz bekci kurtarir
            p.wait(10)
            sinir = time.time() + 30
            while Path(dizin).exists() and time.time() < sinir:
                time.sleep(0.3)
            self.assertFalse(Path(dizin).exists(), "cokmus sureclin kumesi silinmedi")
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()


class OzetTests(unittest.TestCase):
    def test_hepsi_gecti(self):
        d, satir, ok = pg_adimi.ozet({"PASS": 24, "FAIL": 0, "SKIP": 0}, "16.4", release=False, pg_var=True)
        self.assertEqual(d, "tamam")
        self.assertTrue(ok)
        self.assertIn("PASS 24", satir)
        self.assertIn("FAIL 0", satir)
        self.assertIn("SKIP 0", satir)
        self.assertIn("PostgreSQL 16.4", satir)

    def test_pg_yoksa_atlandi_ve_tamam_denmez(self):
        d, satir, ok = pg_adimi.ozet({"PASS": 0, "FAIL": 0, "SKIP": 30}, None, release=False, pg_var=False)
        self.assertEqual(d, "atlandi")
        self.assertTrue(ok)    # CI dusmez
        self.assertIn("atlandı (PostgreSQL yok)", satir)
        self.assertNotIn("tamam", satir)

    def test_release_kipinde_pg_yoksa_hata(self):
        d, satir, ok = pg_adimi.ozet({"PASS": 0, "FAIL": 0, "SKIP": 30}, None, release=True, pg_var=False)
        self.assertEqual(d, "HATA")
        self.assertFalse(ok)
        self.assertIn("atlandı (PostgreSQL yok)", satir)

    def test_kismi_atlama_tamam_sayilmaz(self):
        d, satir, ok = pg_adimi.ozet({"PASS": 20, "FAIL": 0, "SKIP": 4}, "16.4", release=False, pg_var=True)
        self.assertEqual(d, "atlandi")
        self.assertTrue(ok)
        self.assertIn("SKIP 4", satir)
        self.assertIn("kısmen atlandı", satir)
        d, _, ok = pg_adimi.ozet({"PASS": 20, "FAIL": 0, "SKIP": 4}, "16.4", release=True, pg_var=True)
        self.assertEqual((d, ok), ("HATA", False))

    def test_fail_her_kipte_hata(self):
        for rel in (False, True):
            d, satir, ok = pg_adimi.ozet({"PASS": 3, "FAIL": 1, "SKIP": 0}, "16.4", release=rel, pg_var=True)
            self.assertEqual((d, ok), ("HATA", False))
            self.assertIn("FAIL 1", satir)

    def test_hic_pg_testi_bulunamazsa_tamam_denmez(self):
        d, _, ok = pg_adimi.ozet({"PASS": 0, "FAIL": 0, "SKIP": 0}, "16.4", release=False, pg_var=True)
        self.assertNotEqual(d, "tamam")

    def test_sayac_ve_etiketli_siniflar(self):
        sayilar, _ = pg_adimi.calistir_sayilari(ROOT, dahil=["test_pg_yardimci"])
        self.assertEqual(sorted(sayilar), ["FAIL", "PASS", "SKIP"])
        self.assertEqual(sayilar["FAIL"], 0)
        self.assertGreaterEqual(sayilar["PASS"] + sayilar["SKIP"], 3)   # KumeTests etiketli


class AltiTestinDisHedefi(unittest.TestCase):
    def test_alti_test_etiketli(self):
        """ALIG_TEST_PG_HOST isteyen 6 test yardimciyla da kosabilir: etiketli siniflarda sayilirlar."""
        import test_tarama
        import test_tarama_guvenlik
        self.assertTrue(getattr(test_tarama.GercekPgTests, "PG_TESTI", False))
        self.assertTrue(getattr(test_tarama_guvenlik.GercekPgOturumTests, "PG_TESTI", False))
        n = sum(1 for _ in unittest.TestLoader().loadTestsFromTestCase(test_tarama.GercekPgTests)) + \
            sum(1 for _ in unittest.TestLoader().loadTestsFromTestCase(test_tarama_guvenlik.GercekPgOturumTests))
        self.assertEqual(n, 6)


if __name__ == "__main__":
    unittest.main()
