"""LLM report summary (tarama/ozet_llm.py, item 23): off by default, cannot produce evidence, cannot change the score.
There is no real provider; only the fake (deterministic) provider is tested. No network call is made."""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import kurallar, ozet_llm, puan, rapor  # noqa: E402
import test_rapor_gorunum as trg  # noqa: E402

AC = {"ALIG_LLM_OZET": "1"}


class Sabit(ozet_llm.Saglayici):
    def __init__(self, metin=None, hata=None):
        self.metin, self.hata, self.girdi = metin, hata, None

    def ozet(self, girdi, dil):
        self.girdi = girdi
        if self.hata:
            raise self.hata
        return self.metin


def bulgular(**kw):
    return kurallar.incele(trg.belge(**kw)).bulgular


class Temel(unittest.TestCase):
    def setUp(self):
        ozet_llm.temizle()
        self.olaylar = []
        self.addCleanup(ozet_llm.temizle)

    def olay(self, ad, **alan):
        self.olaylar.append((ad, alan))


class EtkinlestirmeTests(Temel):
    def test_kapali_varsayilan(self):
        ozet_llm.kaydet(Sabit("x"))
        self.assertFalse(ozet_llm.etkin({}))
        self.assertIsNone(ozet_llm.ozet_uret(bulgular(yuksek=True), "tr", ortam={}, olay=self.olay))

    def test_yalniz_ortam_degiskeni_yetmez_saglayici_gerekir(self):
        self.assertFalse(ozet_llm.etkin(AC))
        self.assertIsNone(ozet_llm.ozet_uret(bulgular(yuksek=True), "tr", ortam=AC, olay=self.olay))

    def test_yalniz_saglayici_yetmez_degisken_gerekir(self):
        ozet_llm.kaydet(Sabit("x"))
        for deger in ("", "0", "evet", "true"):
            self.assertFalse(ozet_llm.etkin({"ALIG_LLM_OZET": deger}))

    def test_ikisi_varsa_acik(self):
        b = bulgular(yuksek=True)
        kimlik = b[0]["kural"]
        ozet_llm.kaydet(Sabit("%s icin otovakum incelenmeli." % kimlik))
        self.assertEqual(ozet_llm.ozet_uret(b, "tr", ortam=AC, olay=self.olay), "%s icin otovakum incelenmeli." % kimlik)

    def test_gercek_saglayici_modulde_yok(self):
        kaynak = (ROOT / "tarama" / "ozet_llm.py").read_text(encoding="utf-8")
        for yasak in ("urllib", "http.client", "socket", "requests", "ssl"):
            self.assertNotIn("import " + yasak, kaynak)

    def test_canli_sablonlar_degiskeni_acmaz(self):
        for yol in (ROOT / "deploy").rglob("*"):
            if yol.is_file():
                for satir in yol.read_text(encoding="utf-8", errors="replace").splitlines():
                    if "ALIG_LLM_OZET" in satir:
                        self.assertNotRegex(satir, r"ALIG_LLM_OZET\s*[=:]\s*[\"']?1")


class GirdiTests(Temel):
    def test_allowlist_tek_yerde_ve_acik(self):
        self.assertEqual(ozet_llm.GIRDI_ALANLARI, ("kural", "durum", "onem", "baslik"))

    def test_saglayiciya_yalniz_allowlist_alanlari_gider(self):
        s = Sabit("x")
        ozet_llm.kaydet(s)
        b = bulgular(yuksek=True, orta=True)
        ozet_llm.ozet_uret(b, "tr", ortam=AC, olay=self.olay)
        self.assertEqual(len(s.girdi), len(b))
        for oge in s.girdi:
            self.assertEqual(set(oge), set(ozet_llm.GIRDI_ALANLARI))

    def test_kanit_kaynak_oneri_ve_puan_gitmez(self):
        s = Sabit("x")
        ozet_llm.kaydet(s)
        ozet_llm.ozet_uret(bulgular(yuksek=True), "tr", ortam=AC, olay=self.olay)
        gidenler = repr(s.girdi)
        for yasak in ("kanit", "kaynak", "oneri", "geri_alma"):
            self.assertNotIn("'%s'" % yasak, gidenler)
        self.assertNotRegex(gidenler, r"\d+/100")

    def test_yalniz_bulgular_gider_gecen_denetim_gitmez(self):
        s = Sabit("x")
        ozet_llm.kaydet(s)
        ozet_llm.ozet_uret(bulgular(), "tr", ortam=AC, olay=self.olay)
        self.assertEqual(s.girdi, [])

    def test_maskeleme_tanimlayicilari_siler(self):
        m = ozet_llm.maskele
        self.assertNotIn("10.1.2.3", m("sunucu 10.1.2.3 yavas"))
        self.assertNotIn("a@b.com", m("yazan a@b.com"))
        self.assertNotIn("db01.sirket.local", m("host db01.sirket.local kapali"))
        self.assertNotIn("musteri_tablosu", m('tablo "musteri_tablosu" sismis'))
        self.assertNotIn("SELECT", m("sorgu: SELECT * FROM t WHERE a = 1"))
        self.assertNotIn("2001:db8::1", m("adres 2001:db8::1 acik"))

    def test_baslik_maskelenerek_gider(self):
        b = [{"kural": "PG-X-001", "durum": "FAIL", "onem": "yuksek", "kontrol": "k",
              "baslik": {"tr": "Sunucu 10.9.8.7 ve ali@x.com", "en": "e"}, "kanit": [{"ad": "gizli_tablo"}]}]
        s = Sabit("x")
        ozet_llm.kaydet(s)
        ozet_llm.ozet_uret(b, "tr", ortam=AC, olay=self.olay)
        self.assertNotIn("10.9.8.7", repr(s.girdi))
        self.assertNotIn("ali@x.com", repr(s.girdi))
        self.assertNotIn("gizli_tablo", repr(s.girdi))


class DogrulayiciTests(Temel):
    def setUp(self):
        super().setUp()
        self.b = bulgular(yuksek=True)
        self.kid = self.b[0]["kural"]
        self.izinli = {b["kural"] for b in self.b}

    def dene(self, metin):
        ozet_llm.temizle()
        ozet_llm.kaydet(Sabit(metin))
        self.olaylar.clear()
        return ozet_llm.ozet_uret(self.b, "tr", ortam=AC, olay=self.olay)

    def test_girdide_gecen_kimlik_kabul(self):
        self.assertIsNotNone(self.dene("%s once ele alinmali." % self.kid))

    def test_uydurma_kural_kimligi_reddedilir(self):
        self.assertIsNone(self.dene("%s ve PG-UYDURMA-999 sorunlu." % self.kid))
        self.assertEqual(self.olaylar[0][0], "ozet_reddedildi")

    def test_girdide_olmayan_gercek_kimlik_de_reddedilir(self):
        digerleri = [k for k in ("PG-MAINT-001", "PG-SEC-001", "PG-CONF-001") if k not in self.izinli]
        self.assertIsNone(self.dene("%s ve %s." % (self.kid, digerleri[0])))

    def test_puan_ve_yuzde_reddedilir(self):
        for m in ("Puan 85/100.", "Kapsam %90.", "Skor 42 olarak olculdu.", "Yuzde 90 kapsandi."):
            self.assertIsNone(self.dene(m), m)

    def test_gecti_iddiasi_reddedilir(self):
        for m in ("Tum denetimler PASS.", "Denetimler gecti.", "Denetim geçti.", "All checks passed.", "Check is Pass."):
            self.assertIsNone(self.dene(m), m)

    def test_uzunluk_siniri(self):
        self.assertIsNone(self.dene("a " * (ozet_llm.AZAMI_UZUNLUK)))

    def test_bos_ya_da_metin_olmayan_reddedilir(self):
        for m in ("", "   ", None, 5, b"x", ["a"]):
            self.assertIsNone(self.dene(m), repr(m))

    def test_kontrol_karakteri_reddedilir(self):
        self.assertIsNone(self.dene("merhaba\x00dunya"))

    def test_dogrulayici_dogrudan(self):
        self.assertTrue(ozet_llm.dogrula("%s incelenmeli" % self.kid, self.izinli)[0])
        self.assertFalse(ozet_llm.dogrula("PG-AAA-001 incelenmeli", self.izinli)[0])

    def test_red_olayi_icerik_yazmaz(self):
        gizli = "GIZLI-ICERIK PG-UYDURMA-999 ali@x.com"
        self.assertIsNone(self.dene(gizli))
        self.assertEqual(len(self.olaylar), 1)
        self.assertNotIn("GIZLI", repr(self.olaylar))
        self.assertNotIn("UYDURMA", repr(self.olaylar))
        self.assertNotIn("ali@x.com", repr(self.olaylar))

    def test_html_kacisi_raporda(self):
        r = {"belge": trg.belge(yuksek=True), "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        ozet_llm.kaydet(Sabit("%s <script>alert</script> & <b>x</b>" % self.kid))
        html = rapor.govde(r, "tr", "t", gorunum="yonetici", ozet_ortam=AC)[0]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)


class HataTests(Temel):
    def test_saglayici_istisnasi_yutulur_ve_olay_yazilir(self):
        ozet_llm.kaydet(Sabit(hata=RuntimeError("GIZLI ayrinti")))
        self.assertIsNone(ozet_llm.ozet_uret(bulgular(yuksek=True), "tr", ortam=AC, olay=self.olay))
        self.assertEqual(self.olaylar[0][0], "ozet_hata")
        self.assertNotIn("GIZLI", repr(self.olaylar))
        self.assertIn("RuntimeError", repr(self.olaylar))

    def test_olay_yazici_bozuksa_yine_calisir(self):
        ozet_llm.kaydet(Sabit(hata=RuntimeError("x")))

        def kotu(ad, **a):
            raise OSError("disk")
        self.assertIsNone(ozet_llm.ozet_uret(bulgular(yuksek=True), "tr", ortam=AC, olay=kotu))

    def test_varsayilan_olay_gunluge_yazar(self):
        ozet_llm.kaydet(Sabit(hata=ValueError("GIZLI")))
        with self.assertLogs("alig.ozet_llm", level="WARNING") as g:
            ozet_llm.ozet_uret(bulgular(yuksek=True), "tr", ortam=AC)
        self.assertIn("ozet_hata", g.output[0])
        self.assertNotIn("GIZLI", g.output[0])


KUTU = re.compile(r"<aside class=\"llm-ozet\">.*?</aside>\n", re.S)


class RaporTests(Temel):
    def sayfa(self, b, gorunum="yonetici", dil="tr", ortam=None):
        r = {"belge": b, "bitis_utc": "2026-12-01T00:00:00Z", "dil": dil}
        return rapor.govde(r, dil, "t", gorunum=gorunum, ozet_ortam=ortam)[0]

    def test_kapaliyken_cikti_birebir_ayni(self):
        b = trg.belge(yuksek=True, orta=True)
        onceki = trg.sayfa(b, "yonetici")
        ozet_llm.kaydet(Sabit("x"))   # provider exists, variable does not
        self.assertEqual(trg.sayfa(b, "yonetici"), onceki)
        self.assertNotIn("llm-ozet", onceki)

    def test_saglayici_istisna_atinca_rapor_calisir(self):
        b = trg.belge(yuksek=True)
        kapali = self.sayfa(b)
        ozet_llm.kaydet(Sabit(hata=RuntimeError("x")))
        self.assertEqual(self.sayfa(b, ortam=AC), kapali)

    def test_acikken_ayri_kutuda_etiketle_gosterilir(self):
        b = trg.belge(yuksek=True)
        kid = bulgular(yuksek=True)[0]["kural"]
        ozet_llm.kaydet(Sabit("%s once ele alinmali." % kid))
        for dil, etiket in (("tr", "Dil modeli özeti — kanıt değildir; bulgular ve puan kural çıktısıdır"),
                            ("en", "Language model summary — not evidence; findings and score come from the rules")):
            html = self.sayfa(b, dil=dil, ortam=AC)
            kutu = KUTU.search(html)
            self.assertIsNotNone(kutu, dil)
            self.assertIn(etiket, kutu.group(0))
            self.assertIn("once ele alinmali", kutu.group(0))

    def test_puan_ve_bulgu_html_ozet_acik_kapali_ayni(self):
        for b in (trg.belge(yuksek=True, orta=True), trg.belge(kritik=True), trg.belge()):
            kid = [x["kural"] for x in kurallar.incele(b).bulgular]
            ozet_llm.temizle()
            kapali = self.sayfa(b)
            ozet_llm.kaydet(Sabit("%s ele alinmali." % kid[0] if kid else "Bulgu yok."))
            acik = self.sayfa(b, ortam=AC)
            self.assertEqual(KUTU.sub("", acik), kapali)
            if kid:
                self.assertNotEqual(acik, kapali)

    def test_ozet_puani_degistiremez(self):
        b = trg.belge(yuksek=True)
        once = puan.hesapla(kurallar.incele(b)).genel
        ozet_llm.kaydet(Sabit("Puan 100/100"))   # rejected
        html = self.sayfa(b, ortam=AC)
        self.assertNotIn("llm-ozet", html)
        self.assertIn("%d/100" % once, html)
        self.assertEqual(puan.hesapla(kurallar.incele(b)).genel, once)

    def test_teknik_gorunumde_ozet_yok(self):
        ozet_llm.kaydet(Sabit("Bulgu yok."))
        self.assertNotIn("llm-ozet", self.sayfa(trg.belge(yuksek=True), gorunum="teknik", ortam=AC))

    def test_ortam_verilmezse_islem_ortami_okunur_ve_kapali(self):
        ozet_llm.kaydet(Sabit("Bulgu yok."))
        r = {"belge": trg.belge(yuksek=True), "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        eski = os.environ.pop("ALIG_LLM_OZET", None)
        try:
            self.assertNotIn("llm-ozet", rapor.govde(r, "tr", "t", gorunum="yonetici")[0])
        finally:
            if eski is not None:
                os.environ["ALIG_LLM_OZET"] = eski


class SahteSaglayiciTests(Temel):
    def test_sahte_deterministik_ve_dogrulayiciyi_gecer(self):
        b = bulgular(yuksek=True, orta=True)
        ozet_llm.kaydet(ozet_llm.SahteSaglayici())
        a = ozet_llm.ozet_uret(b, "tr", ortam=AC, olay=self.olay)
        c = ozet_llm.ozet_uret(b, "tr", ortam=AC, olay=self.olay)
        self.assertEqual(a, c)
        self.assertIsNotNone(a)
        self.assertEqual(self.olaylar, [])


if __name__ == "__main__":
    unittest.main()
