"""Gecmis karsilastirmasi (tarama/gecmis.py): ayni firma ve ayni veritabani kimligi; kaybolan kanit cozulmus sayilmaz."""
import copy
import itertools
import json
import random
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import depo, gecmis, kanit, kurallar, rapor  # noqa: E402
import test_mssql  # noqa: E402
import test_puan  # noqa: E402
import test_tarama  # noqa: E402

KUME = "a" * 64
GERCEK = ROOT / "tests" / "veri" / "surum" / "16"


def belge(kume=KUME, yedek=False, zaman="2026-11-10T12:00:00Z"):
    b = test_tarama.temiz_belge()
    b["kontroller"]["pg_kume_kimligi"]["satirlar"] = [{"kume": kume}]
    b["kontroller"]["pg_sunucu_rolu"]["satirlar"] = [{"yedek": yedek}]
    b["olusturma_utc"] = zaman
    return b


def kayit(durum, onem=None, neden=None):
    return {"kural": "PG-X-001", "kategori": "bakim", "durum": durum, "onem": onem, "neden": neden}


class KimlikTests(unittest.TestCase):
    def test_kume_ozeti_ve_rol(self):
        self.assertEqual(gecmis.kimlik(belge()), "postgresql:%s:birincil" % KUME)
        self.assertEqual(gecmis.kimlik(belge(yedek=True)), "postgresql:%s:yedek" % KUME)
        self.assertNotEqual(gecmis.kimlik(belge()), gecmis.kimlik(belge(kume="b" * 64)))

    def test_kimlik_yoksa_karsilastirma_yok(self):
        b = belge()
        del b["kontroller"]["pg_kume_kimligi"]
        bozuk = [b, belge(kume="A" * 64), belge(kume="a" * 63), belge(kume=None), belge(yedek=None), belge(yedek="hayir"),
                 test_mssql.temiz_mssql(), {"motor": "postgresql", "kontroller": "x"}, "x"]
        b2 = belge()
        b2["kontroller"]["pg_kume_kimligi"] = {"durum": "hata", "neden": "yetki"}
        b3 = belge()
        b3["kontroller"]["pg_kume_kimligi"]["satirlar"] *= 2
        for b in bozuk + [b2, b3]:
            self.assertIsNone(gecmis.kimlik(b), repr(b)[:80])

    def test_gercek_sunucuda_birincil_ve_yedek_ayni_kume_farkli_rol(self):
        mon, yed, duz = (json.loads((GERCEK / ("%s.json" % h)).read_text(encoding="utf-8")) for h in ("pg_monitor", "yedek", "yetkisiz"))
        km, ky = gecmis.kimlik(mon), gecmis.kimlik(yed)
        self.assertTrue(km and ky)
        self.assertEqual(km.split(":")[1], ky.split(":")[1])   # ayni kume tanimlayicisi
        self.assertEqual((km.split(":")[2], ky.split(":")[2]), ("birincil", "yedek"))
        self.assertEqual(gecmis.kimlik(duz), km)                 # yetkisiz hesap da okur


class DurumTests(unittest.TestCase):
    SINIFLAR = {"S": [kayit("FAIL", "kritik"), kayit("FAIL", "yuksek"), kayit("WARNING", "orta"), kayit("WARNING", "bilgi")],
                "T": [kayit("PASS")],
                "Y": [kayit("NOT_APPLICABLE", neden="slot_yok")],
                "B": [kayit("UNKNOWN", neden="eksik_veri"), kayit("UNAVAILABLE", neden="yetki"),
                      kayit("NOT_APPLICABLE", neden="birincil_degil"), None]}

    def test_siniflar(self):
        for s, kayitlar in self.SINIFLAR.items():
            for k in kayitlar:
                self.assertEqual(gecmis.sinif(k), s, k)

    def test_tum_gecisler(self):
        beklenen = {("S", "T"): "RESOLVED", ("S", "Y"): "RESOLVED", ("S", "B"): "UNKNOWN",
                    ("T", "S"): "REGRESSED", ("Y", "S"): "NEW", ("B", "S"): "UNKNOWN"}
        for o, y in itertools.product("STYB", repeat=2):
            for ok, yk in itertools.product(self.SINIFLAR[o], self.SINIFLAR[y]):
                d = gecmis.durum(ok, yk)
                if (o, y) == ("S", "S"):
                    agir = kanit.ONEM_SIRASI.index(yk["onem"]) < kanit.ONEM_SIRASI.index(ok["onem"])
                    self.assertEqual(d, "REGRESSED" if agir else "PERSISTING", (ok, yk))
                else:
                    self.assertEqual(d, beklenen.get((o, y)), (o, y, ok, yk))

    def test_kaybolan_kanit_cozulmus_sayilmaz(self):
        for once in self.SINIFLAR["S"]:
            for simdi in self.SINIFLAR["B"]:
                self.assertEqual(gecmis.durum(once, simdi), "UNKNOWN")
                self.assertNotEqual(gecmis.durum(once, simdi), "RESOLVED")


class KarsilastirmaTests(unittest.TestCase):
    def test_gercek_belgede_duzeltme_ve_bozulma(self):
        once = json.loads((GERCEK / "pg_monitor.json").read_text(encoding="utf-8"))
        simdi = copy.deepcopy(once)
        k = simdi["kontroller"]
        k["pg_slot"]["satirlar"] = []                               # etkin olmayan slot kaldirildi: konu yok
        k["pg_tablo_autovacuum"]["satirlar"] = []                   # tablolar duzeltildi ama bir veritabani taranmadi
        k["pg_autovacuum"]["satirlar"][0]["setting"] = "off"        # autovacuum kapatildi: once temizdi
        del k["pg_arsiv"]                                           # arsiv kaniti kayboldu (once uyari vardi)
        k["pg_xid_yasi"]["satirlar"][0]["mxid_yas"] = 900000000     # multixact yasi esigi asti
        simdi["olusturma_utc"] = "2026-11-20T12:00:00Z"
        c = gecmis.karsilastir(once, simdi)
        d = {x["kural"]: x["durum"] for x in c.kurallar}
        self.assertEqual(d["PG-HA-001"], "RESOLVED")
        self.assertEqual(d["PG-MAINT-007"], "UNKNOWN")              # kisim kapsamla cozuldu denmez
        self.assertEqual(d["PG-MAINT-006"], "REGRESSED")
        self.assertEqual(d["PG-MAINT-008"], "REGRESSED")
        self.assertEqual(d["PG-BACKUP-001"], "UNKNOWN")             # kaybolan kanit
        self.assertEqual(d["PG-SEC-001"], "PERSISTING")
        self.assertNotIn("PG-MAINT-001", d)                         # iki taramada da temiz
        ac = {x["kural"]: x for x in c.kurallar}
        self.assertEqual(ac["PG-BACKUP-001"]["neden"], "kanit_kayboldu")
        self.assertEqual(c.onceki_puan.genel, test_puan.puan.hesapla(kurallar.incele(once)).genel)
        self.assertEqual(c.yeni_puan.genel, test_puan.puan.hesapla(kurallar.incele(simdi)).genel)
        self.assertLess(c.yeni_puan.kapsam, c.onceki_puan.kapsam)
        self.assertFalse(c.katalog_farkli)
        sira = [x["durum"] for x in c.kurallar]
        self.assertEqual(sira, sorted(sira, key=gecmis.DURUMLAR.index))   # once yeni ve kotulesen

    def test_once_olculemeyen_sorun_yeni_sayilmaz(self):
        once, simdi = belge(), belge(zaman="2026-11-20T12:00:00Z")
        once["kontroller"]["pg_tls_parola"] = {"durum": "hata", "neden": "yetki"}
        simdi["kontroller"]["pg_tls_parola"]["satirlar"][0]["ssl"] = "off"
        x = next(x for x in gecmis.karsilastir(once, simdi).kurallar if x["kural"] == "PG-SEC-001")
        self.assertEqual((x["durum"], x["neden"]), ("UNKNOWN", "onceki_kanit_yok"))

    def test_rastgele_belgelerde_kurallar(self):
        r = random.Random(13)
        for _ in range(400):
            once, simdi = test_puan.rastgele_pg(r), test_puan.rastgele_pg(r)
            for b in (once, simdi):
                for cid in r.sample(sorted(b["kontroller"]), r.randint(0, 3)):
                    del b["kontroller"][cid]
            c = gecmis.karsilastir(once, simdi)
            o = {k["kural"]: k for k in kurallar.incele(once).kayitlar}
            y = {k["kural"]: k for k in kurallar.incele(simdi).kayitlar}
            for x in c.kurallar:
                so, sy = gecmis.sinif(o[x["kural"]]), gecmis.sinif(y[x["kural"]])
                self.assertIn("S", (so, sy))
                if x["durum"] == "RESOLVED":
                    self.assertIn(sy, ("T", "Y"))      # cozuldu ancak kanitla
                if so == "S" and sy == "B":
                    self.assertEqual(x["durum"], "UNKNOWN")
                if x["durum"] == "NEW":
                    self.assertEqual(so, "Y")
            self.assertEqual({x["kural"] for x in c.kurallar},
                             {k for k in o if "S" in (gecmis.sinif(o[k]), gecmis.sinif(y[k]))})


class OncekiRaporTests(unittest.TestCase):
    def setUp(self):
        self.con = depo.baglan(str(Path(tempfile.mkdtemp()) / "t.sqlite"))
        self.firma = depo.firma_kaydet(self.con, "ornek.com.tr", "Ornek", "a@ornek.com.tr", "tarama")["id"]
        self.diger = depo.firma_kaydet(self.con, "baska.com", "Baska", "a@baska.com", "tarama")["id"]

    def ekle(self, token, b, firma=None, dogrulandi=True):
        depo.rapor_ekle(self.con, token, "postgresql", "tr", b, self.firma if firma is None else firma, dogrulandi=dogrulandi)
        return depo.rapor_getir(self.con, token) if dogrulandi else None

    def test_ayni_firma_ayni_kimlik_onceki_en_yeni(self):
        self.ekle("t1", belge(zaman="2026-11-01T00:00:00Z"))
        self.ekle("t2", belge(zaman="2026-11-05T00:00:00Z"))
        self.ekle("t3", belge(kume="b" * 64, zaman="2026-11-06T00:00:00Z"))      # baska kume
        self.ekle("t4", belge(yedek=True, zaman="2026-11-07T00:00:00Z"))         # ayni kumenin yedegi
        self.ekle("t5", belge(zaman="2026-11-08T00:00:00Z"), firma=self.diger)   # baska firma
        self.ekle("t6", belge(zaman="2026-11-09T00:00:00Z"), dogrulandi=False)   # e-posta dogrulamasi bekliyor
        self.ekle("t7", belge(zaman="2026-11-20T00:00:00Z"))                     # daha sonraki tarama
        simdi = self.ekle("t8", belge(zaman="2026-11-10T00:00:00Z"))
        self.assertEqual(depo.onceki_rapor(self.con, simdi)["belge"]["olusturma_utc"], "2026-11-05T00:00:00Z")

    def test_ayni_dosya_kendisiyle_ve_suresi_dolanla_karsilastirilmaz(self):
        self.ekle("t1", belge())
        simdi = self.ekle("t2", belge())                       # ayni dosya ikinci kez yuklendi
        self.assertIsNone(depo.onceki_rapor(self.con, simdi))
        self.ekle("t3", belge(zaman="2026-11-01T00:00:00Z"))
        self.con.execute("UPDATE rapor SET bitis_utc = '2000-01-01T00:00:00Z' WHERE id = 3")
        self.con.commit()
        self.assertIsNone(depo.onceki_rapor(self.con, simdi))

    def test_bozuk_eski_kayit_atlanir(self):
        self.ekle("t1", belge(zaman="2026-11-01T00:00:00Z"))
        self.ekle("t2", belge(zaman="2026-11-02T00:00:00Z"))
        self.con.execute("UPDATE rapor SET belge_json = '{bozuk' WHERE id = 2")
        self.con.commit()
        simdi = self.ekle("t3", belge(zaman="2026-11-03T00:00:00Z"))
        self.assertEqual(depo.onceki_rapor(self.con, simdi)["id"], 1)

    def test_kimliksiz_ya_da_firmasiz_rapor(self):
        self.ekle("t1", belge(zaman="2026-11-01T00:00:00Z"))
        b = belge()
        del b["kontroller"]["pg_kume_kimligi"]
        self.assertIsNone(depo.onceki_rapor(self.con, self.ekle("t2", b)))
        depo.rapor_ekle(self.con, "t3", "postgresql", "tr", belge(), None)
        self.assertIsNone(depo.onceki_rapor(self.con, depo.rapor_getir(self.con, "t3")))


class GosterimTests(unittest.TestCase):
    def sayfa(self, once, simdi, dil="tr"):
        r = {"belge": simdi, "bitis_utc": "2026-12-01T00:00:00Z", "dil": dil}
        o = None if once is None else {"belge": once}
        return rapor.sayfa(r, dil, "t", onceki=o)

    def test_karsilastirma_bolumu(self):
        once, simdi = belge(), belge(zaman="2026-11-20T12:00:00Z")
        once["kontroller"]["pg_tls_parola"]["satirlar"][0]["ssl"] = "off"      # cozuldu
        simdi["kontroller"]["pg_autovacuum"]["satirlar"][0]["setting"] = "off"  # kotulesti
        del simdi["kontroller"]["pg_log_ayarlari"]
        once["kontroller"]["pg_log_ayarlari"]["satirlar"][0]["setting"] = "off"  # kanit kayboldu
        c = gecmis.karsilastir(once, simdi)
        tr, en = self.sayfa(once, simdi), self.sayfa(once, simdi, "en")
        self.assertIn("Önceki taramayla karşılaştırma", tr)
        self.assertIn("2026-11-10T12:00:00Z", tr)
        self.assertIn("%d/100 → %d/100" % (c.onceki_puan.genel, c.yeni_puan.genel), tr)
        self.assertIn("%%%d → %%%d" % (c.onceki_puan.kapsam, c.yeni_puan.kapsam), tr)
        for metin in ("Çözüldü", "Kötüleşti", "Bilinmiyor", "bu taramada kanıt yetersiz: çözüldü sayılmaz"):
            self.assertIn(metin, tr)
        for metin in ("Comparison with the previous scan", "Resolved", "Regressed", "not enough evidence in this scan: not counted as resolved",
                      "%d%% → %d%%" % (c.onceki_puan.kapsam, c.yeni_puan.kapsam)):
            self.assertIn(metin, en)
        self.assertLess(tr.index("Önceki taramayla karşılaştırma"), tr.index("finding-card"))

    def test_onceki_yoksa_bolum_yok_katalog_farkliysa_not(self):
        self.assertNotIn("Önceki taramayla karşılaştırma", self.sayfa(None, belge()))
        once = belge()
        once["katalog_sha256"] = "0" * 64
        self.assertIn("toplayıcının eski sürümüyle", self.sayfa(once, belge(zaman="2026-11-20T12:00:00Z")))


class SunucuTests(test_tarama._SunucuTaban):
    def test_ikinci_taramanin_raporu_oncekiyle_karsilastirilir(self):
        bugun = datetime.now(timezone.utc)
        once = belge(zaman=(bugun - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        once["kontroller"]["pg_tls_parola"]["satirlar"][0]["ssl"] = "off"
        simdi = belge(zaman=(bugun - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        r1 = self.yukle(json.dumps(once).encode())
        r2 = self.yukle(json.dumps(simdi).encode())
        self.assertEqual((r1.status, r2.status), (303, 303))
        g1 = self.get(r1.getheader("Location"))[1].decode()
        g2 = self.get(r2.getheader("Location"))[1].decode()
        self.assertNotIn("Önceki taramayla karşılaştırma", g1)
        self.assertIn("Önceki taramayla karşılaştırma", g2)
        self.assertIn("Çözüldü", g2)
        con = depo.baglan(self.db)
        olaylar = [x[0] for x in con.execute("SELECT olay FROM denetim")]
        self.assertTrue(any(o.startswith("rapor goruntulendi #2") and "karsilastirma #1" in o for o in olaylar), olaylar)
        self.assertIsNone(depo.denetim_dogrula(con))


if __name__ == "__main__":
    unittest.main()
