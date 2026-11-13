"""Saglik puani ve kanit kapsami (tarama/puan.py): bilinmeyen durum puani yukseltmez, aciklanabilir, katsayilar ayarlanir."""
import copy
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import kanit, katalog, kurallar, kurallar_mssql, puan, rapor  # noqa: E402
import test_mssql  # noqa: E402
import test_tarama  # noqa: E402

GERCEK = ROOT / "tests" / "veri" / "surum" / "16"
TUM = kurallar.KURALLAR + kurallar_mssql.KURALLAR


def gercek(hesap):
    return json.loads((GERCEK / ("%s.json" % hesap)).read_text(encoding="utf-8"))


def ornekler():
    """Degerlendirme ornekleri: temiz belgeler, gercek PostgreSQL 16 ciktilari, bulgulu ve bozuk belgeler."""
    b = test_tarama.temiz_belge()
    b["kontroller"]["pg_xid_yasi"]["satirlar"][0]["yas"] = 1700000000
    b["kontroller"]["pg_olu_satir"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "relname": "t", "canli": 1, "olu": 50000, "son_autovacuum": None}]
    b["kontroller"]["pg_md5_roller"] = {"durum": "hata", "neden": "yetki"}
    m = test_mssql.temiz_mssql()
    m["kontroller"]["ms_sysadmin"]["satirlar"] = [{"giris": "dba", "tur": "SQL_LOGIN", "devre_disi": 0}]
    m["kontroller"]["ms_yedek"] = {"durum": "hata", "neden": "yetki"}
    return [test_tarama.temiz_belge(), test_mssql.temiz_mssql(), gercek("pg_monitor"), gercek("yetkisiz"), gercek("super"), b, m,
            {"motor": "postgresql", "kontroller": {}}]


class PuanTests(unittest.TestCase):
    def test_temiz_belge_tam_puan_tam_kapsam(self):
        for belge in (test_tarama.temiz_belge(), test_mssql.temiz_mssql()):
            p = puan.hesapla(kurallar.incele(belge))
            self.assertEqual((p.genel, p.kapsam), (100, 100))
            self.assertEqual(p.kayiplar, [])

    def test_bilinmeyen_durum_puani_yukseltmez(self):
        """Olculen her kural tek tek bilinmiyor yapilir: puan hicbir zaman artmaz (kategori puani da)."""
        for belge in ornekler():
            s = kurallar.incele(belge)
            once = puan.hesapla(s)
            for i, k in enumerate(s.kayitlar):
                for yeni in ("UNKNOWN", "UNAVAILABLE"):
                    if k["durum"] in ("NOT_APPLICABLE", yeni):
                        continue
                    s2 = copy.copy(s)
                    s2.kayitlar = list(s.kayitlar)
                    s2.kayitlar[i] = dict(k, durum=yeni, onem=None, bulgular=[], guven=None)
                    sonra = puan.hesapla(s2)
                    self.assertLessEqual(sonra.ham, once.ham + 1e-9, (k["kural"], k["durum"], yeni))
                    self.assertLessEqual(sonra.kategoriler[k["kategori"]]["ham"], once.kategoriler[k["kategori"]]["ham"] + 1e-9)
                    self.assertLessEqual(sonra.kapsam_ham, once.kapsam_ham)

    def test_belgeden_kanit_eksilince_puan_artmaz(self):
        """Uctan uca: rastgele belgelerden denetim silinir, hataya cevrilir ya da hesap bilgisi kaldirilir. Genel puan,
        kategori puanlari ve kapsam hicbir zaman artmaz (kaybolan kanit cozulmus sorun sayilmaz)."""
        r = random.Random(1113)
        for i in range(800):
            b = rastgele_pg(r) if i % 2 == 0 else rastgele_ms(r)
            once = puan.hesapla(kurallar.incele(b))
            b2 = copy.deepcopy(b)
            for cid in r.sample(sorted(b2["kontroller"]), r.randint(1, 4)):
                if r.random() < 0.5:
                    del b2["kontroller"][cid]
                else:
                    b2["kontroller"][cid] = {"durum": "hata", "neden": r.choice(["yetki", "zaman_asimi", "desteklenmiyor", "hata"])}
            if r.random() < 0.2:
                del b2["superuser"]
            sonra = puan.hesapla(kurallar.incele(b2))
            self.assertLessEqual(sonra.ham, once.ham + 1e-9, i)
            self.assertLessEqual(sonra.kapsam_ham, once.kapsam_ham + 1e-9, i)
            for kat, d in sonra.kategoriler.items():
                self.assertLessEqual(d["ham"], once.kategoriler[kat]["ham"] + 1e-9, (i, kat))

    def test_kaybolan_kanit_puani_iyilestirmez(self):
        b = gercek("pg_monitor")
        once = puan.hesapla(kurallar.incele(b))
        self.assertEqual(kurallar.incele(b).kayitlar[[k.kimlik for k in kurallar.KURALLAR].index("PG-HA-001")]["durum"], "FAIL")
        del b["kontroller"]["pg_slot"]   # basarisiz slot kurali artik olculemiyor
        sonra = puan.hesapla(kurallar.incele(b))
        self.assertLessEqual(sonra.ham, once.ham)
        self.assertLess(sonra.kapsam, once.kapsam)

    def test_formul_ve_dokum(self):
        """puan = 100 * toplam(agirlik * kredi) / toplam(agirlik); kayiplarin toplami 100 - puan."""
        for belge in ornekler():
            s = kurallar.incele(belge)
            p = puan.hesapla(s)
            agirlik = {k.kimlik: puan.VARSAYILAN["agirlik"][k.risk] for k in TUM}
            uyg = [k for k in s.kayitlar if k["durum"] != "NOT_APPLICABLE"]
            toplam = sum(agirlik[k["kural"]] for k in uyg)
            olculen = sum(1 for k in uyg if k["durum"] in ("PASS", "WARNING", "FAIL"))
            self.assertEqual((p.kapsam_ham, p.kapsam), (100 * olculen / len(uyg), 100 * olculen // len(uyg)))   # kapsam asagi yuvarlanir
            if not any(k["durum"] in ("PASS", "WARNING", "FAIL") and agirlik[k["kural"]] > 0 for k in uyg):
                self.assertIsNone(p.genel)   # agirlikli kanit yok: puan hesaplanamadi
                continue
            beklenen = 100 * sum(agirlik[k["kural"]] * puan.kredi(k) for k in uyg) / toplam
            self.assertAlmostEqual(p.ham, beklenen)
            self.assertAlmostEqual(sum(x["kayip"] for x in p.kayiplar), 100 - p.ham)
            self.assertAlmostEqual(p.bulgu_kaybi + p.kanit_kaybi, 100 - p.ham)
            self.assertTrue(p.genel <= p.ham + 1e-9 < p.genel + 1)   # asagi yuvarlanir
            self.assertEqual(p.genel == 100, not p.kayiplar)          # 100 yalniz kayip yoksa
            self.assertTrue(all(x["kayip"] > 0 for x in p.kayiplar))
            self.assertEqual([x["kural"] for x in p.kayiplar if x["tur"] == "kanit"],
                             [x["kural"] for x in p.kayiplar if x["durum"] in ("UNKNOWN", "UNAVAILABLE")])

    def test_kredi(self):
        k = lambda d, o=None: {"durum": d, "onem": o}  # noqa: E731
        self.assertEqual([puan.kredi(k("PASS")), puan.kredi(k("FAIL", "kritik")), puan.kredi(k("UNKNOWN")), puan.kredi(k("UNAVAILABLE"))],
                         [1.0, 0.0, 0.0, 0.0])
        self.assertEqual([puan.kredi(k("WARNING", o)) for o in ("orta", "dusuk", "bilgi")], [0.5, 0.75, 1.0])

    def test_kategori_puani_ve_kapsami(self):
        s = kurallar.incele(gercek("pg_monitor"))
        p = puan.hesapla(s)
        for kat, d in p.kategoriler.items():
            kayit = [k for k in s.kayitlar if k["kategori"] == kat and k["durum"] != "NOT_APPLICABLE"]
            self.assertEqual(d["uygulanabilir"], len(kayit), kat)
            self.assertEqual(d["olculen"], sum(1 for k in kayit if k["durum"] in ("PASS", "WARNING", "FAIL")), kat)
        self.assertNotIn("konfigurasyon", p.kategoriler)   # PostgreSQL'de bu kategoride kural yok: puanlanmaz
        guv = [k for k in s.kayitlar if k["kategori"] == "guvenlik"]
        w = {k.kimlik: puan.VARSAYILAN["agirlik"][k.risk] for k in kurallar.KURALLAR}
        self.assertAlmostEqual(p.kategoriler["guvenlik"]["ham"], 100 * sum(w[k["kural"]] * puan.kredi(k) for k in guv) / sum(w[k["kural"]] for k in guv))

    def test_kucuk_kayip_100_gostermez(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_log_ayarlari"]["satirlar"][0]["setting"] = "off"   # yalniz dusuk riskli bir uyari
        p = puan.hesapla(kurallar.incele(b))
        self.assertEqual((p.genel, p.kapsam, [x["kural"] for x in p.kayiplar]), (99, 100, ["PG-SEC-007"]))
        self.assertGreater(p.ham, 99.5)   # yukari yuvarlansa 100 gorunurdu

    def test_kanit_yoksa_puan_yok(self):
        p = puan.hesapla(kurallar.incele({"motor": "postgresql", "kontroller": {}}))
        self.assertEqual((p.genel, p.kapsam), (None, 0))


class KatsayiTests(unittest.TestCase):
    def test_katsayilar_ayarlanir(self):
        s = kurallar.incele(gercek("pg_monitor"))
        varsayilan = puan.hesapla(s)
        k = puan.katsayi_dogrula({"agirlik": {"kritik": 30}})
        self.assertEqual(k["agirlik"]["yuksek"], puan.VARSAYILAN["agirlik"]["yuksek"])   # verilmeyen varsayilan kalir
        self.assertLess(puan.hesapla(s, k).ham, varsayilan.ham)   # kritik riskli kural basarisiz: agirligi artinca puan duser
        k = puan.katsayi_dogrula({"kategori_carpani": {"ha_dr": 0}})
        self.assertNotEqual(puan.hesapla(s, k).ham, varsayilan.ham)

    def test_gecersiz_katsayi_reddedilir(self):
        for kotu in ({"agirlik": {"kritik": -1}}, {"agirlik": {"cok": 1}}, {"kredi_uyari": {"orta": 1.5}}, {"kredi_uyari": {"orta": "yarim"}},
                     {"kredi": {"UNKNOWN": 1}}, {"kategori_carpani": {"guvenlik": True}}, {"kategori_carpani": {"x": 1}}, [], "x",
                     {"agirlik": {k: 0 for k in kanit.ONEM_SIRASI}}, {"kategori_carpani": {k: 0 for k in kanit.KATEGORILER}},
                     {"agirlik": {"kritik": float("nan")}}, {"agirlik": {"kritik": float("inf")}}, {"agirlik": {"kritik": 10 ** 6}},
                     {"agirlik": []}, {"kredi_uyari": {"kritik": 0.5}}):
            with self.assertRaises(puan.PuanAyarHatasi, msg=repr(kotu)):
                puan.katsayi_dogrula(kotu)

    def test_ortamdan_yukleme(self):
        d = Path(tempfile.mkdtemp())
        (d / "puan.json").write_text(json.dumps({"agirlik": {"kritik": 20}}), encoding="utf-8")
        self.assertEqual(puan.ortamdan({"ALIG_PUAN_AYARI": str(d / "puan.json")})["agirlik"]["kritik"], 20)
        self.assertEqual(puan.ortamdan({}), puan.VARSAYILAN)
        (d / "bozuk.json").write_text("{", encoding="utf-8")
        (d / "nan.json").write_text('{"agirlik": {"kritik": NaN}}', encoding="utf-8")
        (d / "cift.json").write_text('{"agirlik": {"kritik": 1, "kritik": 50}}', encoding="utf-8")
        (d / "gecersiz.json").write_text('{"agirlik": {"kritik": -1}}', encoding="utf-8")
        (d / "buyuk.json").write_text(" " * 70000 + "{}", encoding="utf-8")
        (d / "bom.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"agirlik": {"kritik": 15}}).encode())
        self.assertEqual(puan.ortamdan({"ALIG_PUAN_AYARI": str(d / "bom.json")})["agirlik"]["kritik"], 15)   # Windows duzenleyicisi
        for yol in (d / "bozuk.json", d / "yok.json", d / "nan.json", d / "cift.json", d / "gecersiz.json", d / "buyuk.json", d):
            with self.assertRaises(puan.PuanAyarHatasi):
                puan.ortamdan({"ALIG_PUAN_AYARI": str(yol)})


class BaslangicTests(unittest.TestCase):
    """Gecersiz puan ayariyla iki servis de baslamaz; gecerli ayar etkin olur (rapor ve panel ayni katsayilari kullanir)."""

    def setUp(self):
        eski = puan.ETKIN
        self.addCleanup(setattr, puan, "ETKIN", eski)
        self.d = Path(tempfile.mkdtemp())
        (self.d / "kotu.json").write_text('{"agirlik": {"kritik": -1}}', encoding="utf-8")
        (self.d / "iyi.json").write_text('{"agirlik": {"kritik": 12}}', encoding="utf-8")

    def calistir(self, modul, argv, ayar):
        ortam = {k: v for k, v in os.environ.items() if not k.startswith("ALIG_")}
        ortam[puan.ORTAM] = str(self.d / ayar)
        with mock.patch.dict(os.environ, ortam, clear=True), mock.patch.object(modul, "ThreadingHTTPServer") as sunucu, \
                mock.patch("builtins.print"):
            modul.main(argv)
        return sunucu

    def test_tarama_ve_yonetim_servisi(self):
        from tarama import server as tserver
        from yonetim import server as yserver
        for modul, db in ((tserver, "t.sqlite"), (yserver, "y.sqlite")):
            puan.ETKIN = copy.deepcopy(puan.VARSAYILAN)
            with self.assertRaises(SystemExit) as cm:
                self.calistir(modul, ["--db", str(self.d / db)], "kotu.json")
            self.assertIn("ALIG_PUAN_AYARI=", str(cm.exception))
            self.assertIn("agirlik.kritik", str(cm.exception))
            with self.assertRaises(SystemExit):
                self.calistir(modul, ["--db", str(self.d / db)], "yok.json")
            self.assertEqual(puan.ETKIN, puan.VARSAYILAN)   # hatali ayar etkin olmadi
            sunucu = self.calistir(modul, ["--db", str(self.d / db)], "iyi.json")
            sunucu.return_value.serve_forever.assert_called_once_with()
            self.assertEqual(puan.ETKIN["agirlik"]["kritik"], 12)


class RiskTests(unittest.TestCase):
    def test_her_kuralin_risk_duzeyi_var(self):
        for k in TUM:
            self.assertIn(k.risk, kanit.ONEM_SIRASI, k.kimlik)

    def test_gecersiz_risk_kayit_edilemez(self):
        kural = kanit.kayitci([], "postgresql")
        for kotu in (("guvenlik", "cok", "HIGH"), ("yok", "orta", "HIGH"), ("guvenlik", "orta", "VERY")):
            with self.assertRaises(ValueError):
                kural("PG-SEC-099", *kotu, [], {}, {})

    def test_bulgu_onemi_kural_riskini_asmaz(self):
        """Rastgele gecerli belgelerde: kural, bildirdigi risk duzeyinden daha onemli bulgu uretmez; en yuksek risk de gorulur."""
        r = random.Random(20261113)
        risk = {k.kimlik: k.risk for k in TUM}
        gorulen = {}
        for i in range(3000):
            belge = rastgele_pg(r) if i % 2 == 0 else rastgele_ms(r)
            for b in kurallar.incele(belge).bulgular:
                self.assertGreaterEqual(kanit.ONEM_SIRASI.index(b["onem"]), kanit.ONEM_SIRASI.index(risk[b["kural"]]), (b["kural"], b["onem"]))
                g = gorulen.get(b["kural"])
                if g is None or kanit.ONEM_SIRASI.index(b["onem"]) < kanit.ONEM_SIRASI.index(g):
                    gorulen[b["kural"]] = b["onem"]
        for kimlik, o in gorulen.items():
            self.assertEqual(o, risk[kimlik], "%s: bildirilen risk %s ama en yuksek gorulen %s" % (kimlik, risk[kimlik], o))
        self.assertGreaterEqual(len(gorulen), len(TUM) - 2)


class GosterimTests(unittest.TestCase):
    def sayfa(self, belge, dil="tr"):
        return rapor.sayfa({"belge": belge, "bitis_utc": "2026-12-01T00:00:00Z", "dil": dil}, dil, "t")

    def test_rapor_puan_kapsam_ve_kategoriler(self):
        b = gercek("pg_monitor")
        p = puan.hesapla(kurallar.incele(b))
        tr, en = self.sayfa(b), self.sayfa(b, "en")
        self.assertIn("Sağlık puanı", tr)
        self.assertIn("%d/100" % p.genel, tr)
        self.assertIn("Kanıt kapsamı", tr)
        self.assertIn("%%%d" % p.kapsam, tr)
        self.assertIn("Health score", en)
        self.assertIn("Evidence coverage", en)
        self.assertIn("%d%%" % p.kapsam, en)
        for kat in p.kategoriler:
            self.assertIn(rapor.M["tr"]["kategori"][kat], tr)
        self.assertLess(tr.index("PG-HA-001"), tr.index("finding-card"))   # puani dusuren kural, bulgulardan once aciklamada

    def test_rapor_kanit_yoksa_puan_yazmaz(self):
        b = test_tarama.temiz_belge()
        b["kontroller"] = {cid: {"durum": "hata", "neden": "yetki"} for cid in b["kontroller"]}
        b.pop("superuser", None)   # tarama hesabi kurali da kanitsiz kalsin
        tr = self.sayfa(b)
        self.assertIn("hesaplanamadı", tr)
        self.assertNotIn("/100", tr)


def _ad(r):
    return r.choice(["a", "b", "satis", "x y"])


def rastgele_pg(r):
    b = test_tarama.temiz_belge()
    k = b["kontroller"]
    sec = r.choice
    k["pg_surum"]["satirlar"] = [{"surum_num": sec([100005, 120010, 130020, 140010, 150004, 160002, 170001, 180000])}]
    k["pg_xid_yasi"]["satirlar"] = [{"datname": _ad(r), "yas": sec([1000, 450000000, 1700000000]), "mxid_yas": 1, "freeze_max_age": 200000000}]
    k["pg_bosta_islem"]["satirlar"] = [{"usename": _ad(r), "durum": "idle in transaction", "sure_sn": sec([10, 700, 4000])} for _ in range(sec([0, 1, 2]))]
    k["pg_baglanti"]["satirlar"] = [{"kullanilan": sec([10, 80, 95]), "ust": 100}]
    k["pg_olu_satir"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "relname": _ad(r), "canli": sec([1, 100000]), "olu": sec([20000, 50000]), "son_autovacuum": None} for _ in range(sec([0, 1]))]
    k["pg_gecersiz_indeks"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "indexrelname": _ad(r)} for _ in range(sec([0, 1]))]
    k["pg_kullanilmayan_indeks"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "indexrelname": _ad(r), "bayt": 20000000} for _ in range(sec([0, 1]))]
    k["pg_sequence"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "sequencename": _ad(r), "oran": sec([0.6, 0.85, 0.97])} for _ in range(sec([0, 1]))]
    k["pg_slot"]["satirlar"] = [{"slot_name": _ad(r), "active": sec([True, False]), "wal_status": sec(["reserved", "lost", None]), "geri_bayt": 1} for _ in range(sec([0, 1]))]
    k["pg_arsiv"]["satirlar"] = [{"archive_mode": sec(["on", "off"]), "basarili": 1, "hatali": 0, "son_basari_utc": "2026-11-02T00:00:00Z",
                                  "son_hata_utc": sec([None, "2026-11-03T00:00:00Z"])}]
    k["pg_tls_parola"]["satirlar"] = [{"ssl": sec(["on", "off"]), "password_encryption": sec(["md5", "scram-sha-256"]), "ssl_min_protocol_version": sec(["TLSv1", "TLSv1.2"])}]
    k["pg_md5_roller"]["satirlar"] = [{"sayi": sec([0, 2])}]
    k["pg_super_roller"]["satirlar"] = [{"rolname": _ad(r), "rolcanlogin": True} for _ in range(sec([0, 1, 3]))]
    k["pg_public_create"]["satirlar"] = [{"veritabani": "postgres", "public_create": sec([True, False])}]
    k["pg_log_ayarlari"]["satirlar"] = [{"name": "log_connections", "setting": sec(["on", "off"])}, {"name": "log_disconnections", "setting": "on"}]
    b["superuser"] = sec([True, False])
    return b


def rastgele_ms(r):
    b = test_mssql.temiz_mssql()
    k = b["kontroller"]
    sec = r.choice
    k["ms_surum"]["satirlar"] = [{"ana_surum": sec([11, 13, 15, 16]), "surum": "x", "motor_turu": 3}]
    k["ms_yedek"]["satirlar"] = [{"veritabani": _ad(r), "kurtarma_modeli": "FULL", "tam_saat": sec([None, 10, 200]), "log_saat": sec([1, 30])}]
    k["ms_checkdb"]["satirlar"] = [{"veritabani": _ad(r), "gun": sec([2, 20, 46000])}]
    k["ms_db_ayar"]["satirlar"] = [{"veritabani": _ad(r), "kimlik": 5, "auto_shrink": sec([0, 1]), "auto_close": 0, "sayfa_dogrulama": sec(["CHECKSUM", "NONE"]),
                                    "durum": sec(["ONLINE", "SUSPECT"]), "trustworthy": sec([0, 1])}]
    ayar = {x["ad"]: x for x in k["ms_sunucu_ayar"]["satirlar"]}
    ayar["xp_cmdshell"]["deger"] = sec([0, 1])
    ayar["cross db ownership chaining"]["deger"] = sec([0, 1])
    ayar["max server memory (MB)"]["deger"] = sec([24000, 2147483647])
    ayar["cost threshold for parallelism"]["deger"] = sec([5, 50])
    k["ms_sa"]["satirlar"] = [{"devre_disi": sec([0, 1]), "adi_sa": 1}]
    k["ms_sysadmin"]["satirlar"] = [{"giris": "dba", "tur": "SQL_LOGIN", "devre_disi": sec([0, 1])}]
    k["ms_parola_politikasi"]["satirlar"] = [{"sayi": sec([0, 1])}]
    k["ms_tempdb"]["satirlar"] = [{"veri_dosyasi": sec([1, 4]), "cpu": 8}]
    k["ms_ag"]["satirlar"] = [{"grup": "g", "replika": "r", "saglik": sec(["HEALTHY", "NOT_HEALTHY"]), "rol": "PRIMARY", "baglanti": "CONNECTED"} for _ in range(sec([0, 1]))]
    k["ms_dosya_buyume"]["satirlar"] = [{"veritabani": "a", "dosya": "f", "tur": "LOG"} for _ in range(sec([0, 1]))]
    k["ms_sifreleme"]["satirlar"] = [{"toplam": 5, "sifreli": sec([5, 3])}]
    k["ms_acik_islem"]["satirlar"] = [{"giris": "a", "sure_sn": sec([10, 700, 4000])} for _ in range(sec([0, 1]))]
    k["ms_kimlik"]["satirlar"] = [{"yalniz_windows": sec([0, 1])}]
    b["superuser"] = sec([True, False])
    return b


if __name__ == "__main__":
    unittest.main()
