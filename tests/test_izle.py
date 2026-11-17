"""Read-only monitoring list (ALIG-OPS-001): deploy/izle.py, its systemd wiring and the scheduled-job owner table.

The checks only read; with no alert channel configured the output is only a log (no mail, no webhook, no command).
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT / "form"))
import izle  # noqa: E402
import server as form  # noqa: E402
from tarama import depo  # noqa: E402
from yonetim import depo as ydepo  # noqa: E402

SERVISLER = ROOT / "deploy" / "ansible" / "roles" / "servisler"
BICIM = "%Y-%m-%dT%H:%M:%SZ"
Disk = namedtuple("Disk", "total used free")
GB = 1 << 30


def z(dt):
    return dt.strftime(BICIM)


def simdi():
    return datetime.now(timezone.utc)


def durumlar(sonuclar):
    return {s.ad: s.durum for s in sonuclar}


class Taban(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.veri = self.tmp / "veri"
        self.yedek = self.tmp / "yedek"
        self.veri.mkdir()
        self.yedek.mkdir()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def ayar(self, **kw):
        return izle.Ayar(veri=str(self.veri), yedek=str(self.yedek), **kw)

    def kontrol(self, ad, ayar=None, simdi_=None):
        (k,) = [k for k in izle.KONTROLLER if k.ad == ad]
        return k.calistir(ayar or self.ayar(), simdi_ or simdi())

    def tarama(self):
        con = depo.baglan(str(self.veri / "tarama.sqlite"))
        return con

    def yonetim(self):
        return ydepo.baglan(str(self.veri / "yonetim.sqlite"))

    def form_db(self):
        con = sqlite3.connect(str(self.veri / "form.sqlite"))
        con.execute(form.SCHEMA)
        return con


class TabloTests(unittest.TestCase):
    def test_kontrol_listesi_beklenen_ogeleri_icerir(self):
        adlar = [k.ad for k in izle.KONTROLLER]
        self.assertEqual(len(adlar), len(set(adlar)))
        self.assertEqual(set(adlar), {"health", "disk", "outbox", "pending_requests", "audit_chain", "backup_age", "cert_expiry"})
        for k in izle.KONTROLLER:
            self.assertTrue(k.aciklama, k.ad)
            self.assertTrue(callable(k.calistir), k.ad)

    def test_cikis_kodu_yalniz_kritikte_1(self):
        S = izle.Sonuc
        self.assertEqual(izle.cikis_kodu([S("a", "OK", ""), S("b", "WARN", ""), S("c", "UNKNOWN", ""), S("d", "SKIP", "")]), 0)
        self.assertEqual(izle.cikis_kodu([S("a", "OK", ""), S("b", "CRIT", "")]), 1)

    def test_bozuk_kontrol_calismayi_durdurmaz(self):
        def patla(ayar, simdi_):
            raise RuntimeError("beklenmeyen")
        kal = [izle.Kontrol("bozuk", "x", patla), izle.Kontrol("iyi", "y", lambda a, s: izle.Sonuc("iyi", "OK", "tamam"))]
        sonuc = izle.calistir(izle.Ayar(veri="x", yedek="y"), kontroller=kal)
        self.assertEqual(durumlar(sonuc), {"bozuk": "UNKNOWN", "iyi": "OK"})
        self.assertIn("RuntimeError", sonuc[0].ayrinti)


class _Isleyici(BaseHTTPRequestHandler):
    yanitlar = {"/healthz": (200, b"ok"), "/api/tarama/saglik": (200, b"ok")}

    def do_GET(self):
        kod, govde = self.yanitlar.get(self.path, (404, b""))
        self.send_response(kod)
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def log_message(self, *a):
        pass


class SaglikTests(Taban):
    def sunucu(self, yanitlar):
        sinif = type("H", (_Isleyici,), {"yanitlar": yanitlar})
        s = ThreadingHTTPServer(("127.0.0.1", 0), sinif)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        self.addCleanup(s.server_close)
        self.addCleanup(s.shutdown)
        return "http://127.0.0.1:%d" % s.server_address[1]

    def test_iki_uc_nokta_ok_ise_ok(self):
        r = self.kontrol("health", self.ayar(taban=self.sunucu(dict(_Isleyici.yanitlar))))
        self.assertEqual(r.durum, "OK", r.ayrinti)

    def test_biri_500_ise_kritik(self):
        y = dict(_Isleyici.yanitlar)
        y["/api/tarama/saglik"] = (500, b"hata")
        r = self.kontrol("health", self.ayar(taban=self.sunucu(y)))
        self.assertEqual(r.durum, "CRIT")
        self.assertIn("/api/tarama/saglik", r.ayrinti)

    def test_govde_ok_degilse_kritik(self):
        y = dict(_Isleyici.yanitlar)
        y["/healthz"] = (200, b"degraded")
        self.assertEqual(self.kontrol("health", self.ayar(taban=self.sunucu(y))).durum, "CRIT")

    def test_baglanti_reddi_kritik(self):
        s = ThreadingHTTPServer(("127.0.0.1", 0), _Isleyici)
        port = s.server_address[1]
        s.server_close()
        r = self.kontrol("health", self.ayar(taban="http://127.0.0.1:%d" % port))
        self.assertEqual(r.durum, "CRIT")

    def test_taban_verilmediyse_atlanir(self):
        self.assertEqual(self.kontrol("health", self.ayar()).durum, "SKIP")


class DiskTests(Taban):
    def ayar_disk(self, bos):
        return self.ayar(disk_kullanim=lambda yol: Disk(100 * GB, 100 * GB - bos, bos))

    def test_esikler(self):
        self.assertEqual(self.kontrol("disk", self.ayar_disk(50 * GB)).durum, "OK")
        self.assertEqual(self.kontrol("disk", self.ayar_disk(10 * GB)).durum, "WARN")
        self.assertEqual(self.kontrol("disk", self.ayar_disk(3 * GB)).durum, "CRIT")

    def test_en_kotu_dizin_belirler(self):
        def kullanim(yol):
            return Disk(100 * GB, 0, 2 * GB) if yol == str(self.yedek) else Disk(100 * GB, 0, 90 * GB)
        r = self.kontrol("disk", self.ayar(disk_kullanim=kullanim))
        self.assertEqual(r.durum, "CRIT")
        self.assertIn(str(self.yedek), r.ayrinti)

    def test_okunamayan_dizin_bilinmiyor(self):
        def kullanim(yol):
            raise FileNotFoundError(yol)
        self.assertEqual(self.kontrol("disk", self.ayar(disk_kullanim=kullanim)).durum, "UNKNOWN")


class PostaKutusuTests(Taban):
    def test_bos_kutu_ok(self):
        self.tarama().close()
        self.assertEqual(self.kontrol("outbox").durum, "OK")

    def test_bekleyen_yeni_ok_eski_uyari(self):
        con = self.tarama()
        depo.posta_ekle(con, "a@example.com", "k", "m")
        con.close()
        self.assertEqual(self.kontrol("outbox").durum, "OK")
        self.assertEqual(self.kontrol("outbox", simdi_=simdi() + timedelta(hours=2)).durum, "WARN")

    def test_cok_bekleyen_uyari(self):
        con = self.tarama()
        for i in range(25):
            depo.posta_ekle(con, "a%d@example.com" % i, "k", "m")
        con.close()
        r = self.kontrol("outbox")
        self.assertEqual(r.durum, "WARN")
        self.assertIn("25", r.ayrinti)

    def test_basarisiz_mail_ayrintida_gorunur(self):
        con = self.tarama()
        depo.posta_ekle(con, "a@example.com", "k", "m")
        con.execute("UPDATE posta SET durum='basarisiz'")
        con.commit()
        con.close()
        r = self.kontrol("outbox")
        self.assertIn("failed 1", r.ayrinti)

    def test_veritabani_yoksa_bilinmiyor(self):
        self.assertEqual(self.kontrol("outbox").durum, "UNKNOWN")


class BekleyenTalepTests(Taban):
    def kur(self, yas_gun, kapali=False):
        f = self.form_db()
        f.execute("INSERT INTO contact(id, created_utc, name, company, email, db, message, ip_hash) VALUES(1,?,?,?,?,?,?,?)",
                  (z(simdi() - timedelta(days=yas_gun)), "A", "B", "a@example.com", "pg", "m", "h"))
        f.commit()
        f.close()
        y = self.yonetim()
        if kapali:
            ydepo.talep_durum_yaz(y, 1, "kapandi", "", "ali")
        y.close()
        self.tarama().close()

    def test_yeni_talep_ok_ayrintida_sayi(self):
        self.kur(0)
        r = self.kontrol("pending_requests")
        self.assertEqual(r.durum, "OK", r.ayrinti)
        self.assertIn("1", r.ayrinti)

    def test_eski_acik_talep_uyari(self):
        self.kur(5)
        self.assertEqual(self.kontrol("pending_requests").durum, "WARN")

    def test_kapali_talep_sayilmaz(self):
        self.kur(30, kapali=True)
        self.assertEqual(self.kontrol("pending_requests").durum, "OK")

    def test_acik_portal_talebi_sayilir(self):
        self.kur(0, kapali=True)
        t = self.tarama()
        t.execute("INSERT INTO portal_talep(firma_id, kullanici_id, tur, olusturma_utc, guncelleme_utc) VALUES(1,1,'destek',?,?)",
                  (z(simdi() - timedelta(days=10)), z(simdi() - timedelta(days=10))))
        t.commit()
        t.close()
        r = self.kontrol("pending_requests")
        self.assertEqual(r.durum, "WARN")
        self.assertIn("portal 1", r.ayrinti)

    def test_veritabani_yoksa_bilinmiyor(self):
        self.assertEqual(self.kontrol("pending_requests").durum, "UNKNOWN")


class DenetimZinciriTests(Taban):
    def doldur(self, anahtar=None):
        with mock.patch.dict(os.environ, {"ALIG_DENETIM_ANAHTARI": anahtar} if anahtar else {}, clear=False):
            if not anahtar:
                os.environ.pop("ALIG_DENETIM_ANAHTARI", None)
            t = self.tarama()
            for i in range(3):
                depo.denetim_ekle(t, "sistem", "olay %d" % i)
            t.close()
            y = self.yonetim()
            for i in range(2):
                with depo.islem(y) as c:
                    ydepo.denetim_ekle(c, "sistem", "olay %d" % i)
            y.close()

    def test_saglam_zincir_ok(self):
        self.doldur()
        r = self.kontrol("audit_chain", self.ayar(ortam={}))
        self.assertEqual(r.durum, "OK", r.ayrinti)
        self.assertIn("3", r.ayrinti)

    def test_bozulmus_kayit_kritik(self):
        self.doldur()
        c = sqlite3.connect(str(self.veri / "tarama.sqlite"))
        c.execute("UPDATE denetim SET olay='degistirildi' WHERE seq=2")
        c.commit()
        c.close()
        r = self.kontrol("audit_chain", self.ayar(ortam={}))
        self.assertEqual(r.durum, "CRIT")
        self.assertIn("#2", r.ayrinti)

    def test_anahtarli_zincir_anahtarla_ok_anahtarsiz_uyari(self):
        anahtar = "k" * 40
        self.doldur(anahtar)
        self.assertEqual(self.kontrol("audit_chain", self.ayar(ortam={"ALIG_DENETIM_ANAHTARI": anahtar})).durum, "OK")
        r = self.kontrol("audit_chain", self.ayar(ortam={}))
        self.assertEqual(r.durum, "WARN")
        self.assertIn("key", r.ayrinti)

    def test_yanlis_anahtar_kritik(self):
        self.doldur("k" * 40)
        r = self.kontrol("audit_chain", self.ayar(ortam={"ALIG_DENETIM_ANAHTARI": "z" * 40}))
        self.assertEqual(r.durum, "CRIT")

    def test_kisa_anahtar_bilinmiyor(self):
        self.doldur()
        self.assertEqual(self.kontrol("audit_chain", self.ayar(ortam={"ALIG_DENETIM_ANAHTARI": "kisa"})).durum, "UNKNOWN")

    def test_veritabani_yoksa_bilinmiyor(self):
        self.assertEqual(self.kontrol("audit_chain", self.ayar(ortam={})).durum, "UNKNOWN")


class YedekYasiTests(Taban):
    def yedek_yaz(self, ad, yas_saat):
        (self.veri / (ad + ".sqlite")).write_bytes(b"x")
        t = z(simdi() - timedelta(hours=yas_saat)).replace("-", "").replace(":", "")
        (self.yedek / ("%s-%s.sqlite" % (ad, t))).write_bytes(b"y")

    def test_taze_yedek_ok(self):
        for ad in ("form", "tarama", "yonetim"):
            self.yedek_yaz(ad, 2)
        self.assertEqual(self.kontrol("backup_age").durum, "OK")

    def test_esikler(self):
        for ad in ("form", "tarama", "yonetim"):
            self.yedek_yaz(ad, 2)
        self.yedek_yaz("tarama", 40)  # an old file does not matter: the newest counts
        self.assertEqual(self.kontrol("backup_age").durum, "OK")
        shutil.rmtree(self.yedek)
        self.yedek.mkdir()
        for ad, yas in (("form", 2), ("tarama", 40), ("yonetim", 2)):
            self.yedek_yaz(ad, yas)
        self.assertEqual(self.kontrol("backup_age").durum, "WARN")
        for f in self.yedek.glob("tarama-*"):
            f.unlink()
        self.yedek_yaz("tarama", 80)
        self.assertEqual(self.kontrol("backup_age").durum, "CRIT")

    def test_yedegi_olmayan_veritabani_kritik(self):
        self.yedek_yaz("form", 2)
        (self.veri / "tarama.sqlite").write_bytes(b"x")
        r = self.kontrol("backup_age")
        self.assertEqual(r.durum, "CRIT")
        self.assertIn("tarama", r.ayrinti)

    def test_veri_dizininde_olmayan_veritabani_beklenmez(self):
        self.yedek_yaz("form", 2)
        self.assertEqual(self.kontrol("backup_age").durum, "OK")

    def test_hic_veritabani_yoksa_bilinmiyor(self):
        self.assertEqual(self.kontrol("backup_age").durum, "UNKNOWN")

    def test_yedek_dizini_okunamiyorsa_bilinmiyor(self):
        (self.veri / "form.sqlite").write_bytes(b"x")
        shutil.rmtree(self.yedek)
        self.assertEqual(self.kontrol("backup_age").durum, "UNKNOWN")


class SertifikaTests(Taban):
    def ayar_sertifika(self, gun):
        bitis = simdi() + timedelta(days=gun)
        return self.ayar(sertifika_ad="alig.tech", sertifika_oku=lambda host, port, ad: bitis.timestamp())

    def test_esikler(self):
        self.assertEqual(self.kontrol("cert_expiry", self.ayar_sertifika(60)).durum, "OK")
        self.assertEqual(self.kontrol("cert_expiry", self.ayar_sertifika(15)).durum, "WARN")
        self.assertEqual(self.kontrol("cert_expiry", self.ayar_sertifika(5)).durum, "CRIT")
        self.assertEqual(self.kontrol("cert_expiry", self.ayar_sertifika(-1)).durum, "CRIT")

    def test_okuma_hatasi_kritik(self):
        def oku(host, port, ad):
            raise OSError("baglanti reddedildi")
        r = self.kontrol("cert_expiry", self.ayar(sertifika_ad="alig.tech", sertifika_oku=oku))
        self.assertEqual(r.durum, "CRIT")

    def test_ad_verilmediyse_atlanir(self):
        self.assertEqual(self.kontrol("cert_expiry").durum, "SKIP")

    def test_not_after_bicimi_cozulur(self):
        self.assertAlmostEqual(izle.not_after_saniye("Jan  5 09:34:43 2030 GMT"), 1893836083, delta=1)


class SaltOkunurTests(Taban):
    """Whole run: nothing is written, no alert channel."""

    def kur_hepsi(self):
        self.doldur_ham()

    def doldur_ham(self):
        t = self.tarama()
        depo.denetim_ekle(t, "sistem", "x")
        depo.posta_ekle(t, "a@example.com", "k", "m")
        t.close()
        y = self.yonetim()
        with depo.islem(y) as c:
            ydepo.denetim_ekle(c, "sistem", "x")
        y.close()
        f = self.form_db()
        f.commit()
        f.close()
        for ad in ("form", "tarama", "yonetim"):
            (self.yedek / ("%s-%s.sqlite" % (ad, z(simdi()).replace("-", "").replace(":", "")))).write_bytes(b"b")

    def anlik(self):
        d = {}
        for kok in (self.veri, self.yedek):
            for p in sorted(kok.rglob("*")):
                st = p.stat()
                d[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "")
        return d

    def test_calistirma_hicbir_dosyayi_degistirmez_ve_olusturmaz(self):
        self.doldur_ham()
        once = self.anlik()
        sonuc = izle.calistir(self.ayar(ortam={}))
        self.assertEqual(len(sonuc), len(izle.KONTROLLER))
        self.assertEqual(self.anlik(), once)

    def test_servis_veritabanini_acikken_de_okunur(self):
        """A live WAL database (side files present, a writer connected) is read with mode=ro and without changing the data file."""
        self.doldur_ham()
        t = self.tarama()
        t.execute("PRAGMA journal_mode=WAL")
        depo.denetim_ekle(t, "sistem", "canli")
        self.assertTrue((self.veri / "tarama.sqlite-wal").exists())
        try:
            sonuc = {s.ad: s for s in izle.calistir(self.ayar(ortam={}))}
        finally:
            t.close()
        self.assertEqual(sonuc["audit_chain"].durum, "OK", sonuc["audit_chain"].ayrinti)
        self.assertIn("2 records", sonuc["audit_chain"].ayrinti)  # the record written through the open connection is seen

    def test_kaynakta_yazma_sql_ve_kanal_yok(self):
        kaynak = (ROOT / "deploy" / "izle.py").read_text()
        self.assertNotRegex(kaynak, r"(?i)\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|VACUUM|REINDEX)\b\s+(INTO|TABLE|FROM|INDEX|\w+\s+SET)")
        self.assertNotIn("journal_mode", kaynak)
        self.assertNotIn(".baglan(", kaynak)  # depo.baglan applies migrations and switches to WAL (writes)
        self.assertIn("mode=ro", kaynak)
        for yasak in ("smtplib", "subprocess", "os.system", "webhook", "urllib.request", "sendmail"):
            self.assertNotIn(yasak, kaynak, yasak)

    def test_cikti_yalniz_log_satirlari(self):
        self.doldur_ham()
        cikti, hata = StringIO(), StringIO()
        with mock.patch("sys.stdout", cikti), mock.patch("sys.stderr", hata):
            kod = izle.main(["--veri", str(self.veri), "--yedek", str(self.yedek)])
        satirlar = cikti.getvalue().strip().splitlines()
        self.assertEqual(kod, 0, cikti.getvalue())
        self.assertEqual(hata.getvalue(), "")
        for s in satirlar[:-1]:
            self.assertRegex(s, r"^(OK|WARN|CRIT|UNKNOWN|SKIP) +[a-z_]+: ")
        self.assertRegex(satirlar[-1], r"^izle: \d+ checks")

    def test_json_cikti(self):
        self.doldur_ham()
        cikti = StringIO()
        with mock.patch("sys.stdout", cikti):
            izle.main(["--veri", str(self.veri), "--yedek", str(self.yedek), "--json"])
        belge = json.loads(cikti.getvalue())
        self.assertEqual({s["ad"] for s in belge["sonuclar"]}, {k.ad for k in izle.KONTROLLER})

    def test_kritik_varsa_cikis_1(self):
        cikti = StringIO()
        with mock.patch("sys.stdout", cikti):
            kod = izle.main(["--veri", str(self.veri), "--yedek", str(self.yedek), "--taban", "http://127.0.0.1:1"])
        self.assertEqual(kod, 1)
        self.assertIn("CRIT", cikti.getvalue())


class BirimTelleriTests(unittest.TestCase):
    """The existing alig-izleme unit is extended; no new service, no write access, the smoke test is kept."""

    def setUp(self):
        self.servis = (SERVISLER / "templates" / "alig-izleme.service.j2").read_text()

    def test_duman_testi_korunur_izle_ek_olarak_calisir(self):
        self.assertIn("deploy/duman_testi.py", self.servis)
        self.assertIn("deploy/izle.py", self.servis)
        self.assertIn("OnFailure=alig-uyari.service", self.servis)
        # ExecStopPost runs even when the smoke test failed, so a failing health check does not hide disk/backup findings
        self.assertRegex(self.servis, r"(?m)^ExecStopPost=/usr/bin/python3 .*deploy/izle\.py")

    def test_bakim_birimi_basarisizlikta_uyari_birimini_baslatir(self):
        bakim = (SERVISLER / "templates" / "alig-bakim.service.j2").read_text()
        self.assertRegex(bakim, r"(?m)^OnFailure=alig-uyari\.service$")
        self.assertEqual(bakim.count("OnFailure="), 1)
        self.assertEqual(self.servis.count("OnFailure="), 1)
        # OnFailure belongs to [Unit], before [Service], as in the monitoring unit
        self.assertLess(bakim.index("OnFailure="), bakim.index("[Service]"))
        self.assertIn("alig-uyari.service", (SERVISLER / "tasks" / "main.yml").read_text())
        # hardening and the write paths of the maintenance unit are untouched
        self.assertIn("ReadWritePaths={{ veri_dizini }} {{ yedek_dizini }}", bakim)

    def test_yazma_yetkisi_yok_sertlestirme_korunur(self):
        for ayar in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true", "PrivateTmp=true"):
            self.assertIn(ayar, self.servis)
        self.assertNotIn("ReadWritePaths", self.servis)
        self.assertIn("EnvironmentFile=/etc/alig/env", self.servis)  # for the audit key only

    def test_yeni_servis_ya_da_zamanlayici_yok(self):
        adlar = sorted(p.name for p in (SERVISLER / "templates").iterdir())
        self.assertEqual([a for a in adlar if "izle" in a], ["alig-izleme.service.j2", "alig-izleme.timer.j2"])
        self.assertEqual(sorted(a for a in adlar if a.endswith(".timer.j2")), ["alig-bakim.timer.j2", "alig-izleme.timer.j2"])
        gorevler = (SERVISLER / "tasks" / "main.yml").read_text()
        self.assertEqual(gorevler.count("alig-izleme.service"), 1)
        self.assertNotIn("alig-izle.", gorevler)

    def test_zamanlayici_degismedi(self):
        t = (SERVISLER / "templates" / "alig-izleme.timer.j2").read_text()
        self.assertIn("OnUnitActiveSec=5min", t)

    def test_uyari_birimi_kanal_uydurmaz(self):
        gorevler = (SERVISLER / "tasks" / "main.yml").read_text()
        self.assertIn("[doldurulacak: bildirim yontemi]", gorevler)
        self.assertIn("/usr/bin/logger", gorevler)


class IsSahipleriTablosuTests(unittest.TestCase):
    RUNBOOK = (ROOT / "docs" / "runbook.md").read_text()

    def satirlar(self):
        m = re.search(r"## Scheduled jobs and owners\n(.*?)(?=\n## )", self.RUNBOOK, re.S)
        self.assertIsNotNone(m, "section 'Scheduled jobs and owners' is missing from docs/runbook.md")
        govde = m.group(1)
        self.assertEqual(len(re.findall(r"(?m)^\| Job \|", govde)), 1, "there must be a single table")
        satirlar = [[h.strip() for h in s.strip().strip("|").split("|")] for s in govde.splitlines() if s.startswith("|")]
        return satirlar[0], satirlar[2:]

    def test_tablo_kolonlari(self):
        baslik, _ = self.satirlar()
        for kolon in ("Job", "Unit / trigger", "Code owner", "Failure shows as", "Responsible person"):
            self.assertIn(kolon, baslik)

    def test_her_zamanlayici_ve_isleyen_servis_tabloda(self):
        _, satirlar = self.satirlar()
        metin = "\n".join(" ".join(s) for s in satirlar)
        for p in (SERVISLER / "templates").glob("*.timer.j2"):
            self.assertIn(p.name[:-len(".j2")], metin)
        for ad in ("alig-posta.service", "alig-izleme.timer", "alig-bakim.timer", "certbot", "logrotate"):
            self.assertIn(ad, metin)
        for is_ in ("maintenance", "mail retry", "session cleanup"):
            self.assertIn(is_, metin.lower())

    def test_hicbir_hucre_bos_degil_ve_kisi_adi_uydurulmaz(self):
        baslik, satirlar = self.satirlar()
        self.assertGreaterEqual(len(satirlar), 6)
        kisi = baslik.index("Responsible person")
        for s in satirlar:
            self.assertEqual(len(s), len(baslik), s)
            for h in s:
                self.assertTrue(h, s)
            self.assertIn("[doldurulacak", s[kisi])

    def test_zamanlayici_izleme_bolumu_izle_py_anlatir(self):
        self.assertIn("deploy/izle.py", self.RUNBOOK)
        self.assertIn("ExecStopPost", self.RUNBOOK)


if __name__ == "__main__":
    unittest.main()
