"""ALIG-DB-003e: company deletion + contact requests + KVKK deletion request in ONE PostgreSQL transaction (ortak/silme_pg.py)
and the atomicity test: a failure injected mid-way leaves nothing half-deleted. Real temporary PostgreSQL 16 cluster, the application
role alig_app (not a superuser). SKIPped (never PASS) when PostgreSQL 16 or libpq is missing."""
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pg_sema_kume  # noqa: E402
import pg_yardimci  # noqa: E402
from ortak import pg  # noqa: E402
from ortak import silme_pg  # noqa: E402
from tarama import depo as tarama_depo  # noqa: E402

H = lambda c: c * 64  # noqa: E731

TABLOLAR = ("firma", "firma_silinen", "rapor", "kullanim", "baglanti_istegi", "portal_kullanici", "portal_kod", "portal_oturum",
            "portal_talep", "contact", "talep_durum", "denetim")


class Birim(unittest.TestCase):
    def test_ozet_islevleri_sqlite_deposuyla_ayni(self):
        f = {"anahtar": "example.com"}
        self.assertEqual(silme_pg._firma_ozeti("example.com"), tarama_depo._firma_ozeti(f))
        self.assertEqual(silme_pg._iz_ozeti("example.com"), tarama_depo._iz_ozeti("example.com"))

    def test_like_kacis(self):
        self.assertEqual(silme_pg._like_kacis("a_b%c\\d"), "a\\_b\\%c\\\\d")


@pg_yardimci.pg_testi(pg_sema_kume.PG_VAR, pg_sema_kume.PG_NEDEN)
class SilmePgTests(pg_sema_kume.SemaKumesi, unittest.TestCase):
    def setUp(self):
        self.sql("TRUNCATE alig.firma, alig.contact, alig.talep_durum, alig.firma_silinen, alig.kullanim RESTART IDENTITY CASCADE")
        self.sql("DROP TRIGGER IF EXISTS enjekte ON alig.rapor; DROP TRIGGER IF EXISTS enjekte2 ON alig.firma_silinen")
        self.sql("""
        INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) VALUES
          ('example.com', 'Example', 'a@example.com', 'iletisim', now(), now()),
          ('other.org', 'Other', 'b@other.org', 'iletisim', now(), now());
        INSERT INTO alig.rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id) VALUES
          ('%(a)s', now(), now() + interval '1 day', 'postgresql', 'tr', '{}', 1),
          ('%(b)s', now(), now() + interval '1 day', 'postgresql', 'tr', '{}', 1),
          ('%(c)s', now(), now() + interval '1 day', 'postgresql', 'tr', '{}', 2);
        INSERT INTO alig.kullanim(anahtar_sha256, zaman_utc) VALUES ('%(k1)s', now()), ('%(k2)s', now());
        INSERT INTO alig.portal_kullanici(firma_id, eposta, parola, durum, kayit_utc) VALUES
          (1, 'u@example.com', 'x', 'aktif', now()), (2, 'u@other.org', 'x', 'aktif', now());
        INSERT INTO alig.portal_kod(kod_sha256, kullanici_id, bitis_utc) VALUES ('%(a)s', 1, now() + interval '1 day');
        INSERT INTO alig.portal_oturum(kod_sha256, kullanici_id, csrf, olusturma_utc, son_erisim_utc) VALUES ('%(b)s', 1, 'c', now(), now());
        INSERT INTO alig.portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) VALUES
          (1, 1, 'silme', now(), now()), (1, 1, 'destek', now(), now()), (2, 2, 'silme', now(), now());
        INSERT INTO alig.baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, dil, olusturma_utc, bitis_utc)
          VALUES ('%(c)s', 1, 'k', 'a', '192.0.2.1', 5432, 'db', 'u', 'tr', now(), now() + interval '1 day');
        INSERT INTO alig.contact(created_utc, name, company, email, db, message, ip_hash) VALUES
          (now(), 'A', 'Example', 'a@example.com', 'pg', 'm1', 'h'),
          (now(), 'B', 'Example', 'B@Example.COM', 'pg', 'm2', 'h'),
          (now(), 'C', 'Other', 'c@other.org', 'pg', 'm3', 'h'),
          (now(), 'D', 'Sub', 'd@sub.example.com', 'pg', 'm4', 'h'),
          (now(), 'E', 'Un_derscore', 'e@exampleXcom', 'pg', 'm5', 'h');
        INSERT INTO alig.talep_durum(talep_id, durum, guncelleme_utc, guncelleyen) VALUES
          (1, 'yeni', now(), 'x'), (2, 'yeni', now(), 'x'), (3, 'yeni', now(), 'x');
        """ % {"a": H("a"), "b": H("b"), "c": H("c"), "k1": silme_pg._firma_ozeti("example.com"), "k2": silme_pg._firma_ozeti("other.org")})

    def foto(self):
        """A full snapshot (row count + content hash) of every table the deletion may touch."""
        return {t: self.sql("SELECT count(*) || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '') FROM alig.%s x" % t)
                for t in TABLOLAR}

    def test_basarili_silme_tum_kayitlari_tek_islemde_siler(self):
        b = self.baglan()
        r = silme_pg.firma_sil_birlesik(b, 1)
        self.assertEqual(r, {"firma": 1, "iletisim_talebi": 2, "rapor": 2, "kvkk_silme_talebi": 1})
        for tablo, kosul in (("firma", "id = 1"), ("rapor", "firma_id = 1"), ("portal_kullanici", "firma_id = 1"), ("portal_kod", "true"),
                             ("portal_oturum", "true"), ("portal_talep", "firma_id = 1"), ("baglanti_istegi", "true"),
                             ("kullanim", "anahtar_sha256 = '%s'" % silme_pg._firma_ozeti("example.com")),
                             ("contact", "lower(email) LIKE '%@example.com'"), ("talep_durum", "talep_id IN (1, 2)")):
            self.assertEqual(self.sql("SELECT count(*) FROM alig.%s WHERE %s" % (tablo, kosul)), "0", tablo)
        # the other company and look-alike addresses stay
        self.assertEqual(self.sql("SELECT count(*) FROM alig.firma"), "1")
        self.assertEqual(self.sql("SELECT count(*) FROM alig.rapor"), "1")
        self.assertEqual(self.sql("SELECT count(*) FROM alig.portal_talep"), "1")
        self.assertEqual(self.sql("SELECT string_agg(name, ',' ORDER BY name) FROM alig.contact"), "C,D,E")
        self.assertEqual(self.sql("SELECT talep_id FROM alig.talep_durum"), "3")
        self.assertEqual(self.sql("SELECT count(*) FROM alig.kullanim"), "1")
        self.assertEqual(self.sql("SELECT anahtar_sha256 FROM alig.firma_silinen"), silme_pg._iz_ozeti("example.com"))

    def test_talepleri_koru_secenegi(self):
        r = silme_pg.firma_sil_birlesik(self.baglan(), 1, talepleri_sil=False)
        self.assertEqual(r["iletisim_talebi"], 0)
        self.assertEqual(self.sql("SELECT count(*) FROM alig.contact"), "5")
        self.assertEqual(self.sql("SELECT count(*) FROM alig.firma WHERE id = 1"), "0")

    def test_olmayan_firma_none_ve_hicbir_sey_degismez(self):
        once = self.foto()
        self.assertIsNone(silme_pg.firma_sil_birlesik(self.baglan(), 999))
        self.assertEqual(self.foto(), once)

    def test_denetim_geri_cagrisi_ayni_islemde_calisir(self):
        def denetim(b, sonuc):
            b.sorgu("INSERT INTO alig.denetim(seq, zaman_utc, aktor, olay, onceki, ozet) VALUES(1, now(), 'yonetici:x', $1, '', $2)",
                    ["firma #%d silindi" % sonuc["firma"], H("d")])
        silme_pg.firma_sil_birlesik(self.baglan(), 1, denetim=denetim)
        self.assertEqual(self.sql("SELECT olay FROM alig.denetim"), "firma #1 silindi")
        self.sql("TRUNCATE alig.denetim")

    # --- atomicity: a failure injected mid-way leaves NOTHING half-deleted ---
    def test_atomiklik_uygulama_hatasi_son_adimda(self):
        once = self.foto()

        def bozuk(b, sonuc):
            raise RuntimeError("injected failure after every delete")
        with self.assertRaises(RuntimeError):
            silme_pg.firma_sil_birlesik(self.baglan(), 1, denetim=bozuk)
        self.assertEqual(self.foto(), once)

    def test_atomiklik_denetim_yazimi_basarisiz(self):
        once = self.foto()

        def kotu_denetim(b, sonuc):
            b.sorgu("INSERT INTO alig.denetim(seq, zaman_utc, aktor, olay, onceki, ozet) VALUES(0, now(), 'a', 'b', '', $1)", [H("d")])   # CHECK seq >= 1
        with self.assertRaises(pg.ButunlukHatasi):
            silme_pg.firma_sil_birlesik(self.baglan(), 1, denetim=kotu_denetim)
        self.assertEqual(self.foto(), once)

    def test_atomiklik_veritabani_hatasi_ortada(self):
        """A trigger makes the DELETE of reports fail AFTER the contact requests and the quota rows were already deleted in the same transaction."""
        self.sql("""CREATE FUNCTION alig_test_hata() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RAISE EXCEPTION 'injected' USING ERRCODE = 'P0001'; END $f$;
                    CREATE TRIGGER enjekte BEFORE DELETE ON alig.rapor FOR EACH ROW EXECUTE FUNCTION alig_test_hata()""")
        self.addCleanup(self.sql, "DROP TRIGGER IF EXISTS enjekte ON alig.rapor; DROP FUNCTION IF EXISTS alig_test_hata()")
        once = self.foto()
        self.assertEqual(self.sql("SELECT count(*) FROM alig.contact WHERE lower(email) LIKE '%@example.com'"), "2")
        with self.assertRaises(pg.SorguHatasi) as c:
            silme_pg.firma_sil_birlesik(self.baglan(), 1)
        self.assertEqual(c.exception.sqlstate, "P0001")
        self.assertEqual(self.foto(), once)
        # after the fault is removed the same call succeeds completely (a retry is safe)
        self.sql("DROP TRIGGER enjekte ON alig.rapor")
        self.assertIsNotNone(silme_pg.firma_sil_birlesik(self.baglan(), 1))
        self.assertEqual(self.sql("SELECT count(*) FROM alig.firma WHERE id = 1"), "0")

    def test_atomiklik_iz_kaydi_yazilamazsa_firma_silinmez(self):
        self.sql("""CREATE FUNCTION alig_test_hata2() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RAISE EXCEPTION 'injected2' USING ERRCODE = 'P0002'; END $f$;
                    CREATE TRIGGER enjekte2 BEFORE INSERT ON alig.firma_silinen FOR EACH ROW EXECUTE FUNCTION alig_test_hata2()""")
        self.addCleanup(self.sql, "DROP TRIGGER IF EXISTS enjekte2 ON alig.firma_silinen; DROP FUNCTION IF EXISTS alig_test_hata2()")
        once = self.foto()
        with self.assertRaises(pg.SorguHatasi):
            silme_pg.firma_sil_birlesik(self.baglan(), 1)
        self.assertEqual(self.foto(), once)

    def test_atomiklik_baglanti_kesilince_hicbir_sey_silinmez(self):
        """The backend is killed after the contact requests were deleted, before COMMIT: the server rolls the open transaction back."""
        once = self.foto()
        b = self.baglan()

        def sonda(b_, sonuc):
            self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'alig_app' AND pid <> pg_backend_pid()")
        with self.assertRaises(pg.PgHata):
            silme_pg.firma_sil_birlesik(b, 1, denetim=sonda)
        self.assertEqual(self.foto(), once)

    def test_es_zamanli_iki_silme_biri_kazanir(self):
        sonuc, hata = [], []
        bar = threading.Barrier(2)

        def is_():
            try:
                b = pg.Baglanti.baglan(**self.app_ayar())
                try:
                    bar.wait(10)
                    sonuc.append(silme_pg.firma_sil_birlesik(b, 1))
                finally:
                    b.kapat()
            except Exception as e:   # noqa: BLE001
                hata.append(repr(e))
        ts = [threading.Thread(target=is_) for _ in range(2)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        self.assertEqual(hata, [])
        self.assertEqual(sorted(x is None for x in sonuc), [False, True])
        self.assertEqual(self.sql("SELECT count(*) FROM alig.firma_silinen"), "1")


if __name__ == "__main__":
    unittest.main()
