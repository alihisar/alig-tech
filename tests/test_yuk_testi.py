"""Logic tests of the load script deploy/yuk_testi.py (ALIG-TEST-001): small, fast, deterministic.

No timing value is asserted (it would be flaky); only counts, statuses, refusal rules and formatting.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT))
import yuk_testi  # noqa: E402
from tarama import depo, yukleme  # noqa: E402


class LoopbackTests(unittest.TestCase):
    def test_loopback_adresleri_kabul_edilir(self):
        for h in ("127.0.0.1", "127.1.2.3", "::1", "localhost"):
            self.assertTrue(yuk_testi.loopback_mi(h), h)

    def test_loopback_olmayanlar_reddedilir(self):
        for h in ("0.0.0.0", "10.0.0.5", "192.168.1.10", "8.8.8.8", "alig.tech", "example.com", "", "::", "2001:db8::1",
                  "127.0.0.1.evil.test", "localhost.evil.test", "::ffff:8.8.8.8"):
            self.assertFalse(yuk_testi.loopback_mi(h), h)

    def test_zorunlu_kontrol_firlatir(self):
        yuk_testi.loopback_zorunlu("127.0.0.1")
        with self.assertRaises(yuk_testi.Reddedildi):
            yuk_testi.loopback_zorunlu("alig.tech")

    def test_main_loopback_olmayan_hedefte_calismaz(self):
        self.assertEqual(yuk_testi.main(["--host", "alig.tech"]), 2)
        self.assertEqual(yuk_testi.main(["--host", "10.1.2.3"]), 2)

    def test_istemci_baglanmadan_once_reddeder(self):
        with self.assertRaises(yuk_testi.Reddedildi):
            yuk_testi.istek("alig.tech", 80, "GET", "/")


class OzetTests(unittest.TestCase):
    def test_yuzdelik_en_yakin_sira(self):
        v = [float(i) for i in range(1, 101)]
        self.assertEqual(yuk_testi.yuzdelik(v, 50), 50.0)
        self.assertEqual(yuk_testi.yuzdelik(v, 95), 95.0)
        self.assertEqual(yuk_testi.yuzdelik(v, 99), 99.0)
        self.assertEqual(yuk_testi.yuzdelik(v, 100), 100.0)
        self.assertEqual(yuk_testi.yuzdelik([7.0], 99), 7.0)
        self.assertIsNone(yuk_testi.yuzdelik([], 50))

    def test_ozet_sayilar(self):
        olcumler = [(0.010, 303, None), (0.020, 303, None), (0.030, 429, None), (0.0, None, "TimeoutError")]
        o = yuk_testi.ozet(olcumler, toplam_sn=2.0)
        self.assertEqual(o["istek"], 4)
        self.assertEqual(o["durumlar"], {"303": 2, "429": 1})
        self.assertEqual(o["hatalar"], {"TimeoutError": 1})
        self.assertEqual(o["gecikme_ms"]["min"], 10.0)
        self.assertEqual(o["gecikme_ms"]["max"], 30.0)
        self.assertEqual(o["gecikme_ms"]["p50"], 20.0)
        self.assertEqual(o["saniyede_istek"], 2.0)   # 4 requests in 2 s

    def test_ozet_bos_ve_yalniz_hata(self):
        o = yuk_testi.ozet([(0.0, None, "OSError")], toplam_sn=1.0)
        self.assertIsNone(o["gecikme_ms"])
        self.assertEqual(o["hatalar"], {"OSError": 1})
        self.assertEqual(yuk_testi.ozet([], toplam_sn=1.0)["istek"], 0)

    def test_esanli_calistirma_sirayi_ve_sayiyi_korur(self):
        sonuc = yuk_testi.esanli(lambda i: (0.001, 200 + i, None), 10, 4)
        self.assertEqual([s[1] for s in sonuc], [200 + i for i in range(10)])

    def test_esanli_istisnayi_hata_olarak_sayar(self):
        def is_(i):
            if i % 2:
                raise ConnectionResetError("x")
            return (0.001, 200, None)
        sonuc = yuk_testi.esanli(is_, 6, 3)
        self.assertEqual(sum(1 for s in sonuc if s[2] == "ConnectionResetError"), 3)
        self.assertEqual(sum(1 for s in sonuc if s[1] == 200), 3)


class GovdeTests(unittest.TestCase):
    def test_coklu_parca_alanlar(self):
        govde, ctype = yuk_testi.yukleme_govdesi(b'{"a":1}', "a@x.example.test", "Firma")
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        s = govde.decode()
        for ad in ("sirket", "eposta", "yetki", "dil", "dosya"):
            self.assertIn('name="%s"' % ad, s)
        self.assertIn('{"a":1}', s)

    def test_her_yukleme_ayri_firma_anahtari_verir(self):
        a = depo.firma_anahtari(yuk_testi.eposta(1))
        b = depo.firma_anahtari(yuk_testi.eposta(2))
        self.assertTrue(a and b and a != b)

    def test_ornek_belge_yuklemeden_gecer(self):
        belge = yukleme.coz(json.dumps(yuk_testi.ornek_belge()).encode(), ("postgresql",))
        self.assertEqual(belge["motor"], "postgresql")


class RaporMetniTests(unittest.TestCase):
    def test_rapor_ortam_ve_olcum_tasir_hedef_yazmaz(self):
        sonuc = {"ortam": {"cpu": 2, "python": "3.x", "sistem": "Linux", "sunucu": "s"},
                 "yukleme": yuk_testi.ozet([(0.01, 303, None)], 1.0),
                 "goruntuleme": yuk_testi.ozet([(0.01, 200, None)], 1.0),
                 "hiz_siniri": {"ayar": {"adres_siniri": 5, "pencere_sn": 3600, "sirket_hakki": 2, "sirket_gun": 30},
                                "ip": {"adet": 8, "durumlar": {"303": 5, "429": 3}, "retry_after": ["3600"], "ilk_429_sirasi": 6},
                                "sirket": {"adet": 4, "durumlar": {"303": 2, "429": 2}, "retry_after": ["2592000"], "ilk_429_sirasi": 3}},
                 "parametre": {"yukleme": 1, "goruntuleme": 1, "esanlilik": 1}}
        m = yuk_testi.rapor_metni(sonuc)
        self.assertIn("CPU count: 2", m)
        self.assertIn("Python: 3.x", m)
        self.assertIn("p95", m)
        self.assertIn("429", m)
        self.assertIn("not a capacity statement", m)


class UctanUcaTests(unittest.TestCase):
    def test_kucuk_gercek_calistirma(self):
        s = yuk_testi.olc(yukleme=4, goruntuleme=6, esanlilik=2)
        self.assertEqual(s["yukleme"]["istek"], 4)
        self.assertEqual(s["yukleme"]["durumlar"], {"303": 4})
        self.assertEqual(s["yukleme"]["hatalar"], {})
        self.assertEqual(s["goruntuleme"]["istek"], 6)
        self.assertEqual(s["goruntuleme"]["durumlar"], {"200": 6})
        ip = s["hiz_siniri"]["ip"]
        self.assertEqual(sum(ip["durumlar"].values()), ip["adet"])
        self.assertGreater(ip["durumlar"].get("429", 0), 0)       # the per-address limit was reached
        self.assertGreater(ip["durumlar"].get("303", 0), 0)       # and requests before it passed
        sk = s["hiz_siniri"]["sirket"]
        self.assertGreater(sk["durumlar"].get("429", 0), 0)       # the per-company allowance was reached
        self.assertGreaterEqual(s["ortam"]["cpu"], 1)


if __name__ == "__main__":
    unittest.main()
