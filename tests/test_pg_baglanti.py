"""ALIG-DB-003b: the shared PostgreSQL connection layer ortak/pg.py (not wired into the application).

Two groups:
- unit tests with a fake libpq (no server needed, always run): SQLSTATE mapping, transaction statements, retry rules,
  masking, TLS policy, connection-loss handling;
- PG16 tests on a temporary cluster (tests/pg_yardimci.py), SKIPped if system PostgreSQL 16 or libpq is missing.
"""
import ctypes
import logging
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from ortak import pg  # noqa: E402
import pg_yardimci  # noqa: E402

BULGU = pg_yardimci.pg_bul()
try:
    LIBPQ_VAR = pg.kutuphane_yukle() is not None
except pg.KutuphaneHatasi:
    LIBPQ_VAR = False
PG_NEDEN = BULGU.neden or "libpq yok"

PAROLA = "Uygulama-Parola-Ornek-1"
YANLIS = "YanlisParola-12345"
SIR = "Cok-Gizli-Deger-77"


# --- fake libpq ----------------------------------------------------------------------------------------------

class Sonuc:
    """One scripted PGresult."""

    def __init__(self, durum=1, sqlstate=None, mesaj="", satirlar=(), tipler=(), cmd=""):
        self.durum, self.sqlstate, self.mesaj = durum, sqlstate, mesaj
        self.satirlar, self.tipler, self.cmd = [tuple(r) for r in satirlar], list(tipler), cmd


def tamam(satirlar, tipler=(25,)):
    return Sonuc(2, satirlar=satirlar, tipler=tipler)


def hata(sqlstate, mesaj="hata"):
    return Sonuc(7, sqlstate=sqlstate, mesaj=mesaj)


KES = "kes"           # the connection drops: error result without SQLSTATE, PQstatus becomes bad
BOS = "bos"           # PQexecParams returns NULL


class SahteLib:
    """Minimal stand-in for the libpq function table: records calls, plays a script."""

    def __init__(self, baglanti_hatasi=None):
        self.conninfo = []
        self.gonderilen = []        # (sql, [params]) without the session set_config calls
        self.hepsi = []
        self.betik = []             # queue of Sonuc / KES / BOS; empty queue -> plain success
        self.sonuclar = {}
        self.temizlenen = set()
        self.kapatilan = []
        self.bagli = True
        self.baglanti_hatasi = baglanti_hatasi
        self._n = 0

    # connection
    def PQconnectdb(self, bilgi):
        self.conninfo.append(bilgi.decode("utf-8"))
        self.bagli = self.baglanti_hatasi is None
        return 1

    def PQstatus(self, c):
        return 0 if self.bagli else 1

    def PQerrorMessage(self, c):
        return (self.baglanti_hatasi or "server closed the connection unexpectedly").encode()

    def PQfinish(self, c):
        self.kapatilan.append(c)

    def PQgetCancel(self, c):
        return 99

    def PQcancel(self, c, tampon, n):
        return 1

    def PQfreeCancel(self, c):
        pass

    def PQisthreadsafe(self):
        return 1

    def PQlibVersion(self):
        return 160015

    # execution
    def PQexecParams(self, c, sql, n, tipler, dizi, uzunluk, bicim, sonuc_bicimi):
        sql = sql.decode("utf-8")
        parametreler = [dizi[i] for i in range(n)]
        self.hepsi.append((sql, parametreler))
        if "set_config" not in sql:
            self.gonderilen.append((sql, parametreler))
            iste = self.betik.pop(0) if self.betik else Sonuc(1)
        else:
            iste = Sonuc(2, satirlar=[("x",)], tipler=[25])
        if iste == BOS:
            self.bagli = False
            return None
        if iste == KES:
            self.bagli = False
            iste = Sonuc(7, mesaj="server closed the connection unexpectedly")
        self._n += 1
        self.sonuclar[self._n] = iste
        return self._n

    def PQresultStatus(self, r):
        return self.sonuclar[r].durum

    def PQresultErrorField(self, r, kod):
        s = self.sonuclar[r]
        if kod == pg.PG_DIAG_SQLSTATE:
            return s.sqlstate.encode() if s.sqlstate else None
        if kod == pg.PG_DIAG_MESSAGE_PRIMARY:
            return s.mesaj.encode() if s.mesaj else None
        return None

    def PQresultErrorMessage(self, r):
        return self.sonuclar[r].mesaj.encode()

    def PQntuples(self, r):
        return len(self.sonuclar[r].satirlar)

    def PQnfields(self, r):
        return len(self.sonuclar[r].tipler)

    def PQftype(self, r, j):
        return self.sonuclar[r].tipler[j]

    def PQgetvalue(self, r, i, j):
        v = self.sonuclar[r].satirlar[i][j]
        return str(v).encode()

    def PQgetisnull(self, r, i, j):
        return 1 if self.sonuclar[r].satirlar[i][j] is None else 0

    def PQgetlength(self, r, i, j):
        return len(self.PQgetvalue(r, i, j))

    def PQcmdTuples(self, r):
        return self.sonuclar[r].cmd.encode()

    def PQclear(self, r):
        self.temizlenen.add(r)

    def sorgular(self):
        return [s for s, _ in self.gonderilen]


class SahteKarisim:
    """Patches pg.kutuphane_yukle to return a SahteLib; self.lib is the fake."""

    def setUp(self):
        self.lib = SahteLib()
        yama = mock.patch.object(pg, "kutuphane_yukle", return_value=self.lib)
        yama.start()
        self.addCleanup(yama.stop)

    def baglan(self, **kw):
        ayar = dict(host="/var/run/postgresql", dbname="d", user="u", password=PAROLA)
        ayar.update(kw)
        b = pg.Baglanti.baglan(**ayar)
        self.addCleanup(b.kapat)
        return b


# --- unit tests ----------------------------------------------------------------------------------------------

class HataSiniflariTests(SahteKarisim, unittest.TestCase):
    """SQLSTATE -> exception class mapping."""

    def test_sqlstate_tablosu(self):
        tablo = [
            ("23505", pg.BenzersizlikHatasi), ("23503", pg.ButunlukHatasi), ("23514", pg.ButunlukHatasi),
            ("23502", pg.ButunlukHatasi),
            ("40001", pg.SerilestirmeHatasi), ("40P01", pg.DeadlockHatasi),
            ("42501", pg.YetkiHatasi),
            ("57014", pg.ZamanAsimiHatasi), ("55P03", pg.ZamanAsimiHatasi),
            ("42P01", pg.SorguHatasi), ("22P02", pg.SorguHatasi), ("25006", pg.SorguHatasi),
        ]
        for sqlstate, sinif in tablo:
            with self.subTest(sqlstate=sqlstate):
                b = self.baglan()
                self.lib.betik.append(hata(sqlstate, "m"))
                with self.assertRaises(sinif) as c:
                    b.sorgu("SELECT 1")
                self.assertEqual(c.exception.sqlstate, sqlstate)
                self.assertFalse(b.kopuk)  # a server error is not a connection loss
                self.assertIsInstance(c.exception, pg.PgHata)

    def test_katman_iliskileri(self):
        self.assertTrue(issubclass(pg.DeadlockHatasi, pg.SerilestirmeHatasi))
        self.assertTrue(issubclass(pg.KilitHatasi, pg.ZamanAsimiHatasi))
        self.assertTrue(issubclass(pg.SorguIptalHatasi, pg.ZamanAsimiHatasi))
        self.assertTrue(issubclass(pg.ZamanAsimiHatasi, pg.SorguHatasi))
        self.assertTrue(issubclass(pg.YetkiHatasi, pg.SorguHatasi))
        self.assertTrue(issubclass(pg.SonucBelirsizHatasi, pg.BaglantiHatasi))
        self.assertFalse(issubclass(pg.BaglantiHatasi, pg.SorguHatasi))
        self.assertFalse(issubclass(pg.SerilestirmeHatasi, pg.ButunlukHatasi))

    def test_baglanti_kaybi_sqlstate_gruplari(self):
        for sqlstate in ("08006", "08003", "57P01", "57P02", "57P03", None):
            with self.subTest(sqlstate=sqlstate):
                self.lib.bagli = True
                b = self.baglan()
                self.lib.betik.append(hata(sqlstate, "terminating connection"))
                with self.assertRaises(pg.BaglantiHatasi):
                    b.sorgu("SELECT 1")
                self.assertTrue(b.kopuk)

    def test_detay_mesaja_eklenmez(self):
        b = self.baglan()
        self.lib.betik.append(hata("23505", "duplicate key value violates unique constraint"))
        with self.assertRaises(pg.BenzersizlikHatasi) as c:
            b.sorgu("INSERT ...")
        self.assertIn("[23505]", str(c.exception))


class IslemIfadeTests(SahteKarisim, unittest.TestCase):
    """Which statements the transaction context manager sends."""

    def test_commit_yolu(self):
        b = self.baglan()
        with b.islem():
            self.assertTrue(b.islemde)
            b.sorgu("SELECT 1")
        self.assertFalse(b.islemde)
        self.assertEqual(self.lib.sorgular(), ["BEGIN", "SELECT 1", "COMMIT"])

    def test_istisnada_rollback(self):
        b = self.baglan()
        with self.assertRaises(RuntimeError):
            with b.islem():
                raise RuntimeError("x")
        self.assertEqual(self.lib.sorgular(), ["BEGIN", "ROLLBACK"])
        self.assertFalse(b.islemde)

    def test_sql_hatasinda_rollback_ve_ayni_hata(self):
        b = self.baglan()
        self.lib.betik[:] = [Sonuc(1), hata("23505", "dup")]
        with self.assertRaises(pg.BenzersizlikHatasi):
            with b.islem():
                b.sorgu("INSERT ...")
        self.assertEqual(self.lib.sorgular(), ["BEGIN", "INSERT ...", "ROLLBACK"])

    def test_commit_basarisiz_olursa_rollback_ve_hata(self):
        b = self.baglan()
        self.lib.betik[:] = [Sonuc(1), Sonuc(1), hata("40001", "could not serialize")]
        with self.assertRaises(pg.SerilestirmeHatasi):
            with b.islem():
                b.sorgu("UPDATE ...")
        self.assertEqual(self.lib.sorgular()[-2:], ["COMMIT", "ROLLBACK"])
        self.assertFalse(b.islemde)

    def test_salt_okunur_ve_izolasyon(self):
        b = self.baglan()
        with b.islem(salt_okunur=True, izolasyon="repeatable read"):
            pass
        self.assertEqual(self.lib.sorgular()[0], "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with b.islem(izolasyon="SERIALIZABLE"):
            pass
        self.assertIn("BEGIN ISOLATION LEVEL SERIALIZABLE", self.lib.sorgular())

    def test_izolasyon_beyaz_liste(self):
        b = self.baglan()
        for kotu in ("serializable; DROP TABLE x", "read uncommitted", "", "x"):
            with self.subTest(kotu=kotu):
                with self.assertRaises(ValueError):
                    with b.islem(izolasyon=kotu):
                        pass
        self.assertEqual(self.lib.gonderilen, [])  # nothing was sent for a rejected value
        self.assertFalse(b.islemde)

    def test_islem_zaman_asimlari_set_local_parametreli(self):
        b = self.baglan()
        with b.islem(statement_timeout_ms=1500, lock_timeout_ms=250):
            pass
        sorgular = [(s, p) for s, p in self.lib.hepsi if "set_config" in s][4:]  # skip the 4 session settings
        self.assertEqual(len(sorgular), 2)
        for s, _ in sorgular:
            self.assertIn("true", s.lower())  # is_local = true: SET LOCAL semantics, reverts at the end of the tx
        self.assertEqual(sorgular[0][1], [b"statement_timeout", b"1500"])
        self.assertEqual(sorgular[1][1], [b"lock_timeout", b"250"])

    def test_zaman_asimi_gecersiz_deger(self):
        b = self.baglan()
        for kotu in (0, -5, "10; DROP", 1.5, True):
            with self.subTest(kotu=kotu):
                with self.assertRaises(ValueError):
                    with b.islem(statement_timeout_ms=kotu):
                        pass

    def test_ic_ice_reddi(self):
        b = self.baglan()
        with b.islem():
            with self.assertRaises(pg.PgHata):
                with b.islem():
                    pass
        self.assertEqual(self.lib.sorgular(), ["BEGIN", "COMMIT"])  # the rejected inner call sent nothing

    def test_sorgu_otomatik_tekrar_yok(self):
        b = self.baglan()
        self.lib.betik[:] = [hata("40001", "serialization")]
        with self.assertRaises(pg.SerilestirmeHatasi):
            b.sorgu("UPDATE t SET x = $1", [1])
        self.assertEqual(len(self.lib.gonderilen), 1)  # sent exactly once

    def test_her_sonuc_temizlenir(self):
        b = self.baglan()
        self.lib.betik[:] = [tamam([("a",)]), hata("23505"), Sonuc(1)]
        b.sorgu("SELECT 1")
        with self.assertRaises(pg.BenzersizlikHatasi):
            b.sorgu("INSERT")
        b.sorgu("DELETE")
        self.assertEqual(set(self.lib.sonuclar), self.lib.temizlenen)  # PQclear for every PGresult, error path included


class BaglantiKaybiUnitTests(SahteKarisim, unittest.TestCase):

    def test_kayip_sonrasi_libpq_serbest_birakilir(self):
        b = self.baglan()
        self.lib.betik[:] = [KES]
        with self.assertRaises(pg.BaglantiHatasi):
            b.sorgu("SELECT 1")
        self.assertEqual(len(self.lib.kapatilan), 1)  # PQfinish at once: no half-open PGconn kept around
        self.assertTrue(b.kopuk)
        self.assertIn("kopuk", repr(b))
        n = len(self.lib.gonderilen)
        for _ in range(2):
            with self.assertRaises(pg.BaglantiHatasi) as c:
                b.sorgu("SELECT 1")
            self.assertIn("broken", str(c.exception))
        self.assertEqual(len(self.lib.gonderilen), n)  # nothing is sent on a dead connection
        with self.assertRaises(pg.BaglantiHatasi):
            with b.islem():
                pass
        b.kapat()
        b.kapat()
        self.assertEqual(len(self.lib.kapatilan), 1)  # no double PQfinish
        with self.assertRaises(pg.BaglantiHatasi):
            b.iptal()

    def test_bos_sonuc_kopuk_sayilir(self):
        b = self.baglan()
        self.lib.betik[:] = [BOS]
        with self.assertRaises(pg.BaglantiHatasi):
            b.sorgu("SELECT 1")
        self.assertTrue(b.kopuk)

    def test_islem_ortasinda_kayip_sonucu_belirsiz_degil(self):
        b = self.baglan()
        self.lib.betik[:] = [Sonuc(1), KES]
        with self.assertRaises(pg.BaglantiHatasi) as c:
            with b.islem():
                b.sorgu("INSERT")
        self.assertFalse(c.exception.sonuc_belirsiz)  # a transaction cut before COMMIT cannot have committed
        self.assertFalse(b.islemde)
        self.assertNotIn("ROLLBACK", self.lib.sorgular())  # no ROLLBACK on a dead connection

    def test_commit_sirasinda_kayip_sonucu_belirsiz(self):
        b = self.baglan()
        self.lib.betik[:] = [Sonuc(1), Sonuc(1), KES]
        with self.assertRaises(pg.SonucBelirsizHatasi) as c:
            with b.islem():
                b.sorgu("INSERT")
        self.assertTrue(c.exception.sonuc_belirsiz)
        self.assertIn("unknown", str(c.exception))
        self.assertFalse(b.islemde)

    def test_islem_disi_yazmada_kayip_belirsiz(self):
        b = self.baglan()
        self.lib.betik[:] = [KES]
        with self.assertRaises(pg.BaglantiHatasi) as c:
            b.sorgu("INSERT")
        self.assertTrue(c.exception.sonuc_belirsiz)


class MaskelemeUnitTests(SahteKarisim, unittest.TestCase):

    def test_baglanti_hatasi_metni_maskelenir(self):
        self.lib.baglanti_hatasi = f"connection failed: password={PAROLA} rejected"
        with self.assertLogs("alig.pg", level="DEBUG") as gunluk:
            with self.assertRaises(pg.BaglantiHatasi) as c:
                pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=PAROLA)
        metin = str(c.exception) + repr(c.exception) + " ".join(gunluk.output)
        self.assertNotIn(PAROLA, metin)
        self.assertIn("***", str(c.exception))

    def test_baglanti_dizgisi_hicbir_mesajda_yok(self):
        self.lib.baglanti_hatasi = "bad conninfo " + "host='/s' dbname='d' user='u' password='%s'" % PAROLA
        with self.assertRaises(pg.BaglantiHatasi) as c:
            pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=PAROLA)
        self.assertNotIn(PAROLA, str(c.exception))
        self.assertNotIn("password=", str(c.exception).replace("password='***'", "").replace("password=***", ""))

    def test_kacisli_parola_da_maskelenir(self):
        zor = "pa'ss\\wo rd-99"
        self.lib.baglanti_hatasi = "oops password='pa\\'ss\\\\wo rd-99' and " + zor
        with self.assertRaises(pg.BaglantiHatasi) as c:
            pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=zor)
        self.assertNotIn("wo rd-99", str(c.exception))

    def test_gizli_parametre_sunucu_mesajinda_maskelenir(self):
        b = self.baglan()
        self.lib.betik[:] = [hata("22P02", f'invalid input syntax for type integer: "{SIR}"')]
        with self.assertRaises(pg.SorguHatasi) as c:
            b.sorgu("SELECT $1::int", [SIR], gizli=True)
        self.assertNotIn(SIR, str(c.exception) + repr(c.exception))
        self.assertIn("***", str(c.exception))

    def test_repr_ve_log_parola_ve_sql_icermez(self):
        with self.assertLogs("alig.pg", level="DEBUG") as gunluk:
            b = self.baglan()
            self.lib.betik[:] = [KES]
            with self.assertRaises(pg.BaglantiHatasi):
                b.sorgu("SELECT $1", [SIR])
            logging.getLogger("alig.pg").debug("probe")
        metin = " ".join(gunluk.output) + repr(b) + str(b)
        for yasak in (PAROLA, SIR, "SELECT"):
            self.assertNotIn(yasak, metin)

    def test_gecersiz_deger_hatalari_deger_icermez(self):
        b = self.baglan()
        with self.assertRaises(ValueError) as c:
            b.sorgu("SELECT $1", [SIR + "\x00"])
        self.assertNotIn(SIR, str(c.exception))
        with self.assertRaises(ValueError) as c:
            pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=PAROLA + "\x00")
        self.assertNotIn(PAROLA, str(c.exception))


class TlsUnitTests(SahteKarisim, unittest.TestCase):

    def test_unix_soketi_sslmode_istemez(self):
        self.baglan(host="/var/run/postgresql")
        self.assertNotIn("sslmode", self.lib.conninfo[-1])

    def test_ag_baglantisi_verify_full_ister(self):
        for mod in (None, "disable", "allow", "prefer", "require", "verify-ca"):
            with self.subTest(sslmode=mod):
                with self.assertRaises(ValueError) as c:
                    pg.Baglanti.baglan(host="db.example.internal", dbname="d", user="u", password=PAROLA,
                                       sslmode=mod)
                self.assertNotIn(PAROLA, str(c.exception))
        self.assertEqual(self.lib.conninfo, [])  # rejected before libpq is called

    def test_verify_full_ve_sslrootcert_aktarilir(self):
        self.baglan(host="db.example.internal", port=5432, sslmode="verify-full",
                    sslrootcert="/etc/alig/pg-ca.crt")
        bilgi = self.lib.conninfo[-1]
        self.assertIn("sslmode='verify-full'", bilgi)
        self.assertIn("sslrootcert='/etc/alig/pg-ca.crt'", bilgi)

    def test_host_listesinde_her_ag_adresi_denetlenir(self):
        with self.assertRaises(ValueError):
            pg.Baglanti.baglan(host="/var/run/postgresql,db.example.internal", dbname="d", user="u",
                               password=PAROLA, sslmode=None)

    def test_bilinmeyen_sslmode_ve_bos_host(self):
        with self.assertRaises(ValueError):
            pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=PAROLA, sslmode="bogus")
        with self.assertRaises(ValueError):
            pg.Baglanti.baglan(host=None, dbname="d", user="u", password=PAROLA)  # no environment fallback

    def test_sslrootcert_deger_dogrulamasi(self):
        with self.assertRaises(ValueError):
            pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=PAROLA, sslrootcert="a\x00b")


class ZamanAsimiUnitTests(SahteKarisim, unittest.TestCase):

    def test_baglanti_zaman_asimi_ve_keepalive(self):
        self.baglan(baglanti_zaman_asimi=3)
        bilgi = self.lib.conninfo[-1]
        self.assertIn("connect_timeout='3'", bilgi)
        self.assertIn("keepalives='1'", bilgi)

    def test_oturum_zaman_asimlari_set_config(self):
        self.baglan(statement_timeout_ms=1234, lock_timeout_ms=2345, bosta_islem_zaman_asimi_ms=3456)
        degerler = [p for s, p in self.lib.hepsi if "set_config" in s]
        self.assertIn([b"statement_timeout", b"1234"], degerler)
        self.assertIn([b"lock_timeout", b"2345"], degerler)
        self.assertIn([b"idle_in_transaction_session_timeout", b"3456"], degerler)


class TekrarUnitTests(SahteKarisim, unittest.TestCase):
    """pg.tekrarli_islem: retry rules and bounds. The fake sleep records the waits."""

    def setUp(self):
        super().setUp()
        self.uykular = []

    def calistir(self, baglanti, fn, **kw):
        kw.setdefault("uyku", self.uykular.append)
        return pg.tekrarli_islem(baglanti, fn, **kw)

    def test_kural_ne_salt_okunur_ne_anahtar_ise_reddedilir(self):
        b = self.baglan()
        cagri = []
        with self.assertRaises(ValueError):
            self.calistir(b, cagri.append)
        self.assertEqual(cagri, [])  # the function never ran; no blind retry exists
        with self.assertRaises(ValueError):
            self.calistir(b, cagri.append, idempotency_anahtari="")
        with self.assertRaises(ValueError):
            self.calistir(b, cagri.append, salt_okunur=True, azami_deneme=0)

    def test_salt_okunur_serilestirme_hatasinda_tekrar(self):
        b = self.baglan()
        self.lib.betik[:] = [Sonuc(1), hata("40001", "ser"), Sonuc(1),          # attempt 1 fails, rolled back
                             Sonuc(1), tamam([("7",)]), Sonuc(1)]               # attempt 2 passes
        sonuc = self.calistir(b, lambda c: c.sorgu("SELECT 7"), salt_okunur=True)
        self.assertEqual(sonuc, [("7",)])
        self.assertEqual(self.lib.sorgular().count("BEGIN READ ONLY"), 2)
        self.assertEqual(len(self.uykular), 1)

    def test_yazma_anahtarla_tekrar_edilir(self):
        b = self.baglan()
        sayac = []

        def is_(c):
            sayac.append(1)
            if len(sayac) == 1:
                raise pg.DeadlockHatasi("dl", "40P01")
            return "ok"

        self.assertEqual(self.calistir(b, is_, idempotency_anahtari="anahtar-1"), "ok")
        self.assertEqual(len(sayac), 2)
        self.assertEqual(self.lib.sorgular(), ["BEGIN", "ROLLBACK", "BEGIN", "COMMIT"])

    def test_sinirli_deneme_ve_son_hata(self):
        b = self.baglan()
        sayac = []

        def is_(c):
            sayac.append(1)
            raise pg.SerilestirmeHatasi("hep", "40001")

        with self.assertRaises(pg.SerilestirmeHatasi) as c:
            self.calistir(b, is_, salt_okunur=True, azami_deneme=4)
        self.assertEqual(len(sayac), 4)
        self.assertEqual(c.exception.deneme_sayisi, 4)
        self.assertEqual(len(self.uykular), 3)  # no sleep after the last attempt

    def test_bekleme_ussel_ve_sinirli(self):
        b = self.baglan()

        def is_(c):
            raise pg.SerilestirmeHatasi("hep", "40001")

        with self.assertRaises(pg.SerilestirmeHatasi):
            self.calistir(b, is_, salt_okunur=True, azami_deneme=6, ilk_bekleme_s=0.1, azami_bekleme_s=0.5)
        sinirlar = [0.1, 0.2, 0.4, 0.5, 0.5]
        self.assertEqual(len(self.uykular), 5)
        for bekleme, sinir in zip(self.uykular, sinirlar):
            self.assertLessEqual(bekleme, sinir + 1e-9)
            self.assertGreaterEqual(bekleme, sinir / 2 - 1e-9)

    def test_azami_deneme_ust_siniri(self):
        b = self.baglan()
        with self.assertRaises(ValueError):
            self.calistir(b, lambda c: None, salt_okunur=True, azami_deneme=11)

    def test_tekrar_edilmeyen_hatalar(self):
        b = self.baglan()
        for hata_sinifi, kod in ((pg.BenzersizlikHatasi, "23505"), (pg.YetkiHatasi, "42501"),
                                 (pg.KilitHatasi, "55P03"), (pg.SorguIptalHatasi, "57014"),
                                 (pg.SorguHatasi, "42P01")):
            with self.subTest(kod=kod):
                sayac = []

                def is_(c):
                    sayac.append(1)
                    raise hata_sinifi("x", kod)

                with self.assertRaises(hata_sinifi):
                    self.calistir(b, is_, salt_okunur=True)
                self.assertEqual(len(sayac), 1)
        self.assertEqual(self.uykular, [])

    def test_uygulama_istisnasi_tekrar_edilmez(self):
        b = self.baglan()
        sayac = []

        def is_(c):
            sayac.append(1)
            raise RuntimeError("uygulama")

        with self.assertRaises(RuntimeError):
            self.calistir(b, is_, salt_okunur=True)
        self.assertEqual(len(sayac), 1)

    def test_hazir_baglantida_kayip_tekrar_edilmez(self):
        b = self.baglan()
        self.lib.betik[:] = [Sonuc(1), KES]
        sayac = []

        def is_(c):
            sayac.append(1)
            c.sorgu("SELECT 1")

        with self.assertRaises(pg.BaglantiHatasi):
            self.calistir(b, is_, salt_okunur=True)
        self.assertEqual(len(sayac), 1)

    def test_fabrikada_kayip_yeni_baglantiyla_tekrar(self):
        baglantilar = []

        def fabrika():
            b = pg.Baglanti.baglan(host="/s", dbname="d", user="u", password=PAROLA)
            baglantilar.append(b)
            return b

        self.lib.betik[:] = [Sonuc(1), KES]  # BEGIN ok, the statement kills the first connection
        sonuc = []

        def is_(c):
            sonuc.append(c.sorgu("SELECT 1"))
            return len(sonuc)

        self.assertEqual(self.calistir(fabrika, is_, salt_okunur=True), 1)
        self.assertEqual(len(baglantilar), 2)
        self.assertTrue(baglantilar[0].kopuk)
        self.assertEqual(len(self.lib.kapatilan), 2)  # both connections released at the end; the helper owns them

    def test_fabrikada_yazma_anahtarsiz_olmaz(self):
        with self.assertRaises(ValueError):
            self.calistir(lambda: None, lambda c: None)

    def test_tekrar_gunlugu_sir_icermez(self):
        b = self.baglan()
        sayac = []

        def is_(c):
            sayac.append(1)
            if len(sayac) == 1:
                raise pg.SerilestirmeHatasi(f"x {SIR}".replace(SIR, "***"), "40001")

        with self.assertLogs("alig.pg", level="DEBUG") as gunluk:
            self.calistir(b, is_, salt_okunur=True)
        self.assertTrue(any("retry" in m.lower() for m in gunluk.output))
        self.assertNotIn(PAROLA, " ".join(gunluk.output))


class ParametreliSqlTests(SahteKarisim, unittest.TestCase):

    def test_degerler_sorgu_metnine_girmez(self):
        b = self.baglan()
        kotu = "x'); DROP TABLE kayit; --"
        b.sorgu("SELECT $1::text", [kotu])
        sql, parametreler = self.lib.gonderilen[-1]
        self.assertEqual(sql, "SELECT $1::text")
        self.assertEqual(parametreler, [kotu.encode()])

    def test_nul_sorguda_reddedilir(self):
        b = self.baglan()
        with self.assertRaises(ValueError):
            b.sorgu("SELECT 1\x00")


# --- PG16 tests ----------------------------------------------------------------------------------------------

@pg_yardimci.pg_testi(BULGU.var and LIBPQ_VAR, PG_NEDEN)
class Pg16Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.kume = pg_yardimci.GeciciKume()
        cls.kume.baslat()
        cls.addClassCleanup(cls.kume.durdur)
        cls.dizin, cls.port = cls.kume.soket, cls.kume.port
        cls.kume.rol_olustur("alig_app", parola=PAROLA)
        cls.kume.rol_olustur("alig_dar", parola=PAROLA)  # no privileges at all
        cls.kume.veritabani_olustur("aligtest", sahip="alig_app")
        cls.kume.kimlik_dogrulama("scram-sha-256")

    def baglan(self, kullanici="alig_app", **kw):
        ayar = dict(host=self.dizin, port=self.port, dbname="aligtest", user=kullanici, password=PAROLA)
        ayar.update(kw)
        b = pg.Baglanti.baglan(**ayar)
        self.addCleanup(b.kapat)
        return b

    def setUp(self):
        b = self.baglan()
        b.sorgu("DROP TABLE IF EXISTS kayit CASCADE")
        b.sorgu("CREATE TABLE kayit (id serial PRIMARY KEY, ad text UNIQUE, deger integer)")

    # -- transaction
    def test_rollback_hata_aninda(self):
        b = self.baglan()
        b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["a"])
        with self.assertRaises(pg.BenzersizlikHatasi):
            with b.islem():
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["b"])
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["a"])
        self.assertFalse(b.islemde)
        self.assertEqual(b.sorgu("SELECT ad FROM kayit ORDER BY ad"), [("a",)])
        # the aborted transaction left nothing open: the same connection works and a new transaction commits
        with b.islem():
            b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["c"])
        self.assertEqual(b.sorgu("SELECT ad FROM kayit ORDER BY ad"), [("a",), ("c",)])

    def test_rollback_uygulama_istisnasinda(self):
        b = self.baglan()
        with self.assertRaises(KeyError):
            with b.islem():
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["x"])
                raise KeyError("x")
        self.assertEqual(b.sorgu("SELECT count(*) FROM kayit"), [(0,)])

    def test_cakisan_islemler_commit_gorunurlugu(self):
        a, d = self.baglan(), self.baglan()
        with a.islem():
            a.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["gorunmez"])
            self.assertEqual(d.sorgu("SELECT count(*) FROM kayit"), [(0,)])
        self.assertEqual(d.sorgu("SELECT count(*) FROM kayit"), [(1,)])

    def test_salt_okunur_islem_yazmayi_reddeder(self):
        b = self.baglan()
        with self.assertRaises(pg.SorguHatasi) as c:
            with b.islem(salt_okunur=True):
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["y"])
        self.assertEqual(c.exception.sqlstate, "25006")
        self.assertEqual(b.sorgu("SELECT count(*) FROM kayit"), [(0,)])

    def test_izolasyon_duzeyi_uygulanir(self):
        b = self.baglan()
        with b.islem(izolasyon="serializable", salt_okunur=True):
            self.assertEqual(b.sorgu("SHOW transaction_isolation"), [("serializable",)])
            self.assertEqual(b.sorgu("SHOW transaction_read_only"), [("on",)])
        self.assertEqual(b.sorgu("SHOW transaction_isolation"), [("read committed",)])

    # -- timeouts
    def test_islem_basina_statement_timeout(self):
        b = self.baglan(statement_timeout_ms=30000)
        t0 = time.monotonic()
        with self.assertRaises(pg.ZamanAsimiHatasi) as c:
            with b.islem(statement_timeout_ms=300):
                b.sorgu("SELECT pg_sleep(10)")
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(c.exception.sqlstate, "57014")
        self.assertIsInstance(c.exception, pg.SorguIptalHatasi)
        self.assertEqual(b.sorgu("SHOW statement_timeout"), [("30s",)])  # SET LOCAL did not leak out of the tx
        self.assertEqual(b.sorgu("SELECT 1"), [(1,)])

    def test_kilit_zaman_asimi(self):
        tutan, bekleyen = self.baglan(), self.baglan(lock_timeout_ms=300)
        tutan.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, 0)", ["k"])
        with tutan.islem():
            tutan.sorgu("SELECT * FROM kayit WHERE ad = $1 FOR UPDATE", ["k"])
            t0 = time.monotonic()
            with self.assertRaises(pg.KilitHatasi) as c:
                with bekleyen.islem():
                    bekleyen.sorgu("SELECT * FROM kayit WHERE ad = $1 FOR UPDATE", ["k"])
            self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(c.exception.sqlstate, "55P03")
        self.assertIsInstance(c.exception, pg.ZamanAsimiHatasi)

    def test_baglanti_zaman_asimi_kapali_porta(self):
        with self.assertRaises(pg.BaglantiHatasi) as c:
            pg.Baglanti.baglan(host=self.dizin, port=1, dbname="aligtest", user="alig_app", password=PAROLA,
                               baglanti_zaman_asimi=2)
        self.assertNotIn(PAROLA, str(c.exception))

    # -- classification
    def test_yetki_hatasi(self):
        sahip = self.baglan()
        sahip.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["p"])
        dar = self.baglan(kullanici="alig_dar")
        with self.assertRaises(pg.YetkiHatasi) as c:
            dar.sorgu("SELECT * FROM kayit")
        self.assertEqual(c.exception.sqlstate, "42501")
        self.assertEqual(dar.sorgu("SELECT 1"), [(1,)])

    def test_butunluk_ayrimi(self):
        b = self.baglan()
        b.sorgu("CREATE TABLE IF NOT EXISTS alt (kayit_id int REFERENCES kayit(id), n int CHECK (n > 0))")
        b.sorgu("DELETE FROM alt")
        with self.assertRaises(pg.ButunlukHatasi) as c1:
            b.sorgu("INSERT INTO alt (kayit_id, n) VALUES (999, 1)")
        self.assertEqual(c1.exception.sqlstate, "23503")
        self.assertNotIsInstance(c1.exception, pg.BenzersizlikHatasi)
        with self.assertRaises(pg.ButunlukHatasi) as c2:
            b.sorgu("INSERT INTO alt (kayit_id, n) VALUES (NULL, 0)")
        self.assertEqual(c2.exception.sqlstate, "23514")

    def test_serilestirme_hatasi(self):
        b = self.baglan()
        b.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, 1)", ["s"])
        a, d = self.baglan(), self.baglan()
        with self.assertRaises(pg.SerilestirmeHatasi) as c:
            with a.islem(izolasyon="repeatable read"):
                a.sorgu("SELECT deger FROM kayit WHERE ad = $1", ["s"])
                d.sorgu("UPDATE kayit SET deger = 2 WHERE ad = $1", ["s"])
                a.sorgu("UPDATE kayit SET deger = 3 WHERE ad = $1", ["s"])
        self.assertEqual(c.exception.sqlstate, "40001")
        self.assertNotIsInstance(c.exception, pg.DeadlockHatasi)
        self.assertEqual(b.sorgu("SELECT deger FROM kayit WHERE ad = $1", ["s"]), [(2,)])

    def test_deadlock_hatasi(self):
        b = self.baglan()
        b.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, 0), ($2, 0)", ["d1", "d2"])
        a, d = self.baglan(), self.baglan()
        engel = threading.Barrier(2, timeout=10)
        sonuc = {}

        def calis(ad, c, ilk, ikinci):
            try:
                with c.islem():
                    c.sorgu("UPDATE kayit SET deger = 1 WHERE ad = $1", [ilk])
                    engel.wait()
                    c.sorgu("UPDATE kayit SET deger = 1 WHERE ad = $1", [ikinci])
                sonuc[ad] = "tamam"
            except Exception as e:  # noqa: BLE001
                sonuc[ad] = e

        ts = [threading.Thread(target=calis, args=("a", a, "d1", "d2")),
              threading.Thread(target=calis, args=("d", d, "d2", "d1"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        durumlar = list(sonuc.values())
        olu = [x for x in durumlar if isinstance(x, pg.DeadlockHatasi)]
        self.assertEqual(len(olu), 1, durumlar)  # exactly one victim
        self.assertEqual(olu[0].sqlstate, "40P01")
        self.assertIsInstance(olu[0], pg.SerilestirmeHatasi)
        self.assertEqual(durumlar.count("tamam"), 1)

    # -- connection loss
    def _oldur(self, kurban):
        (pid,), = kurban.sorgu("SELECT pg_backend_pid()")
        izleyici = self.baglan()
        self.assertEqual(izleyici.sorgu("SELECT pg_terminate_backend($1)", [pid]), [(True,)])
        return pid

    def test_backend_sonlandirilinca_guvenli_hata(self):
        b = self.baglan()
        self._oldur(b)
        with self.assertRaises(pg.BaglantiHatasi) as c:
            b.sorgu("SELECT 1")
        self.assertNotIn(PAROLA, str(c.exception))
        self.assertTrue(b.kopuk)
        with self.assertRaises(pg.BaglantiHatasi):  # the same safe error again; no retry, no reconnect
            b.sorgu("SELECT 1")
        b.kapat()

    def test_islem_ortasinda_backend_olumu(self):
        b = self.baglan()
        with self.assertRaises(pg.BaglantiHatasi) as c:
            with b.islem():
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["yazilmamali"])
                self._oldur(b)
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["ikinci"])
        self.assertFalse(c.exception.sonuc_belirsiz)
        self.assertFalse(b.islemde)
        self.assertTrue(b.kopuk)
        self.assertEqual(self.baglan().sorgu("SELECT count(*) FROM kayit"), [(0,)])  # nothing committed

    def test_commit_oncesi_olum_hicbir_sey_yazmaz(self):
        b = self.baglan()
        with self.assertRaises(pg.BaglantiHatasi):
            with b.islem():
                b.sorgu("INSERT INTO kayit (ad) VALUES ($1)", ["kayip"])
                self._oldur(b)
        self.assertEqual(self.baglan().sorgu("SELECT count(*) FROM kayit"), [(0,)])

    def test_tekrarli_salt_okunur_kopma_sonrasi_yeni_baglanti(self):
        denemeler = []

        def fabrika():
            return pg.Baglanti.baglan(host=self.dizin, port=self.port, dbname="aligtest", user="alig_app",
                                      password=PAROLA)

        def is_(c):
            denemeler.append(c)
            if len(denemeler) == 1:
                self._oldur(c)
            return c.sorgu("SELECT 42")

        sonuc = pg.tekrarli_islem(fabrika, is_, salt_okunur=True, ilk_bekleme_s=0.01)
        self.assertEqual(sonuc, [(42,)])
        self.assertEqual(len(denemeler), 2)
        self.assertIsNot(denemeler[0], denemeler[1])

    def test_tekrarli_yazma_serilestirme_tekrari(self):
        b = self.baglan()
        b.sorgu("INSERT INTO kayit (ad, deger) VALUES ($1, 0)", ["sayac"])
        d = self.baglan()
        denemeler = []

        def is_(c):
            denemeler.append(1)
            (deger,), = c.sorgu("SELECT deger FROM kayit WHERE ad = $1", ["sayac"])
            if len(denemeler) == 1:  # a concurrent writer commits between our read and write
                d.sorgu("UPDATE kayit SET deger = deger + 10 WHERE ad = $1", ["sayac"])
            c.sorgu("UPDATE kayit SET deger = $1 WHERE ad = $2", [deger + 1, "sayac"])

        pg.tekrarli_islem(b, is_, idempotency_anahtari="sayac-1", izolasyon="repeatable read",
                          ilk_bekleme_s=0.01)
        self.assertEqual(len(denemeler), 2)
        self.assertEqual(b.sorgu("SELECT deger FROM kayit WHERE ad = $1", ["sayac"]), [(11,)])

    # -- masking
    def test_yanlis_parola_ve_gunluk(self):
        with self.assertLogs("alig.pg", level="DEBUG") as gunluk:
            with self.assertRaises(pg.BaglantiHatasi) as c:
                pg.Baglanti.baglan(host=self.dizin, port=self.port, dbname="aligtest", user="alig_app",
                                   password=YANLIS, baglanti_zaman_asimi=5)
        metin = str(c.exception) + repr(c.exception) + " ".join(gunluk.output)
        self.assertNotIn(YANLIS, metin)
        self.assertNotIn(PAROLA, metin)

    def test_sunucu_mesajinda_gizli_deger(self):
        b = self.baglan()
        with self.assertRaises(pg.SorguHatasi) as c:
            b.sorgu("SELECT $1::int", [SIR], gizli=True)
        self.assertNotIn(SIR, str(c.exception))
        self.assertEqual(c.exception.sqlstate, "22P02")

    def test_ag_baglantisi_sslmode_require_reddedilir_baglanmadan(self):
        with self.assertRaises(ValueError):
            pg.Baglanti.baglan(host="127.0.0.1", port=self.port, dbname="aligtest", user="alig_app",
                               password=PAROLA, sslmode="require")


if __name__ == "__main__":
    unittest.main()
