"""Kip B hedef dogrulamasi: ic aga yonlendirme (SSRF) ve DNS rebinding onlemleri. Ag kullanilmaz."""
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import hedef  # noqa: E402


def sahte(*adresler):
    """getaddrinfo yerine gecen cozumleyici: her cagrida ayni adresleri doner, cagri sayisini tutar."""
    def coz(ad, port, *a, **k):
        coz.cagri += 1
        out = []
        for adr in adresler:
            aile = socket.AF_INET6 if ":" in adr else socket.AF_INET
            out.append((aile, socket.SOCK_STREAM, 6, "", (adr, port) if aile == socket.AF_INET else (adr, port, 0, 0)))
        return out
    coz.cagri = 0
    return coz


def hata(ad, port=5432, coz=None, **k):
    try:
        hedef.dogrula(ad, port, cozumleyici=coz or sahte("93.184.216.34"), **k)
    except hedef.Reddedildi as e:
        return e.kod
    return None


class AdresTests(unittest.TestCase):
    def test_genel_adres_kabul_edilir_ve_ip_sabitlenir(self):
        coz = sahte("93.184.216.34")
        h = hedef.dogrula("db.ornek.com", 5432, cozumleyici=coz)
        self.assertEqual((h.ip, h.port, h.ad), ("93.184.216.34", 5432, "db.ornek.com"))
        self.assertEqual(coz.cagri, 1)   # ad yalnizca bir kez cozulur

    def test_ic_ve_ozel_adresler_reddedilir(self):
        for adr in ("10.0.0.5", "172.16.3.4", "192.168.1.10", "127.0.0.1", "127.8.9.1", "169.254.169.254", "100.64.0.1",
                    "0.0.0.0", "224.0.0.1", "255.255.255.255", "198.18.0.1", "192.0.2.1", "240.0.0.1",
                    "::1", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1", "::", "2001:db8::1"):
            self.assertEqual(hata("db.ornek.com", coz=sahte(adr)), "ic_adres", adr)

    def test_ipv4_tasiyan_ipv6_bicimleri_reddedilir(self):
        for adr in ("::ffff:10.0.0.1", "::ffff:127.0.0.1", "::ffff:169.254.169.254", "64:ff9b::a00:1", "2002:a00:1::1",
                    "2002:7f00:1::1", "::10.0.0.1"):
            self.assertEqual(hata("db.ornek.com", coz=sahte(adr)), "ic_adres", adr)

    def test_bir_kayit_bile_icse_tumu_reddedilir(self):
        self.assertEqual(hata("db.ornek.com", coz=sahte("93.184.216.34", "10.0.0.5")), "ic_adres")
        self.assertEqual(hata("db.ornek.com", coz=sahte("2606:2800:220:1::1", "::1")), "ic_adres")

    def test_kendi_aglarimiz_reddedilir(self):
        self.assertEqual(hata("db.ornek.com", coz=sahte("203.0.114.7"), yasak_aglar=("203.0.114.0/24",)), "ic_adres")
        self.assertIsNone(hata("db.ornek.com", coz=sahte("203.0.115.7"), yasak_aglar=("203.0.114.0/24",)))

    def test_ip_yazimi_dogrudan_denetlenir_cozumleyici_cagrilmaz(self):
        coz = sahte("93.184.216.34")
        self.assertEqual(hata("10.0.0.5", coz=coz), "ic_adres")
        self.assertEqual(hata("[::1]", coz=coz), "ic_adres")
        self.assertEqual(coz.cagri, 0)
        h = hedef.dogrula("93.184.216.34", 5432, cozumleyici=coz)
        self.assertEqual(h.ip, "93.184.216.34")
        self.assertEqual(hedef.dogrula("[2606:2800:220:1::1]", 5432, cozumleyici=coz).ip, "2606:2800:220:1::1")
        self.assertEqual(coz.cagri, 0)

    def test_alisilmadik_sayisal_yazimlar_reddedilir(self):
        for ad in ("2130706433", "0x7f000001", "0x7f.0.0.1", "017700000001", "0177.0.0.1", "127.1", "10.1", "127.0.0.01",
                   "1.2.3", "0", "00.0.0.0"):
            self.assertEqual(hata(ad), "ad", ad)

    def test_gecersiz_adlar(self):
        for ad in ("", " ", "localhost", "db", "db.ornek.com:5432", "http://db.ornek.com", "db.ornek.com/x", "a b.com",
                   "-db.ornek.com", "db..ornek.com", "db.ornek.com@10.0.0.1", "db.ornek.com#x", "x" * 64 + ".com",
                   ("a" * 60 + ".") * 5 + "com", "db.ornek.com\n", "ornek.cоm", "[::1", "::1]", None, 5):
            self.assertEqual(hata(ad), "ad", repr(ad))

    def test_sondaki_nokta_ve_buyuk_harf(self):
        h = hedef.dogrula("DB.Ornek.COM.", 5432, cozumleyici=sahte("93.184.216.34"))
        self.assertEqual(h.ad, "db.ornek.com")

    def test_yerel_son_ekler_reddedilir(self):
        for ad in ("x.localhost", "db.local", "db.internal", "db.lan", "db.home.arpa", "metadata.google.internal"):
            self.assertEqual(hata(ad), "ad", ad)

    def test_portlar(self):
        for port in (5432, 1433, 1024, 6432, 65535, "5432"):
            self.assertIsNone(hata("db.ornek.com", port), port)
        for port in (0, 22, 80, 443, 1023, 65536, -1, "x", None, 5432.5, True, "5432 "):
            self.assertEqual(hata("db.ornek.com", port), "port", repr(port))

    def test_cozumleme_hatalari(self):
        def patlar(*a, **k):
            raise socket.gaierror("yok")
        self.assertEqual(hata("db.ornek.com", coz=patlar), "cozulemedi")
        self.assertEqual(hata("db.ornek.com", coz=sahte()), "cozulemedi")
        self.assertEqual(hata("db.ornek.com", coz=sahte(*["93.184.216.%d" % i for i in range(1, 40)])), "cozulemedi")

    def test_ipv4_tercih_edilir(self):
        h = hedef.dogrula("db.ornek.com", 5432, cozumleyici=sahte("2606:2800:220:1::1", "93.184.216.34"))
        self.assertEqual(h.ip, "93.184.216.34")

    def test_rebinding_ikinci_cozumleme_olmaz(self):
        yanitlar = [["93.184.216.34"], ["10.0.0.5"]]

        def degisen(ad, port, *a, **k):
            adr = yanitlar.pop(0)[0]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (adr, port))]
        h = hedef.dogrula("db.ornek.com", 5432, cozumleyici=degisen)
        self.assertEqual(h.ip, "93.184.216.34")
        self.assertEqual(len(yanitlar), 1)   # ikinci (ic) yanit hic istenmedi
        self.assertEqual(h.baglanti_adresi(), ("93.184.216.34", 5432))

    def test_musteri_iletisi_tek_tiptir(self):
        iletiler = set()
        for ad, port, coz in (("10.0.0.5", 5432, None), ("localhost", 5432, None), ("db.ornek.com", 22, None),
                              ("db.ornek.com", 5432, sahte("127.0.0.1")), ("db.ornek.com", 5432, sahte())):
            try:
                hedef.dogrula(ad, port, cozumleyici=coz or sahte("93.184.216.34"))
            except hedef.Reddedildi as e:
                iletiler.add((e.ileti("tr"), e.ileti("en")))
                self.assertNotIn("10.0.0.5", str(e))
        self.assertEqual(len(iletiler), 1)

    def test_ozet_adresi_gizler(self):
        h = hedef.dogrula("db.ornek.com", 5432, cozumleyici=sahte("93.184.216.34"))
        self.assertRegex(h.ozet(), r"^[0-9a-f]{64}$")
        self.assertNotIn("ornek", h.ozet())


if __name__ == "__main__":
    unittest.main()
