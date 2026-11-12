import copy
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import depo, katalog, kurallar, rapor, server as tserver, uret_toplayici, yukleme  # noqa: E402


def temiz_belge():
    k = {}
    for c in katalog.PG:
        k[c["id"]] = {"durum": "ok", "satirlar": []}
    k["pg_surum"]["satirlar"] = [{"surum_num": 180000}]
    k["pg_baglanti"]["satirlar"] = [{"kullanilan": 10, "ust": 100}]
    k["pg_arsiv"]["satirlar"] = [{"archive_mode": "on", "basarili": 5, "hatali": 0, "son_basari_utc": "2026-11-10T10:00:00Z", "son_hata_utc": None}]
    k["pg_tls_parola"]["satirlar"] = [{"ssl": "on", "password_encryption": "scram-sha-256", "ssl_min_protocol_version": "TLSv1.2"}]
    k["pg_public_create"]["satirlar"] = [{"public_create": False}]
    k["pg_log_ayarlari"]["satirlar"] = [{"name": "log_connections", "setting": "on"}, {"name": "log_disconnections", "setting": "on"}]
    k["pg_md5_roller"]["satirlar"] = [{"sayi": 0}]
    return {"format": katalog.FORMAT, "motor": katalog.MOTOR, "katalog_sha256": uret_toplayici.katalog_ozeti(),
            "olusturma_utc": "2026-11-10T12:00:00Z", "maskeli": False, "superuser": False, "kontroller": k}


class AyristirmaTests(unittest.TestCase):
    def kod(self, veri):
        try:
            yukleme.coz(veri)
        except yukleme.Gecersiz as e:
            return e.kod
        return None

    def test_derinlik_siniri(self):
        self.assertEqual(self.kod(b"[" * 200000), "derin")
        self.assertEqual(self.kod(b'{"a":' * 100000), "derin")
        self.assertEqual(self.kod(b'{"a":' * (yukleme.MAX_DERINLIK + 1) + b"1" + b"}" * (yukleme.MAX_DERINLIK + 1)), "derin")
        ic = b'{"x": "[[[[[[[[[[[[[[[[[[[[ {{{{{{{{{{{{{{{{{{{{{{ \\" [[[["}'   # metin icindeki parantez sayilmaz
        self.assertEqual(self.kod(ic), "alanlar")

    def test_standart_disi_json_reddedilir(self):
        self.assertEqual(self.kod(b'{"format": NaN}'), "json")
        self.assertEqual(self.kod(b'{"format": -Infinity}'), "json")
        self.assertEqual(self.kod(b'{"format":1,"format":2}'), "json")
        self.assertEqual(self.kod(b"\xff\xfe"), "json")
        self.assertEqual(self.kod(b""), "json")

    def test_gecerli_belge_hala_kabul_edilir(self):
        self.assertIsNone(self.kod(json.dumps(temiz_belge(), indent=1).encode()))


class KatalogTests(unittest.TestCase):
    def test_katalog_yalniz_select_ve_yasakli_sozcuk_yok(self):
        yasakli = [w.strip() for w in katalog.YASAKLI]
        for c in katalog.PG:
            sql = re.sub(r"'[^']*'", "''", c["sql"]).lower()
            self.assertTrue(sql.lstrip().startswith("select"), c["id"])
            self.assertNotIn(";", sql, c["id"])
            for w in yasakli:
                kalip = r"\b" + re.escape(w) + (r"" if w.endswith("_") else r"\b")
                self.assertIsNone(re.search(kalip, sql), "%s: yasakli sozcuk %s" % (c["id"], w))

    def test_katalog_kullanici_tablosu_okumaz(self):
        for c in katalog.PG:
            for tablo in re.findall(r"\bfrom\s+([a-z_\.]+)", c["sql"].lower()):
                self.assertTrue(tablo.startswith("pg_") or tablo == "now", "%s: %s" % (c["id"], tablo))

    def test_uretilen_toplayici_guncel(self):
        self.assertEqual(uret_toplayici.main(["--kontrol"]), 0)

    def test_toplayici_dosyasinda_baglanti_yok(self):
        # toplayici parola argumani kabul etmez
        kod = (ROOT / "site" / "assets" / "alig-toplayici.py").read_text(encoding="utf-8")
        self.assertNotIn("--password", kod)
        self.assertNotIn("--parola", kod)
        r = subprocess.run([sys.executable, str(ROOT / "site" / "assets" / "alig-toplayici.py"), "--password", "x"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class KuralTests(unittest.TestCase):
    def test_temiz_belge_bulgu_yok(self):
        b, o = kurallar.degerlendir(temiz_belge())
        self.assertEqual(b, [], b)
        self.assertEqual(o, [])

    def test_bulgu_var(self):
        d = temiz_belge()
        d["kontroller"]["pg_surum"]["satirlar"] = [{"surum_num": 130020}]
        d["kontroller"]["pg_baglanti"]["satirlar"] = [{"kullanilan": 95, "ust": 100}]
        d["kontroller"]["pg_gecersiz_indeks"]["satirlar"] = [{"schemaname": "public", "indexrelname": "i1"}]
        d["kontroller"]["pg_xid_yasi"]["satirlar"] = [{"datname": "x", "yas": 1700000000, "mxid_yas": 1, "freeze_max_age": 200000000}]
        d["kontroller"]["pg_slot"]["satirlar"] = [{"slot_name": "s", "active": False, "wal_status": "lost", "geri_bayt": 5}]
        b, _ = kurallar.degerlendir(d)
        onem = {x["sablon"]: x["onem"] for x in b}
        self.assertEqual(onem["pg_surum_eol"], "yuksek")
        self.assertEqual(onem["pg_baglanti"], "yuksek")
        self.assertEqual(onem["pg_gecersiz_indeks"], "yuksek")
        self.assertEqual(onem["pg_xid_yasi"], "kritik")
        self.assertEqual(onem["pg_slot"], "kritik")
        self.assertEqual([x["onem"] for x in b], sorted([x["onem"] for x in b], key=kurallar.ONEM.index))  # onem sirasi

    def test_olculemedi_temiz_degildir(self):
        d = temiz_belge()
        d["kontroller"]["pg_md5_roller"] = {"durum": "hata", "neden": "yetki"}
        b, o = kurallar.degerlendir(d)
        self.assertEqual(o, [("pg_md5_roller", "yetki")])
        self.assertFalse(any(x["sablon"] == "pg_parola_md5" for x in b))

    def test_superuser_bulgusu(self):
        d = temiz_belge()
        d["superuser"] = True
        b, _ = kurallar.degerlendir(d)
        self.assertTrue(any(x["sablon"] == "pg_super" for x in b))

    def test_surum_destek_sonu_yaklasiyor(self):
        d = temiz_belge()
        d["kontroller"]["pg_surum"]["satirlar"] = [{"surum_num": 140010}]
        d["olusturma_utc"] = "2026-10-01T00:00:00Z"
        b, _ = kurallar.degerlendir(d)
        self.assertEqual([x["onem"] for x in b if x["sablon"] == "pg_surum_eol"], ["orta"])

    def test_bulgu_metinlerinde_nesne_adi_yok(self):
        d = temiz_belge()
        d["kontroller"]["pg_gecersiz_indeks"]["satirlar"] = [{"schemaname": "GIZLI_SEMA", "indexrelname": "GIZLI_INDEKS"}]
        b, _ = kurallar.degerlendir(d)
        for x in b:
            metin = json.dumps({k: x[k] for k in ("baslik", "neden", "oneri", "risk", "geri_alma")})
            self.assertNotIn("GIZLI", metin)


class YuklemeTests(unittest.TestCase):
    def test_gecerli(self):
        yukleme.dogrula(temiz_belge())

    def _reddet(self, mut):
        d = temiz_belge()
        mut(d)
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.dogrula(d)

    def test_yukleme_bilinmeyen_kolon(self):
        self._reddet(lambda d: d["kontroller"]["pg_baglanti"]["satirlar"].append({"kullanilan": 1, "ust": 2, "icerik": "x"}))

    def test_yukleme_bilinmeyen_kontrol_ve_alan(self):
        self._reddet(lambda d: d["kontroller"].update({"pg_tablo_icerigi": {"durum": "ok", "satirlar": []}}))
        self._reddet(lambda d: d.update({"ekstra": 1}))

    def test_yukleme_tur_ve_uzunluk(self):
        self._reddet(lambda d: d["kontroller"]["pg_baglanti"]["satirlar"].__setitem__(0, {"kullanilan": {"x": 1}, "ust": 2}))
        self._reddet(lambda d: d["kontroller"]["pg_super_roller"]["satirlar"].append({"rolname": "a" * 201, "rolcanlogin": True}))
        self._reddet(lambda d: d["kontroller"]["pg_super_roller"].__setitem__("satirlar", [{"rolname": "a", "rolcanlogin": True}] * 201))

    def test_yukleme_katalog_ozeti(self):
        self._reddet(lambda d: d.update({"katalog_sha256": "0" * 64}))

    def test_yukleme_hata_kaydi(self):
        self._reddet(lambda d: d["kontroller"].update({"pg_md5_roller": {"durum": "hata", "neden": "ERROR: relation \"musteri\" ..."}}))

    def test_yukleme_boyut_ve_json(self):
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.coz(b"x" * (yukleme.MAX_BAYT + 1))
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.coz(b"{bozuk")
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.coz(b"[1,2]")


class RaporTests(unittest.TestCase):
    def _rapor(self, d, dil="tr"):
        return {"id": 1, "olusturma_utc": "2026-11-10T12:00:00Z", "bitis_utc": "2026-12-10T12:00:00Z", "motor": "postgresql", "dil": dil, "belge": d}

    def test_rapor_kacis(self):
        d = temiz_belge()
        d["kontroller"]["pg_gecersiz_indeks"]["satirlar"] = [{"schemaname": "<script>alert(1)</script>", "indexrelname": "\"><img src=x onerror=1>"}]
        html = rapor.sayfa(self._rapor(d), "tr", "T" * 43)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)

    def test_rapor_iki_dil_ve_olculemeyen(self):
        d = temiz_belge()
        d["kontroller"]["pg_md5_roller"] = {"durum": "hata", "neden": "yetki"}
        tr = rapor.sayfa(self._rapor(d), "tr", "T" * 43)
        en = rapor.sayfa(self._rapor(d, "en"), "en", "T" * 43)
        self.assertIn("Ölçülemeyenler", tr)
        self.assertIn("Not measured", en)
        self.assertIn("pg_md5_roller", tr)


class DepoTests(unittest.TestCase):
    def con(self):
        return depo.baglan(str(Path(tempfile.mkdtemp()) / "t.sqlite"))

    def test_wal_ve_surum(self):
        c = self.con()
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], len(depo.GOCLER))

    def test_zincir_saglam_ve_kirik(self):
        c = self.con()
        for i in range(3):
            depo.denetim_ekle(c, "musteri", "olay %d" % i)
        self.assertIsNone(depo.denetim_dogrula(c))
        c.execute("UPDATE denetim SET olay='degistirildi' WHERE seq=2")
        self.assertEqual(depo.denetim_dogrula(c), 2)

    def test_zincir_silinen_kayit(self):
        c = self.con()
        for i in range(3):
            depo.denetim_ekle(c, "a", "o%d" % i)
        c.execute("DELETE FROM denetim WHERE seq=2")
        self.assertIsNotNone(depo.denetim_dogrula(c))

    def test_token_saklanmaz_ve_sure(self):
        c = self.con()
        depo.rapor_ekle(c, "gizlitoken", "postgresql", "tr", {"a": 1})
        satirlar = c.execute("SELECT * FROM rapor").fetchall()
        self.assertNotIn("gizlitoken", json.dumps(satirlar))
        self.assertIsNotNone(depo.rapor_getir(c, "gizlitoken"))
        self.assertIsNone(depo.rapor_getir(c, "baska"))
        c.execute("UPDATE rapor SET bitis_utc='2000-01-01T00:00:00Z'")
        self.assertIsNone(depo.rapor_getir(c, "gizlitoken"))
        self.assertEqual(depo.suresi_dolanlari_sil(c), 1)


class SunucuTests(unittest.TestCase):
    def setUp(self):
        self.db = str(Path(tempfile.mkdtemp()) / "s.sqlite")
        depo.baglan(self.db).close()
        self.H = type("H", (tserver.H,), {"db_yolu": self.db, "sinir": tserver.RateLimiter(per_window=50)})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def yukle(self, veri, yetki=True, ctype=None, eposta="ali@ornek.com.tr", sirket="Ornek AS", dil="tr"):
        sinir = "----sinir"
        parcalar = []
        if sirket:
            parcalar.append('--%s\r\nContent-Disposition: form-data; name="sirket"\r\n\r\n%s\r\n' % (sinir, sirket))
        if eposta:
            parcalar.append('--%s\r\nContent-Disposition: form-data; name="eposta"\r\n\r\n%s\r\n' % (sinir, eposta))
        if yetki:
            parcalar.append('--%s\r\nContent-Disposition: form-data; name="yetki"\r\n\r\non\r\n' % sinir)
        parcalar.append('--%s\r\nContent-Disposition: form-data; name="dil"\r\n\r\n%s\r\n' % (sinir, dil))
        govde = "".join(parcalar).encode() + ('--%s\r\nContent-Disposition: form-data; name="dosya"; filename="a.json"\r\nContent-Type: application/json\r\n\r\n' % sinir).encode() \
            + veri + ("\r\n--%s--\r\n" % sinir).encode()
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/api/tarama/yukle", body=govde, headers={"Content-Type": ctype or "multipart/form-data; boundary=" + sinir})
        r = c.getresponse()
        r.govde = r.read().decode("utf-8", "replace")
        return r

    def get(self, yol):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("GET", yol)
        r = c.getresponse()
        return r, r.read()

    def test_yukle_rapor_sil_ve_denetim(self):
        r = self.yukle(json.dumps(temiz_belge()).encode())
        self.assertEqual(r.status, 303)
        yol = r.getheader("Location")
        self.assertRegex(yol, r"^/rapor/[A-Za-z0-9_\-]{43}/$")
        g, govde = self.get(yol)
        self.assertEqual(g.status, 200)
        self.assertIn("Sağlık taraması raporu", govde.decode())
        self.assertEqual(g.getheader("Cache-Control"), "no-store")
        self.assertEqual(self.get("/rapor/" + "A" * 43 + "/")[0].status, 404)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", yol + "sil")
        self.assertEqual(c.getresponse().status, 303)
        self.assertEqual(self.get(yol)[0].status, 404)
        con = depo.baglan(self.db)
        self.assertIsNone(depo.denetim_dogrula(con))
        olaylar = [x[0] for x in con.execute("SELECT olay FROM denetim")]
        self.assertTrue(any("yuklendi" in o for o in olaylar) and any("silindi" in o for o in olaylar))
        self.assertFalse(any(yol.split("/")[2] in o for o in olaylar))  # token denetim kaydina yazilmaz

    def test_dusmanca_json_sunucuyu_dusurmez(self):
        for veri in (b"[" * 200000, b'{"a":' * 100000, b'{"format": NaN}', b'{"format": Infinity}',
                     b'{"format":1,"format":2}', b"\xff\xfe{}", b'{"a":"' + b"\\u0000" * 10 + b'"}', b"9" * 100000):
            r = self.yukle(veri)
            self.assertEqual(r.status, 422, veri[:20])
            self.assertIn("<html", r.govde)
        self.assertEqual(self.yukle(json.dumps(temiz_belge()).encode()).status, 303)   # sunucu ayakta

    def test_hata_sayfasi_kurumsal_ve_iki_dilli(self):
        r = self.yukle(b"{bozuk")
        self.assertEqual(r.status, 422)
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))
        self.assertIn('<html lang="tr">', r.govde)
        self.assertIn('href="/tarama-hazirlik/"', r.govde)
        self.assertIn('href="/saglik-taramasi/"', r.govde)
        self.assertIn("/assets/style.css", r.govde)
        en = self.yukle(b"{bozuk", dil="en")
        self.assertIn('<html lang="en">', en.govde)
        self.assertIn('href="/en/tarama-hazirlik/"', en.govde)
        self.assertNotEqual(r.govde, en.govde)

    def test_hata_sayfasi_her_durum_icin_ayri_ve_kacisli(self):
        veri = json.dumps(temiz_belge()).encode()
        govdeler = [self.yukle(veri, yetki=False).govde, self.yukle(veri, eposta="yanlis").govde,
                    self.yukle(veri, sirket=None).govde, self.yukle(b"{bozuk").govde]
        self.assertEqual(len(set(govdeler)), 4)
        d = temiz_belge()
        d["kontroller"]["<script>x</script>"] = {"durum": "ok", "satirlar": []}
        g = self.yukle(json.dumps(d).encode()).govde
        self.assertNotIn("<script>x", g)

    def test_teknik_ayrinti_musteri_dilinde(self):
        d = temiz_belge()
        d["kontroller"]["pg_surum"]["durum"] = "uydurma"
        veri = json.dumps(d).encode()
        tr = self.yukle(veri).govde
        en = self.yukle(veri, dil="en").govde
        self.assertIn("pg_surum", tr)
        self.assertIn("durum değeri geçersiz", tr)
        self.assertIn("status value is not valid", en)
        self.assertNotIn("durum gecersiz", tr + en)

    def test_yetki_beyani_ve_gecersiz_dosya(self):
        self.assertEqual(self.yukle(json.dumps(temiz_belge()).encode(), yetki=False).status, 422)
        self.assertEqual(self.yukle(b"{bozuk").status, 422)
        d = temiz_belge()
        d["kontroller"]["pg_super_roller"]["satirlar"] = [{"rolname": "x", "rolcanlogin": True, "parola": "gizli"}]
        self.assertEqual(self.yukle(json.dumps(d).encode()).status, 422)

    def test_tur_ve_boyut(self):
        self.assertEqual(self.yukle(b"{}", ctype="application/json").status, 415)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port)
        c.request("POST", "/api/tarama/yukle", body=b"x", headers={"Content-Type": "multipart/form-data; boundary=a", "Content-Length": str(tserver.GOVDE_SINIRI + 1)})
        self.assertEqual(c.getresponse().status, 413)

    def test_sirket_siniri_alan_adina_gore(self):
        veri = json.dumps(temiz_belge()).encode()
        kodlar = [self.yukle(veri, eposta="a@ornek.com").status, self.yukle(veri, eposta="b@ORNEK.com").status,
                  self.yukle(veri, eposta="c@ornek.com").status, self.yukle(veri, eposta="d@baska.com").status]
        self.assertEqual(kodlar, [303, 303, 429, 303])
        con = depo.baglan(self.db)
        self.assertIsNone(depo.denetim_dogrula(con))
        self.assertNotIn("ornek.com", json.dumps(con.execute("SELECT * FROM kullanim").fetchall()))  # sinir tablosunda duz adres yok

    def test_sirket_siniri_ucretsiz_posta_adrese_gore(self):
        veri = json.dumps(temiz_belge()).encode()
        for _ in range(2):
            self.assertEqual(self.yukle(veri, eposta="x@gmail.com").status, 303)
        self.assertEqual(self.yukle(veri, eposta="x@gmail.com").status, 429)
        self.assertEqual(self.yukle(veri, eposta="y@gmail.com").status, 303)

    def test_gecersiz_dosya_hak_harcamaz(self):
        for _ in range(3):
            self.assertEqual(self.yukle(b"{bozuk", eposta="z@ornek.org").status, 422)
        self.assertEqual(self.yukle(json.dumps(temiz_belge()).encode(), eposta="z@ornek.org").status, 303)

    def test_eposta_zorunlu_ve_gecerli(self):
        veri = json.dumps(temiz_belge()).encode()
        self.assertEqual(self.yukle(veri, eposta=None).status, 422)
        self.assertEqual(self.yukle(veri, eposta="yanlis").status, 422)

    def test_sinir_suresi_dolunca_serbest(self):
        con = depo.baglan(self.db)
        a = depo.sirket_anahtari("q@ornek.net")
        depo.kullanim_ekle(con, a)
        depo.kullanim_ekle(con, a)
        self.assertEqual(depo.kullanim_say(con, a), 2)
        con.execute("UPDATE kullanim SET zaman_utc='2000-01-01T00:00:00Z'")
        self.assertEqual(depo.kullanim_say(con, a), 0)
        self.assertEqual(depo.suresi_dolanlari_sil(con), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM kullanim").fetchone()[0], 0)

    def test_firma_kaydi_ve_rapor_eslesmesi(self):
        veri = json.dumps(temiz_belge()).encode()
        self.assertEqual(self.yukle(veri, eposta="Ayse@Firma.com.tr", sirket="Firma <b>AS</b>").status, 303)
        self.assertEqual(self.yukle(veri, eposta="mehmet@firma.com.tr", sirket="Baska Ad").status, 303)
        con = depo.baglan(self.db)
        firmalar = depo.firma_listele(con)
        self.assertEqual(len(firmalar), 1)  # ayni alan adi tek firma
        f = firmalar[0]
        self.assertEqual((f["anahtar"], f["ad"], f["eposta"], f["durum"], f["rapor_sayisi"]), ("firma.com.tr", "Firma <b>AS</b>", "mehmet@firma.com.tr", "aktif", 2))
        self.assertEqual({r["firma_id"] for r in depo.rapor_listele(con)}, {f["id"]})

    def test_sirket_adi_zorunlu(self):
        veri = json.dumps(temiz_belge()).encode()
        self.assertEqual(self.yukle(veri, sirket=None).status, 422)
        self.assertEqual(self.yukle(veri, sirket="x" * 161).status, 422)

    def test_pasif_firma_yukleyemez_aktif_edilince_yukler(self):
        veri = json.dumps(temiz_belge()).encode()
        self.assertEqual(self.yukle(veri, eposta="a@pasif.com").status, 303)
        con = depo.baglan(self.db)
        fid = depo.firma_listele(con)[0]["id"]
        depo.firma_durum_yaz(con, fid, "pasif")
        self.assertEqual(self.yukle(veri, eposta="b@pasif.com").status, 403)
        self.assertEqual(len(depo.rapor_listele(con)), 1)
        self.assertEqual(depo.kullanim_say(con, depo.sirket_anahtari("a@pasif.com")), 1)  # reddedilen istek hak harcamaz
        depo.firma_durum_yaz(con, fid, "aktif")
        self.assertEqual(self.yukle(veri, eposta="b@pasif.com").status, 303)
        with self.assertRaises(ValueError):
            depo.firma_durum_yaz(con, fid, "uydurma")

    def test_firma_sinir_sifirlama_ve_silme(self):
        veri = json.dumps(temiz_belge()).encode()
        for _ in range(2):
            self.assertEqual(self.yukle(veri, eposta="a@dolu.com").status, 303)
        self.assertEqual(self.yukle(veri, eposta="a@dolu.com").status, 429)
        con = depo.baglan(self.db)
        fid = depo.firma_listele(con)[0]["id"]
        self.assertEqual(depo.firma_sinir_sifirla(con, fid), 2)
        self.assertEqual(self.yukle(veri, eposta="a@dolu.com").status, 303)
        self.assertEqual(depo.firma_sil(con, fid), 3)
        self.assertEqual((depo.firma_listele(con), depo.rapor_listele(con)), ([], []))
        self.assertIsNone(depo.firma_sil(con, fid))

    def test_eski_veritabani_goc_eder(self):
        import sqlite3
        yol = str(Path(tempfile.mkdtemp()) / "eski.sqlite")
        c = sqlite3.connect(yol)
        for g in depo.GOCLER[:4]:
            c.execute(g)
        c.execute("PRAGMA user_version=4")
        c.execute("INSERT INTO rapor(token_sha256, olusturma_utc, bitis_utc, motor, dil, belge_json) VALUES('x','2026-01-01T00:00:00Z','2099-01-01T00:00:00Z','postgresql','tr','{}')")
        c.commit()
        c.close()
        con = depo.baglan(yol)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], len(depo.GOCLER))
        self.assertIsNone(depo.rapor_listele(con)[0]["firma_id"])

    def test_saglik_ucu(self):
        self.assertEqual(self.get("/api/tarama/saglik")[0].status, 200)

    def test_hiz_siniri(self):
        self.H.sinir = tserver.RateLimiter(per_window=2)
        self.H.sirket_adet = 100
        kodlar = [self.yukle(b"{}").status for _ in range(3)]
        self.assertEqual(kodlar[-1], 429)


@unittest.skipUnless(os.environ.get("ALIG_TEST_PG_HOST"), "ALIG_TEST_PG_HOST yok: gercek PostgreSQL denemesi atlandi")
class GercekPgTests(unittest.TestCase):
    """ALIG_TEST_PG_HOST (soket dizini ya da host), ALIG_TEST_PG_PORT, ALIG_TEST_PG_USER ile calisir."""

    def calistir(self, *ek):
        cikti = Path(tempfile.mkdtemp()) / "t.json"
        env = dict(os.environ)
        r = subprocess.run([sys.executable, str(ROOT / "site" / "assets" / "alig-toplayici.py"), "--host", os.environ["ALIG_TEST_PG_HOST"],
                            "--port", os.environ.get("ALIG_TEST_PG_PORT", "5432"), "--user", os.environ.get("ALIG_TEST_PG_USER", "alig_hc"),
                            "--out", str(cikti)] + list(ek), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(cikti.read_text())

    def test_toplama_dogrulanir_ve_maskelenir(self):
        d = self.calistir("--maskele")
        yukleme.dogrula(d)
        self.assertTrue(d["maskeli"])
        b, o = kurallar.degerlendir(d)
        self.assertTrue(len(b) + len(o) > 0)

    def test_salt_okunur(self):
        # katalogdaki sorgular salt okunur oturumda calisir; yazma ayni ayarla reddedilir
        r = subprocess.run(["psql", "-X", "-A", "-t", "-h", os.environ["ALIG_TEST_PG_HOST"], "-p", os.environ.get("ALIG_TEST_PG_PORT", "5432"),
                            "-U", os.environ.get("ALIG_TEST_PG_USER", "alig_hc"), "-d", "postgres", "-c", "CREATE TABLE alig_yazma_denemesi(i int)"],
                           capture_output=True, text=True, env=dict(os.environ, PGOPTIONS="-c default_transaction_read_only=on"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("read-only", r.stderr)


if __name__ == "__main__":
    unittest.main()
