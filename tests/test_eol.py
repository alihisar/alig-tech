"""ALIG-SCAN-002: end-of-life (EOL) PostgreSQL major version rule PG-MAINT-009.

The EOL table comes from the postgresql.org versioning policy (tarama/eol.py records the URL and the retrieval date). The rule
is advisory and informational: it does not lower the health score and never recommends an automatic change. Dates are passed in
(the scan date comes from the document); there is no hidden clock call in the evaluation.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import eol, kanit, kurallar, puan, rapor, uret_kurallar, uret_toplayici  # noqa: E402
import test_tarama  # noqa: E402

KIMLIK = "PG-MAINT-009"

# The values verified on 2026-11-16 from https://www.postgresql.org/support/versioning/ (written here independently of the code)
DOGRULANAN = {
    13: ("2020-09-24", "2025-11-13"),
    14: ("2021-09-30", "2026-11-12"),
    15: ("2022-10-13", "2027-11-11"),
    16: ("2023-09-14", "2028-11-09"),
    17: ("2024-09-26", "2029-11-08"),
    18: ("2025-09-25", "2030-11-14"),
}


def belge(surum_num, tarih="2026-11-16T12:00:00Z"):
    b = test_tarama.temiz_belge()
    b["kontroller"]["pg_surum"] = {"durum": "ok", "satirlar": [{"surum_num": surum_num}]}
    b["olusturma_utc"] = tarih
    return b


def kayit(b, kimlik=KIMLIK):
    return next(k for k in kurallar.incele(b).kayitlar if k["kural"] == kimlik)


class TabloTests(unittest.TestCase):
    def test_tablo_dogrulanan_tarihlerle_ayni(self):
        self.assertEqual({m: (v["ilk"], v["son"]) for m, v in eol.VARSAYILAN["tablo"].items()}, DOGRULANAN)

    def test_kaynak_ve_alinma_tarihi_kayitli(self):
        self.assertEqual(eol.KAYNAK_URL, "https://www.postgresql.org/support/versioning/")
        self.assertEqual(eol.ALINMA_TARIHI, "2026-11-16")

    def test_varsayilan_pencere_180_gun(self):
        self.assertEqual(eol.VARSAYILAN["pencere_gun"], 180)

    def test_tablo_sirali_gecerli_tarihler(self):
        for m, v in eol.VARSAYILAN["tablo"].items():
            self.assertLess(date.fromisoformat(v["ilk"]), date.fromisoformat(v["son"]), m)


class DegerlendirTests(unittest.TestCase):
    """Pure function: the date is a parameter."""

    def d(self, ana, gun):
        return eol.degerlendir(ana, date.fromisoformat(gun))

    def test_destek_icinde_ve_pencere_disinda_bulgu_yok(self):
        self.assertIsNone(self.d(16, "2026-11-16"))
        self.assertIsNone(self.d(18, "2026-11-16"))
        # 180 days before the PG15 EOL (2027-11-11) is 2027-05-15; one day earlier is outside the window
        self.assertIsNone(self.d(15, "2027-05-14"))

    def test_pencere_siniri_dahil(self):
        s = self.d(15, "2027-05-15")
        self.assertEqual((s["durum"], s["kalan_gun"], s["destek_sonu"]), ("yaklasiyor", 180, "2027-11-11"))

    def test_eol_gunu_yaklasiyor_sonraki_gun_bitmis(self):
        self.assertEqual(self.d(14, "2026-11-12")["durum"], "yaklasiyor")
        self.assertEqual(self.d(14, "2026-11-12")["kalan_gun"], 0)
        s = self.d(14, "2026-11-13")
        self.assertEqual((s["durum"], s["destek_sonu"]), ("bitmis", "2026-11-12"))

    def test_pg13_bitmis_ve_pg14_bitmek_uzere_bugun(self):
        self.assertEqual(self.d(13, "2026-11-16")["durum"], "bitmis")
        self.assertEqual(self.d(14, "2026-11-16")["durum"], "bitmis")

    def test_13_oncesi_tarihsiz_destek_disi(self):
        for ana in (9, 10, 11, 12):
            s = self.d(ana, "2026-11-16")
            self.assertEqual(s["durum"], "bitmis", ana)
            self.assertIsNone(s["destek_sonu"], ana)   # no date is invented for these versions

    def test_tablo_ustundeki_surum_icin_iddia_yok(self):
        self.assertIsNone(self.d(19, "2035-01-01"))   # unknown future major: nothing is claimed

    def test_ozel_pencere(self):
        ayar = {"tablo": eol.VARSAYILAN["tablo"], "pencere_gun": 400}
        self.assertEqual(eol.degerlendir(15, date(2026, 11, 16), ayar)["durum"], "yaklasiyor")   # 360 days left
        ayar["pencere_gun"] = 0
        self.assertIsNone(eol.degerlendir(15, date(2027, 11, 10), ayar))
        self.assertEqual(eol.degerlendir(15, date(2027, 11, 11), ayar)["durum"], "yaklasiyor")

    def test_saat_cagrisi_yok(self):
        kaynak = (ROOT / "tarama" / "eol.py").read_text(encoding="utf-8")
        self.assertNotRegex(kaynak, r"\.now\(|\.today\(|time\.time\(|utcnow")

    def test_tarih_icin_datetime_de_kabul(self):
        s = eol.degerlendir(14, datetime(2026, 11, 12, 23, 59, tzinfo=timezone.utc))
        self.assertEqual(s["durum"], "yaklasiyor")


class AyarTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def yaz(self, ad, metin):
        (self.d / ad).write_text(metin if isinstance(metin, str) else json.dumps(metin), encoding="utf-8")
        return str(self.d / ad)

    def test_ortam_yoksa_varsayilan(self):
        self.assertEqual(eol.ortamdan({}), eol.VARSAYILAN)

    def test_pencere_ve_tarih_gecersiz_kilinir(self):
        yol = self.yaz("a.json", {"pencere_gun": 90, "son_tarihler": {"14": "2026-12-31"}})
        a = eol.ortamdan({eol.ORTAM: yol})
        self.assertEqual(a["pencere_gun"], 90)
        self.assertEqual(a["tablo"][14]["son"], "2026-12-31")
        self.assertEqual(a["tablo"][14]["ilk"], "2021-09-30")      # not given: stays
        self.assertEqual(a["tablo"][15]["son"], "2027-11-11")      # not given: stays
        self.assertEqual(eol.VARSAYILAN["tablo"][14]["son"], "2026-11-12")   # the default is not mutated

    def test_yeni_surum_eklenebilir(self):
        a = eol.ayar_dogrula({"son_tarihler": {"19": "2031-11-13"}})
        self.assertEqual(a["tablo"][19]["son"], "2031-11-13")

    def test_gecersiz_ayar_reddedilir(self):
        for kotu in ([], "x", {"bilinmeyen": 1}, {"pencere_gun": -1}, {"pencere_gun": True}, {"pencere_gun": 1.5},
                     {"pencere_gun": "90"}, {"pencere_gun": 10 ** 6}, {"son_tarihler": []}, {"son_tarihler": {"on dort": "2026-12-31"}},
                     {"son_tarihler": {"14": "31.12.2026"}}, {"son_tarihler": {"14": "2026-13-45"}}, {"son_tarihler": {"14": 20261231}},
                     {"son_tarihler": {"0": "2026-12-31"}}, {"son_tarihler": {"14": "2020-01-01"}}):   # before the first release
            with self.assertRaises(eol.EolAyarHatasi, msg=repr(kotu)):
                eol.ayar_dogrula(kotu)

    def test_dosya_hatalari(self):
        self.yaz("bozuk.json", "{")
        self.yaz("cift.json", '{"pencere_gun": 1, "pencere_gun": 2}')
        self.yaz("buyuk.json", " " * 70000 + "{}")
        for yol in ("bozuk.json", "yok.json", "cift.json", "buyuk.json", ""):
            if yol == "":
                continue
            with self.assertRaises(eol.EolAyarHatasi, msg=yol):
                eol.ortamdan({eol.ORTAM: str(self.d / yol)})
        with self.assertRaises(eol.EolAyarHatasi):
            eol.ortamdan({eol.ORTAM: str(self.d)})   # a directory

    def test_yukle_etkin_ayari_degistirir(self):
        eski = eol.ETKIN
        self.addCleanup(setattr, eol, "ETKIN", eski)
        eol.yukle({eol.ORTAM: self.yaz("a.json", {"pencere_gun": 30})})
        self.assertEqual(eol.ETKIN["pencere_gun"], 30)
        eol.yukle({})
        self.assertEqual(eol.ETKIN, eol.VARSAYILAN)


class KuralTests(unittest.TestCase):
    def setUp(self):
        eski = eol.ETKIN
        self.addCleanup(setattr, eol, "ETKIN", eski)
        eol.ETKIN = eol.VARSAYILAN

    def test_kayitli_ve_bilgi_duzeyinde(self):
        k = next(x for x in kurallar.KURALLAR if x.kimlik == KIMLIK)
        self.assertEqual((k.kategori, k.risk), ("bakim", "bilgi"))
        self.assertEqual([x.kimlik for x in kurallar.KURALLAR].count(KIMLIK), 1)

    def test_desteklenen_surum_gecer(self):
        k = kayit(belge(180002))
        self.assertEqual((k["durum"], k["onem"]), ("PASS", None))

    def test_bitmis_surum_bilgi_bulgusu(self):
        k = kayit(belge(140010))
        self.assertEqual((k["durum"], k["onem"]), ("WARNING", "bilgi"))
        self.assertEqual(k["bulgular"][0]["kanit"]["destek_sonu"], "2026-11-12")
        self.assertEqual(k["bulgular"][0]["kanit"]["durum"], "bitmis")

    def test_pg13_ve_12(self):
        self.assertEqual(kayit(belge(130020))["bulgular"][0]["kanit"]["destek_sonu"], "2025-11-13")
        k = kayit(belge(120022))["bulgular"][0]
        self.assertEqual(k["onem"], "bilgi")
        self.assertIsNone(k["kanit"]["destek_sonu"])

    def test_pencere_icinde_bilgi(self):
        k = kayit(belge(150001, "2027-06-01T00:00:00Z"))
        self.assertEqual((k["durum"], k["onem"]), ("WARNING", "bilgi"))
        self.assertEqual(k["bulgular"][0]["kanit"]["kalan_gun"], 163)
        self.assertEqual(kayit(belge(150001, "2027-05-14T00:00:00Z"))["durum"], "PASS")

    def test_tarama_tarihi_belgeden_gelir(self):
        # the same version: PASS on an early scan date, finding on a later one (depends only on the document)
        self.assertEqual(kayit(belge(140010, "2026-05-01T00:00:00Z"))["durum"], "PASS")     # 195 days left
        self.assertEqual(kayit(belge(140010, "2026-05-20T00:00:00Z"))["durum"], "WARNING")  # 176 days left

    def test_ayar_kurala_etki_eder(self):
        eol.ETKIN = eol.ayar_dogrula({"pencere_gun": 0})
        self.assertEqual(kayit(belge(150001, "2027-06-01T00:00:00Z"))["durum"], "PASS")
        eol.ETKIN = eol.ayar_dogrula({"son_tarihler": {"14": "2027-06-30"}})
        self.assertEqual(kayit(belge(140010))["durum"], "PASS")   # the operator extended the date (for example a vendor support contract)

    def test_gecersiz_surum_belirsiz(self):
        k = kayit(belge(1234))
        self.assertEqual((k["durum"], k["neden"]), ("UNKNOWN", "gecersiz_veri"))

    def test_puani_dusurmez(self):
        for sn in (140010, 120022, 130020):
            k = kayit(belge(sn))
            self.assertEqual(k["durum"], "WARNING")
            self.assertEqual(puan.kredi(k), 1.0)                      # a warning with info severity has full credit
            self.assertEqual(puan.VARSAYILAN["agirlik"][k["risk"]], 0)  # and the rule has no weight
        # other rules unchanged: dropping this rule's record changes nothing (the rule is outside the weighted ratio)
        s = kurallar.incele(belge(140010))
        ham = puan.hesapla(s).ham
        s.kayitlar = [k for k in s.kayitlar if k["kural"] != KIMLIK]
        self.assertEqual(puan.hesapla(s).ham, ham)

    def test_oneri_otomatik_degisiklik_icermez(self):
        t = kurallar.T["pg_surum_eol_bilgi"]
        for alan in ("baslik", "neden", "oneri", "risk", "geri"):
            self.assertEqual(set(t[alan]), {"tr", "en"})
            self.assertTrue(t[alan]["tr"] and t[alan]["en"])
        self.assertRegex(t["oneri"]["en"].lower(), r"plan|decide|review")
        for dil in ("tr", "en"):
            self.assertNotRegex(" ".join(t[a][dil] for a in t if isinstance(t[a], dict)).lower(), r"pgaudit")

    def test_bilgi_bulgusu_raporda_gorunur(self):
        b = belge(140010)
        sayfa = rapor.sayfa({"belge": b, "bitis_utc": "2026-12-01T00:00:00Z", "dil": "en"}, "en", "t")
        self.assertIn("PG-MAINT-009", sayfa)

    def test_mevcut_kural_ayni_tabloyu_kullanir(self):
        # PG-MAINT-001 (existing, high severity) is unchanged and reads the same table
        self.assertEqual(kayit(belge(140010), "PG-MAINT-001")["onem"], "yuksek")
        eol.ETKIN = eol.ayar_dogrula({"son_tarihler": {"14": "2027-06-30"}})
        self.assertEqual(kayit(belge(140010), "PG-MAINT-001")["durum"], "PASS")


class KatalogTests(unittest.TestCase):
    def test_katalog_belgesi_guncel_ve_kural_var(self):
        metin = (ROOT / "docs" / "kural-katalogu.md").read_text(encoding="utf-8")
        self.assertEqual(metin, uret_kurallar.uret(), "python3 tarama/uret_kurallar.py")
        self.assertRegex(metin, r"\| PG-MAINT-009 \| [^|]+\| Maintenance \| Info")
        self.assertIn("https://www.postgresql.org/support/versioning/", metin)
        self.assertIn("2026-11-16", metin)

    def test_toplayici_ozeti_sabitlenmis_ozetle_ayni(self):
        # Adding the rule reads an existing collector check (pg_surum): the collector catalog digest is not affected, and the
        # digest pinned in the real-server evidence file stays valid. The evidence is not re-pinned.
        kayit_ = json.loads((ROOT / "docs" / "surum-dogrulama.json").read_text(encoding="utf-8"))
        self.assertTrue(kayit_["surumler"])
        for v, s in kayit_["surumler"].items():
            self.assertEqual(s["katalog_sha256"], uret_toplayici.katalog_ozeti(), v)


if __name__ == "__main__":
    unittest.main()
