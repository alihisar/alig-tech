"""SQL Server taramasi (on surum): katalog, toplayici, kurallar, yukleme kapisi. Gercek SQL Server gerekmez."""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import depo, katalog, kurallar, kurallar_mssql, rapor, server as tserver, uret_toplayici, yukleme  # noqa: E402
import test_tarama  # noqa: E402

pg_temiz_belge = test_tarama.temiz_belge

TOPLAYICI = ROOT / "tarama" / "onsurum" / "alig-toplayici-mssql.py"

SAHTE_SQLCMD = r'''#!/usr/bin/env python3
"""Test icin sahte sqlcmd: -Q icindeki sorguya gore sabit JSON basar, basina baslik gurultusu koyar."""
import json, os, sys
a = sys.argv[1:]
sorgu = a[a.index("-Q") + 1]
with open(os.environ["SAHTE_GUNLUK"], "a", encoding="utf-8") as f:
    f.write(json.dumps(a) + "\n")
veri = json.load(open(os.environ["SAHTE_VERI"], encoding="utf-8"))
if "IS_SRVROLEMEMBER" in sorgu:
    print("\n" + json.dumps([{"yonetici": veri.get("__yonetici", 0)}]) + "\n")
    sys.exit(0)
for cid, sonuc in veri.items():
    if cid.startswith("__"):
        continue
    if sonuc["sql"] in sorgu:
        if "hata" in sonuc:
            print(sonuc["hata"])
            sys.exit(1)
        metin = json.dumps(sonuc["satirlar"])
        print("                    \n--------------------\n" + metin[:40] + "\n" + metin[40:] + "\n")
        sys.exit(0)
print("Msg 208, Invalid object name")
sys.exit(1)
'''


def temiz_mssql():
    k = {c["id"]: {"durum": "ok", "satirlar": []} for c in katalog.MSSQL}
    k["ms_surum"]["satirlar"] = [{"ana_surum": 16, "surum": "16.0.4135.4", "motor_turu": 3}]
    k["ms_yedek"]["satirlar"] = [{"veritabani": "satis", "kurtarma_modeli": "FULL", "tam_saat": 20, "log_saat": 1}]
    k["ms_checkdb"]["satirlar"] = [{"veritabani": "satis", "gun": 3}]
    k["ms_db_ayar"]["satirlar"] = [{"veritabani": "satis", "kimlik": 5, "auto_shrink": 0, "auto_close": 0, "sayfa_dogrulama": "CHECKSUM", "durum": "ONLINE", "trustworthy": 0}]
    k["ms_sunucu_ayar"]["satirlar"] = [{"ad": "xp_cmdshell", "deger": 0}, {"ad": "max server memory (MB)", "deger": 24000},
                                       {"ad": "cost threshold for parallelism", "deger": 50}]
    k["ms_sa"]["satirlar"] = [{"devre_disi": 1, "adi_sa": 1}]
    k["ms_parola_politikasi"]["satirlar"] = [{"sayi": 0}]
    k["ms_tempdb"]["satirlar"] = [{"veri_dosyasi": 8, "cpu": 16}]
    k["ms_sifreleme"]["satirlar"] = [{"toplam": 12, "sifreli": 12}]
    k["ms_kimlik"]["satirlar"] = [{"yalniz_windows": 1}]
    return {"format": katalog.FORMAT, "motor": "mssql", "katalog_sha256": uret_toplayici.katalog_ozeti("mssql"),
            "olusturma_utc": "2026-11-10T12:00:00Z", "maskeli": False, "superuser": False, "kontroller": k}


def metinsiz(sql):
    return re.sub(r"'[^']*'", "''", sql).lower()


class KatalogTests(unittest.TestCase):
    def test_yalnizca_tek_select(self):
        for c in katalog.MSSQL:
            sql = c["sql"]
            self.assertTrue(sql.upper().startswith("SELECT "), c["id"])
            govde = metinsiz(sql)
            for yasak in katalog.YASAKLI_MSSQL:
                desen = re.escape(yasak.strip()) if not yasak.strip().isalpha() else r"\b%s\b" % re.escape(yasak.strip())
                self.assertIsNone(re.search(desen, govde), "%s: yasakli ifade %r" % (c["id"], yasak))

    def test_yasakli_denetimi_gercekten_yakalar(self):
        for kotu in ("SELECT 1; DROP TABLE t", "SELECT * INTO x FROM y", "SELECT 1 EXEC xp_cmdshell 'dir'", "SELECT 1 -- yorum"):
            govde = metinsiz(kotu)
            bulundu = any(re.search(re.escape(y.strip()) if not y.strip().isalpha() else r"\b%s\b" % re.escape(y.strip()), govde)
                          for y in katalog.YASAKLI_MSSQL)
            self.assertTrue(bulundu, kotu)

    def test_kolonlar_sorguda_adlandirilmis(self):
        for c in katalog.MSSQL:
            for kolon in c["kolonlar"]:
                self.assertRegex(c["sql"], r"\bAS %s\b" % kolon, c["id"])
            self.assertLessEqual(set(c["maske"]), set(c["kolonlar"]), c["id"])
            self.assertTrue(c["id"].startswith("ms_"))

    def test_kullanici_tablosu_okunmaz(self):
        izinli = re.compile(r"^(sys\.|msdb\.dbo\.backupset$|tempdb\.sys\.)")
        for c in katalog.MSSQL:
            for nesne in re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", c["sql"]):
                self.assertRegex(nesne, izinli, c["id"])

    def test_uretilen_dosyalar_guncel_ve_yayimlanmaz(self):
        self.assertEqual(uret_toplayici.main(["--kontrol"]), 0)
        self.assertTrue(TOPLAYICI.is_file())
        self.assertFalse((ROOT / "site" / "assets" / "alig-toplayici-mssql.py").exists())
        self.assertNotIn("mssql", (ROOT / "site" / "pages" / "saglik-taramasi.html").read_text(encoding="utf-8").lower())

    def test_pg_katalog_ozeti_degismedi(self):
        self.assertEqual(uret_toplayici.katalog_ozeti(), uret_toplayici.katalog_ozeti("postgresql"))
        self.assertNotEqual(uret_toplayici.katalog_ozeti(), uret_toplayici.katalog_ozeti("mssql"))


class GirisSqlTests(unittest.TestCase):
    def test_yalniz_iki_okuma_yetkisi(self):
        kod = "\n".join(s for s in (ROOT / "tarama" / "onsurum" / "alig-giris-mssql.sql").read_text(encoding="utf-8").splitlines()
                        if not s.strip().startswith("--"))
        self.assertEqual(sorted(re.findall(r"GRANT\s+(.+?)\s+TO", kod)), ["VIEW ANY DEFINITION", "VIEW SERVER STATE"])
        self.assertNotRegex(kod, r"(?i)sysadmin|db_owner|db_datareader|CONTROL SERVER|ALTER ROLE|ADD MEMBER|CREATE USER")
        self.assertIn("$(ALIG_PAROLA)", kod)
        self.assertEqual(len(re.findall(r"PASSWORD\s*=\s*N'([^']*)'", kod)), 1)
        kaldir = (ROOT / "tarama" / "onsurum" / "alig-giris-mssql-kaldir.sql").read_text(encoding="utf-8")
        self.assertIn("DROP LOGIN alig_hc", kaldir)


class ToplayiciTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.sqlcmd = self.d / "sqlcmd"
        self.sqlcmd.write_text(SAHTE_SQLCMD, encoding="utf-8")
        self.sqlcmd.chmod(self.sqlcmd.stat().st_mode | stat.S_IEXEC)
        self.gunluk = self.d / "gunluk.txt"
        belge = temiz_mssql()
        self.veri = {c["id"]: {"sql": c["sql"], "satirlar": belge["kontroller"][c["id"]]["satirlar"]} for c in katalog.MSSQL}

    def calistir(self, ek=(), parola="gizli-parola-123", veri=None):
        (self.d / "veri.json").write_text(json.dumps(veri or self.veri), encoding="utf-8")
        env = dict(os.environ, SAHTE_VERI=str(self.d / "veri.json"), SAHTE_GUNLUK=str(self.gunluk))
        env.pop("SQLCMDPASSWORD", None)
        if parola:
            env["SQLCMDPASSWORD"] = parola
        return subprocess.run([sys.executable, str(TOPLAYICI), "--sunucu", "sql.ornek.local,1433", "--sqlcmd", str(self.sqlcmd),
                               "--out", str(self.d / "cikti.json")] + list(ek), capture_output=True, text=True, env=env, cwd=self.d)

    def test_dosya_uretir_ve_yukleme_kabul_eder(self):
        r = self.calistir(["--kullanici", "alig_hc", "--sifrele"])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        ham = (self.d / "cikti.json").read_bytes()
        belge = yukleme.coz(ham, ("postgresql", "mssql"))
        self.assertEqual(belge["motor"], "mssql")
        self.assertEqual(set(belge["kontroller"]), set(katalog.MSSQL_BY_ID))
        self.assertEqual(belge["kontroller"]["ms_surum"]["satirlar"][0]["ana_surum"], 16)
        self.assertNotIn(b"gizli-parola-123", ham)
        self.assertNotIn(b"sql.ornek.local", ham)

    def test_her_sorgu_salt_okuma_onlemleriyle_calisir(self):
        self.calistir(["--kullanici", "alig_hc"])
        cagrilar = [json.loads(s) for s in self.gunluk.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(cagrilar), len(katalog.MSSQL) + 1)
        for a in cagrilar:
            sorgu = a[a.index("-Q") + 1]
            self.assertIn("SET LOCK_TIMEOUT 2000", sorgu)
            self.assertIn("READ UNCOMMITTED", sorgu)
            self.assertIn("FOR JSON PATH", sorgu)
            self.assertEqual(a[a.index("-t") + 1], "15")
            self.assertNotIn("-P", a)
            self.assertNotIn("gizli-parola-123", " ".join(a))

    def test_maskeleme(self):
        self.calistir(["--kullanici", "alig_hc", "--maskele"])
        metin = (self.d / "cikti.json").read_text(encoding="utf-8")
        self.assertNotIn("satis", metin)
        self.assertIn("nesne-1", metin)
        self.assertTrue(json.loads(metin)["maskeli"])

    def test_hata_siniflari_ve_fazla_kolon(self):
        veri = dict(self.veri)
        veri["ms_yedek"] = {"sql": katalog.MSSQL_BY_ID["ms_yedek"]["sql"], "hata": "Msg 229, The SELECT permission was denied on the object 'backupset'"}
        veri["ms_kimlik"] = {"sql": katalog.MSSQL_BY_ID["ms_kimlik"]["sql"], "satirlar": [{"yalniz_windows": 1, "fazla": "x"}]}
        self.calistir(["--kullanici", "alig_hc"], veri=veri)
        belge = yukleme.coz((self.d / "cikti.json").read_bytes(), ("mssql",))
        self.assertEqual(belge["kontroller"]["ms_yedek"], {"durum": "hata", "neden": "yetki"})
        self.assertEqual(belge["kontroller"]["ms_kimlik"]["satirlar"], [{"yalniz_windows": 1}])

    def test_parola_ve_kimlik_secenekleri(self):
        self.assertNotEqual(self.calistir(["--kullanici", "alig_hc"], parola=None).returncode, 0)
        self.assertNotEqual(self.calistir([]).returncode, 0)
        self.assertNotEqual(self.calistir(["--kullanici", "a", "--windows"]).returncode, 0)
        self.assertNotEqual(self.calistir(["--kullanici", "a", "--password", "x"]).returncode, 0)
        r = self.calistir(["--windows"], parola=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-E", json.loads(self.gunluk.read_text(encoding="utf-8").splitlines()[-1]))

    def test_sysadmin_uyarisi(self):
        veri = dict(self.veri, __yonetici=1)
        r = self.calistir(["--kullanici", "sa"], veri=veri)
        self.assertIn("sysadmin", r.stderr)
        self.assertTrue(json.loads((self.d / "cikti.json").read_text(encoding="utf-8"))["superuser"])


class KuralTests(unittest.TestCase):
    def sablonlar(self, belge):
        return {b["sablon"]: b for b in kurallar.degerlendir(belge)[0]}

    def test_temiz_belge_bulgu_uretmez(self):
        bulgu, olcul = kurallar.degerlendir(temiz_mssql())
        self.assertEqual(bulgu, [])
        self.assertEqual(olcul, [])

    def test_surum_destegi(self):
        d = temiz_mssql()
        d["kontroller"]["ms_surum"]["satirlar"][0]["ana_surum"] = 13   # 2016: destek 2026-07-14'te bitti
        b = self.sablonlar(d)["ms_surum_eol"]
        self.assertEqual((b["onem"], b["kanit"]["surum"]), ("yuksek", "2016"))
        d["kontroller"]["ms_surum"]["satirlar"][0]["ana_surum"] = 11
        self.assertEqual(self.sablonlar(d)["ms_surum_eol"]["kanit"]["destek_sonu"], "gecmis")
        d["kontroller"]["ms_surum"]["satirlar"][0].update(ana_surum=12, motor_turu=5)   # Azure SQL: surum kurali uygulanmaz
        self.assertNotIn("ms_surum_eol", self.sablonlar(d))

    def test_yedek_ve_checkdb(self):
        d = temiz_mssql()
        d["kontroller"]["ms_yedek"]["satirlar"] = [
            {"veritabani": "a", "kurtarma_modeli": "SIMPLE", "tam_saat": None, "log_saat": None},
            {"veritabani": "b", "kurtarma_modeli": "FULL", "tam_saat": 10, "log_saat": 72},
            {"veritabani": "c", "kurtarma_modeli": "SIMPLE", "tam_saat": 10, "log_saat": None}]
        d["kontroller"]["ms_checkdb"]["satirlar"] = [{"veritabani": "a", "gun": 46000}, {"veritabani": "b", "gun": None}, {"veritabani": "c", "gun": 2}]
        s = self.sablonlar(d)
        self.assertEqual(s["ms_yedek"]["onem"], "yuksek")
        self.assertEqual(s["ms_yedek"]["kanit"]["nesneler"], ["a", "b"])
        self.assertEqual((s["ms_checkdb"]["kanit"]["veritabani_sayisi"], s["ms_checkdb"]["kanit"]["hic_calismamis"]), (1, 1))

    def test_ayar_ve_guvenlik_bulgulari(self):
        d = temiz_mssql()
        k = d["kontroller"]
        k["ms_db_ayar"]["satirlar"] = [
            {"veritabani": "x", "kimlik": 5, "auto_shrink": 1, "auto_close": 0, "sayfa_dogrulama": "NONE", "durum": "SUSPECT", "trustworthy": 1},
            {"veritabani": "msdb", "kimlik": 4, "auto_shrink": 0, "auto_close": 0, "sayfa_dogrulama": "CHECKSUM", "durum": "ONLINE", "trustworthy": 1}]
        k["ms_sunucu_ayar"]["satirlar"] = [{"ad": "xp_cmdshell", "deger": 1}, {"ad": "max server memory (MB)", "deger": 2147483647},
                                           {"ad": "cost threshold for parallelism", "deger": 5}]
        k["ms_sa"]["satirlar"] = [{"devre_disi": 0, "adi_sa": 1}]
        k["ms_parola_politikasi"]["satirlar"] = [{"sayi": 3}]
        k["ms_tempdb"]["satirlar"] = [{"veri_dosyasi": 1, "cpu": 8}]
        k["ms_ag"]["satirlar"] = [{"grup": "ag1", "replika": "n2", "saglik": "NOT_HEALTHY", "rol": "SECONDARY", "baglanti": "DISCONNECTED"}]
        k["ms_dosya_buyume"]["satirlar"] = [{"veritabani": "x", "dosya": "x_log", "tur": "LOG"}]
        k["ms_sifreleme"]["satirlar"] = [{"toplam": 10, "sifreli": 4}]
        k["ms_acik_islem"]["satirlar"] = [{"giris": "app", "sure_sn": 4000}]
        k["ms_kimlik"]["satirlar"] = [{"yalniz_windows": 0}]
        k["ms_sysadmin"]["satirlar"] = [{"giris": "dba1", "tur": "SQL_LOGIN", "devre_disi": 0}]
        d["superuser"] = True
        bulgu = kurallar.degerlendir(d)[0]
        s = {b["sablon"]: b for b in bulgu}
        beklenen = {"ms_db_durum": "yuksek", "ms_sayfa_dogrulama": "yuksek", "ms_auto": "orta", "ms_trustworthy": "orta",
                    "ms_tehlikeli_ayar": "yuksek", "ms_bellek": "orta", "ms_paralellik": "dusuk", "ms_sa": "orta",
                    "ms_parola_politikasi": "orta", "ms_tempdb": "orta", "ms_ag": "yuksek", "ms_dosya_buyume": "dusuk",
                    "ms_sifreleme": "orta", "ms_acik_islem": "yuksek", "ms_kimlik": "dusuk", "ms_sysadmin": "bilgi",
                    "ms_sysadmin_ile_tarama": "orta"}
        self.assertEqual({k2: v["onem"] for k2, v in s.items()}, beklenen)
        self.assertEqual(s["ms_trustworthy"]["kanit"]["nesneler"], ["x"])   # msdb sayilmaz
        sira = [kurallar.ONEM.index(b["onem"]) for b in bulgu]
        self.assertEqual(sira, sorted(sira))

    def test_olculemeyen_temiz_sayilmaz(self):
        d = temiz_mssql()
        d["kontroller"]["ms_yedek"] = {"durum": "hata", "neden": "yetki"}
        del d["kontroller"]["ms_ag"]
        bulgu, olcul = kurallar.degerlendir(d)
        self.assertEqual(sorted(olcul), [("ms_ag", "calistirilmadi"), ("ms_yedek", "yetki")])

    def test_her_sablon_iki_dilde_ve_nesne_adi_tasimaz(self):
        for ad, t in kurallar_mssql.T.items():
            for alan in ("baslik", "neden", "oneri", "risk", "geri"):
                self.assertTrue(t[alan]["tr"] and t[alan]["en"], ad)
            self.assertIn(t["is_"], kurallar.IS)

    def test_rapor_motoru_ve_on_surum_notu(self):
        d = temiz_mssql()
        d["kontroller"]["ms_ag"]["satirlar"] = [{"grup": "<b>ag</b>", "replika": "n2", "saglik": "NOT_HEALTHY", "rol": "SECONDARY", "baglanti": "CONNECTED"}]
        r = {"id": 1, "olusturma_utc": "2026-11-10T12:00:00Z", "bitis_utc": "2026-12-10T12:00:00Z", "motor": "mssql", "dil": "tr", "belge": d}
        tr = rapor.sayfa(r, "tr", "t")
        self.assertIn("SQL Server", tr)
        self.assertIn("ön sürümdür", tr)
        self.assertNotIn("<b>ag</b>", tr)
        self.assertIn("preview", rapor.sayfa(r, "en", "t"))
        pg = {"id": 2, "olusturma_utc": "2026-11-10T12:00:00Z", "bitis_utc": "2026-12-10T12:00:00Z", "motor": "postgresql", "dil": "tr", "belge": pg_temiz_belge()}
        self.assertNotIn("ön sürümdür", rapor.sayfa(pg, "tr", "t"))


class YuklemeKapisiTests(test_tarama.SunucuTests):
    def test_mssql_varsayilan_olarak_kapali(self):
        r = self.yukle(json.dumps(temiz_mssql()).encode())
        self.assertEqual(r.status, 422)
        self.assertIn("henüz açık değil", r.govde)

    def test_mssql_acilinca_rapor_verir(self):
        self.H.motorlar = ("postgresql", "mssql")
        r = self.yukle(json.dumps(temiz_mssql()).encode())
        self.assertEqual(r.status, 303)
        self.assertIn("SQL Server", self.get(r.getheader("Location"))[1].decode())

    def test_motorlar_arasi_kontrol_karismaz(self):
        self.H.motorlar = ("postgresql", "mssql")
        d = temiz_mssql()
        d["kontroller"]["pg_surum"] = {"durum": "ok", "satirlar": [{"surum_num": 160000}]}
        self.assertEqual(self.yukle(json.dumps(d).encode()).status, 422)
        d = temiz_mssql()
        d["motor"] = "oracle"
        self.assertEqual(self.yukle(json.dumps(d).encode()).status, 422)


# Devralinan PostgreSQL sunucu testleri burada yeniden kosmasin.
for _ad in [a for a in dir(test_tarama.SunucuTests) if a.startswith("test_")]:
    setattr(YuklemeKapisiTests, _ad, None)
del test_tarama


if __name__ == "__main__":
    unittest.main()
