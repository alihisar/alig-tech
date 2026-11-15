"""ALIG-DB-002: ctypes + libpq surucu prototipi (degerlendirme). Uygulamaya baglanmaz.

PG16 gecici kumesi setUpClass'ta kurulur, tearDownClass'ta silinir. PG ya da libpq yoksa testler atlanir.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ortak import pg  # noqa: E402

PG_BIN = Path("/usr/lib/postgresql/16/bin")
PG_VAR = (PG_BIN / "initdb").exists() and (PG_BIN / "pg_ctl").exists()
try:
    LIBPQ_VAR = pg.kutuphane_yukle() is not None
except pg.KutuphaneHatasi:
    LIBPQ_VAR = False

PAROLA = "Uygulama-Parola-Ornek-1"
YANLIS = "YanlisParola-12345"


def _komut(args):
    """Root ise postgres kullanicisiyla calistirir (initdb root'ta calismaz)."""
    if os.geteuid() == 0:
        args = ["runuser", "-u", "postgres", "--"] + list(args)
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=40)


def _bos_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class KumeKarisimi:
    """Test sinifi icin gecici PG16 kumesi: uygulama rolu superuser degil, scram-sha-256 ile baglanir."""

    @classmethod
    def setUpClass(cls):
        if not (PG_VAR and LIBPQ_VAR):
            raise unittest.SkipTest("PostgreSQL 16 ya da libpq yok")
        # postgres kullanicisinin gecebilecegi kisa bir dizin (Unix soketi yolu icin de kisa olmali)
        cls.dizin = tempfile.mkdtemp(prefix="alig-pg-")
        cls.sunucu_calisiyor = False
        try:
            os.chmod(cls.dizin, 0o755)
            cls.veri = os.path.join(cls.dizin, "veri")
            if os.geteuid() == 0:
                import pwd
                pw = pwd.getpwnam("postgres")
                os.chown(cls.dizin, pw.pw_uid, pw.pw_gid)
            cls.port = _bos_port()
            _komut([str(PG_BIN / "initdb"), "-D", cls.veri, "-A", "trust", "-U", "postgres", "--no-locale", "-E", "UTF8"])
            secenek = f"-c listen_addresses='' -c unix_socket_directories={cls.dizin} -p {cls.port} -c fsync=off"
            _komut([str(PG_BIN / "pg_ctl"), "-D", cls.veri, "-o", secenek, "-w", "-t", "30",
                    "-l", os.path.join(cls.dizin, "pg.log"), "start"])
            cls.sunucu_calisiyor = True
            psql = [str(PG_BIN / "psql"), "-h", cls.dizin, "-p", str(cls.port), "-U", "postgres", "-d", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-q", "-c"]
            _komut(psql + [f"CREATE ROLE alig_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{PAROLA}'"])
            _komut(psql + ["CREATE DATABASE aligtest OWNER alig_app"])
            hba = Path(cls.veri) / "pg_hba.conf"
            hba.write_text("local all all scram-sha-256\n", encoding="utf-8")
            _komut([str(PG_BIN / "pg_ctl"), "-D", cls.veri, "reload"])
        except Exception:
            cls._temizle()
            raise

    @classmethod
    def _temizle(cls):
        if getattr(cls, "sunucu_calisiyor", False):
            try:
                _komut([str(PG_BIN / "pg_ctl"), "-D", cls.veri, "-m", "immediate", "-w", "stop"])
            except Exception:
                pass
            cls.sunucu_calisiyor = False
        shutil.rmtree(cls.dizin, ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        cls._temizle()

    def baglan(self, **kw):
        ayar = dict(host=self.dizin, port=self.port, dbname="aligtest", user="alig_app", password=PAROLA)
        ayar.update(kw)
        b = pg.Baglanti.baglan(**ayar)
        self.addCleanup(b.kapat)
        return b


class SaltUnitTests(unittest.TestCase):
    """Sunucu gerektirmeyen birim testler."""

    def test_baglanti_dizgisi_kacis(self):
        s = pg._baglanti_dizgisi({"host": "/x y", "password": "a'b\\c d"})
        self.assertIn("password='a\\'b\\\\c d'", s)
        self.assertIn("host='/x y'", s)

    def test_baglanti_dizgisi_nul_reddi(self):
        with self.assertRaises(ValueError):
            pg._baglanti_dizgisi({"password": "a\x00b"})

    def test_sir_maskeleme(self):
        self.assertNotIn("gizli123", pg._maskele("hata gizli123 burada", ["gizli123"]))
        self.assertEqual(pg._maskele("abc", [None, ""]), "abc")

    @unittest.skipUnless(LIBPQ_VAR, "libpq yok")
    def test_libpq_bulunamazsa_acik_hata(self):
        with self.assertRaises(pg.KutuphaneHatasi) as c:
            pg.kutuphane_yukle(adaylar=["libpq-yok.so.99"], onbellek=False)
        self.assertIn("libpq", str(c.exception))

    def test_parametre_donusumu(self):
        self.assertEqual(pg._parametre_metni(True), b"true")
        self.assertEqual(pg._parametre_metni(12), b"12")
        self.assertIsNone(pg._parametre_metni(None))
        self.assertEqual(pg._parametre_metni("ğ"), "ğ".encode("utf-8"))
        with self.assertRaises(ValueError):
            pg._parametre_metni(datetime(2026, 1, 1))  # saat dilimsiz zaman reddedilir
        with self.assertRaises(TypeError):
            pg._parametre_metni(object())
        with self.assertRaises(ValueError):
            pg._parametre_metni("a\x00b")

    @unittest.skipUnless(LIBPQ_VAR, "libpq yok")
    def test_baglanti_hatasi_parola_sizdirmaz(self):
        # var olmayan soket dizini: hata metni parolayi icermemeli
        with self.assertRaises(pg.BaglantiHatasi) as c:
            pg.Baglanti.baglan(host="/yok-boyle-dizin", port=1, dbname="x", user="u", password=YANLIS,
                               baglanti_zaman_asimi=2)
        self.assertNotIn(YANLIS, str(c.exception))


@unittest.skipUnless(PG_VAR and LIBPQ_VAR, "PostgreSQL 16 ya da libpq yok")
class PgPrototipTests(KumeKarisimi, unittest.TestCase):

    def setUp(self):
        b = self.baglan()
        b.sorgu("DROP TABLE IF EXISTS kayit")
        b.sorgu("CREATE TABLE kayit (id serial PRIMARY KEY, ad text UNIQUE, deger integer, zaman timestamptz)")

    def test_baglanti_ve_rol(self):
        b = self.baglan()
        self.assertEqual(b.sorgu("SELECT 1 + $1::int", [41]), [(42,)])
        self.assertEqual(b.sorgu("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"), [(False,)])
        self.assertEqual(b.sorgu("SELECT current_user"), [("alig_app",)])
        self.assertTrue(pg.thread_guvenli())

    def test_oturum_zaman_asimlari(self):
        b = self.baglan(statement_timeout_ms=1234, lock_timeout_ms=2345, bosta_islem_zaman_asimi_ms=3456)
        self.assertEqual(b.sorgu("SHOW statement_timeout"), [("1234ms",)])
        self.assertEqual(b.sorgu("SHOW lock_timeout"), [("2345ms",)])
        self.assertEqual(b.sorgu("SHOW idle_in_transaction_session_timeout"), [("3456ms",)])

    def test_parametreli_sorgu_enjeksiyon_deger_kalir(self):
        b = self.baglan()
        kotu = "x'); DROP TABLE kayit; --"
        b.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, $2)", [kotu, 7])
        self.assertEqual(b.sorgu("SELECT ad, deger FROM kayit WHERE ad = $1", [kotu]), [(kotu, 7)])
        self.assertEqual(b.sorgu("SELECT count(*) FROM kayit"), [(1,)])  # tablo duruyor

    def test_null_ve_turkce_gidis_donus(self):
        b = self.baglan()
        metin = "ığüşöçİĞÜŞÖÇ ışık ğ"
        b.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, $2)", [metin, None])
        b.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, $2)", ["", 0])
        self.assertEqual(b.sorgu("SELECT ad, deger FROM kayit ORDER BY id"), [(metin, None), ("", 0)])
        self.assertEqual(b.sorgu("SELECT $1::text", [None]), [(None,)])

    def test_timestamptz_gidis_donus(self):
        b = self.baglan()
        t = datetime(2026, 11, 15, 10, 30, 5, 123456, tzinfo=timezone(timedelta(hours=3)))
        b.sorgu("INSERT INTO kayit (ad, zaman) VALUES ($1, $2)", ["z", t])
        (donen,), = b.sorgu("SELECT zaman FROM kayit WHERE ad = $1", ["z"])
        self.assertEqual(donen, t)
        self.assertIsNotNone(donen.tzinfo)
        (simdi,), = b.sorgu("SELECT now()")
        self.assertIsNotNone(simdi.tzinfo)

    def test_islem_commit_ve_istisnada_geri_alma(self):
        b = self.baglan()
        with b.islem():
            b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["tamam"])
        with self.assertRaises(RuntimeError):
            with b.islem():
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["yazilmamali"])
                raise RuntimeError("uygulama hatasi")
        self.assertEqual(b.sorgu("SELECT ad FROM kayit ORDER BY id"), [("tamam",)])
        self.assertFalse(b.islemde)

    def test_islem_icinde_sql_hatasi_geri_alir(self):
        b = self.baglan()
        b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["a"])
        with self.assertRaises(pg.BenzersizlikHatasi):
            with b.islem():
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["b"])
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["a"])
        self.assertEqual(b.sorgu("SELECT ad FROM kayit ORDER BY ad"), [("a",)])

    def test_ic_ice_islem_reddedilir(self):
        b = self.baglan()
        with b.islem():
            with self.assertRaises(pg.PgHata):
                with b.islem():
                    pass

    def test_benzersizlik_hatasi_sinifi(self):
        b = self.baglan()
        b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["tek"])
        with self.assertRaises(pg.BenzersizlikHatasi) as c:
            b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["tek"])
        self.assertEqual(c.exception.sqlstate, "23505")
        self.assertIsInstance(c.exception, pg.ButunlukHatasi)
        self.assertIsInstance(c.exception, pg.SorguHatasi)
        # hata sonrasi baglanti kullanilabilir (islem disinda)
        self.assertEqual(b.sorgu("SELECT 1"), [(1,)])

    def test_diger_sqlstate_sinifi(self):
        b = self.baglan()
        with self.assertRaises(pg.SorguHatasi) as c:
            b.sorgu("SELECT * FROM yok_boyle_tablo")
        self.assertEqual(c.exception.sqlstate, "42P01")
        self.assertNotIsInstance(c.exception, pg.BenzersizlikHatasi)

    def test_statement_timeout(self):
        b = self.baglan(statement_timeout_ms=500)
        t0 = time.monotonic()
        with self.assertRaises(pg.SorguIptalHatasi) as c:
            b.sorgu("SELECT pg_sleep(10)")
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(c.exception.sqlstate, "57014")
        self.assertEqual(b.sorgu("SELECT 1"), [(1,)])

    def test_pqcancel_ile_iptal(self):
        b = self.baglan()
        izleyici = self.baglan()
        sonuc = {}

        def calis():
            try:
                b.sorgu("SELECT pg_sleep(20) /* iptal-deneme */")
            except Exception as e:  # noqa: BLE001
                sonuc["hata"] = e

        t = threading.Thread(target=calis)
        t0 = time.monotonic()
        t.start()
        for _ in range(100):  # sorgu sunucuda aktif olana dek bekle
            if izleyici.sorgu("SELECT count(*) FROM pg_stat_activity WHERE query LIKE $1 AND state = 'active' "
                              "AND pid <> pg_backend_pid()", ["%iptal-deneme%"])[0][0]:
                break
            time.sleep(0.05)
        b.iptal()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertLess(time.monotonic() - t0, 8)
        self.assertIsInstance(sonuc.get("hata"), pg.SorguIptalHatasi)
        self.assertEqual(b.sorgu("SELECT 2"), [(2,)])

    def test_yanlis_parolada_metinde_parola_yok(self):
        with self.assertRaises(pg.BaglantiHatasi) as c:
            pg.Baglanti.baglan(host=self.dizin, port=self.port, dbname="aligtest", user="alig_app",
                               password=YANLIS, baglanti_zaman_asimi=5)
        metin = str(c.exception) + repr(c.exception)
        self.assertNotIn(YANLIS, metin)
        self.assertNotIn(PAROLA, metin)

    def test_repr_parola_icermez(self):
        b = self.baglan()
        self.assertNotIn(PAROLA, repr(b) + str(b))

    def test_kapali_baglanti_kullanimi_reddedilir(self):
        b = self.baglan()
        b.kapat()
        b.kapat()  # ikinci kapatma zararsiz
        with self.assertRaises(pg.BaglantiHatasi):
            b.sorgu("SELECT 1")

    def test_bellek_sizintisi_kaba(self):
        b = self.baglan()
        sayfa = os.sysconf("SC_PAGE_SIZE")

        def rss():
            with open("/proc/self/statm") as f:
                return int(f.read().split()[1]) * sayfa

        yuk = "ğ" * 2000
        for _ in range(100):  # isinma
            b.sorgu("SELECT $1::text, $2::int", [yuk, 1])
        once = rss()
        for i in range(1000):
            b.sorgu("SELECT $1::text, $2::int", [yuk, i])
            if i % 10 == 0:
                with self.assertRaises(pg.SorguHatasi):  # hata yolundaki PQclear de sizdirmamali
                    b.sorgu("SELECT * FROM yok_boyle_tablo")
        artis = rss() - once
        self.assertLess(artis, 8 * 1024 * 1024, f"RSS artisi {artis} bayt")

    def test_iki_is_parcacigi_ayri_baglantilarla_paralel(self):
        sonuc, hatalar = [], []

        def is_(ad):
            try:
                b = pg.Baglanti.baglan(host=self.dizin, port=self.port, dbname="aligtest", user="alig_app",
                                       password=PAROLA)
                try:
                    b.sorgu("SELECT pg_sleep(0.6)")
                    b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", [ad])
                    sonuc.append(ad)
                finally:
                    b.kapat()
            except Exception as e:  # noqa: BLE001
                hatalar.append(e)

        t0 = time.monotonic()
        ts = [threading.Thread(target=is_, args=(a,)) for a in ("i1", "i2")]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        gecen = time.monotonic() - t0
        self.assertEqual(hatalar, [])
        self.assertEqual(sorted(sonuc), ["i1", "i2"])
        self.assertLess(gecen, 1.15)  # seri olsaydi >= 1.2 sn
        self.assertEqual(self.baglan().sorgu("SELECT count(*) FROM kayit"), [(2,)])

    def test_baglanti_is_parcacigi_arasinda_paylasilamaz(self):
        b = self.baglan()
        sonuc = {}

        def uzun():
            try:
                b.sorgu("SELECT pg_sleep(1.5)")
            except Exception as e:  # noqa: BLE001
                sonuc["hata"] = e

        t = threading.Thread(target=uzun)
        t.start()
        time.sleep(0.4)
        with self.assertRaises(pg.EszamanliKullanimHatasi):
            b.sorgu("SELECT 1")
        t.join(10)
        self.assertNotIn("hata", sonuc)


@unittest.skipUnless(PG_VAR and LIBPQ_VAR, "PostgreSQL 16 ya da libpq yok")
class BaglantiKesintisiTests(KumeKarisimi, unittest.TestCase):

    def _sunucuyu_durdur(self):
        _komut([str(PG_BIN / "pg_ctl"), "-D", self.veri, "-m", "immediate", "-w", "stop"])
        type(self).sunucu_calisiyor = False

    def test_sunucu_durdurulunca_guvenli_hata(self):
        b = self.baglan()
        b.sorgu("CREATE TABLE IF NOT EXISTS k (x int)")
        self.assertEqual(b.sorgu("SELECT 1"), [(1,)])
        with self.assertRaises(pg.BaglantiHatasi):  # islem ortasinda kesinti: basari ilan edilmez
            with b.islem():
                b.sorgu("INSERT INTO k VALUES ($1)", [1])
                self._sunucuyu_durdur()
                b.sorgu("INSERT INTO k VALUES ($1)", [2])
        self.assertFalse(b.islemde)
        for _ in range(2):  # tekrar denemeyiz; her seferinde ayni guvenli hata
            with self.assertRaises(pg.BaglantiHatasi) as c:
                b.sorgu("INSERT INTO k VALUES ($1)", [1])
            self.assertNotIn(PAROLA, str(c.exception))
        self.assertTrue(b.kopuk)
        with self.assertRaises(pg.BaglantiHatasi):
            with b.islem():
                pass
        with self.assertRaises(pg.BaglantiHatasi):
            pg.Baglanti.baglan(host=self.dizin, port=self.port, dbname="aligtest", user="alig_app",
                               password=PAROLA, baglanti_zaman_asimi=2)
