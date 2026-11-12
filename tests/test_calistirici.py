"""Kip B ayri calistirici: yerel soket uzerinden is alir, sonucu dogrulanmis JSON olarak doner."""
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import baglanti, calistirici, hedef, server as tserver  # noqa: E402
import test_tarama  # noqa: E402

temiz_belge = test_tarama.temiz_belge
del test_tarama
KANIT = "ab" * 16


class Temel(unittest.TestCase):
    def baslat(self, tara=None, **k):
        self.d = Path(tempfile.mkdtemp())
        self.soket = str(self.d / "c.sock")
        self.cagrilar = []

        def sahte(h, **arg):
            self.cagrilar.append((h, arg))
            return temiz_belge()
        self.srv = calistirici.Sunucu(self.soket, tara=tara or sahte, **k)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def tara(self, h=None, **k):
        arg = dict(veritabani="postgres", kullanici="alig_hc", parola="gizli-parola", kanit=KANIT)
        arg.update(k)
        return calistirici.uzaktan_tara(self.soket, h or hedef.Hedef("db.ornek.com", "93.184.216.34", 5432), **arg)

    def kod(self, h=None, **k):
        try:
            self.tara(h, **k)
        except baglanti.BaglantiHatasi as e:
            return e.kod
        return None

    def ham(self, veri):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(self.soket)
        s.sendall(veri)
        try:
            bas = s.recv(4)
            n = struct.unpack(">I", bas)[0] if len(bas) == 4 else 0
            govde = b""
            while len(govde) < n:
                p = s.recv(n - len(govde))
                if not p:
                    break
                govde += p
            return json.loads(govde) if govde else None
        finally:
            s.close()


class CalistiriciTests(Temel):
    def test_is_calisir_ve_belge_doner(self):
        self.baslat()
        belge = self.tara(maskele=True)
        self.assertEqual(belge["motor"], "postgresql")
        h, arg = self.cagrilar[0]
        self.assertEqual((h.ad, h.ip, h.port), ("db.ornek.com", "93.184.216.34", 5432))
        self.assertEqual(arg["parola"], "gizli-parola")
        self.assertEqual(arg["sslmode"], "require")
        self.assertTrue(arg["maskele"])

    def test_soket_yalniz_sahip_ve_gruba_acik(self):
        self.baslat()
        self.assertEqual(os.stat(self.soket).st_mode & 0o777, 0o660)

    def test_calistirici_hedefi_kendisi_de_denetler(self):
        self.baslat()
        for ad, ip, port in (("db.ornek.com", "10.0.0.5", 5432), ("db.ornek.com", "127.0.0.1", 5432), ("db.ornek.com", "169.254.169.254", 5432),
                             ("db.ornek.com", "::1", 5432), ("db.ornek.com", "93.184.216.34", 22), ("localhost", "93.184.216.34", 5432),
                             ("db.ornek.com", "ornek", 5432), ("10.0.0.5", "93.184.216.34", 5432)):
            self.assertEqual(self.kod(hedef.Hedef(ad, ip, port)), "hedef", (ad, ip, port))
        self.assertEqual(self.cagrilar, [])

    def test_kendi_aglarimiz(self):
        self.baslat(yasak_aglar=("93.184.216.0/24",))
        self.assertEqual(self.kod(), "hedef")

    def test_gecersiz_alanlar_reddedilir(self):
        self.baslat()
        self.assertEqual(self.kod(kanit="xyz"), "bicim")
        self.assertEqual(self.kod(veritabani="a b"), "bicim")
        self.assertEqual(self.kod(kullanici="a;b"), "bicim")
        self.assertEqual(self.kod(parola=""), "bicim")
        self.assertEqual(self.cagrilar, [])

    def test_tarama_hatasi_kod_olarak_doner(self):
        def patlar(h, **k):
            raise baglanti.BaglantiHatasi("kanit")
        self.baslat(tara=patlar)
        self.assertEqual(self.kod(), "kanit")

    def test_beklenmeyen_hata_ayrinti_sizdirmaz(self):
        def patlar(h, **k):
            raise RuntimeError("gizli ic ayrinti /var/lib/alig")
        self.baslat(tara=patlar)
        yanit = self.ham(calistirici.paketle({"ad": "db.ornek.com", "ip": "93.184.216.34", "port": 5432, "veritabani": "postgres",
                                               "kullanici": "alig_hc", "parola": "p", "kanit": KANIT, "maskele": False}))
        self.assertEqual(yanit, {"hata": "baglanti"})

    def test_bozuk_ve_dev_istekler(self):
        self.baslat()
        self.assertEqual(self.ham(struct.pack(">I", 5) + b"{bozu"), {"hata": "bicim"})
        self.assertEqual(self.ham(struct.pack(">I", 10 ** 7)), {"hata": "bicim"})
        self.assertEqual(self.ham(calistirici.paketle([1, 2])), {"hata": "bicim"})
        self.assertEqual(self.ham(calistirici.paketle({"ad": "x"})), {"hata": "bicim"})
        self.assertIsNotNone(self.tara())   # sunucu ayakta

    def test_es_zamanli_sinir(self):
        bekle, girdi = threading.Event(), threading.Event()

        def yavas(h, **k):
            girdi.set()
            bekle.wait(5)
            return temiz_belge()
        self.baslat(tara=yavas, es_zamanli=1)
        t = threading.Thread(target=self.tara)
        t.start()
        self.assertTrue(girdi.wait(5))
        self.assertEqual(self.kod(), "mesgul")
        bekle.set()
        t.join(5)

    def test_izinsiz_kullanici_reddedilir(self):
        self.baslat(izinli_uidler=(os.getuid() + 12345,))
        self.assertEqual(self.kod(), "calistirici")
        self.assertEqual(self.cagrilar, [])

    def test_calistirici_kotu_belge_donerse_istemci_reddeder(self):
        def kotu(h, **k):
            b = temiz_belge()
            b["kontroller"]["uydurma"] = {"durum": "ok", "satirlar": []}
            return b
        self.baslat(tara=kotu)
        self.assertEqual(self.kod(), "bicim")

    def test_soket_yoksa(self):
        self.d = Path(tempfile.mkdtemp())
        self.soket = str(self.d / "yok.sock")
        self.assertEqual(self.kod(), "calistirici")

    def test_parola_yanitta_ve_gunlukte_yok(self):
        import io
        import contextlib
        tampon = io.StringIO()
        self.baslat()
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            belge = self.tara()
        self.assertNotIn("gizli-parola", json.dumps(belge) + tampon.getvalue())


class BirimTests(unittest.TestCase):
    SABLON = ROOT / "deploy" / "ansible" / "roles" / "servisler"

    def test_calistirici_birimi_sertlestirilmis_ve_ic_aga_kapali(self):
        t = (self.SABLON / "templates" / "alig-calistirici.service.j2").read_text(encoding="utf-8")
        for ayar in ("NoNewPrivileges=true", "ProtectSystem=strict", "CapabilityBoundingSet=", "PrivateTmp=true", "ProtectHome=true",
                     "User={{ calistirici_kullanici }}", "RuntimeDirectory=alig-calistirici"):
            self.assertIn(ayar, t)
        deny = [s for s in t.splitlines() if s.startswith("IPAddressDeny=")][0]
        for ag in ("localhost", "link-local", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7"):
            self.assertIn(ag, deny)
        self.assertNotIn("IPAddressAllow", t)
        self.assertNotIn("EnvironmentFile", t)   # servis sirlari calistiriciya verilmez
        self.assertNotIn("ReadWritePaths", t)    # veri dizinine erisemez
        self.assertIn("InaccessiblePaths={{ veri_dizini }} {{ yedek_dizini }} /etc/alig", t)

    def test_varsayilan_olarak_kurulmaz_ve_web_birimi_ic_aga_kapali_kalir(self):
        degisken = (ROOT / "deploy" / "ansible" / "group_vars" / "all.yml").read_text(encoding="utf-8")
        self.assertIn("dogrudan_baglanti: false", degisken)
        gorevler = (self.SABLON / "tasks" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("when: dogrudan_baglanti", gorevler)
        web = (self.SABLON / "templates" / "alig-tarama.service.j2").read_text(encoding="utf-8")
        self.assertIn("IPAddressDeny=any", web)
        self.assertIn("{% if dogrudan_baglanti %}", web)


class SunucuBaglantisiTests(unittest.TestCase):
    def test_uretimde_soket_olmadan_dogrudan_acilmaz(self):
        self.assertFalse(tserver.dogrudan_ayarla({"ALIG_DOGRUDAN": "1"}, type("H", (tserver.H,), {})))
        H = type("H", (tserver.H,), {})
        self.assertTrue(tserver.dogrudan_ayarla({"ALIG_DOGRUDAN": "1", "ALIG_CALISTIRICI_SOKETI": "/run/x.sock", "ALIG_YASAK_AGLAR": "203.0.113.0/24, 2001:db8::/32"}, H))
        self.assertTrue(H.dogrudan)
        self.assertEqual(H.calistirici_soketi, "/run/x.sock")
        self.assertEqual(H.yasak_aglar, ("203.0.113.0/24", "2001:db8::/32"))
        self.assertFalse(tserver.dogrudan_ayarla({}, type("H", (tserver.H,), {})))


if __name__ == "__main__":
    unittest.main()
