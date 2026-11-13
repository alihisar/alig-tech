import os
import smtplib
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import depo, posta  # noqa: E402


class SahteSmtp:
    """smtplib.SMTP yerine: cagrilari kaydeder. starttls_yok=True ise sunucu STARTTLS sunmuyor gibi davranir."""
    kayitlar = []

    def __init__(self, sunucu, port, timeout=None, context=None, starttls_yok=False, gonderim_hatasi=None):
        self.olaylar = [("baglan", sunucu, port, timeout, context is not None)]
        self.starttls_yok, self.gonderim_hatasi = starttls_yok, gonderim_hatasi
        SahteSmtp.kayitlar.append(self)

    def ehlo(self):
        self.olaylar.append(("ehlo",))

    def starttls(self, context=None):
        if self.starttls_yok:
            raise smtplib.SMTPNotSupportedError("STARTTLS yok")
        self.olaylar.append(("starttls", context is not None))

    def login(self, k, p):
        self.olaylar.append(("login", k))

    def send_message(self, m):
        if self.gonderim_hatasi:
            raise self.gonderim_hatasi
        self.olaylar.append(("gonder", m["From"], m["To"], m["Subject"], m.get_content()))

    def quit(self):
        self.olaylar.append(("quit",))


def sahte(**ek):
    return lambda *a, **k: SahteSmtp(*a, **dict(k, **ek))


class GondericiTests(unittest.TestCase):
    def setUp(self):
        SahteSmtp.kayitlar = []

    def test_starttls_girisden_once_ve_ileti_basliklari(self):
        g = posta.SmtpGonderici("smtp.ornek.com", "tarama@alig.tech", 587, "kul", "par", smtp=sahte())
        g.gonder("ali@firma.com", "Konu", "Metin https://alig.tech/rapor/x/")
        o = SahteSmtp.kayitlar[0].olaylar
        adlar = [x[0] for x in o]
        self.assertLess(adlar.index("starttls"), adlar.index("login"))
        self.assertEqual(o[0][2:], (587, 20, False))
        gonder = next(x for x in o if x[0] == "gonder")
        self.assertIn("tarama@alig.tech", gonder[1])
        self.assertEqual(gonder[2:4], ("ali@firma.com", "Konu"))
        self.assertIn("https://alig.tech/rapor/x/", gonder[4])
        self.assertEqual(adlar[-1], "quit")

    def test_starttls_yoksa_parola_gonderilmez(self):
        g = posta.SmtpGonderici("smtp.ornek.com", "tarama@alig.tech", 587, "kul", "par", smtp=sahte(starttls_yok=True))
        with self.assertRaises(smtplib.SMTPNotSupportedError):
            g.gonder("ali@firma.com", "Konu", "Metin")
        self.assertNotIn("login", [x[0] for x in SahteSmtp.kayitlar[0].olaylar])

    def test_465_dogrudan_tls(self):
        g = posta.SmtpGonderici("smtp.ornek.com", "tarama@alig.tech", 465, smtp=None, smtp_ssl=sahte())
        g.gonder("ali@firma.com", "Konu", "Metin")
        o = SahteSmtp.kayitlar[0].olaylar
        self.assertTrue(o[0][4])  # TLS baglami verildi
        self.assertNotIn("starttls", [x[0] for x in o])

    def test_ayarlar(self):
        with self.assertRaises(posta.PostaAyarHatasi):
            posta.gonderici_kur({})
        with self.assertRaises(posta.PostaAyarHatasi):
            posta.gonderici_kur({"ALIG_SMTP_SUNUCU": "smtp.ornek.com", "ALIG_EPOSTA_GONDEREN": "yok"})
        with self.assertRaises(posta.PostaAyarHatasi):
            posta.gonderici_kur({"ALIG_SMTP_SUNUCU": "smtp.ornek.com", "ALIG_EPOSTA_GONDEREN": "a@b.c", "ALIG_SMTP_KULLANICI": "k"})
        with self.assertRaises(posta.PostaAyarHatasi):
            posta.gonderici_kur({"ALIG_SMTP_SUNUCU": "smtp.ornek.com", "ALIG_EPOSTA_GONDEREN": "a@b.c", "ALIG_SMTP_PORT": "x"})
        g = posta.gonderici_kur({"ALIG_SMTP_SUNUCU": "smtp.ornek.com", "ALIG_EPOSTA_GONDEREN": "a@b.c", "ALIG_SMTP_PORT": "2525"})
        self.assertEqual((g.sunucu, g.port), ("smtp.ornek.com", 2525))
        self.assertIsInstance(posta.gonderici_kur({"ALIG_POSTA_DIZINI": tempfile.mkdtemp()}), posta.DosyaGonderici)

    def test_dosya_gonderici_yalniz_sahibine_acik(self):
        d = Path(tempfile.mkdtemp())
        posta.DosyaGonderici(d).gonder("ali@firma.com", "Konu", "Metin")
        f = next(d.iterdir())
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertIn(b"Subject: Konu", f.read_bytes())


class KutuTests(unittest.TestCase):
    def setUp(self):
        self.con = depo.baglan(str(Path(tempfile.mkdtemp()) / "t.sqlite"))

    def test_gonderilen_iletinin_metni_silinir(self):
        depo.posta_ekle(self.con, "Ali@Firma.com", "Konu", "gizli baglanti")
        depo.posta_ekle(self.con, "b@firma.com", "Konu", "gizli baglanti 2")
        giden = []
        g = type("G", (), {"gonder": lambda self, a, k, m: giden.append((a, k, m))})()
        self.assertEqual(posta.isle(self.con, g), (2, 0))
        self.assertEqual([x[0] for x in giden], ["ali@firma.com", "b@firma.com"])
        self.assertEqual(self.con.execute("SELECT durum, metin FROM posta").fetchall(), [("gonderildi", ""), ("gonderildi", "")])
        self.assertEqual(posta.isle(self.con, g), (0, 0))  # ikinci kez gonderilmez

    def test_gecici_hatada_yeniden_denenir_sinirda_vazgecilir(self):
        depo.posta_ekle(self.con, "a@firma.com", "Konu", "gizli")
        g = type("G", (), {"gonder": lambda self, a, k, m: (_ for _ in ()).throw(OSError("ag yok"))})()
        for i in range(depo.POSTA_DENEME):
            self.assertEqual(posta.isle(self.con, g), (0, 1))
        durum, metin, deneme, hata = self.con.execute("SELECT durum, metin, deneme, son_hata FROM posta").fetchone()
        self.assertEqual((durum, metin, deneme, hata), ("basarisiz", "", depo.POSTA_DENEME, "OSError"))
        self.assertEqual(posta.isle(self.con, g), (0, 0))

    def test_posta_kaydi_saklama_suresinde_silinir_bekleyen_silinmez(self):
        depo.posta_ekle(self.con, "a@firma.com", "Konu", "gizli")
        depo.posta_ekle(self.con, "b@firma.com", "Konu", "gizli")
        depo.posta_sonuc(self.con, 1)
        self.con.execute("UPDATE posta SET olusturma_utc='2000-01-01T00:00:00Z'")
        self.con.commit()
        depo.suresi_dolanlari_sil(self.con)
        self.assertEqual([x[0] for x in self.con.execute("SELECT alici FROM posta")], ["b@firma.com"])

    def test_iletiler_iki_dilde(self):
        k, m = posta.dogrulama_iletisi("tr", "https://alig.tech/rapor/x/")
        self.assertIn("https://alig.tech/rapor/x/", m)
        self.assertIn("24 saat", m)
        k2, m2 = posta.dogrulama_iletisi("en", "https://alig.tech/rapor/x/")
        self.assertNotEqual(k, k2)
        self.assertIn("24 hours", m2)


class KomutTests(unittest.TestCase):
    def test_ayarsiz_baslamaz(self):
        eski = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith(("ALIG_SMTP", "ALIG_POSTA", "ALIG_EPOSTA"))}
        try:
            self.assertEqual(posta.main(["--db", str(Path(tempfile.mkdtemp()) / "t.sqlite")]), 2)
        finally:
            os.environ.update(eski)


if __name__ == "__main__":
    unittest.main()
