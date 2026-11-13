"""Rapor gorunumleri (tarama/rapor.py): yonetici ozeti ve teknik rapor, kanit ile yorum ayri, yazdirma duzeni.
Ayni belgeden ayni cikti: dil modeli yok, ozet yalniz kural ciktisindan uretilir."""
import copy
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import gecmis, kurallar, puan, rapor  # noqa: E402
import test_tarama  # noqa: E402


def belge(**duzeltme):
    b = test_tarama.temiz_belge()
    k = b["kontroller"]
    if duzeltme.get("yuksek"):
        k["pg_autovacuum"]["satirlar"][0]["setting"] = "off"
    if duzeltme.get("orta"):
        k["pg_md5_roller"]["satirlar"] = [{"sayi": 3}]
    if duzeltme.get("kritik"):
        k["pg_xid_yasi"]["satirlar"][0]["yas"] = 2_000_000_000
    if duzeltme.get("kanitsiz"):
        k["pg_log_ayarlari"] = {"durum": "hata", "neden": "yetki"}
    return b


def sayfa(b, gorunum, dil="tr", onceki=None):
    r = {"belge": b, "bitis_utc": "2026-12-01T00:00:00Z", "dil": dil}
    return rapor.sayfa(r, dil, "t", onceki=None if onceki is None else {"belge": onceki}, gorunum=gorunum)


class SecimTests(unittest.TestCase):
    def test_varsayilan_teknik_gecersiz_deger_teknige_duser(self):
        b = belge(yuksek=True)
        r = {"belge": b, "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        varsayilan = rapor.sayfa(r, "tr", "t")
        self.assertEqual(varsayilan, sayfa(b, "teknik"))
        for kotu in ("", "x", None, "YONETICI", "yonetici ", 5, ["yonetici"]):
            self.assertEqual(sayfa(b, kotu), varsayilan, repr(kotu))
        self.assertNotEqual(sayfa(b, "yonetici"), varsayilan)

    def test_gorunum_secenekleri_tek_yerde(self):
        self.assertEqual(rapor.GORUNUMLER, ("yonetici", "teknik"))
        self.assertEqual(rapor.gorunum_sec("yonetici"), "yonetici")
        self.assertEqual(rapor.gorunum_sec("teknik"), "teknik")
        self.assertEqual(rapor.gorunum_sec("baska"), "teknik")

    def test_iki_gorunum_birbirine_baglanir_gecerli_olan_isaretlidir(self):
        for dil, ad in (("tr", ("Yönetici özeti", "Teknik rapor")), ("en", ("Executive summary", "Technical report"))):
            for g in rapor.GORUNUMLER:
                h = sayfa(belge(), g, dil)
                self.assertIn('href="?gorunum=yonetici"', h)
                self.assertIn('href="?gorunum=teknik"', h)
                self.assertIn(ad[0], h)
                self.assertIn(ad[1], h)
                self.assertEqual(h.count('aria-current="page"'), 1)
                self.assertRegex(h, r'<a [^>]*href="\?gorunum=%s"[^>]*aria-current="page"|<a [^>]*aria-current="page"[^>]*href="\?gorunum=%s"' % (g, g))


class YoneticiOzetiTests(unittest.TestCase):
    def test_bolumler_sirayla_ve_teknik_icerik_yok(self):
        h = sayfa(belge(yuksek=True, orta=True), "yonetici")
        sira = ["Genel durum", "En önemli riskler", "Yapılması gerekenler", "Önceki taramaya göre değişim", "Bu özet neye dayanır"]
        yer = [h.index("<h2>%s" % s) for s in sira]
        self.assertEqual(yer, sorted(yer))
        for yok in ("Denetim sonuçları", 'class="ev"', "finding-card", "Puanı düşüren denetimler", "<code>PG-"):
            self.assertNotIn(yok, h)

    def test_genel_durum_en_agir_bulguya_gore(self):
        durum = {
            "temiz": ("Bu taramada bulgu çıkmadı", belge()),
            "orta": ("Küçük iyileştirmeler gerekiyor", belge(orta=True)),
            "yuksek": ("Dikkat gerekiyor", belge(yuksek=True, orta=True)),
            "kritik": ("Acil dikkat gerekiyor", belge(kritik=True, yuksek=True, orta=True)),
        }
        for ad, (metin, b) in durum.items():
            h = sayfa(b, "yonetici")
            self.assertIn(metin, h, ad)
            for baska, (m2, _) in durum.items():
                if baska != ad:
                    self.assertNotIn(m2, h, "%s sayfasinda %s metni" % (ad, baska))

    def test_kanitsiz_denetim_temiz_sayilmaz(self):
        h = sayfa(belge(kanitsiz=True), "yonetici")
        pn = puan.hesapla(kurallar.incele(belge(kanitsiz=True)))
        self.assertIn("değerlendirme eksik: %d / %d denetim için kanıt geldi" % (pn.olculen, pn.uygulanabilir), h)
        self.assertIn("temiz sayılmadı", h)
        # yalniz kanitsizlik varken ozet "bulgu yok" demekle yetinmez
        self.assertNotIn("Bu taramada bulgu çıkmadı", h)
        # bulgu da varsa bulgu durumu yazilir, eksik kanit ayrica belirtilir
        h2 = sayfa(belge(kanitsiz=True, yuksek=True), "yonetici")
        self.assertIn("Dikkat gerekiyor", h2)
        self.assertIn("1 denetim için yeterli kanıt gelmedi", h2)

    def test_hic_kanit_yoksa_durum_belirlenemez(self):
        b = belge()
        for cid in list(b["kontroller"]):
            b["kontroller"][cid] = {"durum": "hata", "neden": "yetki"}
        h = sayfa(b, "yonetici")
        pn = puan.hesapla(kurallar.incele(b))
        self.assertLess(pn.olculen, pn.uygulanabilir)
        self.assertNotIn("Bu taramada bulgu çıkmadı", h)
        self.assertIn("değerlendirme eksik: %d / %d" % (pn.olculen, pn.uygulanabilir), h)

    def test_puan_ve_kapsam_yazilir(self):
        b = belge(yuksek=True)
        pn = puan.hesapla(kurallar.incele(b))
        h = sayfa(b, "yonetici")
        self.assertIn("%d/100" % pn.genel, h)
        self.assertIn("%%%d" % pn.kapsam, h)

    def test_riskler_agirdan_hafife_en_cok_bes_ve_digerleri_sayilir(self):
        b = belge(kritik=True, yuksek=True, orta=True)
        bulgu = kurallar.incele(b).bulgular
        h = sayfa(b, "yonetici")
        riskler = h[h.index("<h2>En önemli riskler"):h.index("<h2>Yapılması gerekenler")]
        satirlar = re.findall(r"<tr><th scope=\"row\">(.*?)</th>", riskler)
        self.assertEqual(len(satirlar), min(5, len(bulgu)))
        sirali = sorted(bulgu, key=lambda x: (kurallar.ONEM.index(x["onem"]), x["kural"]))
        self.assertEqual(satirlar, [x["baslik"]["tr"] for x in sirali[:5]])
        # 5'ten fazla bulgu: kalan sayisi yazilir
        cok = copy.deepcopy(b)
        cok["kontroller"]["pg_tls_parola"]["satirlar"][0]["ssl"] = "off"
        n = len(kurallar.incele(cok).bulgular)
        h2 = sayfa(cok, "yonetici")
        if n > 5:
            self.assertIn("%d bulgu daha" % (n - 5), h2)

    def test_is_etkisi_ve_kanit_turu_sutunlari(self):
        b = belge(yuksek=True)
        x = kurallar.incele(b).bulgular[0]
        h = sayfa(b, "yonetici")
        from html import escape
        self.assertIn(escape(x["neden"]["tr"]), h)
        self.assertIn("Olası iş etkisi", h)
        self.assertIn("Kanıt türü", h)
        self.assertIn("Kesin kanıt", h)   # HIGH: ayar ya da katalog durumu

    def test_dusuk_guvenli_bulgu_hipotez_olarak_etiketlenir(self):
        b = belge(yuksek=True)
        c = kurallar.incele(b)
        # kanit modelindeki guven HIGH/MEDIUM/LOW her biri ayri etiket alir
        from tarama.rapor import M
        for dil in ("tr", "en"):
            etiket = M[dil]["tur"]
            self.assertEqual(set(etiket), {"HIGH", "MEDIUM", "LOW"})
            self.assertEqual(len(set(etiket.values())), 3)
        self.assertIn("Hipotez", M["tr"]["tur"]["LOW"])
        self.assertIn("Hypothesis", M["en"]["tur"]["LOW"])
        self.assertTrue(c.bulgular)

    def test_oneriler_onem_sirasiyla_numarali_listede(self):
        b = belge(kritik=True, yuksek=True, orta=True)
        bulgu = kurallar.incele(b).bulgular
        h = sayfa(b, "yonetici")
        bolum = h[h.index("<h2>Yapılması gerekenler"):h.index("<h2>Önceki taramaya göre değişim")]
        self.assertIn("<ol", bolum)
        ogeler = re.findall(r"<li>(.*?)</li>", bolum, re.S)
        self.assertEqual(len(ogeler), len(bulgu))
        from html import escape
        sirali = sorted(bulgu, key=lambda x: (kurallar.ONEM.index(x["onem"]), x["kural"]))
        for oge, x in zip(ogeler, sirali):
            self.assertIn(escape(x["oneri"]["tr"]), oge)
        self.assertIn("Hiçbir değişiklik uygulanmamıştır", h)

    def test_oneri_yokken_liste_yerine_aciklama(self):
        h = sayfa(belge(), "yonetici")
        self.assertNotIn("<ol", h)
        self.assertIn("Bu taramada öncelikli bir iş yok", h)

    def test_onceki_tarama_yoksa_acikca_soylenir(self):
        h = sayfa(belge(yuksek=True), "yonetici")
        self.assertIn("Karşılaştırılacak önceki tarama bulunamadı", h)

    def test_onceki_tarama_varsa_puan_ve_sayilar(self):
        once = belge(yuksek=True, orta=True)
        once["olusturma_utc"] = "2026-11-01T12:00:00Z"
        simdi = belge(yuksek=True, kritik=True)
        simdi["olusturma_utc"] = "2026-11-10T12:00:00Z"
        for b in (once, simdi):
            b["kontroller"]["pg_kume_kimligi"]["satirlar"] = [{"kume": "a" * 64}]
        c = gecmis.karsilastir(once, simdi)
        h = sayfa(simdi, "yonetici", onceki=once)
        self.assertIn("2026-11-01T12:00:00Z", h)
        self.assertIn("%d/100 → %d/100" % (c.onceki_puan.genel, c.yeni_puan.genel), h)
        for d, n in c.say().items():
            if n:
                self.assertIn("%s: %d" % ({"NEW": "Yeni", "REGRESSED": "Kötüleşti", "PERSISTING": "Sürüyor", "RESOLVED": "Çözüldü", "UNKNOWN": "Bilinmiyor"}[d], n), h)
        self.assertNotIn("Karşılaştırılacak önceki tarama bulunamadı", h)

    def test_kaybolan_kanit_ozette_cozuldu_gorunmez(self):
        once = belge()
        simdi = belge(kanitsiz=True)
        once["kontroller"]["pg_log_ayarlari"]["satirlar"] = [{"name": "log_connections", "setting": "off"}, {"name": "log_disconnections", "setting": "on"}]
        for b in (once, simdi):
            b["kontroller"]["pg_kume_kimligi"]["satirlar"] = [{"kume": "a" * 64}]
        c = gecmis.karsilastir(once, simdi)
        h = sayfa(simdi, "yonetici", onceki=once)
        self.assertEqual(c.say()["UNKNOWN"], 1)
        self.assertIn("Bilinmiyor: 1", h)
        self.assertNotIn("Çözüldü: 1", h)

    def test_ingilizce_ayni_yapi(self):
        h = sayfa(belge(yuksek=True, orta=True), "yonetici", "en")
        for s in ("Executive summary", "Overall status", "Top risks", "Actions in priority order",
                  "Change since the previous scan", "What this summary is based on", "Possible business impact", "Evidence type",
                  "Attention needed", "No changes have been applied"):
            self.assertIn(s, h)
        self.assertNotRegex(h, r"Yönetici|Önceki tarama|Bu taramada")

    def test_kullanici_verisi_kacirilir(self):
        b = belge(yuksek=True)
        b["kontroller"]["pg_kume_kimligi"]["satirlar"] = [{"kume": "a" * 64}]
        once = copy.deepcopy(b)
        once["olusturma_utc"] = "<script>alert(1)</script>"
        h = sayfa(b, "yonetici", onceki=once)
        self.assertNotIn("<script>alert(1)", h)

    def test_ayni_belge_ayni_cikti(self):
        b = belge(kritik=True, yuksek=True, orta=True)
        self.assertEqual(sayfa(b, "yonetici"), sayfa(copy.deepcopy(b), "yonetici"))


class TeknikRaporTests(unittest.TestCase):
    def test_bulgu_kartinda_kanit_ve_yorum_ayri_bloklar(self):
        for dil, kanit_b, yorum_b in (("tr", "Kanıt", "Yorum"), ("en", "Evidence", "Interpretation")):
            h = sayfa(belge(yuksek=True), "teknik", dil)
            kart = h[h.index('<section class="finding-card'):h.index("</section>", h.index('<section class="finding-card'))]
            self.assertIn('<div class="kanit-blok"><h4>%s</h4>' % kanit_b, kart)
            self.assertIn('<div class="yorum-blok"><h4>%s</h4>' % yorum_b, kart)
            self.assertLess(kart.index("kanit-blok"), kart.index("yorum-blok"))
            kanit_k = kart[kart.index("kanit-blok"):kart.index("yorum-blok")]
            yorum_k = kart[kart.index("yorum-blok"):]
            self.assertIn('class="ev"', kanit_k)          # olculen degerler kanit blogunda
            self.assertNotIn('class="ev"', yorum_k)
            for et in (("Kaynak", "Kanıt güveni", "Durum") if dil == "tr" else ("Source", "Evidence confidence", "Status")):
                self.assertIn(et, kanit_k)
            for et in (("Neden önemli", "Öneri", "Önerinin riski", "Geri alma", "İş büyüklüğü") if dil == "tr"
                       else ("Why it matters", "Proposal", "Risk of the proposal", "Rollback", "Effort")):
                self.assertIn(et, yorum_k)
                self.assertNotIn(et, kanit_k)

    def test_kanit_turu_kartta_yazilir(self):
        h = sayfa(belge(yuksek=True), "teknik")
        self.assertIn("Kesin kanıt", h)

    def test_degisiklik_oncesi_sonrasi_bolumu_yalniz_bulgu_varken(self):
        h = sayfa(belge(yuksek=True), "teknik")
        self.assertIn("Değişiklikten önce ve sonra", h)
        for s in ("kendi ortamınızda", "geri alma planı", "aynı taramayı yeniden"):
            self.assertIn(s, h)
        self.assertNotIn("Değişiklikten önce ve sonra", sayfa(belge(), "teknik"))
        self.assertIn("Before and after a change", sayfa(belge(yuksek=True), "teknik", "en"))

    def test_teknik_gorunum_ozet_bolumlerini_icermez(self):
        h = sayfa(belge(yuksek=True), "teknik")
        for yok in ("En önemli riskler", "Bu özet neye dayanır"):
            self.assertNotIn(yok, h)
        self.assertIn("Denetim sonuçları", h)

    def test_silme_ve_cta_her_iki_gorunumde(self):
        r = {"belge": belge(), "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        for g in rapor.GORUNUMLER:
            icerik, _, _ = rapor.govde(r, "tr", "T" * 43, gorunum=g)
            self.assertIn("/rapor/%s/sil" % ("T" * 43), icerik)
            self.assertIn("Denetim iste", icerik)

    def test_eylemsiz_govde_gorunum_baglantilarini_korur(self):
        r = {"belge": belge(), "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        icerik, _, _ = rapor.govde(r, "tr", "", eylemler=False, gorunum="yonetici")
        self.assertNotIn("/sil", icerik)
        self.assertIn('href="?gorunum=teknik"', icerik)


class YazdirmaTests(unittest.TestCase):
    css = (ROOT / "site" / "themes" / "c" / "style.css").read_text(encoding="utf-8")

    def yazdirma(self):
        return " ".join(re.findall(r"@media print\{(.*?)\}\s*(?=\n|$)", self.css, re.S))

    def test_yazdirmada_sekmeler_ve_eylemler_gizlenir_kartlar_bolunmez(self):
        y = "".join(re.findall(r"@media print\{.*", self.css))
        for s in (".rapor-sekme", ".report form", "break-inside:avoid"):
            self.assertIn(s, y)
        self.assertIn("@page{margin:", self.css)

    def test_yazdirma_dis_kaynak_ve_betik_icermez(self):
        self.assertNotIn("http", "".join(re.findall(r"@media print\{.*", self.css)))

    def test_sayfa_betik_icermez(self):
        for g in rapor.GORUNUMLER:
            self.assertNotIn("<script", sayfa(belge(yuksek=True), g))


class SunucuGorunumTests(test_tarama._SunucuTaban):
    def test_sorgu_parametresi_gorunumu_secer(self):
        r = self.yukle(__import__("json").dumps(belge(yuksek=True)).encode())
        self.assertEqual(r.status, 303)
        yol = r.getheader("Location")
        varsayilan = self.get(yol)[1].decode()
        self.assertIn("Denetim sonuçları", varsayilan)
        ozet = self.get(yol + "?gorunum=yonetici")[1].decode()
        self.assertIn("<h2>Genel durum", ozet)
        self.assertNotIn("Denetim sonuçları", ozet)
        self.assertEqual(self.get(yol + "?gorunum=bilinmeyen")[1].decode(), varsayilan)
        self.assertEqual(self.get(yol + "?gorunum=yonetici&gorunum=teknik")[1].decode(), ozet)   # ilk deger gecerli

    def test_ingilizce_rapor_ingilizce_ozet(self):
        r = self.yukle(__import__("json").dumps(belge(yuksek=True)).encode(), dil="en")
        ozet = self.get(r.getheader("Location") + "?gorunum=yonetici")[1].decode()
        self.assertIn("Executive summary", ozet)
        self.assertIn("<h2>Overall status", ozet)


if __name__ == "__main__":
    unittest.main()
