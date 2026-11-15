"""ALIG-DB-003a: PostgreSQL schema and roles (db/sema/*.sql, db/uygula.py). Not tied to the application.
A temporary PostgreSQL 16 cluster is opened with tests/pg_yardimci.py (initdb, Unix socket, trust authentication: only this test cluster); SKIPped if PostgreSQL is absent."""
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import pg_yardimci  # noqa: E402

SEMA = ROOT / "db" / "sema"
UYGULA = ROOT / "db" / "uygula.py"
BULGU = pg_yardimci.pg_bul()
SQLSTATE = re.compile(r"(?:ERROR|FATAL):\s+([0-9A-Z]{5}):")


def uygula_modulu():
    spec = importlib.util.spec_from_file_location("db_uygula", UYGULA)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class UygulaBirimTests(unittest.TestCase):
    """Does not need PostgreSQL."""

    def test_sema_dosyalari_sirali_ve_sifre_icermez(self):
        adlar = sorted(p.name for p in SEMA.glob("*.sql"))
        self.assertGreaterEqual(len(adlar), 4)
        for i, ad in enumerate(adlar, 1):
            self.assertTrue(ad.startswith("%04d_" % i), ad)
            govde = (SEMA / ad).read_text(encoding="utf-8")
            self.assertNotRegex(govde, r"(?i)\bpassword\b|\bparola\b\s*['=]", ad)
            if i > 1:   # 0001 sets up the roles and the schema as the administrator; the later ones create objects as alig_owner
                ilk = [satir for satir in govde.splitlines() if satir.strip() and not satir.startswith("--")][0]
                self.assertEqual(ilk.strip(), "SET ROLE alig_owner;", ad)

    def test_dosya_listesi_yinelenen_ve_gecersiz_adi_reddeder(self):
        u = uygula_modulu()
        d = Path(tempfile.mkdtemp())
        try:
            (d / "0001_a.sql").write_text("SELECT 1;")
            (d / "0001_b.sql").write_text("SELECT 1;")
            with self.assertRaises(u.GocHatasi):
                u.dosyalari_oku(d)
            (d / "0001_b.sql").unlink()
            (d / "x.sql").write_text("SELECT 1;")
            with self.assertRaises(u.GocHatasi):
                u.dosyalari_oku(d)
            (d / "x.sql").unlink()
            (d / "0003_c.sql").write_text("SELECT 1;")   # 0002 missing: a gap
            with self.assertRaises(u.GocHatasi):
                u.dosyalari_oku(d)
        finally:
            shutil.rmtree(d)

    def test_psql_komutu_parola_tasimaz_ve_guvenli_bayraklari_kullanir(self):
        u = uygula_modulu()
        argv = u.psql_argv(Path("/x/0001_a.sql"))
        self.assertEqual(argv[0], "psql")
        for b in ("-X", "-1"):
            self.assertIn(b, argv)
        self.assertIn("ON_ERROR_STOP=1", argv)
        self.assertNotIn("-W", argv)
        self.assertFalse([a for a in argv if "password" in a.lower() or "PGPASSWORD" in a])

    def test_baglanti_ortam_degiskeni_yoksa_calismaz(self):
        r = subprocess.run([sys.executable, str(UYGULA)], capture_output=True, text=True,
                           env={"PATH": os.environ.get("PATH", "")})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PGDATABASE", r.stderr)


@pg_yardimci.pg_testi(BULGU.var, BULGU.neden)
class PgSemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kume = pg_yardimci.GeciciKume()
        cls.kume.baslat()
        cls.addClassCleanup(cls.kume.durdur)
        cls.kok, cls.veri, cls.soket = Path(cls.kume.dizin), cls.kume.veri, Path(cls.kume.soket)
        cls.port = str(cls.kume.port)
        cls.sayac = 0
        cls.db = cls.yeni_db()
        r = cls.uygula(cls.db)
        assert r.returncode == 0, r.stderr

    @classmethod
    def ortam(cls, db, kullanici="postgres"):
        e = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        e.update(PATH="%s:%s" % (cls.kume.bulgu.dizin, e.get("PATH", "")), PGHOST=str(cls.soket), PGPORT=cls.port,
                 PGDATABASE=db, PGUSER=kullanici, PGCONNECT_TIMEOUT="10")
        return e

    @classmethod
    def yeni_db(cls):
        cls.sayac += 1
        ad = "t%d" % cls.sayac
        r = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-c", 'CREATE DATABASE "%s"' % ad],
                           capture_output=True, text=True, env=cls.ortam("postgres"))
        assert r.returncode == 0, r.stderr
        return ad

    @classmethod
    def uygula(cls, db, dizin=None, kullanici="postgres"):
        argv = [sys.executable, str(UYGULA)] + (["--dizin", str(dizin)] if dizin else [])
        return subprocess.run(argv, capture_output=True, text=True, env=cls.ortam(db, kullanici), timeout=60)

    def sql(self, kullanici, sorgu, db=None):
        """(return code, stdout, sqlstate or None, stderr)"""
        r = subprocess.run(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-f", "-"],
                           input=sorgu, capture_output=True, text=True, env=self.ortam(db or self.db, kullanici), timeout=30)
        m = SQLSTATE.search(r.stderr)
        return r.returncode, r.stdout.strip(), (m.group(1) if m else None), r.stderr

    def tek(self, kullanici, sorgu, db=None):
        rc, out, _, err = self.sql(kullanici, sorgu, db)
        self.assertEqual(rc, 0, err)
        return out

    def baglanti_reddedilir(self, kullanici):
        rc, _, _, err = self.sql(kullanici, "SELECT 1")
        self.assertNotEqual(rc, 0)
        self.assertIn("permission denied for database", err)

    def reddedilir_migrations_yazma(self):
        self.reddedilir("alig_app", "INSERT INTO alig.schema_migrations(surum, dosya_sha256) VALUES('9999_x.sql', '%s')" % ("0" * 64))
        self.reddedilir("alig_migrator", "DELETE FROM alig.schema_migrations")
        self.reddedilir("alig_migrator", "UPDATE alig.schema_migrations SET dosya_sha256 = dosya_sha256")

    def reddedilir(self, kullanici, sorgu, durum="42501"):
        rc, _, kod, err = self.sql(kullanici, sorgu)
        self.assertNotEqual(rc, 0, "reddedilmedi: " + sorgu)
        self.assertEqual(kod, durum, err)

    # --- migrations ---
    def test_tum_dosyalar_uygulandi_ve_ozetler_dogru(self):
        dosyalar = sorted(SEMA.glob("*.sql"))
        out = self.tek("postgres", "SELECT surum || ' ' || dosya_sha256 FROM alig.schema_migrations ORDER BY surum")
        beklenen = "\n".join("%s %s" % (p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in dosyalar)
        self.assertEqual(out, beklenen)

    def test_ikinci_calistirma_idempotent(self):
        once = self.tek("postgres", "SELECT count(*), max(uygulama_utc) FROM alig.schema_migrations")
        r = self.uygula(self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no new migration", r.stdout)
        self.assertEqual(self.tek("postgres", "SELECT count(*), max(uygulama_utc) FROM alig.schema_migrations"), once)

    def test_degistirilmis_eski_dosya_reddedilir(self):
        d = Path(tempfile.mkdtemp(dir=self.kok))
        for p in SEMA.glob("*.sql"):
            shutil.copy(p, d / p.name)
        db = self.yeni_db()
        r = self.uygula(db, d)
        self.assertEqual(r.returncode, 0, r.stderr)
        hedef = sorted(d.glob("*.sql"))[1]
        hedef.write_text(hedef.read_text(encoding="utf-8") + "\n-- sonradan eklendi\n", encoding="utf-8")
        yeni = d / ("%04d_yeni.sql" % (len(list(d.glob("*.sql"))) + 1))
        yeni.write_text("CREATE TABLE alig.olmamali(i int);", encoding="utf-8")
        r = self.uygula(db, d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(hedef.name, r.stderr)
        self.assertEqual(self.tek("postgres", "SELECT to_regclass('alig.olmamali') IS NULL", db), "t")   # the new file was not applied either

    def test_ilk_dosya_yoneticiyle_sonrakiler_gocu_rolüyle_uygulanir(self):
        d = Path(tempfile.mkdtemp(dir=self.kok))
        shutil.copy(SEMA / "0001_roller.sql", d / "0001_roller.sql")
        db = self.yeni_db()
        self.assertEqual(self.uygula(db, d).returncode, 0)
        for p in SEMA.glob("*.sql"):
            shutil.copy(p, d / p.name)
        r = self.uygula(db, d, "alig_migrator")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM alig.schema_migrations", db), str(len(list(SEMA.glob("*.sql")))))
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM pg_tables WHERE schemaname='alig' AND tableowner <> 'alig_owner'", db), "0")
        self.assertEqual(self.uygula(db, d, "alig_migrator").returncode, 0)   # second run

    def test_yarida_kalan_dosya_geri_alinir(self):
        d = Path(tempfile.mkdtemp(dir=self.kok))
        for p in SEMA.glob("*.sql"):
            shutil.copy(p, d / p.name)
        db = self.yeni_db()
        self.assertEqual(self.uygula(db, d).returncode, 0)
        n = len(list(d.glob("*.sql"))) + 1
        (d / ("%04d_bozuk.sql" % n)).write_text("SET ROLE alig_owner;\nCREATE TABLE alig.yarim(i int);\nSELECT hatali;\n", encoding="utf-8")
        r = self.uygula(db, d)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.tek("postgres", "SELECT to_regclass('alig.yarim') IS NULL", db), "t")
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM alig.schema_migrations", db), str(n - 1))

    # --- roles ---
    def test_rol_ozellikleri(self):
        satir = lambda r: self.tek("postgres", "SELECT rolsuper::int, rolcreatedb::int, rolcreaterole::int, rolreplication::int, "
                                   "rolbypassrls::int, rolcanlogin::int, (rolpassword IS NULL)::int FROM pg_authid WHERE rolname='%s'" % r)
        # super, createdb, createrole, replication, bypassrls, login, no password
        self.assertEqual(satir("alig_app"), "0|0|0|0|0|1|1")
        self.assertEqual(satir("alig_owner"), "0|0|0|0|0|0|1")
        self.assertEqual(satir("alig_migrator"), "0|0|0|0|0|1|1")
        self.assertEqual(satir("alig_readonly"), "0|0|0|0|0|1|1")
        self.assertEqual(satir("alig_backup"), "0|0|0|1|0|1|1")

    def test_arama_yolu_ve_saat_dilimi_sabit(self):
        for r in ("alig_app", "alig_migrator", "alig_readonly"):
            self.assertEqual(self.tek(r, "SHOW search_path"), "alig, pg_catalog", r)
            self.assertEqual(self.tek(r, "SHOW TimeZone"), "UTC", r)

    def test_public_semasinda_create_yok(self):
        for r in ("alig_app", "alig_readonly", "alig_migrator", "alig_owner"):
            self.assertEqual(self.tek("postgres", "SELECT has_schema_privilege('%s', 'public', 'CREATE')::int" % r), "0", r)
        self.assertEqual(self.tek("postgres", "SELECT (nspacl::text ~ '(^|,|\\{)=[A-Za-z]*C')::int FROM pg_namespace WHERE nspname='public'"), "0")
        self.reddedilir("alig_app", "CREATE TABLE public.x(i int)")

    def test_uygulama_rolu_ddl_yapamaz(self):
        self.reddedilir("alig_app", "CREATE TABLE alig.x(i int)")
        self.reddedilir("alig_app", "CREATE TABLE x(i int)")
        self.reddedilir("alig_app", "ALTER TABLE alig.firma ADD COLUMN x int", "42501")
        self.reddedilir("alig_app", "DROP TABLE alig.firma", "42501")
        self.reddedilir("alig_app", "TRUNCATE alig.firma")

    def test_gocu_rolu_owner_adina_ddl_yapar(self):
        self.assertEqual(self.tek("alig_migrator", "BEGIN; SET ROLE alig_owner; CREATE TABLE alig.gecici(i int); "
                                  "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='alig.gecici'::regclass; ROLLBACK;").splitlines()[-2:][0],
                         "alig_owner")
        self.reddedilir("alig_migrator", "CREATE ROLE kotu")   # no privilege to create roles

    def test_salt_okuma_rolu_yazamaz_ve_secili_sutunlari_okur(self):
        self.reddedilir("alig_readonly", "INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) "
                        "VALUES('a.b', 'x', 'x@a.b', 'form', now(), now())")
        self.reddedilir("alig_readonly", "UPDATE alig.firma SET ad='x'")
        self.reddedilir("alig_readonly", "DELETE FROM alig.firma")
        self.tek("alig_readonly", "SELECT id, anahtar, ad, durum FROM alig.firma")
        self.tek("alig_readonly", "SELECT seq, ozet FROM alig.denetim")
        self.reddedilir("alig_readonly", "SELECT belge_json FROM alig.rapor")
        self.reddedilir("alig_readonly", "SELECT parola FROM alig.portal_kullanici")
        self.reddedilir("alig_readonly", "SELECT totp FROM alig.kullanici")

    def test_yedek_rolu_veriye_erisemez(self):
        self.baglanti_reddedilir("alig_backup")   # no connect privilege on the database (only the replication connection)
        self.reddedilir_migrations_yazma()

    def test_rolsuz_baglanti_reddedilir(self):
        self.tek("postgres", "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='baska_rol') THEN CREATE ROLE baska_rol LOGIN; END IF; END $$")
        self.baglanti_reddedilir("baska_rol")   # PUBLIC CONNECT was removed: only the alig roles connect

    # --- audit chains ---
    def test_denetim_tablolarinda_yalniz_insert_ve_select(self):
        for t in ("denetim", "yonetim_denetim"):
            self.tek("alig_app", "INSERT INTO alig.%s(seq, zaman_utc, aktor, olay, onceki, ozet) VALUES(1, now(), 'sistem', 'x', '', '%s')" % (t, "a" * 64))
            self.assertEqual(self.tek("alig_app", "SELECT count(*) FROM alig.%s" % t), "1")
            self.reddedilir("alig_app", "UPDATE alig.%s SET olay='y'" % t)
            self.reddedilir("alig_app", "DELETE FROM alig.%s" % t)
            self.reddedilir("alig_app", "TRUNCATE alig.%s" % t)
            self.reddedilir("alig_app", "INSERT INTO alig.%s(seq, zaman_utc, aktor, olay, onceki, ozet) VALUES(1, now(), 'a', 'b', '', '%s')" % (t, "b" * 64), "23505")
            self.reddedilir("alig_app", "INSERT INTO alig.%s(seq, zaman_utc, aktor, olay, onceki, ozet, mod) VALUES(9, now(), 'a', 'b', '', '%s', 7)" % (t, "c" * 64), "23514")
        # cleanup as owner (the application role cannot delete)
        self.tek("postgres", "DELETE FROM alig.denetim; DELETE FROM alig.yonetim_denetim")

    # --- constraints ---
    FIRMA = ("INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) "
             "VALUES('%s', 'ad', 'a@%s', 'form', now(), now()) RETURNING id")

    def test_yabanci_anahtar_ihlali(self):
        self.reddedilir("alig_app", "INSERT INTO alig.rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id) "
                        "VALUES('%s', now(), now(), 'm', 'tr', '{}', 999999)" % ("a" * 64), "23503")
        self.reddedilir("alig_app", "INSERT INTO alig.portal_oturum(kod_sha256, kullanici_id, csrf, olusturma_utc, son_erisim_utc) "
                        "VALUES('%s', 999999, 'c', now(), now())" % ("b" * 64), "23503")

    def test_benzersizlik_ihlali(self):
        self.tek("alig_app", self.FIRMA % ("uniq.test", "uniq.test"))
        self.reddedilir("alig_app", self.FIRMA % ("uniq.test", "uniq.test"), "23505")
        self.tek("postgres", "DELETE FROM alig.firma WHERE anahtar='uniq.test'")

    def test_check_ihlalleri(self):
        self.reddedilir("alig_app", "INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc, durum) "
                        "VALUES('chk.test', 'a', 'a@b.c', 'form', now(), now(), 'silinmis')", "23514")
        self.reddedilir("alig_app", "INSERT INTO alig.portal_kullanici(eposta, parola, durum, kayit_utc) "
                        "VALUES('a@b.c', 'x', 'aktif', now())", "23514")   # an active user must have a company
        self.reddedilir("alig_app", "INSERT INTO alig.posta(alici, konu, metin, olusturma_utc, durum) "
                        "VALUES('a@b.c', 'k', 'm', now(), 'belirsiz')", "23514")
        self.reddedilir("alig_app", "INSERT INTO alig.idempotency_anahtari(anahtar, istek_ozeti, sonuc) VALUES('k1', 'kisa', '')", "23514")
        self.reddedilir("alig_app", "INSERT INTO alig.rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json) "
                        "VALUES('%s', now(), now(), 'm', 'tr', 'json degil')" % ("c" * 64), "23514")
        self.reddedilir("alig_app", "INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc) VALUES('nn.test', 'a', 'a@b.c', 'f', now())", "23502")

    def test_idempotency_anahtari_benzersiz(self):
        ozet = "d" * 64
        self.tek("alig_app", "INSERT INTO alig.idempotency_anahtari(anahtar, istek_ozeti, sonuc) VALUES('ik-1', '%s', '{}')" % ozet)
        self.reddedilir("alig_app", "INSERT INTO alig.idempotency_anahtari(anahtar, istek_ozeti, sonuc) VALUES('ik-1', '%s', '{}')" % ozet, "23505")
        self.tek("alig_app", "DELETE FROM alig.idempotency_anahtari WHERE anahtar='ik-1'")

    def test_firma_silinince_bagli_kayitlar_kaskad_kullanim_kalir(self):
        fid = self.tek("alig_app", self.FIRMA % ("kask.test", "kask.test")).splitlines()[0]
        h = lambda c: c * 64
        kur = """
        INSERT INTO alig.rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json, firma_id) VALUES('%(a)s', now(), now(), 'm', 'tr', '{}', %(f)s);
        INSERT INTO alig.baglanti_istegi(token_sha256, firma_id, kanit, ad, ip, port, veritabani, kullanici, dil, olusturma_utc, bitis_utc)
          VALUES('%(b)s', %(f)s, 'k', 'a', '10.0.0.1', 5432, 'db', 'u', 'tr', now(), now());
        INSERT INTO alig.portal_kullanici(firma_id, eposta, parola, durum, kayit_utc) VALUES(%(f)s, 'u@kask.test', 'p', 'aktif', now());
        INSERT INTO alig.portal_kod(kod_sha256, kullanici_id, bitis_utc) SELECT '%(c)s', id, now() FROM alig.portal_kullanici WHERE firma_id=%(f)s;
        INSERT INTO alig.portal_oturum(kod_sha256, kullanici_id, csrf, olusturma_utc, son_erisim_utc) SELECT '%(d)s', id, 'c', now(), now() FROM alig.portal_kullanici WHERE firma_id=%(f)s;
        INSERT INTO alig.portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) SELECT %(f)s, id, 'silme', now(), now() FROM alig.portal_kullanici WHERE firma_id=%(f)s;
        INSERT INTO alig.kullanim(anahtar_sha256, zaman_utc) VALUES('%(e)s', now());
        """ % {"a": h("1"), "b": h("2"), "c": h("3"), "d": h("4"), "e": h("5"), "f": fid}
        self.tek("alig_app", kur)
        # a second open deletion request is blocked per company
        self.reddedilir("alig_app", "INSERT INTO alig.portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) "
                        "SELECT %s, id, 'silme', now(), now() FROM alig.portal_kullanici WHERE firma_id=%s" % (fid, fid), "23505")
        self.tek("alig_app", "DELETE FROM alig.firma WHERE id=%s" % fid)
        for t in ("rapor", "baglanti_istegi", "portal_kullanici", "portal_talep"):
            self.assertEqual(self.tek("postgres", "SELECT count(*) FROM alig.%s WHERE firma_id=%s" % (t, fid)), "0", t)
        for t in ("portal_kod", "portal_oturum"):
            self.assertEqual(self.tek("postgres", "SELECT count(*) FROM alig.%s" % t), "0", t)
        # usage is not tied to the company by a foreign key (it uses the key digest): the application deletes it separately in firma_sil
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM alig.kullanim WHERE anahtar_sha256='%s'" % h("5")), "1")
        self.tek("postgres", "DELETE FROM alig.kullanim")

    def test_kimlikler_silinince_yeniden_kullanilmaz(self):
        a = self.tek("alig_app", self.FIRMA % ("kimlik1.test", "kimlik1.test")).splitlines()[0]
        self.tek("alig_app", "DELETE FROM alig.firma WHERE id=%s" % a)
        b = self.tek("alig_app", self.FIRMA % ("kimlik2.test", "kimlik2.test")).splitlines()[0]
        self.assertGreater(int(b), int(a))
        self.tek("alig_app", "DELETE FROM alig.firma WHERE id=%s" % b)

    def test_tablolar_sahibi_owner_ve_uygulama_gerekli_dml_yapar(self):
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                  "WHERE n.nspname='alig' AND c.relkind IN ('r','S') AND pg_get_userbyid(c.relowner) <> 'alig_owner'"), "0")
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                  "WHERE n.nspname='alig' AND c.relkind='r'"), self.tek("postgres", "SELECT count(*) FROM pg_tables WHERE schemaname='alig'"))
        # every table is in the known list: if an unknown table is added this test forces a review of the new table's privileges
        beklenen = sorted("""baglanti_istegi contact denetim esitleme firma firma_silinen giris_denemesi giris_ip idempotency_anahtari
            kullanici kullanim oturum portal_deneme portal_kod portal_kullanici portal_oturum portal_talep posta rapor
            schema_migrations talep_durum yonetim_denetim""".split())
        self.assertEqual(self.tek("postgres", "SELECT string_agg(tablename, ' ' ORDER BY tablename) FROM pg_tables WHERE schemaname='alig'").split(), beklenen)
        # no objects outside the schema; PUBLIC holds no privilege on any alig table
        self.assertEqual(self.tek("postgres", "SELECT count(*) FROM information_schema.table_privileges WHERE table_schema='alig' AND grantee='PUBLIC'"), "0")


if __name__ == "__main__":
    unittest.main()
