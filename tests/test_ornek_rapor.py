"""Ornek rapor sayfasi (yol haritasi madde 19): sentetik belgeden uretilir, acikca etiketlenir, eylem icermez.
Uretilen dosyalar (site/uretilen/) elle duzenlenmez: tarama/uret_ornek_rapor.py ile uretilir, bu testler depodakini denetler."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
from tarama import kurallar, puan, rapor, uret_ornek_rapor, yukleme  # noqa: E402
import build  # noqa: E402

ETIKET = {"tr": "Örnek rapor: sentetik test verisinden üretildi, gerçek bir müşteriye ait değildir",
          "en": "Sample report: generated from synthetic test data, not belonging to any real customer"}
SAYFALAR = {"tr": ("ornek-rapor/index.html", "ornek-rapor-teknik/index.html"),
            "en": ("en/ornek-rapor/index.html", "en/ornek-rapor-teknik/index.html")}


class UreticiTests(unittest.TestCase):
    def test_belge_yukleme_dogrulamasindan_gecer_ve_bulgu_uretir(self):
        b = uret_ornek_rapor.belge()
        yukleme.dogrula(b)
        self.assertGreaterEqual(len(kurallar.incele(b).bulgular), 3)

    def test_nesne_adlari_acikca_sahte(self):
        b = uret_ornek_rapor.belge()
        goruldu = 0
        for bulgu in kurallar.incele(b).bulgular:
            for ad in bulgu["kanit"].get("nesneler", []):
                goruldu += 1
                self.assertTrue(all(p.startswith("ornek") for p in ad.split(".")), ad)
        self.assertGreater(goruldu, 0)

    def test_deterministik(self):
        self.assertEqual(uret_ornek_rapor.uret(), uret_ornek_rapor.uret())

    def test_dort_dosya_iki_dil_iki_gorunum(self):
        d = uret_ornek_rapor.uret()
        self.assertEqual(sorted(d), ["ornek-rapor-teknik.en.html", "ornek-rapor-teknik.tr.html",
                                     "ornek-rapor-yonetici.en.html", "ornek-rapor-yonetici.tr.html"])

    def test_depodaki_uretilmis_dosyalar_guncel(self):
        for ad, metin in uret_ornek_rapor.uret().items():
            yol = uret_ornek_rapor.HEDEF / ad
            self.assertTrue(yol.is_file(), ad)
            self.assertEqual(yol.read_text(encoding="utf-8"), metin, "%s eski: python3 tarama/uret_ornek_rapor.py" % ad)
        self.assertEqual(uret_ornek_rapor.main(["--kontrol"]), 0)

    def test_eylem_ve_form_yok(self):
        for ad, metin in uret_ornek_rapor.uret().items():
            for yok in ("<form", "<button", "/sil", "Raporu şimdi sil", "Delete report now", "<script", " onclick", "style="):
                self.assertNotIn(yok, metin, "%s: %s" % (ad, yok))
            self.assertNotIn("otomatik silinir", metin)
            self.assertNotIn("automatically deleted", metin)

    def test_sekmeler_statik_sayfalara_baglanir(self):
        d = uret_ornek_rapor.uret()
        for dil, on in (("tr", "/"), ("en", "/en/")):
            yon, tek = d["ornek-rapor-yonetici.%s.html" % dil], d["ornek-rapor-teknik.%s.html" % dil]
            for metin in (yon, tek):
                self.assertIn('href="%sornek-rapor/"' % on, metin)
                self.assertIn('href="%sornek-rapor-teknik/"' % on, metin)
                self.assertNotIn("?gorunum=", metin)
                self.assertEqual(metin.count('aria-current="page"'), 1)
            self.assertIn('href="%sornek-rapor/" aria-current="page"' % on, yon)
            self.assertIn('href="%sornek-rapor-teknik/" aria-current="page"' % on, tek)

    def test_puan_sentetik_belgeden_cikar(self):
        b = uret_ornek_rapor.belge()
        genel = puan.hesapla(kurallar.incele(b)).genel
        self.assertIsNotNone(genel)
        self.assertIn("%d/100" % genel, uret_ornek_rapor.uret()["ornek-rapor-teknik.tr.html"])

    def test_standart_rapor_degismedi(self):
        b = uret_ornek_rapor.belge()
        r = {"belge": b, "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        icerik, _, _ = rapor.govde(r, "tr", "T" * 43)
        self.assertIn('href="?gorunum=yonetici"', icerik)
        self.assertIn("2026-12-01T00:00:00Z", icerik)
        self.assertIn("/rapor/%s/sil" % ("T" * 43), icerik)


class SayfaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cikti = {}
        for tema in build.THEMES:
            out = Path(tempfile.mkdtemp()) / "out"
            build.build(tema, out, "https://alig.tech", False)
            cls.cikti[tema] = out

    def test_her_temada_dort_sayfa_ve_etiket_en_ustte(self):
        for tema, out in self.cikti.items():
            for dil, yollar in SAYFALAR.items():
                for yol in yollar:
                    metin = (out / yol).read_text(encoding="utf-8")
                    self.assertIn(ETIKET[dil], metin, "%s %s" % (tema, yol))
                    self.assertLess(metin.index(ETIKET[dil]), metin.index("<h1>"), "%s %s: etiket basliktan once" % (tema, yol))
                    self.assertNotIn("{{", metin)

    def test_etiket_yazdirmada_gizlenmez(self):
        css = (ROOT / "site" / "base.css").read_text(encoding="utf-8")
        self.assertIn(".ornek-etiket", css)
        for tema in build.THEMES:
            tcss = (ROOT / "site" / "themes" / tema / "style.css").read_text(encoding="utf-8")
            for kural in re.findall(r"@media print\{.*", tcss):
                self.assertNotIn("ornek-etiket", kural)

    def test_ana_sayfa_ve_saglik_taramasi_ornek_rapora_baglanir(self):
        for tema, out in self.cikti.items():
            for dil, on in (("tr", ""), ("en", "en/")):
                ana = (out / on / "index.html").read_text(encoding="utf-8")
                self.assertIn('href="/%sornek-rapor/"' % on, ana, "%s %s ana sayfa" % (tema, dil))
                st = (out / on / "saglik-taramasi" / "index.html").read_text(encoding="utf-8")
                self.assertIn('href="/%sornek-rapor/"' % on, st, "%s %s saglik-taramasi" % (tema, dil))

    def test_sitemap_ve_dil_baglantilari(self):
        out = self.cikti["a"]
        sm = (out / "sitemap.xml").read_text(encoding="utf-8")
        for yol in ("/ornek-rapor/", "/en/ornek-rapor/", "/ornek-rapor-teknik/", "/en/ornek-rapor-teknik/"):
            self.assertIn("https://alig.tech" + yol, sm)
        self.assertIn('hreflang="en" href="https://alig.tech/en/ornek-rapor/"',
                      (out / "ornek-rapor" / "index.html").read_text(encoding="utf-8"))

    def test_sayfada_eylem_dugmesi_yok(self):
        for out in self.cikti.values():
            for yollar in SAYFALAR.values():
                for yol in yollar:
                    metin = (out / yol).read_text(encoding="utf-8")
                    self.assertNotIn("/sil", metin)
                    self.assertNotIn("<button", metin)


if __name__ == "__main__":
    unittest.main()
