"""PostgreSQL surum ve yetki matrisi: surume gore sorgu secimi, desteklenmeyen surumde sorgu calismaz, yetki zorunlulugu,
gercek sunucu kaniti (docs/surum-dogrulama.json, tests/veri/surum) ile katalog bildiriminin tutarliligi."""
import copy
import importlib.util
import json
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import baglanti, hedef, kanit, katalog, kurallar, rapor, uret_kurallar, yukleme  # noqa: E402
from tarama.uret_toplayici import katalog_ozeti  # noqa: E402
import test_baglanti  # noqa: E402
import test_tarama  # noqa: E402

DOGRULAMA = json.loads((ROOT / "docs" / "surum-dogrulama.json").read_text(encoding="utf-8"))
BELGELER = ROOT / "tests" / "veri" / "surum"


def toplayici_modulu():
    spec = importlib.util.spec_from_file_location("alig_toplayici", ROOT / "site" / "assets" / "alig-toplayici.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def durumlar(belge):
    return {k["kural"]: (k["durum"], k["neden"]) for k in kurallar.incele(belge).kayitlar}


class MatrisTests(unittest.TestCase):
    def test_her_denetimde_surum_ve_yetki(self):
        for c in katalog.PG:
            self.assertIsInstance(c["en_az"], int, c["id"])
            self.assertIn(c["yetki"], katalog.YETKILER, c["id"])
            self.assertTrue(c.get("en_cok") is None or c["en_cok"] >= c["en_az"], c["id"])
            onceki = c["en_az"] - 1
            for v in c.get("eski_surum", ()):
                self.assertTrue(set(v) == {"en_cok", "sql", "not"} and v["not"].strip(), c["id"])
                self.assertGreater(v["en_cok"], onceki, c["id"])   # artan sirada, en_az'dan sonra
                onceki = v["en_cok"]
            self.assertTrue(c.get("en_cok") is None or onceki < c["en_cok"], c["id"])

    def test_sorgu_secimi(self):
        slot = katalog.PG_BY_ID["pg_slot"]
        eski = katalog.sorgu(slot, 12)
        self.assertEqual(re.findall(r"\w*wal_status\w*", eski), ["wal_status"])   # yalniz takma ad: PostgreSQL 12'de kolon yok
        self.assertIn("NULL::text AS wal_status", eski)
        self.assertEqual(katalog.sorgu(slot, 13), slot["sql"])
        self.assertEqual(katalog.sorgu(slot, 19), slot["sql"])     # yeni surumde ana sorgu
        self.assertEqual(katalog.sorgu(slot, None), slot["sql"])   # surum bilinmiyorsa ana sorgu
        self.assertIsNone(katalog.sorgu(slot, 11))
        self.assertEqual(katalog.sorgu(katalog.PG_BY_ID["pg_surum"], 9), katalog.PG_BY_ID["pg_surum"]["sql"])
        sahte = {"sql": "S", "en_az": 13, "en_cok": 15, "eski_surum": [{"en_cok": 13, "sql": "E", "not": "n"}]}
        self.assertEqual([katalog.sorgu(sahte, v) for v in (12, 13, 14, 15, 16)], [None, "E", "S", "S", None])

    def test_eski_surum_sorgulari_ayni_kolonlari_adlandirir(self):
        for c in katalog.PG:
            kolonlar = [k for k in c["kolonlar"] if not (k == "veritabani" and c.get("kapsam") == "veritabani")]
            for sql in katalog.sorgular(c):
                for k in kolonlar:
                    self.assertRegex(sql, r"\b%s\b" % re.escape(k), "%s: %s" % (c["id"], k))

    def test_toplayici_ayni_secimi_yapar(self):
        t = toplayici_modulu()
        self.assertEqual([c["id"] for c in t.KATALOG["kontroller"]], [c["id"] for c in katalog.PG])
        for c in t.KATALOG["kontroller"]:
            for v in list(range(8, 22)) + [None]:
                self.assertEqual(t.sorgu_sec(c, v), katalog.sorgu(katalog.PG_BY_ID[c["id"]], v), (c["id"], v))
        self.assertEqual((t.KATALOG["surum_alt"], t.KATALOG["surum_ust"]), (katalog.SURUM_ALT, katalog.SURUM_UST))

    def test_matris_belgesi_guncel(self):
        self.assertEqual(uret_kurallar.main(["--kontrol"]), 0, "python3 tarama/uret_kurallar.py calistirin")


class ToplayiciSurumTests(test_tarama.ToplayiciTaban):
    """Sahte psql: sunucu surumu ilk sorguda doner; toplayici desteklenmeyen sorguyu hic gondermez."""

    def calistirilan(self):
        return [g["sql"] for g in self.gunluk()]

    def test_eski_surumde_ayri_sorgu(self):
        self.ayar["surum"] = 120022
        eski = katalog.sorgu(katalog.PG_BY_ID["pg_slot"], 12)
        self.ayar["kontroller"]["pg_slot"] = {"sql": eski, "satirlar": {"postgres": [{"slot_name": "s", "active": False, "wal_status": None, "geri_bayt": 5}]}}
        b, _ = self.calistir()
        yukleme.dogrula(b)
        self.assertTrue(any(eski in s for s in self.calistirilan()))
        self.assertFalse(any(katalog.PG_BY_ID["pg_slot"]["sql"] in s for s in self.calistirilan()))
        self.assertEqual(b["kontroller"]["pg_slot"]["durum"], "ok")
        self.assertEqual(durumlar(b)["PG-HA-001"][0], "FAIL")   # PostgreSQL 12'de etkin olmayan slot yine bulunur

    def test_desteklenmeyen_surumde_sorgu_calismaz(self):
        self.ayar["surum"] = 110022
        b, _ = self.calistir()
        yukleme.dogrula(b)
        calisan = self.calistirilan()
        for c in katalog.PG:
            if katalog.sorgu(c, 11) is None:
                self.assertEqual(b["kontroller"][c["id"]], {"durum": "hata", "neden": "desteklenmiyor"}, c["id"])
                self.assertFalse(any(sql in s for sql in katalog.sorgular(c) for s in calisan), c["id"])
            else:
                self.assertTrue(any(c["sql"] in s for s in calisan), c["id"])
        self.assertIn("sinanmadi", self.r.stderr)
        d = durumlar(b)
        self.assertEqual(d["PG-MAINT-004"], ("UNAVAILABLE", "desteklenmiyor"))


class KipBSurumTests(test_baglanti.Temel):
    def tara(self):
        return baglanti.tara(self.h, veritabani="postgres", kullanici="alig_hc", parola=test_baglanti.PAROLA, kanit=test_baglanti.KANIT, psql=str(self.psql))

    def test_desteklenmeyen_surumde_sorgu_calismaz(self):
        self.ayar["surum"] = 110022
        self.yaz()
        b = self.tara()
        calisan = [g["argv"][g["argv"].index("-c") + 1] for g in self.gunluk()]
        desteklenen = [c for c in katalog.PG if katalog.sorgu(c, 11) is not None]
        self.assertEqual(len(calisan), 2 + len(desteklenen))   # ilk sorgu + veritabani listesi + desteklenen denetimler
        for c in katalog.PG:
            if katalog.sorgu(c, 11) is None:
                self.assertEqual(b["kontroller"][c["id"]], {"durum": "hata", "neden": "desteklenmiyor"}, c["id"])

    def test_eski_surumde_ayri_sorgu(self):
        self.ayar["surum"] = 120022
        eski = katalog.sorgu(katalog.PG_BY_ID["pg_slot"], 12)
        self.ayar["kontroller"]["pg_slot"] = {"sql": eski, "satirlar": []}
        self.yaz()
        b = self.tara()
        self.assertEqual(b["kontroller"]["pg_slot"], {"durum": "ok", "satirlar": []})
        calisan = [g["argv"][g["argv"].index("-c") + 1] for g in self.gunluk()]
        self.assertTrue(any(eski in s for s in calisan))


class YetkiTests(unittest.TestCase):
    def belge(self, **hesap):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_hesap"]["satirlar"][0].update(hesap)
        return b

    def test_rolu_olmayan_hesapta_kural_gecemez(self):
        b = self.belge(pg_read_all_stats=False, pg_read_all_settings=False)
        d = durumlar(b)
        for kimlik in ("PG-PERF-001", "PG-CAP-001", "PG-SEC-001", "PG-SEC-002"):
            self.assertEqual(d[kimlik], ("UNKNOWN", "rol_eksik"), kimlik)
        self.assertEqual(d["PG-MAINT-004"][0], "PASS")   # rol gerektirmeyen denetim etkilenmez

    def test_bulgu_varsa_rol_eksigi_gizlemez(self):
        b = self.belge(pg_read_all_stats=False)
        b["kontroller"]["pg_bosta_islem"]["satirlar"] = [{"usename": "app", "durum": "idle in transaction", "sure_sn": 4000}]
        self.assertEqual(durumlar(b)["PG-PERF-001"][0], "FAIL")

    def test_super_kullanici_her_seyi_gorur(self):
        b = self.belge(super_kullanici=True, pg_read_all_stats=False, pg_read_all_settings=False)
        self.assertEqual(durumlar(b)["PG-PERF-001"], ("PASS", None))

    def test_hesap_okunamazsa_bilinmiyor(self):
        for e in (None, {"durum": "hata", "neden": "hata"}, {"durum": "ok", "satirlar": []},
                  {"durum": "ok", "satirlar": [{"super_kullanici": None, "pg_read_all_stats": True, "pg_read_all_settings": True}]}):
            b = test_tarama.temiz_belge()
            if e is None:
                del b["kontroller"]["pg_hesap"]
            else:
                b["kontroller"]["pg_hesap"] = e
            self.assertEqual(durumlar(b)["PG-PERF-001"], ("UNKNOWN", "rol_bilinmiyor"), e)


class SurumGuvenTests(unittest.TestCase):
    def test_sinanmamis_surumde_guven_en_cok_orta(self):
        for surum, sinanan in ((160015, True), (180001, False), (120022, False)):
            b = test_tarama.temiz_belge()
            b["kontroller"]["pg_surum"]["satirlar"] = [{"surum_num": surum}]
            s = kurallar.incele(b)
            self.assertEqual((s.baglam["ana_surum"], s.baglam["sinanan"]), (surum // 10000, sinanan))
            guvenler = {k["guven"] for k in s.kayitlar if k["guven"]}
            self.assertEqual("HIGH" in guvenler, sinanan, surum)
        b = test_tarama.temiz_belge()
        del b["kontroller"]["pg_surum"]
        s = kurallar.incele(b)
        self.assertEqual((s.baglam["ana_surum"], s.baglam["sinanan"]), (None, False))
        self.assertNotIn("HIGH", {k["guven"] for k in s.kayitlar})

    def test_rapor_surumu_ve_sinanma_durumunu_yazar(self):
        b = test_tarama.temiz_belge()
        r = {"belge": b, "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        self.assertIn("PostgreSQL 16: bu sürümde sınandı", rapor.sayfa(r, "tr", "t"))
        b["kontroller"]["pg_surum"]["satirlar"] = [{"surum_num": 180001}]
        self.assertIn("PostgreSQL 18: bu sürüm araçla henüz sınanmadı", rapor.sayfa(r, "tr", "t"))
        self.assertIn("PostgreSQL 18: this version has not been tested", rapor.sayfa(dict(r, dil="en"), "en", "t"))

    def test_sql_server_raporunda_surum_satiri_yok(self):
        import test_mssql
        r = {"belge": test_mssql.temiz_mssql(), "bitis_utc": "2026-12-01T00:00:00Z", "dil": "tr"}
        self.assertNotIn("Sunucu sürümü", rapor.sayfa(r, "tr", "t"))


class GercekSunucuKanitiTests(unittest.TestCase):
    """docs/surum-dogrulama.json ve tests/veri/surum: tarama/surum_dogrula.py'nin gercek PostgreSQL'de topladigi kanit."""

    def test_sinanan_surumlerin_kaniti_tam_ve_guncel(self):
        self.assertTrue(katalog.SINANAN)
        for v in katalog.SINANAN:
            s = DOGRULAMA["surumler"].get(str(v))
            self.assertIsNotNone(s, "PostgreSQL %d icin kanit yok" % v)
            self.assertEqual(s["katalog_sha256"], katalog_ozeti(), "PostgreSQL %d kaniti eski katalogla: surum_dogrula.py yeniden calistirin" % v)
            self.assertEqual(set(s["hesaplar"]), {"pg_monitor", "yetkisiz", "super"})
            for c in katalog.PG:
                if katalog.sorgu(c, v) is None:
                    continue
                hesap = "super" if c["yetki"] == "superuser" else "pg_monitor"
                self.assertEqual(s["hesaplar"][hesap]["kontroller"][c["id"]]["durum"], "ok", "%s PostgreSQL %d" % (c["id"], v))

    def test_bildirilen_yetki_kanitla_tutarli(self):
        for v, s in DOGRULAMA["surumler"].items():
            h = {a: s["hesaplar"][a]["kontroller"] for a in s["hesaplar"]}
            for c in katalog.PG:
                if c["id"] not in h["pg_monitor"] or c["id"] == "pg_hesap":   # pg_hesap hesabin kendisini anlatir
                    continue
                mon, duz, sup = h["pg_monitor"][c["id"]], h["yetkisiz"][c["id"]], h["super"][c["id"]]
                ad = "%s PostgreSQL %s" % (c["id"], v)
                if c["yetki"] == "herkes":
                    self.assertEqual(duz, mon, ad + ": yetkisiz hesapta farkli sonuc; yetki 'herkes' degil")
                elif c["yetki"] == "pg_read_all_stats":
                    self.assertEqual(mon["durum"], "ok", ad)
                    self.assertNotEqual(duz, mon, ad + ": yetkisiz hesapta ayni sonuc; senaryo farki gostermiyor")
                elif c["yetki"] == "pg_read_all_settings":
                    self.assertEqual((mon["durum"], duz.get("neden")), ("ok", "yetki"), ad)
                else:
                    self.assertEqual((mon.get("neden"), sup["durum"]), ("yetki", "ok"), ad)

    def test_gercek_belgeler_dogrulanir_ve_kurallar_beklendigi_gibi(self):
        for v in katalog.SINANAN:
            belge = {a: json.loads((BELGELER / str(v) / ("%s.json" % a)).read_text(encoding="utf-8")) for a in ("pg_monitor", "yetkisiz", "super")}
            for b in belge.values():
                yukleme.dogrula(copy.deepcopy(b))
            mon, duz, sup = (durumlar(belge[a]) for a in ("pg_monitor", "yetkisiz", "super"))
            # senaryo: etkin olmayan slot, gecersiz indeks, MD5 rol, bosta acik islem (esik alti), okunamayan sequence
            self.assertEqual(mon["PG-HA-001"][0], "FAIL")
            self.assertEqual(mon["PG-MAINT-004"][0], "FAIL")
            self.assertEqual(mon["PG-SEC-003"], ("UNAVAILABLE", "yetki"))
            self.assertEqual(sup["PG-SEC-003"][0], "WARNING")
            self.assertEqual(sup["PG-SEC-005"][0], "WARNING")
            self.assertEqual(mon["PG-PERF-001"], ("PASS", None))
            self.assertEqual(duz["PG-PERF-001"], ("UNKNOWN", "rol_eksik"))   # yetkisiz hesap baska oturumu goremedi: gecti denmez
            self.assertEqual(duz["PG-CAP-001"], ("UNKNOWN", "rol_eksik"))
            self.assertEqual(mon["PG-CAP-002"][0], "UNKNOWN")                # sequence okunamadi ve gizli veritabani taranmadi
            self.assertEqual(sup["PG-CAP-002"][0], "FAIL")
            self.assertTrue(kurallar.incele(belge["pg_monitor"]).baglam["sinanan"])


if __name__ == "__main__":
    unittest.main()
