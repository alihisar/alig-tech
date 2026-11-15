"""ALIG-DB-005: PostgreSQL backup and restore (db/yedek.py). Not tied to the application.
The end-to-end drill is on a temporary PostgreSQL 16 cluster (initdb, Unix socket, trust: only this test cluster): schema, sample data and two
audit chains, a cluster with the WAL archive on, pg_basebackup (alig_backup role), pg_verifybackup, data after the backup, a timestamp,
an "accident" (emptying a table), PITR into a second empty directory, chain verification. SKIPped if PostgreSQL is absent.
The drill duration is for a local PG16 and small data; it is NOT an RTO target or measurement."""
import importlib.util
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YEDEK = ROOT / "db" / "yedek.py"
UYGULA = ROOT / "db" / "uygula.py"
PG16 = Path("/usr/lib/postgresql/16/bin")
PG_VAR = all((PG16 / a).exists() for a in ("initdb", "psql", "pg_basebackup", "pg_verifybackup"))
AYRAC = chr(31)
SURE_SINIRI = 90.0


def modul():
    spec = importlib.util.spec_from_file_location("db_yedek", YEDEK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ozet_hesapla():
    spec = importlib.util.spec_from_file_location("tarama_depo", ROOT / "tarama" / "depo.py")
    sys.path.insert(0, str(ROOT))
    try:
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.path.remove(str(ROOT))
    return m.ozet_hesapla


def agac(dizin):
    """List of (relative path, size, mtime_ns): proves the directory did not change."""
    cikti = []
    for p in sorted(Path(dizin).rglob("*")):
        st = p.lstat()
        cikti.append((str(p.relative_to(dizin)), st.st_size, st.st_mtime_ns))
    return cikti


class YedekBirimTests(unittest.TestCase):
    """Does not need PostgreSQL."""

    def setUp(self):
        self.y = modul()
        self.d = Path(tempfile.mkdtemp(prefix="aligyedekbirim"))
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_basebackup_komutu_parola_tasimaz_ve_akitir(self):
        argv = self.y.basebackup_argv("/yedek/x", "duz")
        for b in ("-w", "stream", "--manifest-checksums=SHA256", "alig_backup"):
            self.assertIn(b, argv)
        self.assertFalse([a for a in argv if "password" in a.lower() or "PGPASSWORD" in a])
        self.assertIn("t", self.y.basebackup_argv("/yedek/x", "tar"))

    def test_arsiv_komutu_uzerine_yazmaz_ve_atomiktir(self):
        k = self.y.arsiv_komutu("/wal")
        self.assertIn("test ! -f /wal/%f", k)
        self.assertIn("mv /wal/%f.gecici /wal/%f", k)
        self.assertIn("cp %p /wal/%f.gecici", k)
        self.assertEqual(self.y.restore_komutu("/wal"), 'test -f /wal/%f && cp /wal/%f "%p"')

    def test_tehlikeli_yol_ve_zaman_reddedilir(self):
        for yol in ("/wal'; rm -rf /; '", "goreli/yol", "/a b", '/a"b', "/a;b"):
            with self.assertRaises(self.y.YedekHatasi, msg=yol):
                self.y.arsiv_komutu(yol)
        with self.assertRaises(self.y.YedekHatasi):
            self.y.kurtarma_ayarlari(None, "2026-11-15 10:00:00+00")   # no point-in-time restore without an archive
        for z in ("dun", "2026-11-15 10:00:00", "2026-11-15'; DROP", "2026-11-15 10:00:00+00'"):
            with self.assertRaises(self.y.YedekHatasi, msg=z):
                self.y.kurtarma_ayarlari("/wal", z)
        s = self.y.kurtarma_ayarlari("/wal", "2026-11-15 10:00:00+00")
        self.assertIn("archive_mode = off", s)
        self.assertTrue(any(x.startswith("recovery_target_time = '2026-11-15 10:00:00+00'") for x in s))
        self.assertEqual(self.y.kurtarma_ayarlari(), ["archive_mode = off"])

    def _yedek_yap(self, kok, adlar):
        for ad in adlar:
            (kok / ad).mkdir(parents=True)
            (kok / ad / "backup_manifest").write_text("{}")

    def test_eskileri_sil_en_yeni_n_taneyi_saklar(self):
        adlar = ["pg-2026110%dT010101Z" % i for i in range(1, 6)]
        self._yedek_yap(self.d, adlar)
        (self.d / "pg-20261101T010101Z.devam").mkdir()          # partial backup: not counted, not deleted
        (self.d / "baska-dizin").mkdir()                          # foreign: left alone
        (self.d / "pg-20261109T010101Z").mkdir()                  # without a manifest: incomplete, not counted
        silinecek = self.y.eskileri_sil(self.d, 2, evet=False)
        self.assertEqual([p.name for p in silinecek], adlar[:3])
        self.assertTrue(all((self.d / a).exists() for a in adlar))   # a dry run does not delete
        self.y.eskileri_sil(self.d, 2, evet=True)
        kalan = sorted(p.name for p in self.d.iterdir())
        self.assertEqual(kalan, sorted(adlar[3:] + ["pg-20261101T010101Z.devam", "baska-dizin", "pg-20261109T010101Z"]))
        with self.assertRaises(self.y.YedekHatasi):
            self.y.eskileri_sil(self.d, 0, evet=True)
        self.assertEqual(len(self.y.yedekleri_listele(self.d)), 2)

    def test_arac_yoksa_hata_ve_yarim_yedek_birakmaz(self):
        kok = self.d / "yedek"
        e = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        e["ALIG_PG_BIN"] = str(self.d / "yok")
        r = subprocess.run([sys.executable, str(YEDEK), "al", "--kok", str(kok)], capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 1)
        self.assertIn("tool not found", r.stderr)
        self.assertEqual(list(kok.iterdir()), [])
        self.assertEqual((kok.stat().st_mode & 0o777), 0o700)

    def test_kullanim_hatasi_2_doner_ve_arsiv_onerisi_yazar(self):
        r = subprocess.run([sys.executable, str(YEDEK), "geri-yukle"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run([sys.executable, str(YEDEK), "arsiv-onerisi", "--wal-arsivi", "/var/lib/wal"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("archive_mode = on", r.stdout)
        self.assertIn("test ! -f /var/lib/wal/%f", r.stdout)


@unittest.skipUnless(PG_VAR, "PostgreSQL 16 yok: yedek tatbikati atlandi")
class YedekTatbikatTests(unittest.TestCase):
    sureler = {}

    @classmethod
    def setUpClass(cls):
        cls.root_mu = os.geteuid() == 0
        cls.pw = pwd.getpwnam("postgres") if cls.root_mu else None
        cls.kok = Path(tempfile.mkdtemp(prefix="aligyedek", dir="/tmp"))
        os.chmod(cls.kok, 0o755)
        cls.calisanlar = []
        cls.baslangic = time.perf_counter()
        try:
            cls.sahip(cls.kok)
            cls.soket, cls.arsiv, cls.veri = cls.kok / "soket", cls.kok / "arsiv", cls.kok / "veri"
            cls.yedek_kok = cls.kok / "yedekler"
            for d in (cls.soket, cls.arsiv):
                d.mkdir(mode=0o700)
                cls.sahip(d)
            cls.port = cls.bos_port()
            cls.y = modul()
            cls.pg(["initdb", "-D", str(cls.veri), "-U", "postgres", "--auth=trust", "-E", "UTF8", "--no-locale"])
            with open(cls.veri / "postgresql.conf", "a") as f:
                f.write("\nwal_level = replica\nfsync = off\narchive_mode = on\narchive_command = '%s'\n"
                        % cls.y.arsiv_komutu(cls.arsiv))
            cls.baslat(cls.veri, cls.port, cls.soket)
            cls.db = "aligyedek"
            cls.sql("postgres", "CREATE DATABASE %s" % cls.db, db="postgres")
            r = subprocess.run([sys.executable, str(UYGULA)], capture_output=True, text=True,
                               env=cls.ortam(cls.port, cls.soket, cls.db, "postgres"), timeout=60)
            assert r.returncode == 0, r.stderr
            cls.ornek_veri()
            # full backup (alig_backup role), the drill clock starts here
            t0 = time.perf_counter()
            r = cls.yedek_cmd("al", "--kok", str(cls.yedek_kok))
            cls.sureler["yedek_al"] = time.perf_counter() - t0
            assert r.returncode == 0, r.stdout + r.stderr
            cls.yedek = sorted(p for p in cls.yedek_kok.iterdir() if p.name.startswith("pg-"))[-1]
            # data after the backup, a timestamp, an erroneous change
            cls.sql("postgres", "INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) "
                                "SELECT 'yb' || g, 'Yedek Sonrasi Şirketi ' || g, 'yb' || g || '@ornek.test', 'test', now(), now() "
                                "FROM generate_series(1, 50) g")
            cls.denetim_ekle("alig.denetim", 3, "test", "yedek-sonrasi")
            time.sleep(0.4)
            cls.zaman = cls.sql("postgres", "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US') || '+00'")[1]
            time.sleep(0.4)
            cls.sql("postgres", "INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) "
                                "VALUES('hatali', 'Hatali Satir', 'h@ornek.test', 'test', now(), now())")
            cls.sql("postgres", "DELETE FROM alig.firma")     # "accidentally" emptying the table
            seg = cls.sql("postgres", "SELECT pg_walfile_name(pg_current_wal_lsn())")[1]
            cls.sql("postgres", "SELECT pg_switch_wal()")
            cls.arsivi_bekle(seg)
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for veri, _ in [(cls.veri, 0)] + [(v, 0) for v in cls.calisanlar]:
            if (Path(veri) / "postmaster.pid").exists():
                cls.pg(["pg_ctl", "-D", str(veri), "-m", "immediate", "-w", "stop"], kontrol=False)
        shutil.rmtree(cls.kok, ignore_errors=True)
        if cls.sureler:
            print("\n[ALIG-DB-005 tatbikat, yerel PG16, kucuk veri; RTO hedefi DEGIL] " +
                  ", ".join("%s=%.2fs" % (k, v) for k, v in cls.sureler.items()), file=sys.stderr)

    # --- helpers ---
    @classmethod
    def sahip(cls, yol, ozyinelemeli=False):
        if cls.root_mu:
            subprocess.run(["chown"] + (["-R"] if ozyinelemeli else []) + ["%d:%d" % (cls.pw.pw_uid, cls.pw.pw_gid), str(yol)], check=True)

    @staticmethod
    def bos_port():
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = str(s.getsockname()[1])
        s.close()
        return p

    @classmethod
    def pg(cls, argv, kontrol=True):
        komut = [str(PG16 / argv[0])] + argv[1:]
        if cls.root_mu:
            komut = ["runuser", "-u", "postgres", "--"] + komut
        r = subprocess.run(komut, capture_output=True, text=True, timeout=60)
        if kontrol and r.returncode != 0:
            raise RuntimeError("%s: %s" % (argv[0], r.stderr[-500:]))
        return r

    @classmethod
    def baslat(cls, veri, port, soket):
        cls.pg(["pg_ctl", "-D", str(veri), "-w", "-t", "30", "-l", str(cls.kok / ("gunluk-" + port + ".txt")), "-o",
                "-p %s -k %s -c listen_addresses=" % (port, soket), "start"])

    @classmethod
    def ortam(cls, port, soket, db, kullanici="postgres"):
        e = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        e.update(PATH="%s:%s" % (PG16, e.get("PATH", "")), PGHOST=str(soket), PGPORT=str(port), PGDATABASE=db,
                 PGUSER=kullanici, PGCONNECT_TIMEOUT="10")
        return e

    @classmethod
    def sql(cls, kullanici, sorgu, db=None, port=None, soket=None, kontrol=True):
        r = subprocess.run(["psql", "-X", "-A", "-t", "-F", AYRAC, "-v", "ON_ERROR_STOP=1", "-f", "-"], input=sorgu,
                           capture_output=True, text=True, timeout=60,
                           env=cls.ortam(port or cls.port, soket or cls.soket, db or cls.db, kullanici))
        if kontrol and r.returncode != 0:
            raise RuntimeError("psql: %s" % r.stderr[-500:])
        return r.returncode, r.stdout.strip("\n")

    @classmethod
    def yedek_cmd(cls, *args, kullanici_soket=None):
        return subprocess.run([sys.executable, str(YEDEK)] + list(args), capture_output=True, text=True, timeout=120,
                              env=cls.ortam(cls.port, cls.soket, "postgres", "alig_backup"))

    @classmethod
    def denetim_ekle(cls, tablo, seq, olay, aktor="tatbikat"):
        onceki = ""
        if seq > 1:
            onceki = cls.sql("postgres", "SELECT ozet FROM %s WHERE seq = %d" % (tablo, seq - 1))[1]
        oz = ozet_hesapla()(seq, aktor, olay, onceki, None, "")
        # application role: only INSERT/SELECT (0005_yetkiler.sql)
        cls.sql("alig_app", "INSERT INTO %s(seq, zaman_utc, aktor, olay, onceki, ozet, mod, alanlar) "
                            "VALUES(%d, now(), '%s', '%s', '%s', '%s', 2, '')" % (tablo, seq, aktor, olay, onceki, oz))

    @classmethod
    def ornek_veri(cls):
        cls.sql("postgres", "INSERT INTO alig.firma(anahtar, ad, eposta, kaynak, kayit_utc, son_utc) "
                            "SELECT 'f' || g, 'Örnek Şirket ' || g, 'f' || g || '@ornek.test', 'test', now(), now() "
                            "FROM generate_series(1, 200) g")
        for tablo in ("alig.denetim", "alig.yonetim_denetim"):
            cls.denetim_ekle(tablo, 1, "olay-bir")
            cls.denetim_ekle(tablo, 2, "olay-iki")

    @classmethod
    def arsivi_bekle(cls, segment, sn=20):
        bitis = time.time() + sn
        while time.time() < bitis:
            if (cls.arsiv / segment).exists():
                return
            time.sleep(0.1)
        raise RuntimeError("WAL arsivlenmedi: " + segment)

    def zincir_saglam(self, tablo, port, soket, beklenen):
        _, cikti = self.sql("postgres", "SELECT seq, aktor, olay, onceki, ozet, mod, alanlar FROM %s ORDER BY seq" % tablo,
                            port=port, soket=soket)
        satirlar = [s.split(AYRAC) for s in cikti.splitlines()]
        self.assertEqual(len(satirlar), beklenen, tablo)
        onceki, hesap = "", ozet_hesapla()
        for seq, aktor, olay, on, oz, mod, alanlar in satirlar:
            self.assertEqual(on, onceki, "zincir kopuk: %s #%s" % (tablo, seq))
            self.assertEqual(oz, hesap(int(seq), aktor, olay, on, None, alanlar), "ozet uyusmuyor: %s #%s" % (tablo, seq))
            onceki = oz

    # --- tests ---
    def test_yedek_dogrulanir_ve_izinleri_dardir(self):
        r = self.yedek_cmd("dogrula", "--yedek", str(self.yedek))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.yedek_kok.stat().st_mode & 0o777, 0o700)
        self.assertTrue((self.yedek / "backup_manifest").is_file())
        self.assertTrue(list((self.yedek / "pg_wal").glob("0*")), "akitilmis WAL yedekte yok")
        self.assertFalse([p for p in self.yedek_kok.iterdir() if p.name.endswith(".devam")])
        # role: only REPLICATION; cannot connect to the database
        rc, _ = self.sql("alig_backup", "SELECT 1", kontrol=False)
        self.assertNotEqual(rc, 0)

    def test_pitr_zamana_geri_yukler(self):
        t0 = time.perf_counter()
        hedef = self.kok / "geri1"
        r = self.yedek_cmd("geri-yukle", "--yedek", str(self.yedek), "--hedef", str(hedef), "--wal-arsivi", str(self.arsiv),
                           "--hedef-zaman", self.zaman, "--evet")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t1 = time.perf_counter()
        self.assertTrue((hedef / "recovery.signal").exists())
        self.assertEqual(hedef.stat().st_mode & 0o777, 0o700)
        self.sahip(hedef, True)
        port, soket = self.bos_port(), self.kok / "soket2"
        soket.mkdir(mode=0o700)
        self.sahip(soket)
        self.calisanlar.append(hedef)
        self.baslat(hedef, port, soket)
        bitis = time.time() + 40
        while True:
            _, kurtarmada = self.sql("postgres", "SELECT pg_is_in_recovery()", port=port, soket=soket)
            if kurtarmada == "f" or time.time() > bitis:
                break
            time.sleep(0.1)
        t2 = time.perf_counter()
        self.assertEqual(kurtarmada, "f", "kurtarma bitmedi")
        # the rows added after the backup and the rows "accidentally" deleted came back; the later erroneous change did not
        self.assertEqual(self.sql("postgres", "SELECT count(*) FROM alig.firma", port=port, soket=soket)[1], "250")
        self.assertEqual(self.sql("postgres", "SELECT count(*) FROM alig.firma WHERE anahtar = 'hatali'", port=port, soket=soket)[1], "0")
        self.assertEqual(self.sql("postgres", "SELECT count(*) FROM alig.firma WHERE ad LIKE 'Yedek Sonras_ Şirketi%%'",
                                  port=port, soket=soket)[1], "50")
        self.zincir_saglam("alig.denetim", port, soket, 3)
        self.zincir_saglam("alig.yonetim_denetim", port, soket, 2)
        # the restored cluster does not write to the source's archive
        self.assertEqual(self.sql("postgres", "SHOW archive_mode", port=port, soket=soket)[1], "off")
        # the source cluster still shows an empty table (the accident) at this point: the restore did not touch the source
        self.assertEqual(self.sql("postgres", "SELECT count(*) FROM alig.firma")[1], "0")
        self.sureler["geri_yukle_komutu"] = t1 - t0
        self.sureler["kurtarma_bitisi"] = t2 - t1
        self.sureler["al_dahil_toplam"] = self.sureler["yedek_al"] + (t2 - t0)
        self.assertLess(time.perf_counter() - self.baslangic, SURE_SINIRI)

    def test_bozulmus_yedek_dogrulamadan_gecmez_ve_geri_yuklenmez(self):
        kopya = self.kok / "bozuk" / self.yedek.name
        shutil.copytree(self.yedek, kopya)
        dosyalar = sorted((p for p in (kopya / "base").rglob("*") if p.is_file() and p.stat().st_size > 8192),
                          key=lambda p: -p.stat().st_size)
        self.assertTrue(dosyalar)
        hedef_dosya = dosyalar[0]
        ham = bytearray(hedef_dosya.read_bytes())
        ham[4000] ^= 0xFF
        hedef_dosya.write_bytes(bytes(ham))
        r = self.yedek_cmd("dogrula", "--yedek", str(kopya))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout + r.stderr, r"(?i)checksum|mismatch|differ")
        hedef = self.kok / "geri-bozuk"
        r = self.yedek_cmd("geri-yukle", "--yedek", str(kopya), "--hedef", str(hedef), "--evet")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(hedef.exists(), "bozuk yedekten hedef olusturuldu")
        # the original backup was not affected
        self.assertEqual(self.yedek_cmd("dogrula", "--yedek", str(self.yedek)).returncode, 0)

    def test_dolu_hedef_reddedilir_calisan_kume_dahil(self):
        dolu = self.kok / "dolu"
        dolu.mkdir()
        (dolu / "onemli.txt").write_text("silinmemeli")
        once = agac(dolu)
        for hedef in (dolu, self.veri):   # the second one is the running cluster's data directory
            canli = agac(hedef) if hedef == self.veri else None
            r = self.yedek_cmd("geri-yukle", "--yedek", str(self.yedek), "--hedef", str(hedef), "--evet")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("bos degil", r.stderr)
            if canli is not None:
                self.assertEqual({a[0] for a in agac(hedef)} - {a[0] for a in canli}, set())
        self.assertEqual(agac(dolu), once)
        self.assertEqual((dolu / "onemli.txt").read_text(), "silinmemeli")
        self.assertEqual(self.sql("postgres", "SELECT 1")[1], "1")   # the running cluster still responds
        # restoring into the backup's own directory is also rejected
        r = self.yedek_cmd("geri-yukle", "--yedek", str(self.yedek), "--hedef", str(self.yedek / "alt"), "--evet")
        self.assertEqual(r.returncode, 1)

    def test_kuru_calistirma_hicbir_sey_yazmaz(self):
        bos = self.kok / "bos-hedef"
        bos.mkdir()
        yok = self.kok / "olmayan-hedef"
        once = agac(self.yedek_kok), agac(self.arsiv)
        for hedef in (bos, yok):
            r = self.yedek_cmd("geri-yukle", "--yedek", str(self.yedek), "--hedef", str(hedef),
                               "--wal-arsivi", str(self.arsiv), "--hedef-zaman", self.zaman)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("KURU CALISTIRMA", r.stdout)
            self.assertIn("recovery_target_time", r.stdout)
        self.assertEqual(list(bos.iterdir()), [])
        self.assertFalse(yok.exists())
        self.assertEqual((agac(self.yedek_kok), agac(self.arsiv)), once)
        # eskileri-sil does not delete without --evet either
        r = self.yedek_cmd("eskileri-sil", "--kok", str(self.yedek_kok), "--sakla", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(agac(self.yedek_kok), once[0])

    def test_tar_bicimi_dogrulanir_ve_acilir(self):
        kok = self.kok / "yedek-tar"
        r = self.yedek_cmd("al", "--kok", str(kok), "--bicim", "tar")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        y = sorted(kok.iterdir())[-1]
        self.assertTrue((y / "base.tar").is_file() and (y / "pg_wal.tar").is_file())
        self.assertEqual(self.yedek_cmd("dogrula", "--yedek", str(y)).returncode, 0)
        hedef = self.kok / "geri-tar"
        r = self.yedek_cmd("geri-yukle", "--yedek", str(y), "--hedef", str(hedef), "--evet")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((hedef / "PG_VERSION").is_file())
        self.assertTrue(list((hedef / "pg_wal").glob("0*")))
        self.assertFalse((hedef / "recovery.signal").exists())   # without an archive: no PITR claim


if __name__ == "__main__":
    unittest.main()
