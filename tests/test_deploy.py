import hashlib
import sqlite3
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import functools

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT))
import bakim  # noqa: E402
import duman_testi  # noqa: E402
import paketle  # noqa: E402
from tarama import depo  # noqa: E402


class PaketTests(unittest.TestCase):
    def test_tekrarlanabilir_ve_manifest(self):
        a, oa = paketle.paketle("9.9.9", "https://alig.tech", out_dir=tempfile.mkdtemp())
        b, ob = paketle.paketle("9.9.9", "https://alig.tech", out_dir=tempfile.mkdtemp())
        self.assertEqual(oa, ob)
        with tarfile.open(a) as tar:
            adlar = tar.getnames()
            manifest = tar.extractfile("MANIFEST.sha256").read().decode()
            for satir in manifest.splitlines():
                ozet, ad = satir.split("  ", 1)
                self.assertEqual(hashlib.sha256(tar.extractfile(ad).read()).hexdigest(), ozet, ad)
            self.assertEqual(tar.extractfile("site/surum.txt").read().decode().strip(), "9.9.9")
        for gerekli in ("site/index.html", "site/en/index.html", "form/server.py", "tarama/server.py", "VERSION"):
            self.assertIn(gerekli, adlar)
        self.assertFalse([x for x in adlar if "__pycache__" in x or x.endswith(".sqlite")])

    def test_surum_bicimi_ve_release_kapisi(self):
        with self.assertRaises(SystemExit):
            paketle.paketle("v1", "https://alig.tech", out_dir=tempfile.mkdtemp())
        with self.assertRaises(SystemExit):  # yer tutucular dururken --release durur
            paketle.paketle("1.0.0", "https://alig.tech", release=True, out_dir=tempfile.mkdtemp())


class BakimTests(unittest.TestCase):
    def test_yedek_butunluk_eski_silme_ve_rapor_temizligi(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        con = depo.baglan(str(veri / "tarama.sqlite"))
        depo.rapor_ekle(con, "eski", "postgresql", "tr", {"a": 1})
        con.execute("UPDATE rapor SET bitis_utc='2000-01-01T00:00:00Z'")
        con.commit()
        con.close()
        f = sqlite3.connect(veri / "form.sqlite")
        f.execute("CREATE TABLE contact(i int)")
        f.commit()
        f.close()
        for i in range(3):
            (yedek / f"form-2020010{i}T000000Z.sqlite").write_text("x")
        self.assertEqual(bakim.main(["--veri", str(veri), "--yedek", str(yedek), "--sakla", "2"]), 0)
        yedekler = sorted(p.name for p in yedek.iterdir())
        self.assertEqual(len([x for x in yedekler if x.startswith("form-")]), 2)  # 3 eski + 1 yeni, 2 kalir
        self.assertEqual(len([x for x in yedekler if x.startswith("tarama-")]), 1)
        yeni = next(p for p in yedek.iterdir() if p.name.startswith("tarama-"))
        self.assertEqual(oct(yeni.stat().st_mode)[-3:], "600")
        self.assertEqual(sqlite3.connect(veri / "tarama.sqlite").execute("SELECT count(*) FROM rapor").fetchone()[0], 0)
        self.assertEqual(sqlite3.connect(yeni).execute("PRAGMA integrity_check").fetchone()[0], "ok")


class DumanTests(unittest.TestCase):
    def test_paketlenmis_site_gecer_ve_eksik_basarisiz(self):
        paket, _ = paketle.paketle("1.2.3", "https://alig.tech", out_dir=tempfile.mkdtemp())
        kok = Path(tempfile.mkdtemp())
        with tarfile.open(paket) as tar:
            tar.extractall(kok, filter="data")

        class H(SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def end_headers(self):  # nginx'in verdigi basliklari taklit et
                for k, v in (("Content-Security-Policy", "default-src 'self'"), ("X-Content-Type-Options", "nosniff"),
                             ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY")):
                    self.send_header(k, v)
                super().end_headers()

            def do_GET(self):
                if self.path in ("/healthz", "/api/tarama/saglik"):
                    self.send_response(200)
                    self.send_header("Content-Length", "3")
                    self.end_headers()
                    self.wfile.write(b"ok\n")
                    return
                super().do_GET()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(kok / "site")))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        taban = "http://127.0.0.1:%d" % srv.server_port
        self.assertEqual(duman_testi.calistir(taban, surum="1.2.3"), [])
        self.assertTrue(duman_testi.calistir(taban, surum="9.9.9"))
        (kok / "site" / "demo" / "index.html").unlink()
        self.assertTrue(any("/demo/" in h for h in duman_testi.calistir(taban)))


if __name__ == "__main__":
    unittest.main()


class YapilandirmaTests(unittest.TestCase):
    """Sunucuya gitmeden yakalanabilecek yapilandirma hatalari."""
    SABLON = ROOT / "deploy" / "ansible" / "roles"

    def test_nginx_konumlari_ortak_basliklari_icerir(self):
        konum = (self.SABLON / "web" / "templates" / "alig-konumlar.conf.j2").read_text()
        self.assertEqual(konum.count("location "), konum.count("include snippets/alig-basliklar.conf"))
        https = (self.SABLON / "web" / "templates" / "alig-https.conf.j2").read_text()
        self.assertNotIn("http2 on", https)  # Ubuntu 24.04 nginx 1.24 tanimaz
        self.assertIn("proxy_set_header X-Real-IP $remote_addr", konum)
        self.assertIn("client_max_body_size 6m", konum)

    def test_hsts_her_konumda(self):
        self.assertIn("Strict-Transport-Security", (self.SABLON / "web" / "templates" / "alig-basliklar.conf.j2").read_text())

    def test_systemd_birimleri_sertlestirilmis(self):
        for ad in ("alig-form.service.j2", "alig-tarama.service.j2"):
            t = (self.SABLON / "servisler" / "templates" / ad).read_text()
            for ayar in ("NoNewPrivileges=true", "ProtectSystem=strict", "IPAddressDeny=any", "CapabilityBoundingSet=", "--host 127.0.0.1"):
                self.assertIn(ayar, t, ad)

    def test_gorev_adlarinda_iki_nokta_ust_uste_yok(self):
        import re
        for yol in (ROOT / "deploy" / "ansible").rglob("*.yml"):
            for s in yol.read_text().splitlines():
                m = re.match(r"^\s*-?\s*name:\s*(.*)$", s)
                if m and ": " in m.group(1) and not m.group(1).startswith(('"', "'")):
                    self.fail(f"{yol.name}: ad tirnaksiz ve ': ' iceriyor -> {s.strip()}")

    def test_sirlar_depoda_degil(self):
        for yol in (ROOT / "deploy").rglob("*"):
            if yol.is_file() and yol.suffix in (".yml", ".j2", ".ini", ".py"):
                self.assertNotRegex(yol.read_text(), r"BEGIN (RSA |OPENSSH )?PRIVATE KEY", yol.name)
        self.assertNotIn("inventory.ini", [p.name for p in (ROOT / "deploy" / "ansible").iterdir()])
