"""ALIG-DB-003d: yonetim/depo_pg.py (admin store on PostgreSQL) against a temporary PostgreSQL 16 cluster.

Mirrors the store-level tests of tests/test_yonetim.py (login, lockout, TOTP replay, sessions, new-IP record, user operations,
request status, transactions, cleanup incl. denetle=True, panel counts) and adds the audit-chain tests: the same canonical format and the shared
verifier across SQLite and PostgreSQL, the tail lock under real concurrent connections, and the refusal of UPDATE/DELETE/TRUNCATE for the
application role. The whole module is SKIPPED (not passed) when no PostgreSQL 16 is available.
The server (yonetim/server.py) is not wired to this store yet; the HTTP-level tests of test_yonetim.py still run on SQLite only."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_yardimci  # noqa: E402
from ortak import pg  # noqa: E402
from tarama import depo as tdepo  # noqa: E402
from yonetim import depo, depo_pg, guvenlik  # noqa: E402

BULGU = pg_yardimci.pg_bul()
PAROLA = "cok-gizli-parola-123"
ANAHTAR = "k" * 40
_kume = {}
_sayac = [0]


def setUpModule():
    if not BULGU.var:
        return
    k = pg_yardimci.GeciciKume()
    k.baslat()
    _kume["k"] = k


def tearDownModule():
    k = _kume.pop("k", None)
    if k:
        k.durdur()


def yeni_veritabani():
    """A fresh database with every db/sema file applied by the superuser of the temporary cluster. Returns its name."""
    k = _kume["k"]
    _sayac[0] += 1
    db = "y%d" % _sayac[0]
    k.veritabani_olustur(db)
    r = subprocess.run([sys.executable, str(ROOT / "db" / "uygula.py")], capture_output=True, text=True,
                       env=k.ortam(db, "postgres"), timeout=120)
    assert r.returncode == 0, r.stderr
    return db


def baglan(db, kullanici="alig_app"):
    k = _kume["k"]
    return pg.Baglanti.baglan(host=k.soket, port=int(k.port), dbname=db, user=kullanici)


TEMIZLE = ("TRUNCATE alig.kullanici, alig.giris_denemesi, alig.talep_durum, alig.yonetim_denetim, alig.denetim, alig.firma, "
           "alig.contact, alig.posta RESTART IDENTITY CASCADE")


@pg_yardimci.pg_testi(BULGU.var, BULGU.neden)
class PgTaban(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = yeni_veritabani()

    def setUp(self):
        _kume["k"].sql(TEMIZLE, db=self.db)
        self.con = self.baglanti()

    def baglanti(self, kullanici="alig_app"):
        c = baglan(self.db, kullanici)
        self.addCleanup(c.kapat)
        return c

    def sql(self, sorgu):
        """As the superuser of the test cluster: for setup and tampering only."""
        return _kume["k"].sql(sorgu, db=self.db)

    def kullanici(self, ad="ali"):
        return depo_pg.kullanici_ekle(self.con, ad, PAROLA)

    def son(self, tablo="yonetim_denetim"):
        r = self.con.sorgu("SELECT olay, alanlar FROM alig.%s ORDER BY seq DESC LIMIT 1" % tablo)
        return r[0]

    def satirlar(self, tablo="yonetim_denetim"):
        return self.con.sorgu("SELECT seq, aktor, olay, onceki, ozet, mod, alanlar FROM alig.%s ORDER BY seq" % tablo)

    def reddedilir(self, con, sorgu, durum="42501"):
        with self.assertRaises(pg.SorguHatasi, msg=sorgu) as m:
            con.sorgu(sorgu)
        self.assertEqual(m.exception.sqlstate, durum)


# ------------------------------------------------------------------------------------------------ audit chain
class ZincirTests(PgTaban):
    GIRDILER = [
        ("ali", "giris yapildi", {"kullanici": "ali", "sonuc": "basarili", "ip_ozeti": "ab12", "yeni_ip": 0}),
        ("sistem", "basarisiz giris: \u015f\u00fcl\u00fc", {"kullanici": "\u015f\u00fcl\u00fc", "sonuc": "basarisiz", "neden": "hatali"}),
        ("cli", "kullanici eklendi: veli", None),
        ("ali", "uzun alan", {"firma": "x" * 300, "yeni_ip": True, "talep": 7}),
        ("ali", "bo\u015f | ay\u0131r\u0131c\u0131 ve 'tirnak'", {"hedef": "a|b"}),
    ]

    def sqlite_zinciri(self, girdiler):
        s = sqlite3.connect(str(Path(tempfile.mkdtemp()) / "t.sqlite"))
        tdepo.goc_uygula(s, tdepo.GOCLER)
        for a, o, al in girdiler:
            tdepo.denetim_ekle(s, a, o, al)
        self.addCleanup(s.close)
        return s

    def pg_zinciri(self, girdiler, zincir_ad="yonetim"):
        for a, o, al in girdiler:
            depo_pg.denetim_ekle(self.con, a, o, al, zincir_ad=zincir_ad)

    def sqlite_satirlari(self, s):
        return s.execute("SELECT seq, aktor, olay, onceki, ozet, mod, alanlar FROM denetim ORDER BY seq").fetchall()

    def test_ayni_girdiler_ayni_satirlari_uretir_anahtarsiz(self):
        s = self.sqlite_zinciri(self.GIRDILER)
        self.pg_zinciri(self.GIRDILER)
        self.assertEqual([tuple(r) for r in self.satirlar()], self.sqlite_satirlari(s))
        self.assertEqual(len(self.satirlar()), len(self.GIRDILER))

    def test_ayni_girdiler_ayni_satirlari_uretir_anahtarli(self):
        with mock.patch.dict(os.environ, {tdepo.ANAHTAR_ORTAM: ANAHTAR}):
            s = self.sqlite_zinciri(self.GIRDILER)
            self.pg_zinciri(self.GIRDILER)
            pgs = [tuple(r) for r in self.satirlar()]
            self.assertEqual(pgs, self.sqlite_satirlari(s))
            self.assertTrue(all(r[5] & 1 for r in pgs))   # HMAC bit
            self.assertIsNone(depo_pg.denetim_dogrula(self.con))
            self.assertEqual(depo_pg.denetim_durum(self.con, ANAHTAR.encode())["anahtarli"], True)

    def test_tarama_zinciri_de_ayni_bicimde_yazilir(self):
        s = self.sqlite_zinciri(self.GIRDILER)
        self.pg_zinciri(self.GIRDILER, "tarama")
        self.assertEqual([tuple(r) for r in self.satirlar("denetim")], self.sqlite_satirlari(s))
        self.assertIsNone(depo_pg.denetim_dogrula(self.con, zincir_ad="tarama"))

    def test_sqlite_zinciri_pg_dogrulayicisinda_dogrulanir(self):
        for anahtar in (None, ANAHTAR):
            with self.subTest(anahtar=anahtar), mock.patch.dict(os.environ, {tdepo.ANAHTAR_ORTAM: anahtar} if anahtar else {}, clear=False):
                if not anahtar:
                    os.environ.pop(tdepo.ANAHTAR_ORTAM, None)
                self.sql(TEMIZLE)
                s = self.sqlite_zinciri(self.GIRDILER)
                for r in self.sqlite_satirlari(s):   # the migration path: the rows are inserted as they are
                    self.con.sorgu("INSERT INTO alig.yonetim_denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) "
                                   "VALUES($1, now(), $2, $3, $4, $5, $6, $7)", list(r))
                self.assertIsNone(depo_pg.denetim_dogrula(self.con))
                self.assertEqual(depo_pg.denetim_durum(self.con)["kayit"], len(self.GIRDILER))
                # and the chain keeps growing from the imported tail on either side
                depo_pg.denetim_ekle(self.con, "ali", "yeni")
                self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_pg_zinciri_sqlite_dogrulayicisinda_dogrulanir(self):
        for anahtar in (None, ANAHTAR):
            with self.subTest(anahtar=anahtar):
                with mock.patch.dict(os.environ, {tdepo.ANAHTAR_ORTAM: anahtar} if anahtar else {}):
                    if not anahtar:
                        os.environ.pop(tdepo.ANAHTAR_ORTAM, None)
                    self.sql(TEMIZLE)
                    self.pg_zinciri(self.GIRDILER)
                    s = sqlite3.connect(str(Path(tempfile.mkdtemp()) / "t.sqlite"))
                    self.addCleanup(s.close)
                    tdepo.goc_uygula(s, tdepo.GOCLER)
                    s.executemany("INSERT INTO denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) VALUES(?,'2026-01-01T00:00:00Z',?,?,?,?,?,?)",
                                  [tuple(r) for r in self.satirlar()])
                    s.commit()
                    self.assertIsNone(tdepo.denetim_dogrula(s, ANAHTAR.encode() if anahtar else None))
                    tdepo.denetim_ekle(s, "x", "sqlite yazdi")   # SQLite appends to the PostgreSQL-written chain
                    self.assertIsNone(tdepo.denetim_dogrula(s, ANAHTAR.encode() if anahtar else None))

    def test_ayni_sonuc_dict_iki_arka_uc(self):
        s = self.sqlite_zinciri(self.GIRDILER)
        self.pg_zinciri(self.GIRDILER)
        self.assertEqual(depo_pg.denetim_durum(self.con), tdepo.denetim_durum(s))

    def test_degistirilen_kayit_bozuk_olarak_bulunur(self):
        self.pg_zinciri(self.GIRDILER)
        self.sql("UPDATE alig.yonetim_denetim SET olay='degistirildi' WHERE seq=3")
        self.assertEqual(depo_pg.denetim_dogrula(self.con), 3)

    def test_silinen_kayit_bozuk_olarak_bulunur(self):
        self.pg_zinciri(self.GIRDILER)
        self.sql("DELETE FROM alig.yonetim_denetim WHERE seq=2")
        self.assertEqual(depo_pg.denetim_dogrula(self.con), 3)

    def test_disa_aktarilan_zincir_basi_kesilmeyi_yakalar(self):
        self.pg_zinciri(self.GIRDILER)
        bas = depo_pg.zincir_basi(self.con)
        self.assertEqual(bas["seq"], len(self.GIRDILER))
        self.sql("DELETE FROM alig.yonetim_denetim WHERE seq=%d" % bas["seq"])
        self.assertEqual(depo_pg.denetim_durum(self.con, None, bas)["bozuk"], bas["seq"])

    def test_yanlis_anahtar_ve_anahtarsiz_dogrulama(self):
        with mock.patch.dict(os.environ, {tdepo.ANAHTAR_ORTAM: ANAHTAR}):
            self.pg_zinciri(self.GIRDILER)
        self.assertEqual(depo_pg.denetim_dogrula(self.con, b"y" * 40), 1)
        d = depo_pg.denetim_durum(self.con, None)
        self.assertEqual((d["bozuk"], d["dogrulanamayan"]), (None, len(self.GIRDILER)))

    def test_uygulama_rolu_denetim_tablolarini_degistiremez(self):
        self.pg_zinciri(self.GIRDILER[:2])
        self.pg_zinciri(self.GIRDILER[:2], "tarama")
        for tablo in ("yonetim_denetim", "denetim"):
            self.reddedilir(self.con, "UPDATE alig.%s SET olay='x'" % tablo)
            self.reddedilir(self.con, "UPDATE alig.%s SET olay='x' WHERE false" % tablo)
            self.reddedilir(self.con, "DELETE FROM alig.%s" % tablo)
            self.reddedilir(self.con, "DELETE FROM alig.%s WHERE seq=1" % tablo)
            self.reddedilir(self.con, "TRUNCATE alig.%s" % tablo)
        self.reddedilir(self.con, "CREATE TABLE alig.olmamali(i int)")
        self.assertEqual(len(self.satirlar()), 2)
        self.assertEqual(len(self.satirlar("denetim")), 2)
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_ayni_seq_ikinci_kez_yazilamaz(self):
        depo_pg.denetim_ekle(self.con, "a", "b")
        s = self.satirlar()[0]
        with self.assertRaises(pg.BenzersizlikHatasi):
            self.con.sorgu("INSERT INTO alig.yonetim_denetim(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) "
                           "VALUES($1, now(), 'x', 'y', $2, $3, 3, '')", [s[0], s[3], s[4]])
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_bilinmeyen_zincir_adi_reddedilir(self):
        with self.assertRaises(ValueError):
            depo_pg.denetim_ekle(self.con, "a", "b", zincir_ad="x; DROP TABLE alig.kullanici")

    def test_listele_say_ve_zincir_basi(self):
        self.assertIsNone(depo_pg.zincir_basi(self.con))
        self.pg_zinciri(self.GIRDILER)
        self.assertEqual(depo_pg.denetim_say(self.con), len(self.GIRDILER))
        liste = depo_pg.denetim_listele(self.con, limit=2, offset=1)
        self.assertEqual([r[0] for r in liste], [len(self.GIRDILER) - 1, len(self.GIRDILER) - 2])
        self.assertRegex(liste[0][1], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class ZincirEszamanlilikTests(PgTaban):
    def test_es_zamanli_yazarlar_tek_saglam_zincir_birakir(self):
        is_parcacigi, yazma = 8, 25
        hatalar, b = [], threading.Barrier(is_parcacigi)

        def yaz(i):
            try:
                c = baglan(self.db)
                try:
                    b.wait(timeout=20)
                    for j in range(yazma):
                        depo_pg.denetim_ekle(c, "w%d" % i, "olay %d" % j, {"talep": j})
                finally:
                    c.kapat()
            except BaseException as ex:  # noqa: BLE001
                hatalar.append(repr(ex))
        ts = [threading.Thread(target=yaz, args=(i,)) for i in range(is_parcacigi)]
        [t.start() for t in ts]
        [t.join(120) for t in ts]
        self.assertEqual(hatalar, [])
        satirlar = self.satirlar()
        self.assertEqual([r[0] for r in satirlar], list(range(1, is_parcacigi * yazma + 1)))   # no gap, no duplicate
        self.assertEqual(len({r[3] for r in satirlar}), len(satirlar))   # every record has its own predecessor: no fork
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))
        for i in range(is_parcacigi):   # every writer's own records are all present and in its own order
            self.assertEqual([r[2] for r in satirlar if r[1] == "w%d" % i], ["olay %d" % j for j in range(yazma)])

    def test_es_zamanli_is_islemleri_ve_iki_zincir(self):
        """Writers that run a business action plus the audit record in one transaction, on both chains, from separate connections."""
        self.kullanici()
        hatalar, b = [], threading.Barrier(6)

        def yaz(i):
            try:
                c = baglan(self.db)
                try:
                    b.wait(timeout=20)
                    for j in range(10):
                        if i % 2:
                            depo_pg.talep_durum_yaz(c, i * 100 + j, "gorusuluyor", "n", "ali")
                        else:
                            with c.islem():   # yonetim first, then tarama: the documented order
                                depo_pg.denetim_ekle(c, "ali", "y %d/%d" % (i, j))
                                depo_pg.denetim_ekle(c, "ali", "t %d/%d" % (i, j), zincir_ad="tarama")
                finally:
                    c.kapat()
            except BaseException as ex:  # noqa: BLE001
                hatalar.append(repr(ex))
        ts = [threading.Thread(target=yaz, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join(120) for t in ts]
        self.assertEqual(hatalar, [])
        self.assertEqual(depo_pg.denetim_say(self.con), 1 + 30 + 30)    # user added + 30 status writes + 30 paired
        self.assertEqual(depo_pg.denetim_say(self.con, "tarama"), 30)
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))
        self.assertIsNone(depo_pg.denetim_dogrula(self.con, zincir_ad="tarama"))
        self.assertEqual(len(depo_pg.talep_durumlari(self.con)), 30)

    def test_acik_islemdeki_yazar_ikinciyi_bekletir_ve_sira_korunur(self):
        depo_pg.denetim_ekle(self.con, "a", "bir")
        c2 = self.baglanti()
        sonuc = {}

        def ikinci():
            depo_pg.denetim_ekle(c2, "b", "iki")
            sonuc["bitti"] = time.time()
        with self.con.islem():
            depo_pg.denetim_ekle(self.con, "a", "uc")   # seq 2, uncommitted, holds the chain lock
            t = threading.Thread(target=ikinci)
            t.start()
            t.join(0.8)
            self.assertTrue(t.is_alive(), "the second writer must wait for the tail lock")
            self.assertEqual(len(self.baglanti().sorgu("SELECT seq FROM alig.yonetim_denetim")), 1)   # nothing visible yet
        t.join(20)
        self.assertFalse(t.is_alive())
        satirlar = self.satirlar()
        self.assertEqual([(r[0], r[2]) for r in satirlar], [(1, "bir"), (2, "uc"), (3, "iki")])
        self.assertEqual(satirlar[2][3], satirlar[1][4])
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_geri_alinan_islem_zincirde_bosluk_birakmaz(self):
        depo_pg.denetim_ekle(self.con, "a", "bir")
        with self.assertRaises(RuntimeError):
            with self.con.islem():
                depo_pg.denetim_ekle(self.con, "a", "geri alinacak")
                raise RuntimeError("iptal")
        depo_pg.denetim_ekle(self.con, "a", "iki")
        self.assertEqual([(r[0], r[2]) for r in self.satirlar()], [(1, "bir"), (2, "iki")])
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_yazar_baglantisi_kopunca_zincir_sagam_kalir(self):
        depo_pg.denetim_ekle(self.con, "a", "bir")
        k = self.baglanti()
        pid = k.sorgu("SELECT pg_backend_pid()")[0][0]
        with self.assertRaises(pg.BaglantiHatasi):
            with k.islem():
                depo_pg.denetim_ekle(k, "a", "yarim")
                self.sql("SELECT pg_terminate_backend(%d)" % pid)
                k.sorgu("SELECT 1")
        depo_pg.denetim_ekle(self.con, "a", "iki")    # the dead writer's lock is gone with its session
        self.assertEqual([r[2] for r in self.satirlar()], ["bir", "iki"])
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))


# ------------------------------------------------------------------------------------------------ store behaviour
class DepoTests(PgTaban):
    def gir(self, gizli, ip, adim, parola=PAROLA, ad="ali"):
        t = time.time() + 30 * adim * 3   # each login has its own TOTP window (the code is single use)
        return depo_pg.giris(self.con, ad, parola, guvenlik.totp_kod(gizli, int(t // 30)), ip, simdi=t)

    def test_basarili_giris_ve_oturum(self):
        g = self.kullanici()
        kod, neden = self.gir(g, "198.51.100.1", 1)
        self.assertIsNone(neden)
        o = depo_pg.oturum(self.con, kod)
        self.assertEqual(o["ad"], "ali")
        self.assertTrue(o["csrf"])
        self.assertIsNone(depo_pg.oturum(self.con, "baska-kod"))
        self.assertIsNone(depo_pg.oturum(self.con, ""))
        # only the digest of the session code is stored
        self.assertEqual(self.con.sorgu("SELECT kod_sha256 FROM alig.oturum")[0][0], guvenlik.ozet(kod))
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_yanlis_parola_kod_ve_kullanici_ayni_yanit(self):
        g = self.kullanici()
        self.assertEqual(self.gir(g, "1.1.1.1", 1, parola="yanlis-parola-000"), (None, "hatali"))
        self.assertEqual(depo_pg.giris(self.con, "ali", PAROLA, "000000", "1.1.1.1"), (None, "hatali"))
        self.assertEqual(self.gir(g, "1.1.1.1", 2, ad="yok"), (None, "hatali"))
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 0)

    def test_totp_kodu_ikinci_kez_kullanilamaz(self):
        g = self.kullanici()
        t = time.time()
        kod = guvenlik.totp_kod(g, int(t // 30))
        self.assertIsNotNone(depo_pg.giris(self.con, "ali", PAROLA, kod, "1.1.1.1", simdi=t)[0])
        self.assertEqual(depo_pg.giris(self.con, "ali", PAROLA, kod, "1.1.1.1", simdi=t), (None, "hatali"))

    def test_kilitleme(self):
        g = self.kullanici()
        for i in range(depo_pg.DENEME_KULLANICI):
            self.assertEqual(self.gir(g, "1.1.1.1", i + 1, parola="yanlis-parola-000")[1], "hatali")
        self.assertEqual(self.gir(g, "1.1.1.1", 9)[1], "engelli")    # blocked even with the correct credentials
        self.assertTrue(depo_pg.giris_engelli(self.con, "ali", "9.9.9.9"))
        self.assertIn("engellendi", self.son()[0])

    def test_ip_kilitlemesi_ve_basarida_kullanici_sayaci_temizlenir(self):
        g = self.kullanici()
        for i in range(depo_pg.DENEME_KULLANICI - 1):
            self.gir(g, "1.1.1.1", i + 1, parola="yanlis-parola-000")
        self.assertIsNotNone(self.gir(g, "1.1.1.1", 8)[0])
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.giris_denemesi WHERE anahtar='k:ali'")[0][0], 0)
        self.assertGreater(self.con.sorgu("SELECT count(*) FROM alig.giris_denemesi WHERE anahtar LIKE 'ip:%'")[0][0], 0)

    def test_oturum_zaman_asimi_ve_cikis(self):
        g = self.kullanici()
        kod = self.gir(g, "1.1.1.1", 1)[0]
        self.sql("UPDATE alig.oturum SET son_erisim_utc='2000-01-01T00:00:00Z'")
        self.assertIsNone(depo_pg.oturum(self.con, kod))
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 0)   # the expired session is deleted
        kod = self.gir(g, "1.1.1.1", 2)[0]
        self.sql("UPDATE alig.oturum SET olusturma_utc=now() - interval '9 hours'")      # 8 hours at most
        self.assertIsNone(depo_pg.oturum(self.con, kod))
        kod = self.gir(g, "1.1.1.1", 3)[0]
        self.assertIsNotNone(depo_pg.oturum(self.con, kod))
        depo_pg.cikis(self.con, kod)
        self.assertIsNone(depo_pg.oturum(self.con, kod))

    def test_oturum_erisimi_son_erisimi_gunceller(self):
        g = self.kullanici()
        kod = self.gir(g, "1.1.1.1", 1)[0]
        self.sql("UPDATE alig.oturum SET son_erisim_utc=now() - interval '20 minutes'")
        self.assertIsNotNone(depo_pg.oturum(self.con, kod))
        self.assertTrue(self.con.sorgu("SELECT now() - son_erisim_utc < interval '1 minute' FROM alig.oturum")[0][0])

    def test_yeni_ip_uyari_ilk_giris_ve_bilinen_ip_degil(self):
        g = self.kullanici()
        self.assertIsNotNone(self.gir(g, "198.51.100.1", 1)[0])
        olay, al = self.son()
        self.assertEqual(olay, "giris yapildi")  # the first login is not a warning
        self.assertEqual(json.loads(al)["yeni_ip"], 0)
        self.assertIsNotNone(self.gir(g, "198.51.100.1", 2)[0])
        self.assertEqual(self.son()[0], "giris yapildi")
        self.assertIsNotNone(self.gir(g, "203.0.113.9", 3)[0])
        olay, al = self.son()
        self.assertEqual(olay, "yeni IP'den giris yapildi")
        a = json.loads(al)
        self.assertEqual((a["yeni_ip"], a["sonuc"], a["kullanici"]), (1, "basarili", "ali"))
        self.assertNotIn("203.0.113.9", al + olay)   # a plain address is not written to the audit
        self.assertNotIn("203.0.113.9", json.dumps([list(map(str, r)) for r in self.con.sorgu("SELECT * FROM alig.giris_ip")]))
        self.assertIsNotNone(self.gir(g, "203.0.113.9", 4)[0])
        self.assertEqual(self.son()[0], "giris yapildi")   # now a known IP
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_basarisiz_giris_yapisal_kayit_ve_kullanici_silinince_ip_silinir(self):
        g = self.kullanici()
        self.assertIsNone(self.gir(g, "198.51.100.1", 1, parola="yanlis-parola-000")[0])
        a = json.loads(self.son()[1])
        self.assertEqual((a["sonuc"], a["neden"]), ("basarisiz", "hatali"))
        self.assertNotIn("198.51.100.1", self.son()[1])
        self.gir(g, "198.51.100.1", 2)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.giris_ip")[0][0], 1)
        self.assertEqual(depo_pg.kullanici_sil(self.con, "ali"), 1)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.giris_ip")[0][0], 0)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 0)
        self.assertEqual(depo_pg.kullanici_sil(self.con, "ali"), 0)

    def test_parola_degisince_oturumlar_kapanir(self):
        g = self.kullanici()
        kod = self.gir(g, "1.1.1.1", 1)[0]
        self.assertIsNotNone(depo_pg.oturum(self.con, kod))
        self.assertEqual(depo_pg.kullanici_parola(self.con, "ali", "yeni-parola-456789"), 1)
        self.assertIsNone(depo_pg.oturum(self.con, kod))
        self.assertNotIn(PAROLA, json.dumps([list(r) for r in self.con.sorgu("SELECT * FROM alig.kullanici")], default=str))
        self.assertEqual(self.gir(g, "1.1.1.1", 2)[1], "hatali")
        self.assertIsNotNone(self.gir(g, "1.1.1.1", 3, parola="yeni-parola-456789")[0])
        self.assertEqual(depo_pg.kullanici_parola(self.con, "yok", "x" * 20), 0)
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_totp_yenile(self):
        g = self.kullanici()
        kod = self.gir(g, "1.1.1.1", 1)[0]
        yeni = depo_pg.kullanici_totp_yenile(self.con, "ali")
        self.assertNotEqual(yeni, g)
        self.assertIsNone(depo_pg.oturum(self.con, kod))
        self.assertIsNone(depo_pg.kullanici_totp_yenile(self.con, "yok"))
        self.assertIsNotNone(self.gir(yeni, "1.1.1.1", 2)[0])

    def test_ayni_kullanici_iki_kez_eklenemez_ve_denetim_yazilmaz(self):
        self.kullanici()
        once = depo_pg.denetim_say(self.con)
        with self.assertRaises(pg.BenzersizlikHatasi):
            self.kullanici()
        self.assertEqual(depo_pg.denetim_say(self.con), once)
        self.assertEqual(depo_pg.kullanici_listele(self.con)[0][0], "ali")
        self.assertTrue(depo_pg.kullanici_var(self.con, "ali"))
        self.assertFalse(depo_pg.kullanici_var(self.con, "veli"))

    # --- transactions: the action and its audit record together
    def bozuk_denetim(self):
        return mock.patch.object(depo_pg, "denetim_ekle", side_effect=RuntimeError("denetim yazilamadi"))

    def test_talep_durumu_denetimsiz_kalmaz(self):
        with self.bozuk_denetim():
            with self.assertRaises(RuntimeError):
                depo_pg.talep_durum_yaz(self.con, 1, "kapandi", "", "ali")
        self.assertEqual(depo_pg.talep_durumlari(self.con), {})

    def test_kullanici_ekleme_denetimsiz_kalmaz(self):
        with self.bozuk_denetim():
            with self.assertRaises(RuntimeError):
                depo_pg.kullanici_ekle(self.con, "veli", PAROLA)
        self.assertFalse(depo_pg.kullanici_var(self.con, "veli"))

    def test_kullanici_silme_ve_parola_denetimsiz_kalmaz(self):
        self.kullanici()
        with self.bozuk_denetim():
            with self.assertRaises(RuntimeError):
                depo_pg.kullanici_sil(self.con, "ali")
            with self.assertRaises(RuntimeError):
                depo_pg.kullanici_parola(self.con, "ali", "yeni-parola-456789")
        self.assertTrue(depo_pg.kullanici_var(self.con, "ali"))
        self.assertTrue(guvenlik.parola_dogrula(PAROLA, self.con.sorgu("SELECT parola FROM alig.kullanici")[0][0]))

    def test_giris_denetimsiz_kalmaz(self):
        g = self.kullanici()
        with self.bozuk_denetim():
            with self.assertRaises(RuntimeError):
                self.gir(g, "1.1.1.1", 1)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 0)
        self.assertEqual(self.con.sorgu("SELECT totp_sayac FROM alig.kullanici")[0][0], 0)   # the counter is rolled back too

    def test_ayni_dogrulama_kodu_es_zamanli_iki_giriste_bir_kez_gecer(self):
        g = self.kullanici()
        t = time.time()
        kod = guvenlik.totp_kod(g, int(t // 30))
        b, sonuc = threading.Barrier(2), []
        gercek = guvenlik.totp_dogrula

        def yavas(*a, **k):   # widen the window between reading and writing the counter
            time.sleep(0.3)
            return gercek(*a, **k)

        def gir(n):
            c = baglan(self.db)
            try:
                b.wait(timeout=20)
                sonuc.append(depo_pg.giris(c, "ali", PAROLA, kod, "198.51.100.%d" % n, simdi=t)[0] is not None)
            finally:
                c.kapat()
        with mock.patch.object(guvenlik, "totp_dogrula", side_effect=yavas):
            ts = [threading.Thread(target=gir, args=(i,)) for i in range(2)]
            [x.start() for x in ts]
            [x.join(60) for x in ts]
        self.assertEqual(sorted(sonuc), [False, True])
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 1)
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    # --- request statuses
    def test_talep_durumu_yazilir_guncellenir_ve_dogrulanir(self):
        depo_pg.talep_durum_yaz(self.con, 5, "gorusuluyor", "not", "ali")
        d = depo_pg.talep_durumlari(self.con)
        self.assertEqual((d[5]["durum"], d[5]["aciklama"], d[5]["guncelleyen"]), ("gorusuluyor", "not", "ali"))
        self.assertRegex(d[5]["guncelleme_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        depo_pg.talep_durum_yaz(self.con, 5, "kapandi", "x" * 900, "veli")
        d = depo_pg.talep_durumlari(self.con)
        self.assertEqual((len(d), d[5]["durum"], len(d[5]["aciklama"]), d[5]["guncelleyen"]), (1, "kapandi", 500, "veli"))
        with self.assertRaises(ValueError):
            depo_pg.talep_durum_yaz(self.con, 5, "yok", "", "ali")
        self.assertEqual(depo_pg.denetim_say(self.con), 2)
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    # --- cleanup
    def eski_oturum_ve_deneme(self, g):
        self.gir(g, "1.1.1.1", 1)   # a fresh session that must stay
        self.sql("INSERT INTO alig.oturum(kod_sha256, ad, csrf, olusturma_utc, son_erisim_utc) VALUES"
                 "(repeat('a',64),'ali','c', now() - interval '9 hours', now()), (repeat('b',64),'ali','c', now() - interval '10 hours', now())")
        self.sql("INSERT INTO alig.giris_denemesi(anahtar, zaman_utc) VALUES('k:ali', now() - interval '2 days'), ('k:ali', now())")

    def test_temizle_denetimsiz_cagri_davranisi_ayni(self):
        g = self.kullanici()
        self.eski_oturum_ve_deneme(g)
        once = depo_pg.denetim_say(self.con)
        self.assertEqual(depo_pg.temizle(self.con), 2)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 1)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.giris_denemesi WHERE zaman_utc < now() - interval '1 day'")[0][0], 0)
        self.assertEqual(depo_pg.denetim_say(self.con), once)   # the admin-login call writes no audit record

    def test_temizle_denetle_tek_sistem_kaydi_yazar(self):
        g = self.kullanici()
        self.eski_oturum_ve_deneme(g)
        once = depo_pg.denetim_say(self.con)
        self.assertEqual(depo_pg.temizle(self.con, denetle=True), 2)
        self.assertEqual(depo_pg.denetim_say(self.con), once + 1)
        olay = self.satirlar()[-1]
        self.assertEqual((olay[1], olay[2]), ("sistem", "suresi dolan 2 yonetim oturumu silindi"))
        self.assertEqual(depo_pg.temizle(self.con, denetle=True), 0)
        self.assertEqual(depo_pg.denetim_say(self.con), once + 1)   # nothing is recorded when none expired
        self.assertIsNone(depo_pg.denetim_dogrula(self.con))

    def test_temizle_denetle_kayit_yazilamazsa_silme_geri_alinir(self):
        g = self.kullanici()
        self.eski_oturum_ve_deneme(g)
        with self.bozuk_denetim():
            with self.assertRaises(RuntimeError):
                depo_pg.temizle(self.con, denetle=True)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.oturum")[0][0], 3)
        self.assertEqual(self.con.sorgu("SELECT count(*) FROM alig.giris_denemesi")[0][0], 2)

    def test_temizle_uygulama_rolunun_yetkisiyle_calisir(self):
        # the cleanup only needs DELETE on giris_denemesi/oturum; it never touches the chain tables
        self.assertEqual(depo_pg.temizle(self.con, denetle=True), 0)

    def test_oturum_listele(self):
        g = self.kullanici()
        self.gir(g, "1.1.1.1", 1)
        l = depo_pg.oturum_listele(self.con)
        self.assertEqual([r[0] for r in l], ["ali"])
        self.assertRegex(l[0][1], r"Z$")

    # --- panel counts
    def test_gosterge_sayilari(self):
        self.kullanici()
        self.sql("""
INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, durum, kayit_utc, son_utc) VALUES
  ('a.com','A','a@a.com','tarama','aktif', now(), now()), ('p.com','P','p@p.com','tarama','pasif', now(), now());
INSERT INTO alig.rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id) VALUES
  (repeat('1',64), now(), now() + interval '30 days', 'postgresql', 'tr', '{}', 1),
  (repeat('2',64), now() - interval '20 days', now() + interval '30 days', 'postgresql', 'tr', '{}', 1);
INSERT INTO alig.portal_kullanici(firma_id, eposta, parola, durum, kayit_utc) VALUES (1, 'u@a.com', 'x', 'aktif', now());
INSERT INTO alig.portal_talep(firma_id, kullanici_id, tur, durum, olusturma_utc, guncelleme_utc) VALUES
  (1, 1, 'destek', 'yeni', now(), now()), (1, 1, 'denetim', 'inceleniyor', now(), now()), (1, 1, 'silme', 'tamamlandi', now(), now());
INSERT INTO alig.baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, dil, olusturma_utc, bitis_utc, durum) VALUES
  (repeat('3',64), 1, 'k', 'ad', '10.0.0.1', 5432, 'db', 'u', 'tr', now(), now() + interval '1 hour', 'bekliyor'),
  (repeat('4',64), 1, 'k', 'ad', '10.0.0.1', 5432, 'db', 'u', 'tr', now(), now() + interval '1 hour', 'tamam'),
  (repeat('5',64), 1, 'k', 'ad', '10.0.0.1', 5432, 'db', 'u', 'tr', now() - interval '2 hours', now() - interval '1 hour', 'bekliyor');
INSERT INTO alig.posta(alici, konu, metin, olusturma_utc, durum) VALUES
  ('a@b.com','k','m', now(), 'bekliyor'), ('c@d.com','k','m', now(), 'gonderildi');
""")
        g = depo_pg.gosterge(self.con)
        self.assertEqual((g["tarama_7"], g["tarama_30"]), (1, 2))
        self.assertEqual((g["firma_aktif"], g["firma_pasif"]), (1, 1))
        self.assertEqual(g["portal_acik"], 2)
        self.assertEqual(g["kipb_bekleyen"], 1)        # the expired waiting request is not counted
        self.assertEqual(g["posta_bekleyen"], 1)
        self.assertEqual(g["iletisim_acik"], 0)
        self.assertIsNone(g["zincir_tarama"]["bozuk"])
        self.assertIsNone(g["zincir_yonetim"]["bozuk"])

    def test_gosterge_yonetim_zinciri_ve_eksik_veri(self):
        self.kullanici()
        g = depo_pg.gosterge(self.con)
        self.assertEqual(g["zincir_yonetim"]["bozuk"], None)
        self.assertEqual(g["zincir_yonetim"]["kayit"], 1)
        self.assertIsNone(g["zincir_tarama"]["bozuk"])          # an empty scan chain is sound, not "no data"
        for k in ("tarama_7", "tarama_30", "firma_aktif", "firma_pasif", "iletisim_acik", "portal_acik", "kipb_bekleyen", "posta_bekleyen"):
            self.assertEqual(g[k], 0, k)

    def test_gosterge_okunamayan_sayi_none_doner_sifir_degil(self):
        self.kullanici()
        sinirli = self.baglanti("alig_readonly")    # no privilege on contact/portal_talep/posta/baglanti_istegi
        g = depo_pg.gosterge(sinirli)
        self.assertIsNone(g["iletisim_acik"])
        self.assertIsNone(g["posta_bekleyen"])
        self.assertIsNone(g["portal_acik"])
        self.assertEqual(g["firma_aktif"], 0)
        self.assertEqual(g["zincir_yonetim"]["kayit"], 1)

    def test_gosterge_salt_okumadir_ve_kapali_talep_iletisim_sayisini_dusurur(self):
        self.kullanici()
        self.sql("INSERT INTO alig.contact(created_utc, name, company, email, db, message, ip_hash) VALUES"
                 "(now(),'a','b','a@b.com','pg','m','h'), (now(),'c','d','c@d.com','pg','m','h')")
        once = depo_pg.denetim_say(self.con)
        self.assertEqual(depo_pg.gosterge(self.con)["iletisim_acik"], 2)
        self.assertEqual(depo_pg.denetim_say(self.con), once)
        depo_pg.talep_durum_yaz(self.con, 1, "gorusuluyor", "", "ali")
        self.assertEqual(depo_pg.gosterge(self.con)["iletisim_acik"], 2)    # still open
        depo_pg.talep_durum_yaz(self.con, 1, "kapandi", "", "ali")
        self.assertEqual(depo_pg.gosterge(self.con)["iletisim_acik"], 1)
        depo_pg.talep_durum_yaz(self.con, 999, "kapandi", "", "ali")        # a status without a contact row changes nothing
        self.assertEqual(depo_pg.gosterge(self.con)["iletisim_acik"], 1)

    # --- degraded mode: no silent fallback
    def test_baglanti_kopunca_sqlite_e_dusmez(self):
        g = self.kullanici()
        pid = self.con.sorgu("SELECT pg_backend_pid()")[0][0]
        self.sql("SELECT pg_terminate_backend(%d)" % pid)
        for cagri in (lambda: self.gir(g, "1.1.1.1", 1), lambda: depo_pg.oturum(self.con, "x"), lambda: depo_pg.gosterge(self.con),
                      lambda: depo_pg.denetim_ekle(self.con, "a", "b")):
            with self.assertRaises(pg.BaglantiHatasi):
                cagri()

    def test_yapilandirma_yoksa_acik_hata(self):
        fake = mock.Mock()
        fake.yukle.return_value = None
        with mock.patch.dict(sys.modules, {"ortak.pg_ayar": fake}), mock.patch("ortak.pg_ayar", fake, create=True):
            with self.assertRaises(depo_pg.YapilandirmaHatasi):
                depo_pg.baglan({})
        with mock.patch.dict(sys.modules, {"ortak.pg_ayar": None}):    # the parser module is missing
            with self.assertRaises(depo_pg.YapilandirmaHatasi):
                depo_pg.baglan({})

    def test_baglan_ayarlardan_baglanir(self):
        k = _kume["k"]
        fake = mock.Mock()
        fake.yukle.return_value = {"host": k.soket, "port": int(k.port), "dbname": self.db, "user": "alig_app"}
        with mock.patch.dict(sys.modules, {"ortak.pg_ayar": fake}), mock.patch("ortak.pg_ayar", fake, create=True):
            c = depo_pg.baglan({"X": "1"})
        self.addCleanup(c.kapat)
        fake.yukle.assert_called_once_with({"X": "1"})
        self.assertEqual(c.sorgu("SELECT current_user")[0][0], "alig_app")


if __name__ == "__main__":
    unittest.main()
