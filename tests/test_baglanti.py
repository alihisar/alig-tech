"""Kip B: dogrudan baglanti. Sahte psql ile; ag ve gercek veritabani gerekmez."""
import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import baglanti, depo, hedef, katalog, server as tserver  # noqa: E402
import test_tarama  # noqa: E402

temiz_belge = test_tarama.temiz_belge
del test_tarama

SAHTE_PSQL = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
d = Path(__file__).resolve().parent
ayar = json.loads((d / "ayar.json").read_text(encoding="utf-8"))
a = sys.argv[1:]
with open(d / "gunluk.txt", "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": a, "env": dict(os.environ)}) + "\n")
if os.environ.get("PGPASSWORD") != ayar["parola"]:
    sys.stderr.write("psql: error: FATAL:  password authentication failed\n")
    sys.exit(2)
sql = a[a.index("-c") + 1]
if "shobj_description" in sql:
    print(json.dumps([{"super": ayar["super"], "kanit": ayar["kanit"], "surum": ayar.get("surum", 160015)}]))
    sys.exit(0)
if "has_database_privilege" in sql:
    print(json.dumps(ayar.get("veritabanlari", [{"veritabani": "postgres", "baglanir": True}])))
    sys.exit(0)
for cid, s in ayar["kontroller"].items():
    if s["sql"] in sql:
        if s.get("hata"):
            sys.stderr.write(s["hata"] + "\n")
            sys.exit(1)
        print(json.dumps(s["satirlar"]))
        sys.exit(0)
sys.exit(1)
'''
KANIT = "0123456789abcdef0123456789abcdef"
PAROLA = "cok-gizli-parola-987"


class Temel(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.psql = self.d / "psql"
        self.psql.write_text(SAHTE_PSQL, encoding="utf-8")
        self.psql.chmod(self.psql.stat().st_mode | stat.S_IEXEC)
        b = temiz_belge()
        self.ayar = {"parola": PAROLA, "super": False, "kanit": baglanti.kanit_metni(KANIT),
                     "kontroller": {c["id"]: {"sql": c["sql"], "satirlar": b["kontroller"][c["id"]]["satirlar"]} for c in katalog.PG}}
        self.yaz()
        self.h = hedef.Hedef("db.ornek.com", "93.184.216.34", 5432)

    def yaz(self):
        (self.d / "ayar.json").write_text(json.dumps(self.ayar), encoding="utf-8")

    def gunluk(self):
        p = self.d / "gunluk.txt"
        return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


class TaraTests(Temel):
    def tara(self, **k):
        arg = dict(veritabani="postgres", kullanici="alig_hc", parola=PAROLA, kanit=KANIT, psql=str(self.psql))
        arg.update(k)
        return baglanti.tara(self.h, **arg)

    def kod(self, **k):
        try:
            self.tara(**k)
        except baglanti.BaglantiHatasi as e:
            return e.kod
        return None

    def test_basarili_tarama_dogrulanmis_belge_verir(self):
        belge = self.tara()
        self.assertEqual(belge["motor"], "postgresql")
        self.assertEqual(set(belge["kontroller"]), set(katalog.PG_BY_ID))
        self.assertFalse(belge["superuser"])
        self.assertEqual(len(self.gunluk()), len(katalog.PG) + 2)   # ilk sorgu + veritabani listesi + her denetim bir kez

    def test_her_veritabani_taranir_uygunsuz_ad_baglantiya_girmez(self):
        self.ayar["veritabanlari"] = [{"veritabani": "postgres", "baglanir": True}, {"veritabani": "satis", "baglanir": True},
                                      {"veritabani": "kotu ad host=10.0.0.1", "baglanir": True}, {"veritabani": "gizli", "baglanir": False}]
        self.yaz()
        belge = self.tara()
        dizgiler = [g["argv"][g["argv"].index("-d") + 1] for g in self.gunluk()]
        self.assertTrue(any("dbname=satis " in d for d in dizgiler))
        self.assertFalse(any("10.0.0.1" in d or "gizli" in d for d in dizgiler))
        olu = belge["kontroller"]["pg_kapsam"]
        self.assertEqual(sorted(olu["atlanan"], key=lambda x: x["veritabani"]),
                         [{"veritabani": "gizli", "neden": "yetki"}, {"veritabani": "kotu ad host=10.0.0.1", "neden": "ad"}])
        for d in dizgiler:
            self.assertIn("hostaddr=93.184.216.34", d)   # her veritabaninda da dogrulanan IP

    def test_baglanti_dogrulanan_ipye_sabitlenir_ve_tls_ister(self):
        self.tara()
        for g in self.gunluk():
            dizgi = g["argv"][g["argv"].index("-d") + 1]
            self.assertIn("hostaddr=93.184.216.34", dizgi)
            self.assertIn("host=db.ornek.com", dizgi)
            self.assertIn("sslmode=require", dizgi)
            self.assertIn("channel_binding=require", dizgi)   # parola duz ya da MD5 ile gonderilmez, SCRAM aktarmasi onlenir
            self.assertIn("-w", g["argv"])   # parola asla sorulmaz

    def test_parola_argumanlarda_yok_ortam_temiz(self):
        os.environ["ALIG_FORM_SALT"] = "servis-sirri"
        os.environ["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY", "http://vekil:1")
        self.addCleanup(os.environ.pop, "ALIG_FORM_SALT", None)
        self.tara()
        for g in self.gunluk():
            self.assertNotIn(PAROLA, " ".join(g["argv"]))
            self.assertEqual(g["env"]["PGPASSWORD"], PAROLA)
            self.assertNotIn("ALIG_FORM_SALT", g["env"])
            self.assertNotIn("HTTPS_PROXY", g["env"])
            self.assertIn("default_transaction_read_only=on", g["env"]["PGOPTIONS"])
            self.assertIn("statement_timeout=15000", g["env"]["PGOPTIONS"])

    def test_kanit_uyusmazsa_katalog_calismaz(self):
        self.assertEqual(self.kod(kanit="f" * 32), "kanit")
        self.assertEqual(len(self.gunluk()), 1)
        self.ayar["kanit"] = None
        self.yaz()
        self.assertEqual(self.kod(), "kanit")

    def test_super_kullanici_reddedilir(self):
        self.ayar["super"] = True
        self.yaz()
        self.assertEqual(self.kod(), "super")
        self.assertEqual(len(self.gunluk()), 1)

    def test_yanlis_parola_ve_bicim(self):
        self.assertEqual(self.kod(parola="yanlis"), "baglanti")
        self.assertEqual(self.kod(parola=""), "baglanti")
        for kotu in ("postgres sslmode=disable", "a;b", "x' host=10.0.0.1", "", "a b", "ş"):
            self.assertEqual(self.kod(veritabani=kotu), "bicim", kotu)
            self.assertEqual(self.kod(kullanici=kotu), "bicim", kotu)
        self.assertEqual(self.kod(sslmode="disable"), "bicim")

    def test_yetki_hatasi_olculemedi_olur_fazla_kolon_atilir(self):
        self.ayar["kontroller"]["pg_md5_roller"]["hata"] = "ERROR:  permission denied for table pg_authid"
        self.ayar["kontroller"]["pg_surum"]["satirlar"] = [{"surum_num": 160004, "fazla": "x"}]
        self.yaz()
        belge = self.tara()
        self.assertEqual(belge["kontroller"]["pg_md5_roller"], {"durum": "hata", "neden": "yetki"})
        self.assertEqual(belge["kontroller"]["pg_surum"]["satirlar"], [{"surum_num": 160004}])

    def test_kotu_niyetli_sunucu_yaniti_reddedilir(self):
        self.ayar["kontroller"]["pg_eklentiler"]["satirlar"] = [{"extname": "x" * 5000, "extversion": "1"}]
        self.yaz()
        self.assertEqual(self.kod(), "bicim")

    def test_maskeleme(self):
        self.ayar["kontroller"]["pg_gecersiz_indeks"]["satirlar"] = [{"schemaname": "gizli_sema", "indexrelname": "gizli_indeks"}]
        self.yaz()
        belge = self.tara(maskele=True)
        self.assertNotIn("gizli_sema", json.dumps(belge))
        self.assertTrue(belge["maskeli"])


# Gercek bir sertifika degil, yalniz bicim denetimi icin yeterli rastgele base64 govde (PEM biciminde).
SAHTE_GOVDE = "\n".join(["MIIBszCCAVmgAwIBAgIUQ2hhbmdlTWVJZlBvc3NpYmxlMDEyMzQ1Njc4OTBhYmNkZWYw"] * 3 + ["QUJDREVGRw=="])
SAHTE_CA = "-----BEGIN CERTIFICATE-----\n" + SAHTE_GOVDE + "\n-----END CERTIFICATE-----\n"


class CaPemTests(unittest.TestCase):
    def kod(self, pem):
        try:
            baglanti.ca_dogrula(pem)
        except baglanti.BaglantiHatasi as e:
            return e.kod
        return None

    def test_gecerli_pem_kabul_edilir_ve_normallesir(self):
        self.assertIsNone(self.kod(SAHTE_CA))
        self.assertEqual(baglanti.ca_dogrula(SAHTE_CA.replace("\n", "\r\n")), SAHTE_CA)   # satir sonu normallesir
        self.assertEqual(baglanti.ca_dogrula("  \n" + SAHTE_CA + "\n\n"), SAHTE_CA)
        iki = SAHTE_CA + SAHTE_CA
        self.assertEqual(baglanti.ca_dogrula(iki), iki)   # ara CA + kok CA zinciri

    def test_gecersiz_pemler_reddedilir(self):
        govde = SAHTE_GOVDE
        kotuler = {
            "bos": "", "bosluk": "  \n ", "tur": None, "sayi": 5,
            "ozel_anahtar": "-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----\n" % govde,
            "sertifika_arti_anahtar": SAHTE_CA + "-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----\n" % govde,
            "onde_metin": "merhaba\n" + SAHTE_CA, "sonda_metin": SAHTE_CA + "ek satir\n",
            "bitis_yok": "-----BEGIN CERTIFICATE-----\n%s\n" % govde,
            "baslangic_yok": "%s\n-----END CERTIFICATE-----\n" % govde,
            "govde_bos": "-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n",
            "bozuk_base64": "-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n" % "!!!!notbase64$$$$",
            "govdede_baslik": "-----BEGIN CERTIFICATE-----\nProc-Type: 4,ENCRYPTED\n%s\n-----END CERTIFICATE-----\n" % govde,
            "nul": SAHTE_CA.replace("MIIB", "MI\x00B"),
            "ascii_disi": SAHTE_CA.replace("MIIB", "MIİB"),
            "cok_sertifika": SAHTE_CA * (baglanti.CA_EN_COK_SERTIFIKA + 1),
            "cok_buyuk": "-----BEGIN CERTIFICATE-----\n" + ("A" * 80 + "\n") * 1000 + "-----END CERTIFICATE-----\n",
            "ic_ice": "-----BEGIN CERTIFICATE-----\n-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n-----END CERTIFICATE-----\n" % govde,
            "uzun_satir": "-----BEGIN CERTIFICATE-----\n" + "A" * 200 + "\n-----END CERTIFICATE-----\n",
        }
        for ad, pem in kotuler.items():
            self.assertEqual(self.kod(pem), "ca", ad)

    def test_buyuk_pem_ayrisma_oncesi_reddedilir(self):
        self.assertEqual(self.kod("A" * (baglanti.CA_PEM_SINIRI + 1)), "ca")


class SslrootcertDizgisiTests(Temel):
    def dizgi(self, **k):
        return baglanti.baglanti_dizgisi(self.h, "postgres", "alig_hc", **k)

    def test_varsayilan_degismez_require_ve_channel_binding(self):
        d = self.dizgi()
        self.assertIn("sslmode=require", d)
        self.assertIn("channel_binding=require", d)
        self.assertNotIn("sslrootcert", d)

    def test_verify_full_kok_sertifika_ister(self):
        d = self.dizgi(sslmode="verify-full", sslrootcert="/tmp/alig-ca-ab12/ca.pem")
        self.assertIn("sslmode=verify-full", d)
        self.assertIn("sslrootcert=/tmp/alig-ca-ab12/ca.pem", d)
        self.assertIn("channel_binding=require", d)   # dogrulama kanal baglamayi kaldirmaz
        for mod in ("verify-full", "verify-ca"):
            with self.assertRaises(baglanti.BaglantiHatasi):
                self.dizgi(sslmode=mod)   # kok sertifikasiz dogrulama: libpq ev dizinine duser, kabul edilmez

    def test_sslrootcert_yolu_dizgiye_ek_anahtar_sokamaz(self):
        for kotu in ("ca.pem", "/tmp/a b/ca.pem", "/tmp/a'b/ca.pem", "/tmp/a\\b", "/tmp/x sslmode=disable", "/tmp/a=b", "/tmp/a\nb",
                     "/tmp/a\x00b", "", "system", "/" + "a" * 300, "/tmp/\u015f/ca.pem", None, 5):
            with self.assertRaises(baglanti.BaglantiHatasi, msg=repr(kotu)):
                self.dizgi(sslmode="verify-full", sslrootcert=kotu)

    def test_kok_sertifika_verify_olmadan_verilmez(self):
        with self.assertRaises(baglanti.BaglantiHatasi):
            self.dizgi(sslmode="require", sslrootcert="/tmp/x/ca.pem")   # sessizce yok sayilmaz

    def test_alig_scan_001_dogrulamalari_korunur(self):
        for h in (hedef.Hedef("a b", "93.184.216.34", 5432), hedef.Hedef("db.ornek.com", "93.184.216.34 sslmode=disable", 5432),
                  hedef.Hedef("db.ornek.com", "93.184.216.34", 0), hedef.Hedef("db.ornek.com", "93.184.216.34", True)):
            with self.assertRaises(baglanti.BaglantiHatasi):
                baglanti.baglanti_dizgisi(h, "postgres", "alig_hc", "verify-full", "/tmp/x/ca.pem")


class CaIleTaramaTests(Temel):
    """Yalniz CA'ya ozgu denemeler (TaraTests'in yardimcilari ortak, testleri yeniden kosulmaz)."""
    tara, kod = TaraTests.tara, TaraTests.kod

    def setUp(self):
        super().setUp()
        self.izler = []
        gercek = baglanti._calistir

        def izle(psql, dizgi, parola, sql, sure):
            m = [x for x in dizgi.split() if x.startswith("sslrootcert=")]
            if m:
                yol = m[0].split("=", 1)[1]
                dizin = os.path.dirname(yol)
                self.izler.append({"yol": yol, "var": os.path.exists(yol), "dosya_izni": stat.S_IMODE(os.stat(yol).st_mode),
                                   "dizin_izni": stat.S_IMODE(os.stat(dizin).st_mode), "icerik": Path(yol).read_text(encoding="ascii")})
            return gercek(psql, dizgi, parola, sql, sure)
        baglanti._calistir = izle
        self.addCleanup(setattr, baglanti, "_calistir", gercek)

    def test_ca_ile_verify_full_ve_gecici_dosya_0600(self):
        self.tara(ca_pem=SAHTE_CA)
        for g in self.gunluk():
            dizgi = g["argv"][g["argv"].index("-d") + 1]
            self.assertIn("sslmode=verify-full", dizgi)
            self.assertIn("sslrootcert=", dizgi)
            self.assertIn("channel_binding=require", dizgi)
            self.assertIn("host=db.ornek.com", dizgi)   # sertifika bu ada gore denetlenir
        self.assertEqual(len(self.izler), len(self.gunluk()))
        for iz in self.izler:
            self.assertEqual(iz["dosya_izni"], 0o600)
            self.assertEqual(iz["dizin_izni"], 0o700)
            self.assertEqual(iz["icerik"], SAHTE_CA)
        for iz in self.izler:   # is bitince dosya ve dizin yok
            self.assertFalse(os.path.exists(iz["yol"]))
            self.assertFalse(os.path.exists(os.path.dirname(iz["yol"])))

    def test_ca_ile_sslmode_require_istense_de_verify_full_olur(self):
        self.tara(ca_pem=SAHTE_CA, sslmode="require")
        self.assertTrue(all("sslmode=verify-full" in g["argv"][g["argv"].index("-d") + 1] for g in self.gunluk()))

    def test_gecici_dosya_hata_yolunda_da_silinir(self):
        self.ayar["super"] = True
        self.yaz()
        self.assertEqual(self.kod(ca_pem=SAHTE_CA), "super")
        self.assertEqual(len(self.izler), 1)
        self.assertFalse(os.path.exists(os.path.dirname(self.izler[0]["yol"])))
        self.ayar["super"] = False
        self.yaz()
        self.assertEqual(self.kod(ca_pem=SAHTE_CA, parola="yanlis"), "baglanti")
        self.assertFalse(os.path.exists(os.path.dirname(self.izler[-1]["yol"])))

    def test_gecersiz_ca_hicbir_baglanti_acmaz(self):
        self.assertEqual(self.kod(ca_pem="-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"), "ca")
        self.assertEqual(self.gunluk(), [])
        self.assertEqual(self.izler, [])

    def test_ca_yoksa_mevcut_varsayilan_aynen_surer(self):
        self.tara()
        self.assertEqual(self.izler, [])
        for g in self.gunluk():
            dizgi = g["argv"][g["argv"].index("-d") + 1]
            self.assertIn("sslmode=require", dizgi)
            self.assertNotIn("sslrootcert", dizgi)

    def test_verify_full_ca_olmadan_reddedilir(self):
        self.assertEqual(self.kod(sslmode="verify-full"), "bicim")
        self.assertEqual(self.gunluk(), [])

    def test_ca_parolayi_arguman_ve_ortama_yazmaz(self):
        self.tara(ca_pem=SAHTE_CA)
        for g in self.gunluk():
            self.assertNotIn(SAHTE_GOVDE.splitlines()[0], " ".join(g["argv"]))   # PEM argumanda yok, yalniz dosya yolu


class CiktiSiniriTests(unittest.TestCase):
    def test_surec_cikti_siniri_ve_sure_korunur(self):
        eski = baglanti.CIKTI_SINIRI
        baglanti.CIKTI_SINIRI = 1000
        self.addCleanup(setattr, baglanti, "CIKTI_SINIRI", eski)
        with self.assertRaises(OverflowError):
            baglanti._surec_calistir([sys.executable, "-c", "print('x' * 5000)"], dict(os.environ), 10)
        with self.assertRaises(TimeoutError):
            baglanti._surec_calistir([sys.executable, "-c", "import time; time.sleep(5)"], dict(os.environ), 0.3)


class SunucuTests(Temel):
    def setUp(self):
        super().setUp()
        self.db = str(self.d / "s.sqlite")
        depo.baglan(self.db).close()

        self.saat, self.beklemeler, self.dns_gecikme = 1000.0, [], 0.0   # sahte saat: gercek beklemeyle test uzamaz

        def ilerle(sn):
            self.saat += sn

        def bekle(sn):
            self.beklemeler.append(sn)
            ilerle(sn)

        def sahte_dogrula(ad, port, yasak_aglar=(), **k):
            def coz(a, p, *x, **y):
                ilerle(self.dns_gecikme)
                if a == "yok.ornek.com":
                    raise OSError("ad cozulemedi")
                return [(2, 1, 6, "", ("10.0.0.5" if a == "ic.ornek.com" else "93.184.216.34", p))]
            return hedef.dogrula(ad, port, cozumleyici=coz, yasak_aglar=yasak_aglar)
        self.ilerle = ilerle
        self.H = type("H", (tserver.H,), {"db_yolu": self.db, "sinir": tserver.RateLimiter(per_window=100), "dogrudan": True,
                                          "psql": str(self.psql), "hedef_dogrula": staticmethod(sahte_dogrula),
                                          "saat": staticmethod(lambda: self.saat), "bekle": staticmethod(bekle)})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def izin_ver(self, eposta="ali@ornek.com.tr", izin=True):
        c = depo.baglan(self.db)
        f = depo.firma_kaydet(c, depo.firma_anahtari(eposta), "Ornek AS", eposta, "tarama")
        depo.firma_izin_yaz(c, f["id"], izin)
        c.close()
        return f["id"]

    def post(self, yol, alanlar):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", yol, body=urlencode(alanlar).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        r.govde = r.read().decode("utf-8", "replace")
        return r

    def baslat(self, **k):
        alanlar = dict(sirket="Ornek AS", eposta="ali@ornek.com.tr", sunucu="db.ornek.com", port="5432", veritabani="postgres",
                       kullanici="alig_hc", yetki="on", dil="tr")
        alanlar.update(k)
        return self.post("/api/tarama/baglan", {a: b for a, b in alanlar.items() if b is not None})

    def istek(self, r):
        import re
        return re.search(r'action="(/api/tarama/baglan/[A-Za-z0-9_\-]{43})"', r.govde).group(1)

    def kanit_ayarla(self, r):
        import re
        self.ayar["kanit"] = re.search(r"IS &#x27;(alig-kanit-[0-9a-f]{32})&#x27;", r.govde).group(1)
        self.yaz()

    def olaylar(self):
        c = depo.baglan(self.db)
        try:
            return [x[0] for x in c.execute("SELECT olay FROM denetim")]
        finally:
            c.close()

    def test_varsayilan_olarak_kapali(self):
        self.H.dogrudan = False
        self.izin_ver()
        self.assertEqual(self.baslat().status, 404)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("GET", "/api/tarama/baglan")
        self.assertEqual(c.getresponse().status, 404)
        self.assertFalse(tserver.H.dogrudan)

    def test_izinsiz_ve_pasif_firma_reddedilir(self):
        r = self.baslat()
        self.assertEqual(r.status, 403)
        self.assertIn("onaylanmış", r.govde)
        fid = self.izin_ver()
        c = depo.baglan(self.db)
        depo.firma_durum_yaz(c, fid, "pasif")
        c.close()
        self.assertEqual(self.baslat().status, 403)

    def test_ic_adres_ve_gecersiz_hedef_tek_tip_reddedilir(self):
        self.izin_ver()
        govdeler = set()
        for k in (dict(sunucu="ic.ornek.com"), dict(sunucu="127.0.0.1"), dict(sunucu="localhost"), dict(port="22"),
                  dict(veritabani="x sslmode=disable"), dict(kullanici="a;b"), dict(sunucu="169.254.169.254")):
            r = self.baslat(**k)
            self.assertEqual(r.status, 422, k)
            govdeler.add(r.govde)
        self.assertEqual(len(govdeler), 1)   # neden disariya sizmaz
        self.assertEqual(self.gunluk(), [])   # hicbir baglanti denenmedi
        self.assertTrue(any("hedefi reddedildi (ic_adres)" in o for o in self.olaylar()))

    def test_tam_akis_rapor_verir_parola_iz_birakmaz(self):
        self.izin_ver()
        r = self.baslat()
        self.assertEqual(r.status, 200)
        self.assertIn("COMMENT ON ROLE alig_hc IS", r.govde)
        self.kanit_ayarla(r)
        s = self.post(self.istek(r), {"parola": PAROLA})
        self.assertEqual(s.status, 303, s.govde)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("GET", s.getheader("Location"))
        g = c.getresponse()
        self.assertEqual(g.status, 200)
        self.assertIn("Sağlık taraması raporu", g.read().decode())
        self.assertEqual(self.post(self.istek(r), {"parola": PAROLA}).status, 404)   # istek tek kullanimlik
        ham = b""
        for p in Path(self.d).glob("s.sqlite*"):
            try:  # -shm/-wal dosyalari sunucu baglantisi kapanirken kaybolabilir
                ham += p.read_bytes()
            except FileNotFoundError:
                pass
        self.assertNotIn(PAROLA.encode(), ham)
        self.assertFalse(any("93.184.216.34" in o or "db.ornek.com" in o for o in self.olaylar()))
        self.assertTrue(any("dogrudan tarama tamamlandi" in o for o in self.olaylar()))
        con = depo.baglan(self.db)
        self.assertIsNone(depo.denetim_dogrula(con))
        self.assertEqual(depo.kullanim_say(con, depo.sirket_anahtari("ali@ornek.com.tr")), 1)

    def test_kanit_yoksa_tarama_calismaz_ve_deneme_siniri(self):
        self.izin_ver()
        r = self.baslat()
        yol = self.istek(r)
        for _ in range(3):
            s = self.post(yol, {"parola": PAROLA})
            self.assertEqual(s.status, 422)
            self.assertIn("kanıt", s.govde.lower())
        self.assertEqual(len(self.gunluk()), 3)   # yalniz ilk sorgu, katalog hic calismadi
        self.assertEqual(self.post(yol, {"parola": PAROLA}).status, 429)
        self.assertEqual(self.post(yol, {"parola": PAROLA}).status, 404)
        con = depo.baglan(self.db)
        self.assertEqual(depo.kullanim_say(con, depo.sirket_anahtari("ali@ornek.com.tr")), 0)   # basarisiz deneme hak harcamaz

    def test_super_kullanici_ve_yanlis_parola(self):
        self.izin_ver()
        r = self.baslat()
        self.kanit_ayarla(r)
        self.assertEqual(self.post(self.istek(r), {"parola": "yanlis"}).status, 422)
        self.ayar["super"] = True
        self.yaz()
        s = self.post(self.istek(r), {"parola": PAROLA})
        self.assertEqual(s.status, 422)
        self.assertIn("süper kullanıcı", s.govde)

    def test_gecersiz_istek_ve_saatlik_sinir(self):
        self.izin_ver()
        self.assertEqual(self.post("/api/tarama/baglan/" + "A" * 43, {"parola": "x"}).status, 404)
        for _ in range(depo.ISTEK_SAATLIK):
            self.assertEqual(self.baslat().status, 200)
        self.assertEqual(self.baslat().status, 429)

    def test_izin_kaldirilirsa_acik_istek_calismaz(self):
        fid = self.izin_ver()
        r = self.baslat()
        self.kanit_ayarla(r)
        c = depo.baglan(self.db)
        depo.firma_izin_yaz(c, fid, False)
        c.close()
        self.assertEqual(self.post(self.istek(r), {"parola": PAROLA}).status, 403)
        self.assertEqual(self.gunluk(), [])

    def test_form_ca_alani_iki_dilde(self):
        self.izin_ver()
        for dil, metin in (("tr", "CA sertifikası"), ("en", "CA certificate")):
            r = self.baslat(dil=dil)
            self.assertEqual(r.status, 200)
            self.assertIn('<textarea id="b-ca" name="ca_pem"', r.govde)
            self.assertIn(metin, r.govde)
            self.assertNotIn(" required", r.govde.split('name="ca_pem"')[1].split(">")[0])   # alan istege bagli
            self.assertIn("verify-full", r.govde)

    def test_ca_ile_tam_akis_verify_full_kullanir(self):
        self.izin_ver()
        r = self.baslat()
        self.kanit_ayarla(r)
        s = self.post(self.istek(r), {"parola": PAROLA, "ca_pem": SAHTE_CA})
        self.assertEqual(s.status, 303, s.govde)
        for g in self.gunluk():
            dizgi = g["argv"][g["argv"].index("-d") + 1]
            self.assertIn("sslmode=verify-full", dizgi)
            self.assertIn("sslrootcert=", dizgi)
            self.assertNotIn(SAHTE_GOVDE.splitlines()[0], json.dumps(g["argv"]))
        ham = b"".join(p.read_bytes() for p in Path(self.d).glob("s.sqlite") if p.exists())
        self.assertNotIn(SAHTE_GOVDE.splitlines()[0].encode(), ham)   # CA da kaydedilmez

    def test_ca_olmadan_mevcut_varsayilan(self):
        self.izin_ver()
        r = self.baslat()
        self.kanit_ayarla(r)
        self.assertEqual(self.post(self.istek(r), {"parola": PAROLA, "ca_pem": "  \n"}).status, 303)   # bos alan = CA yok
        for g in self.gunluk():
            dizgi = g["argv"][g["argv"].index("-d") + 1]
            self.assertIn("sslmode=require", dizgi)
            self.assertNotIn("sslrootcert", dizgi)

    def test_gecersiz_ca_acik_hata_verir_deneme_harcamaz_baglanmaz(self):
        self.izin_ver()
        r = self.baslat()
        self.kanit_ayarla(r)
        yol = self.istek(r)
        for _ in range(5):   # deneme hakki (3) bu hatayla tukenmez
            s = self.post(yol, {"parola": PAROLA, "ca_pem": "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"})
            self.assertEqual(s.status, 422)
            self.assertIn("CA sertifikası", s.govde)
        c = depo.baglan(self.db)
        self.assertEqual(c.execute("SELECT deneme FROM baglanti_istegi ORDER BY id LIMIT 1").fetchone()[0], 0)
        c.close()
        en = self.baslat(dil="en")
        self.kanit_ayarla(en)
        s = self.post(self.istek(en), {"parola": PAROLA, "ca_pem": "kotu"})
        self.assertEqual(s.status, 422)
        self.assertIn("CA certificate", s.govde)
        self.assertEqual(self.gunluk(), [])
        self.assertEqual(self.post(self.istek(en), {"parola": PAROLA, "ca_pem": SAHTE_CA}).status, 303)   # istek hala gecerli (hak harcanmadi)

    def test_dev_ca_govdesi_reddedilir(self):
        self.izin_ver()
        r = self.baslat()
        yol = self.istek(r)
        s = self.post(yol, {"parola": PAROLA, "ca_pem": "A" * 500000})
        self.assertIn(s.status, (415, 422))
        self.assertEqual(self.gunluk(), [])

    # ---- yanit suresi ve govdesi tek tip ----
    def test_hedef_red_nedenleri_ayni_sure_ve_govde(self):
        self.izin_ver()
        sonuclar = []
        for k, gecikme in ((dict(sunucu="ic.ornek.com"), 0), (dict(sunucu="127.0.0.1"), 0), (dict(sunucu="localhost"), 0), (dict(port="22"), 0),
                           (dict(veritabani="x sslmode=disable"), 0), (dict(sunucu="yok.ornek.com"), 0), (dict(sunucu="yok.ornek.com"), 4.0),
                           (dict(sunucu="ic.ornek.com"), 2.5), (dict(sunucu="169.254.169.254"), 0)):
            self.dns_gecikme = gecikme
            bas = self.saat
            r = self.baslat(**k)
            sonuclar.append((r.status, r.govde, round(self.saat - bas, 6)))
        self.assertEqual({x[0] for x in sonuclar}, {422})
        self.assertEqual(len({x[1] for x in sonuclar}), 1)
        self.assertEqual({x[2] for x in sonuclar}, {tserver.H.SABIT_RED_SN})   # DNS ne kadar surerse sursun toplam sure ayni

    def test_basarili_baslangic_ve_diger_hatalar_bekletilmez(self):
        self.izin_ver()
        self.assertEqual(self.baslat().status, 200)
        self.assertEqual(self.beklemeler, [])
        self.assertEqual(self.baslat(sirket="").status, 422)   # hedefle ilgisiz hata: sure sabitlemeye gerek yok
        self.assertEqual(self.beklemeler, [])

    def test_baglanti_hatalari_ayni_sure_ve_govde(self):
        self.izin_ver()
        sonuclar = []
        gercek = self.H.tara

        def tara_gecikmeli(sn, kod):
            def f(*a, **k):
                self.ilerle(sn)
                raise baglanti.BaglantiHatasi(kod)
            return staticmethod(f)
        for sn, kod in ((0.0, "baglanti"), (10.2, "baglanti"), (3.0, "bicim"), (0.5, "hedef")):
            self.H.tara = tara_gecikmeli(sn, kod)
            r = self.baslat()
            self.kanit_ayarla(r)
            bas = self.saat
            s = self.post(self.istek(r), {"parola": PAROLA})
            sonuclar.append((s.status, s.govde, round(self.saat - bas, 6)))
        r = self.baslat()   # gercek (sahte psql) yanlis parola da ayni
        self.kanit_ayarla(r)
        self.H.tara = staticmethod(gercek)
        bas = self.saat
        s = self.post(self.istek(r), {"parola": "yanlis"})
        sonuclar.append((s.status, s.govde, round(self.saat - bas, 6)))
        self.assertEqual({x[0] for x in sonuclar}, {422})
        self.assertEqual(len({x[1] for x in sonuclar}), 1)
        self.assertEqual({x[2] for x in sonuclar}, {tserver.H.SABIT_BAGLANTI_SN})

    def test_sabit_sure_zaten_asilmissa_ek_bekleme_yok(self):
        self.izin_ver()
        self.dns_gecikme = tserver.H.SABIT_RED_SN + 5
        self.baslat(sunucu="yok.ornek.com")
        self.assertEqual(self.beklemeler, [])   # alt sinir; ustten kirpma yapilmaz

    def test_sabit_sureler_makul_ve_basarida_bekleme_yok(self):
        self.assertTrue(0 < tserver.H.SABIT_RED_SN <= 10)
        self.assertGreater(tserver.H.SABIT_BAGLANTI_SN, 10)   # psql connect_timeout=10 sn'yi kapsamali
        self.izin_ver()
        r = self.baslat()
        self.kanit_ayarla(r)
        self.assertEqual(self.post(self.istek(r), {"parola": PAROLA}).status, 303)
        self.assertEqual(self.beklemeler, [])

    def test_form_sayfasi_iki_dilde(self):
        for dil, metin in (("tr", "Doğrudan bağlantıyla tarama"), ("en", "Scan over a direct connection")):
            c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
            c.request("GET", "/api/tarama/baglan?dil=" + dil)
            g = c.getresponse()
            self.assertEqual(g.status, 200)
            self.assertIn(metin, g.read().decode())


if __name__ == "__main__":
    unittest.main()
