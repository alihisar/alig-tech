"""Katalog genisletme (madde 12): autovacuum, tablo duzeyinde autovacuum, multixact yasi, replikasyon gecikmesi,
pg_stat_statements, gecici dosyalar ve yedek sunucuda calisan WAL konum sorgulari."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import katalog, kurallar  # noqa: E402
import test_tarama  # noqa: E402

GB = 1024 ** 3


def belge(**kontroller):
    b = test_tarama.temiz_belge()
    for cid, satirlar in kontroller.items():
        b["kontroller"][cid] = {"durum": "ok", "satirlar": satirlar}
    return b


def kayit(b, kimlik):
    return next(k for k in kurallar.incele(b).kayitlar if k["kural"] == kimlik)


def durum(b, kimlik):
    k = kayit(b, kimlik)
    return k["durum"], k["neden"]


def onem(b, kimlik):
    k = kayit(b, kimlik)
    return k["durum"], k["onem"]


class KatalogTests(unittest.TestCase):
    YENI = {"pg_autovacuum": "herkes", "pg_tablo_autovacuum": "herkes", "pg_replikasyon": "pg_read_all_stats",
            "pg_sorgu_istatistigi": "pg_read_all_settings", "pg_gecici_dosya": "herkes"}

    def test_yeni_denetimler_ve_yetkileri(self):
        for cid, yetki in self.YENI.items():
            c = katalog.PG_BY_ID[cid]
            self.assertEqual((c["en_az"], c["yetki"]), (12, yetki), cid)
        self.assertEqual(katalog.PG_BY_ID["pg_tablo_autovacuum"].get("kapsam"), "veritabani")
        self.assertIn("mxid_freeze_max_age", katalog.PG_BY_ID["pg_xid_yasi"]["kolonlar"])

    def test_wal_konumu_yedek_sunucuda_hata_vermez(self):
        """pg_current_wal_lsn() yedek sunucuda hata verir: her sorgu once pg_is_in_recovery() ile ayirmali."""
        gorulen = 0
        for c in katalog.PG:
            for sql in katalog.sorgular(c):
                if "pg_current_wal_lsn()" in sql:
                    gorulen += 1
                    self.assertRegex(sql, r"CASE WHEN pg_is_in_recovery\(\) THEN pg_last_wal_receive_lsn\(\) ELSE pg_current_wal_lsn\(\) END",
                                     c["id"])
        self.assertGreaterEqual(gorulen, 3)   # pg_slot (iki bicim) ve pg_replikasyon

    def test_tablo_autovacuum_sorgusu_bool_yazimlarini_tanir(self):
        """reloptions degeri yazildigi gibi saklanir (off, 0, false, no...): PostgreSQL'in bool okumasiyla ayni kume."""
        kalip = re.search(r"~\* '([^']+)'", katalog.PG_BY_ID["pg_tablo_autovacuum"]["sql"]).group(1)
        for kapali in ("autovacuum_enabled=off", "autovacuum_enabled=0", "autovacuum_enabled=FALSE", "autovacuum_enabled=no",
                       "autovacuum_enabled=f", "autovacuum_enabled=of", "fillfactor=70,autovacuum_enabled=off",
                       "autovacuum_enabled=off,fillfactor=70"):
            self.assertTrue(re.search(kalip, kapali, re.I), kapali)
        for acik in ("autovacuum_enabled=on", "autovacuum_enabled=true", "autovacuum_enabled=1", "toast.autovacuum_enabled=off",
                     "autovacuum_enabled=offf", "autovacuum_vacuum_scale_factor=0", "x_autovacuum_enabled=off", ""):
            self.assertFalse(re.search(kalip, acik, re.I), acik)


class AutovacuumTests(unittest.TestCase):
    def ayar(self, av="on", tc="on"):
        return belge(pg_autovacuum=[{"name": "autovacuum", "setting": av}, {"name": "track_counts", "setting": tc}])

    def test_acik_gecer_kapali_basarisiz(self):
        self.assertEqual(durum(self.ayar(), "PG-MAINT-006"), ("PASS", None))
        for b, kapali in ((self.ayar(av="off"), ["autovacuum"]), (self.ayar(tc="off"), ["track_counts"]),
                          (self.ayar("off", "off"), ["autovacuum", "track_counts"])):
            k = kayit(b, "PG-MAINT-006")
            self.assertEqual((k["durum"], k["onem"]), ("FAIL", "yuksek"))
            self.assertEqual(k["bulgular"][0]["kanit"]["kapali_ayarlar"], kapali)

    def test_eksik_ya_da_taninmayan_deger(self):
        self.assertEqual(durum(belge(pg_autovacuum=[{"name": "autovacuum", "setting": "on"}]), "PG-MAINT-006"), ("UNKNOWN", "eksik_veri"))
        self.assertEqual(durum(self.ayar(av="belki"), "PG-MAINT-006"), ("UNKNOWN", "gecersiz_veri"))

    def test_tablo_duzeyinde_kapali(self):
        self.assertEqual(durum(belge(), "PG-MAINT-007"), ("PASS", None))
        k = kayit(belge(pg_tablo_autovacuum=[{"veritabani": "satis db", "schemaname": "public", "relname": "olu"}]), "PG-MAINT-007")
        self.assertEqual((k["durum"], k["onem"]), ("WARNING", "orta"))
        self.assertEqual(k["bulgular"][0]["kanit"]["nesneler"], ["satis db.public.olu"])
        self.assertEqual(k["gozlem"], {"tablo": 1})   # gozlemde nesne adi yok


class MultixactTests(unittest.TestCase):
    def yas(self, mxid, esik=400000000):
        return belge(pg_xid_yasi=[{"datname": "postgres", "yas": 1000, "mxid_yas": mxid, "freeze_max_age": 200000000,
                                   "mxid_freeze_max_age": esik}])

    def test_esikler(self):
        self.assertEqual(durum(self.yas(1000), "PG-MAINT-008"), ("PASS", None))
        self.assertEqual(onem(self.yas(799999999), "PG-MAINT-008"), ("PASS", None))
        self.assertEqual(onem(self.yas(800000000), "PG-MAINT-008"), ("WARNING", "orta"))
        self.assertEqual(onem(self.yas(300000000, esik=100000000), "PG-MAINT-008"), ("WARNING", "orta"))   # ayara gore
        self.assertEqual(onem(self.yas(1600000000), "PG-MAINT-008"), ("FAIL", "kritik"))
        self.assertEqual(kayit(self.yas(1600000000), "PG-MAINT-008")["bulgular"][0]["kanit"]["veritabani"], "postgres")

    def test_ayar_yoksa_bilinmiyor_xid_kurali_etkilenmez(self):
        b = self.yas(1000, esik=None)
        self.assertEqual(durum(b, "PG-MAINT-008"), ("UNKNOWN", "eksik_veri"))
        self.assertEqual(durum(b, "PG-MAINT-002"), ("PASS", None))


class ReplikasyonTests(unittest.TestCase):
    def rep(self, *satirlar):
        return belge(pg_replikasyon=[dict({"uygulama": "r%d" % i, "durum": "streaming", "senkron": "async", "gecikme_sn": 0.5,
                                           "gecikme_bayt": 1024}, **s) for i, s in enumerate(satirlar)])

    def test_replika_yoksa_uygulanmaz(self):
        self.assertEqual(durum(belge(), "PG-HA-002"), ("NOT_APPLICABLE", "replika_yok"))
        self.assertEqual(durum(self.rep({"durum": "backup", "gecikme_bayt": None}), "PG-HA-002"), ("NOT_APPLICABLE", "replika_yok"))   # pg_basebackup

    def test_esikler(self):
        self.assertEqual(durum(self.rep({}), "PG-HA-002"), ("PASS", None))
        self.assertEqual(durum(self.rep({"gecikme_sn": None}), "PG-HA-002"), ("PASS", None))   # yetisen replikada gecikme NULL
        self.assertEqual(onem(self.rep({"gecikme_sn": 59.9}), "PG-HA-002"), ("PASS", None))
        self.assertEqual(onem(self.rep({"gecikme_sn": 60}), "PG-HA-002"), ("WARNING", "orta"))
        self.assertEqual(onem(self.rep({"gecikme_sn": 600}), "PG-HA-002"), ("FAIL", "yuksek"))
        self.assertEqual(onem(self.rep({"gecikme_bayt": GB}), "PG-HA-002"), ("WARNING", "orta"))   # yeniden oynatma durunca sure gecikmesi buyumez
        self.assertEqual(onem(self.rep({"gecikme_bayt": 16 * GB}), "PG-HA-002"), ("FAIL", "yuksek"))
        self.assertEqual(onem(self.rep({"durum": "catchup"}), "PG-HA-002"), ("WARNING", "orta"))
        k = kayit(self.rep({}, {"gecikme_sn": 700, "gecikme_bayt": 5}), "PG-HA-002")
        self.assertEqual((k["durum"], k["bulgular"][0]["kanit"]["nesneler"], k["bulgular"][0]["kanit"]["sorunlu_replika"]), ("FAIL", ["r1"], 1))
        self.assertEqual(k["gozlem"], {"replika": 2, "en_yuksek_gecikme_sn": 700, "en_yuksek_gecikme_bayt": 1024})

    def test_eksik_ya_da_gecersiz(self):
        self.assertEqual(durum(self.rep({"durum": None, "senkron": None, "gecikme_sn": None, "gecikme_bayt": None}), "PG-HA-002"),
                         ("UNKNOWN", "eksik_veri"))   # yetkisiz hesap: satir gorunur, degerler bos; replika yok denmez
        self.assertEqual(durum(self.rep({"gecikme_bayt": None}), "PG-HA-002"), ("UNKNOWN", "eksik_veri"))
        self.assertEqual(durum(self.rep({"gecikme_bayt": -5}), "PG-HA-002"), ("UNKNOWN", "gecersiz_veri"))
        self.assertEqual(durum(self.rep({"gecikme_sn": -1}), "PG-HA-002"), ("UNKNOWN", "gecersiz_veri"))
        k = belge(pg_replikasyon=[{"uygulama": "r", "durum": None, "senkron": None, "gecikme_sn": None, "gecikme_bayt": None}])
        k["kontroller"]["pg_hesap"]["satirlar"] = [{"super_kullanici": False, "pg_read_all_stats": False, "pg_read_all_settings": False}]
        self.assertEqual(durum(k, "PG-HA-002"), ("UNKNOWN", "rol_eksik"))


class SorguIstatistigiTests(unittest.TestCase):
    def pss(self, kutuphane, izleme="top"):
        return belge(pg_sorgu_istatistigi=[{"shared_preload_libraries": kutuphane, "izleme": izleme}])

    def test_yuklu_ve_topluyor(self):
        for k in ("pg_stat_statements", '"$libdir/pg_stat_statements", auto_explain', "auto_explain,PG_STAT_STATEMENTS",
                  "pg_stat_statements.so"):
            self.assertEqual(durum(self.pss(k), "PG-PERF-002"), ("PASS", None), k)
        self.assertEqual(durum(self.pss("pg_stat_statements", "all"), "PG-PERF-002"), ("PASS", None))

    def test_yuklu_degil_ya_da_toplamiyor(self):
        for k in ("", "auto_explain", "pg_stat_statements_ek"):
            self.assertEqual(onem(self.pss(k, None), "PG-PERF-002"), ("WARNING", "dusuk"), k)
        self.assertEqual(onem(self.pss("pg_stat_statements", "none"), "PG-PERF-002"), ("WARNING", "dusuk"))
        self.assertEqual(kayit(self.pss(""), "PG-PERF-002")["gozlem"], {"yuklu": False, "izleme": "top"})

    def test_bilinmeyen_deger(self):
        self.assertEqual(durum(self.pss("pg_stat_statements", None), "PG-PERF-002"), ("UNKNOWN", "eksik_veri"))
        self.assertEqual(durum(self.pss("pg_stat_statements", "hepsi"), "PG-PERF-002"), ("UNKNOWN", "gecersiz_veri"))


class GeciciDosyaTests(unittest.TestCase):
    TARAMA = "2026-11-10T12:00:00Z"   # temiz_belge olusturma zamani

    def gd(self, *satirlar):
        return belge(pg_gecici_dosya=[dict({"datname": "db%d" % i, "dosya": 1, "bayt": 0, "sifirlama_utc": None}, **s)
                                      for i, s in enumerate(satirlar)])

    def test_kullanim_yoksa_gecer(self):
        self.assertEqual(durum(self.gd({"dosya": 0}, {"dosya": 0}), "PG-PERF-003"), ("PASS", None))

    def test_pencere_bilinirse_gunluk_hiz(self):
        self.assertEqual(durum(self.gd({"bayt": 50 * GB, "sifirlama_utc": "2026-10-31T12:00:00Z"}), "PG-PERF-003"), ("PASS", None))   # 5 GB/gun
        k = kayit(self.gd({"bayt": 50 * GB, "sifirlama_utc": "2026-11-08T12:00:00Z"}), "PG-PERF-003")   # 25 GB/gun
        self.assertEqual((k["durum"], k["onem"]), ("WARNING", "dusuk"))
        self.assertEqual((k["bulgular"][0]["kanit"]["gunluk_bayt"], k["bulgular"][0]["kanit"]["olcum_gunu"]), (25 * GB, 2.0))
        self.assertEqual(onem(self.gd({"bayt": 300 * GB, "sifirlama_utc": "2026-11-09T12:00:00Z"}), "PG-PERF-003"), ("WARNING", "orta"))
        # bir saatlik pencere bir gun sayilir: kisa pencere hizi buyutmez
        self.assertEqual(durum(self.gd({"bayt": 5 * GB, "sifirlama_utc": "2026-11-10T11:00:00Z"}), "PG-PERF-003"), ("PASS", None))

    def test_pencere_bilinmezse_bilgi(self):
        k = kayit(self.gd({"bayt": 3 * GB}, {"bayt": GB, "sifirlama_utc": "2026-10-31T12:00:00Z"}), "PG-PERF-003")
        self.assertEqual((k["durum"], k["onem"]), ("WARNING", "bilgi"))
        self.assertEqual(k["bulgular"][0]["kanit"]["pencere_bilinmeyen_veritabani"], 1)
        self.assertEqual(k["gozlem"], {"gecici_bayt": 4 * GB, "gecici_dosya": 2})

    def test_gecersiz(self):
        self.assertEqual(durum(self.gd({"bayt": 5, "sifirlama_utc": "dun"}), "PG-PERF-003"), ("UNKNOWN", "gecersiz_veri"))
        self.assertEqual(durum(self.gd({"bayt": -5}), "PG-PERF-003"), ("UNKNOWN", "gecersiz_veri"))


class YedekSunucuTests(unittest.TestCase):
    """Yedek sunucuda tablo istatistikleri (olu satir, indeks kullanimi) tutulmaz ve arsivleme birincilin isidir:
    gercek PostgreSQL 16 yedeginde olu satir kurali veri yokken temiz cikiyordu. Bu kurallar yedekte uygulanmaz."""
    BIRINCIL = {"PG-MAINT-003", "PG-MAINT-005", "PG-BACKUP-001"}

    def rol(self, yedek):
        b = test_tarama.temiz_belge()
        if yedek is None:
            del b["kontroller"]["pg_sunucu_rolu"]
        else:
            b["kontroller"]["pg_sunucu_rolu"]["satirlar"] = [{"yedek": yedek}]
        return b

    def test_birincile_ozgu_kurallar(self):
        self.assertEqual({k.kimlik for k in kurallar.KURALLAR if k.birincil}, self.BIRINCIL)
        self.assertEqual(katalog.PG_BY_ID["pg_sunucu_rolu"]["en_az"], 0)
        self.assertIn("pg_sunucu_rolu", kurallar.BILGI)

    def test_yedekte_uygulanmaz_digerleri_etkilenmez(self):
        b = self.rol(True)
        b["kontroller"]["pg_olu_satir"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "relname": "t", "canli": 1, "olu": 50000,
                                                        "son_autovacuum": None}]
        for k in kurallar.incele(b).kayitlar:
            if k["kural"] in self.BIRINCIL:
                self.assertEqual((k["durum"], k["neden"], k["bulgular"]), ("NOT_APPLICABLE", "birincil_degil", []), k["kural"])
            elif k["kural"] not in ("PG-HA-001", "PG-HA-002"):
                self.assertEqual(k["durum"], "PASS", k["kural"])
        self.assertTrue(kurallar.incele(b).baglam["yedek"])
        for k in kurallar.incele(self.rol(False)).kayitlar:
            if k["kural"] in self.BIRINCIL:
                self.assertEqual(k["durum"], "PASS", k["kural"])

    def test_rol_bilinmiyorsa_gecemez_bulgu_yine_raporlanir(self):
        for b in (self.rol(None), self.rol("evet")):
            for kimlik in self.BIRINCIL:
                self.assertEqual(durum(b, kimlik), ("UNKNOWN", "sunucu_rolu_bilinmiyor"), kimlik)
        b = self.rol(None)
        b["kontroller"]["pg_olu_satir"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "relname": "t", "canli": 1, "olu": 50000,
                                                        "son_autovacuum": None}]
        self.assertEqual(durum(b, "PG-MAINT-003")[0], "WARNING")

    def test_raporda_sunucu_rolu(self):
        from tarama import rapor
        for yedek, tr, en in ((True, "yedek sunucu: birincile özgü 3 denetim uygulanmaz", "standby: 3 primary-only checks are not applicable"),
                              (False, "birincil", "primary"), (None, "bilinmiyor", "unknown")):
            r = {"belge": self.rol(yedek), "bitis_utc": "2026-12-01T00:00:00Z"}
            self.assertIn("<dt>Sunucu rolü</dt><dd>%s</dd>" % tr, rapor.sayfa(dict(r, dil="tr"), "tr", "t"))
            self.assertIn("<dt>Server role</dt><dd>%s</dd>" % en, rapor.sayfa(dict(r, dil="en"), "en", "t"))


class MuhendislikEsikleriTests(unittest.TestCase):
    def test_esikler_onay_listesinde(self):
        metin = (ROOT / "docs" / "doldurulacak.md").read_text(encoding="utf-8")
        for anahtar in kurallar.MUHENDISLIK:
            self.assertIn("`%s`" % anahtar, metin, anahtar)


if __name__ == "__main__":
    unittest.main()
