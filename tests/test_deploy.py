import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import functools

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT))
import bakim  # noqa: E402
import hazirlik  # noqa: E402
import duman_testi  # noqa: E402
import paketle  # noqa: E402
from tarama import depo, saklama  # noqa: E402
from yonetim import depo as ydepo  # noqa: E402


class PaketTests(unittest.TestCase):
    def test_tekrarlanabilir_ve_manifest(self):
        a, oa = paketle.paketle("9.9.9", "https://alig.tech", out_dir=tempfile.mkdtemp())
        b, ob = paketle.paketle("9.9.9", "https://alig.tech", out_dir=tempfile.mkdtemp())
        self.assertEqual(oa, ob)
        with tarfile.open(a) as tar:
            adlar = tar.getnames()
            manifest = tar.extractfile("MANIFEST.sha256").read().decode()
            for satir in manifest.splitlines():
                ozet, ad = satir.split("  ", 1)
                self.assertEqual(hashlib.sha256(tar.extractfile(ad).read()).hexdigest(), ozet, ad)
            self.assertEqual(tar.extractfile("site/surum.txt").read().decode().strip(), "9.9.9")
        for gerekli in ("site/index.html", "site/en/index.html", "form/server.py", "tarama/server.py", "VERSION"):
            self.assertIn(gerekli, adlar)
        self.assertFalse([x for x in adlar if "__pycache__" in x or x.endswith(".sqlite")])

    def test_surum_bicimi_ve_release_kapisi(self):
        with self.assertRaises(SystemExit):
            paketle.paketle("v1", "https://alig.tech", out_dir=tempfile.mkdtemp())
        with self.assertRaises(SystemExit):  # yer tutucular dururken --release durur
            paketle.paketle("1.0.0", "https://alig.tech", release=True, out_dir=tempfile.mkdtemp())


class BakimTests(unittest.TestCase):
    def test_yedek_butunluk_eski_silme_ve_rapor_temizligi(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        con = depo.baglan(str(veri / "tarama.sqlite"))
        depo.rapor_ekle(con, "eski", "postgresql", "tr", {"a": 1})
        con.execute("UPDATE rapor SET bitis_utc='2000-01-01T00:00:00Z'")
        con.commit()
        con.close()
        f = sqlite3.connect(veri / "form.sqlite")
        f.execute("CREATE TABLE contact(id INTEGER PRIMARY KEY, created_utc TEXT NOT NULL)")
        f.commit()
        f.close()
        for i in range(3):
            (yedek / f"form-2020010{i}T000000Z.sqlite").write_text("x")
        self.assertEqual(bakim.main(["--veri", str(veri), "--yedek", str(yedek), "--sakla", "2"]), 0)
        yedekler = sorted(p.name for p in yedek.iterdir())
        self.assertEqual(len([x for x in yedekler if x.startswith("form-")]), 2)  # 3 eski + 1 yeni, 2 kalir
        self.assertEqual(len([x for x in yedekler if x.startswith("tarama-")]), 1)
        yeni = next(p for p in yedek.iterdir() if p.name.startswith("tarama-"))
        self.assertEqual(oct(yeni.stat().st_mode)[-3:], "600")
        self.assertEqual(sqlite3.connect(veri / "tarama.sqlite").execute("SELECT count(*) FROM rapor").fetchone()[0], 0)
        self.assertEqual(sqlite3.connect(yeni).execute("PRAGMA integrity_check").fetchone()[0], "ok")


FORM_SEMA = "CREATE TABLE contact(id INTEGER PRIMARY KEY, created_utc TEXT NOT NULL, name TEXT, company TEXT, email TEXT, db TEXT, message TEXT, ip_hash TEXT)"


class SaklamaTests(unittest.TestCase):
    def kur(self):
        veri = Path(tempfile.mkdtemp())
        con = depo.baglan(str(veri / "tarama.sqlite"))
        return veri, con

    def test_varsayilan_ve_ortam_ayari(self):
        self.assertEqual(saklama.gun("firma", {}), 365)
        self.assertEqual(saklama.gun("firma", {"ALIG_SAKLAMA_FIRMA_GUN": "90"}), 90)
        self.assertIsNone(saklama.gun("firma", {"ALIG_SAKLAMA_FIRMA_GUN": "suresiz"}))
        self.assertIsNone(saklama.gun("denetim", {}))
        for kotu in ("abc", "-5", "99999", "1.5"):
            with self.assertRaises(saklama.SaklamaHatasi):
                saklama.gun("firma", {"ALIG_SAKLAMA_FIRMA_GUN": kotu})
        with self.assertRaises(saklama.SaklamaHatasi):  # rapor suresiz olamaz
            saklama.gun("rapor", {"ALIG_SAKLAMA_RAPOR_GUN": "0"})

    def test_rapor_suresi_ortamdan(self):
        veri, con = self.kur()
        with mock.patch.dict(os.environ, {"ALIG_SAKLAMA_RAPOR_GUN": "7"}):
            depo.rapor_ekle(con, "t", "postgresql", "tr", {"a": 1})
        bitis = con.execute("SELECT bitis_utc, olusturma_utc FROM rapor").fetchone()
        fark = datetime.strptime(bitis[0], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(bitis[1], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(fark.days, 7)

    def test_eski_firma_silinir_etkin_raporlu_ve_yeni_firma_kalir(self):
        veri, con = self.kur()
        eski = depo.firma_kaydet(con, "eski.com", "Eski A.S.", "a@eski.com", "yukleme", zaman="2020-01-01T00:00:00Z")
        raporlu = depo.firma_kaydet(con, "raporlu.com", "R", "a@raporlu.com", "yukleme", zaman="2020-01-01T00:00:00Z")
        yeni = depo.firma_kaydet(con, "yeni.com", "Y", "a@yeni.com", "yukleme")
        depo.rapor_ekle(con, "tok", "postgresql", "tr", {"a": 1}, firma_id=raporlu["id"])
        self.assertEqual(depo.saklama_uygula(con), 1)
        kalan = {r[0] for r in con.execute("SELECT id FROM firma")}
        self.assertEqual(kalan, {raporlu["id"], yeni["id"]})
        olaylar = [r[0] for r in con.execute("SELECT olay FROM denetim")]
        self.assertTrue(any("saklama suresi doldu, firma #%d silindi" % eski["id"] == o for o in olaylar))
        self.assertFalse(any("Eski A.S." in o or "eski.com" in o for o in olaylar))  # kisisel veri denetime yazilmaz
        self.assertIsNone(depo.denetim_dogrula(con))

    def test_saklamayla_silinen_firma_eski_talepten_geri_gelmez(self):
        veri, con = self.kur()
        depo.firma_kaydet(con, "eski.com", "E", "a@eski.com", "talep", zaman="2020-01-01T00:00:00Z", guncelle=False)
        self.assertEqual(depo.saklama_uygula(con), 1)
        self.assertIsNone(depo.firma_kaydet(con, "eski.com", "E", "a@eski.com", "talep", zaman="2020-01-01T00:00:00Z", guncelle=False))
        self.assertEqual(con.execute("SELECT count(*) FROM firma").fetchone()[0], 0)
        self.assertIsNotNone(depo.firma_kaydet(con, "eski.com", "E", "a@eski.com", "tarama"))  # yeni etkinlik yeni kayit acar

    def test_saklama_silmesi_denetimsiz_kalmaz(self):
        veri, con = self.kur()
        depo.firma_kaydet(con, "eski.com", "E", "a@eski.com", "yukleme", zaman="2020-01-01T00:00:00Z")
        with mock.patch.object(depo, "denetim_ekle", side_effect=RuntimeError("denetim yazilamadi")):
            with self.assertRaises(RuntimeError):
                depo.saklama_uygula(con)
        self.assertEqual(con.execute("SELECT count(*) FROM firma").fetchone()[0], 1)

    def test_firma_suresiz_ise_dokunulmaz(self):
        veri, con = self.kur()
        depo.firma_kaydet(con, "eski.com", "E", "a@eski.com", "yukleme", zaman="2020-01-01T00:00:00Z")
        with mock.patch.dict(os.environ, {"ALIG_SAKLAMA_FIRMA_GUN": "0"}):
            self.assertEqual(depo.saklama_uygula(con), 0)

    def test_bakim_eski_talepleri_ve_durum_notlarini_siler(self):
        veri, con = self.kur()
        con.close()
        f = sqlite3.connect(veri / "form.sqlite")
        f.execute(FORM_SEMA)
        f.execute("INSERT INTO contact(id, created_utc) VALUES(1,'2020-01-01T00:00:00Z')")
        f.execute("INSERT INTO contact(id, created_utc) VALUES(2,'2999-01-01T00:00:00Z')")
        f.commit()
        f.close()
        y = ydepo.baglan(str(veri / "yonetim.sqlite"))
        y.execute("INSERT INTO talep_durum(talep_id, durum, aciklama, guncelleme_utc, guncelleyen) VALUES(1,'yeni','','2020-01-01T00:00:00Z','ali')")
        y.execute("INSERT INTO talep_durum(talep_id, durum, aciklama, guncelleme_utc, guncelleyen) VALUES(2,'yeni','','2020-01-01T00:00:00Z','ali')")
        y.commit()
        y.close()
        self.assertEqual(bakim.talepleri_sil(veri), 1)
        self.assertEqual(sqlite3.connect(veri / "form.sqlite").execute("SELECT id FROM contact").fetchall(), [(2,)])
        y = ydepo.baglan(str(veri / "yonetim.sqlite"))
        self.assertEqual(y.execute("SELECT talep_id FROM talep_durum").fetchall(), [(2,)])
        self.assertIn("1 talep silindi", y.execute("SELECT olay FROM denetim ORDER BY seq DESC LIMIT 1").fetchone()[0])
        self.assertIsNone(ydepo.denetim_dogrula(y))

    def test_bakim_gecersiz_saklama_ayarinda_durur(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"ALIG_SAKLAMA_FIRMA_GUN": "abc"}):
            self.assertEqual(bakim.main(["--veri", str(veri), "--yedek", str(yedek)]), 2)

    def test_tablo_tum_siniflari_listeler(self):
        adlar = [r[0] for r in saklama.tablo({})]
        self.assertEqual(adlar, list(saklama.SINIFLAR))


class GeriYuklemeTests(unittest.TestCase):
    def kur(self, anahtarli=False):
        self.veri, self.yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        con = depo.baglan(str(self.veri / "tarama.sqlite"))
        ort = {depo.ANAHTAR_ORTAM: "k" * 40} if anahtarli else {}
        with mock.patch.dict(os.environ, ort):
            for i in range(3):
                depo.denetim_ekle(con, "musteri", "olay %d" % i)
        depo.rapor_ekle(con, "tok", "postgresql", "tr", {"a": 1})
        con.close()
        zaman = "20261112T000000Z"
        self.yd = bakim.yedekle(self.veri / "tarama.sqlite", self.yedek, zaman)

    def cikti(self):
        self.satirlar = []
        return self.satirlar.append

    def test_yedek_bozulur_geri_yuklenir_zincir_saglam(self):
        self.kur()
        hedef = self.veri / "tarama.sqlite"
        c = sqlite3.connect(hedef)
        c.execute("UPDATE denetim SET olay='sahte' WHERE seq=2")  # veri bozuldu
        c.execute("DELETE FROM rapor")
        c.commit()
        c.close()
        self.assertEqual(depo.denetim_dogrula(depo.baglan(str(hedef))), 2)
        self.assertEqual(bakim.geri_yukle(self.yd, self.veri, evet=True, cikti=self.cikti()), 0)
        con = depo.baglan(str(hedef))
        self.assertIsNone(depo.denetim_dogrula(con))
        self.assertEqual(con.execute("SELECT count(*) FROM rapor").fetchone()[0], 1)
        self.assertEqual(oct(hedef.stat().st_mode)[-3:], "600")
        self.assertEqual(len(list(self.veri.glob("tarama.sqlite.onceki-*"))), 1)  # bozuk dosya silinmez, ayri durur
        con.close()

    def test_evet_olmadan_hicbir_sey_degismez(self):
        self.kur()
        hedef = self.veri / "tarama.sqlite"
        c = sqlite3.connect(hedef)
        c.execute("DELETE FROM rapor")
        c.commit()
        c.close()
        once = bakim._ozet(hedef)
        self.assertEqual(bakim.geri_yukle(self.yd, self.veri, cikti=self.cikti()), 0)
        self.assertEqual(bakim._ozet(hedef), once)
        self.assertTrue(any("KURU CALISTIRMA" in x for x in self.satirlar))

    def test_bozuk_yedek_reddedilir_ve_hedefe_dokunulmaz(self):
        self.kur()
        hedef = self.veri / "tarama.sqlite"
        once = bakim._ozet(hedef)
        bozuk = self.yedek / "tarama-20261113T000000Z.sqlite"
        c = sqlite3.connect(self.yd)   # veri tasiyan bir sayfayi boz (bos sayfa bozulmasi butunluk denetiminde gorunmez)
        kok = c.execute("SELECT rootpage FROM sqlite_master WHERE name='denetim'").fetchone()[0]
        boyut = c.execute("PRAGMA page_size").fetchone()[0]
        c.close()
        veri = bytearray(self.yd.read_bytes())
        veri[(kok - 1) * boyut + 8:(kok - 1) * boyut + 108] = b"\xff" * 100
        bozuk.write_bytes(bytes(veri))
        self.assertEqual(bakim.geri_yukle(bozuk, self.veri, evet=True, cikti=self.cikti()), 1)
        metin = bozuk.parent / "tarama-20261114T000000Z.sqlite"
        metin.write_text("sqlite degil")
        self.assertEqual(bakim.geri_yukle(metin, self.veri, evet=True, cikti=self.cikti()), 1)
        self.assertEqual(bakim._ozet(hedef), once)
        self.assertTrue(any("YAPILMADI" in x for x in self.satirlar))

    def test_zinciri_kirik_yedek_reddedilir(self):
        self.kur()
        k = self.yedek / "tarama-20261115T000000Z.sqlite"
        shutil.copyfile(self.yd, k)
        c = sqlite3.connect(k)
        c.execute("UPDATE denetim SET olay='sahte' WHERE seq=1")
        c.commit()
        c.close()
        self.assertEqual(bakim.geri_yukle(k, self.veri, evet=True, cikti=self.cikti()), 1)
        self.assertTrue(any("denetim zinciri kirik: kayit #1" in x for x in self.satirlar))

    def test_zincir_basi_kesilmis_yedegi_yakalar(self):
        self.kur()
        bas = depo.zincir_basi(sqlite3.connect(self.veri / "tarama.sqlite"))
        bas_dosya = self.yedek / "bas.json"
        bas_dosya.write_text(json.dumps(bas), encoding="utf-8")
        self.assertEqual(bakim.geri_yukle(self.yd, self.veri, bas=bas_dosya, cikti=self.cikti()), 0)
        k = self.yedek / "tarama-20261115T000000Z.sqlite"  # son kayit kesilmis yedek
        shutil.copyfile(self.yd, k)
        c = sqlite3.connect(k)
        c.execute("DELETE FROM denetim WHERE seq=3")
        c.commit()
        c.close()
        self.assertEqual(bakim.geri_yukle(k, self.veri, bas=bas_dosya, cikti=self.cikti()), 1)

    def test_anahtarli_zincir_anahtarsiz_uyari_anahtarla_dogrulanir(self):
        self.kur(anahtarli=True)
        self.assertEqual(bakim.geri_yukle(self.yd, self.veri, cikti=self.cikti()), 0)
        self.assertTrue(any("anahtar olmadan" in x for x in self.satirlar))
        with mock.patch.dict(os.environ, {depo.ANAHTAR_ORTAM: "k" * 40}):
            self.assertEqual(bakim.geri_yukle(self.yd, self.veri, cikti=self.cikti()), 0)
            self.assertFalse(any("anahtar olmadan" in x for x in self.satirlar))
        with mock.patch.dict(os.environ, {depo.ANAHTAR_ORTAM: "y" * 40}):  # yanlis anahtar
            self.assertEqual(bakim.geri_yukle(self.yd, self.veri, cikti=self.cikti()), 1)

    def test_hedef_kullanimdaysa_durur(self):
        self.kur()
        hedef = self.veri / "tarama.sqlite"
        tutan = sqlite3.connect(hedef)
        tutan.execute("BEGIN EXCLUSIVE")
        try:
            self.assertEqual(bakim.geri_yukle(self.yd, self.veri, evet=True, cikti=self.cikti()), 1)
            self.assertTrue(any("kullanimda" in x for x in self.satirlar))
        finally:
            tutan.execute("ROLLBACK")
            tutan.close()

    def test_bosta_baglanti_tutan_surec_varken_durur(self):
        """Calisan servis istekler arasinda bosta olsa bile dosyayi acik tutabilir; kilit denetimi bunu goremez."""
        import multiprocessing as mp
        self.kur()
        ctx = mp.get_context("fork")
        hazir, bitir = ctx.Event(), ctx.Event()

        def tut(yol):
            c = sqlite3.connect(yol)
            c.execute("SELECT count(*) FROM denetim").fetchone()  # okuma yapildi, islem acik degil
            hazir.set()
            bitir.wait(30)
            c.close()
        p = ctx.Process(target=tut, args=(str(self.veri / "tarama.sqlite"),))
        p.start()
        try:
            self.assertTrue(hazir.wait(10))
            self.assertEqual(bakim.geri_yukle(self.yd, self.veri, evet=True, cikti=self.cikti()), 1)
            self.assertTrue(any("kullanimda" in x for x in self.satirlar), self.satirlar)
        finally:
            bitir.set()
            p.join(10)
        self.assertEqual(bakim.geri_yukle(self.yd, self.veri, evet=True, cikti=self.cikti()), 0)

    def test_yeni_sema_surumlu_yedek_reddedilir(self):
        self.kur()
        k = self.yedek / "tarama-20261116T000000Z.sqlite"
        shutil.copyfile(self.yd, k)
        c = sqlite3.connect(k)
        c.execute("PRAGMA user_version=%d" % (len(depo.GOCLER) + 5))
        c.commit()
        c.close()
        self.assertEqual(bakim.geri_yukle(k, self.veri, evet=True, cikti=self.cikti()), 1)

    def test_bilinmeyen_ad_ve_hedefsiz_yukleme(self):
        self.kur()
        x = self.yedek / "baska-20261116T000000Z.sqlite"
        shutil.copyfile(self.yd, x)
        self.assertEqual(bakim.geri_yukle(x, self.veri, evet=True, cikti=self.cikti()), 2)
        bos = Path(tempfile.mkdtemp())  # sunucu kaybi: hedef dizin bos
        self.assertEqual(bakim.geri_yukle(self.yd, bos, evet=True, cikti=self.cikti()), 0)
        self.assertIsNone(depo.denetim_dogrula(depo.baglan(str(bos / "tarama.sqlite"))))

    def test_komut_satiri(self):
        self.kur()
        self.assertEqual(bakim.main(["geri-yukle", "--veri", str(self.veri), "--dosya", str(self.yd)]), 0)

    def test_yonetim_ve_form_yedegi(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        y = ydepo.baglan(str(veri / "yonetim.sqlite"))
        ydepo.denetim_ekle(y, "ali", "bir")
        y.close()
        yy = bakim.yedekle(veri / "yonetim.sqlite", yedek, "20261112T000000Z")
        f = sqlite3.connect(veri / "form.sqlite")
        f.execute(FORM_SEMA)
        f.commit()
        f.close()
        fy = bakim.yedekle(veri / "form.sqlite", yedek, "20261112T000000Z")
        self.assertEqual(bakim.geri_yukle(yy, veri, evet=True, cikti=lambda *_: None), 0)
        self.assertEqual(bakim.geri_yukle(fy, veri, evet=True, cikti=lambda *_: None), 0)


class HazirlikTests(unittest.TestCase):
    """deploy/hazirlik.py: sunucu denetimi gecici dizinde sinanir; gercek sunucu kaniti degildir."""
    def kur(self, mod_env=0o640, mod_veri=0o750, mod_db=0o600):
        kok = Path(tempfile.mkdtemp())
        v = hazirlik.yukle_degiskenler()
        for p, m in (("/etc/alig", 0o750), (v["veri_dizini"], mod_veri), (v["yedek_dizini"], 0o700)):
            (kok / p.lstrip("/")).mkdir(parents=True)
            (kok / p.lstrip("/")).chmod(m)
        env = kok / "etc/alig/env"
        env.write_text("ALIG_FORM_SALT=%s\nALIG_DENETIM_ANAHTARI=%s\n" % ("a" * 64, "b" * 64))
        env.chmod(mod_env)
        db = kok / v["veri_dizini"].lstrip("/") / "tarama.sqlite"
        db.write_text("x")
        db.chmod(mod_db)
        return kok, v

    def bul(self, sonuc, parca):
        return [d for a, d, _ in sonuc if parca in a]

    def sunucu(self, kok, v, disk=None):
        return hazirlik.sunucu(v, str(kok), servis_kontrol=False, disk=disk or shutil.disk_usage)

    def test_dogru_kurulum_gecer_ve_sir_degeri_yazdirilmaz(self):
        kok, v = self.kur()
        sonuc = self.sunucu(kok, v)
        self.assertEqual(self.bul(sonuc, "izinleri"), ["PASS"] * 4)
        self.assertEqual(self.bul(sonuc, "ALIG_DENETIM_ANAHTARI"), ["PASS"])
        self.assertNotIn("b" * 20, repr(sonuc))

    def test_acik_izin_ve_gevsek_dosya_yakalanir(self):
        kok, v = self.kur(mod_env=0o644, mod_veri=0o755, mod_db=0o644)
        sonuc = self.sunucu(kok, v)
        self.assertIn("FAIL", self.bul(sonuc, "/etc/alig/env izinleri"))
        self.assertIn("FAIL", self.bul(sonuc, v["veri_dizini"] + " izinleri"))
        self.assertEqual(self.bul(sonuc, "yalniz sahibine acik: tarama.sqlite"), ["FAIL"])

    def test_eksik_ya_da_kisa_anahtar_yakalanir(self):
        kok, v = self.kur()
        (kok / "etc/alig/env").write_text("ALIG_FORM_SALT=kisa\n")
        sonuc = self.sunucu(kok, v)
        self.assertEqual(self.bul(sonuc, "ALIG_FORM_SALT"), ["FAIL"])
        self.assertEqual(self.bul(sonuc, "ALIG_DENETIM_ANAHTARI"), ["FAIL"])

    def test_disk_esikleri(self):
        D = type("D", (), {})
        def disk(bos):
            d = D()
            d.total, d.free = 100 * (1 << 30), int(bos * (1 << 30))
            return d
        self.assertEqual(hazirlik.disk_durumu("/", lambda _: disk(50))[0], "PASS")
        self.assertEqual(hazirlik.disk_durumu("/", lambda _: disk(15))[0], "WARN")
        self.assertEqual(hazirlik.disk_durumu("/", lambda _: disk(5))[0], "FAIL")
        kok, v = self.kur()
        self.assertEqual(self.bul(self.sunucu(kok, v, disk=lambda _: disk(5)), "disk doluluk"), ["FAIL", "FAIL"])

    def test_yerel_ozet_gercek_sunucu_satirlari_not_tested(self):
        sonuc = hazirlik.yerel()
        durum = {a: d for a, d, _ in sonuc}
        self.assertEqual(durum["GERCEK DAGITIM ansible-playbook site.yml"], "NOT_TESTED")
        self.assertEqual(durum["KURU CALISTIRMA ansible-playbook site.yml --check --diff"], "NOT_TESTED")
        self.assertNotIn("FAIL", durum.values())

    def test_kontrol_listesi_yalniz_done_ya_da_not_tested(self):
        metin = (ROOT / "docs" / "canli-kontrol-listesi.md").read_text(encoding="utf-8")
        satirlar = [x for x in metin.splitlines() if x.startswith("| ") and not x.startswith(("| Madde", "| ---"))]
        self.assertGreater(len(satirlar), 20)
        for x in satirlar:
            durum = x.split("|")[2].strip()
            self.assertIn(durum, ("DONE", "NOT_TESTED"), x)
            if durum == "DONE":  # kanitsiz DONE olmaz
                self.assertTrue(x.split("|")[3].strip(), x)

    def test_yazdir_fail_varsa_hata_kodu(self):
        self.assertEqual(hazirlik.yazdir([("a", "PASS", ""), ("b", "FAIL", "x")], cikti=lambda *_: None), 1)
        self.assertEqual(hazirlik.yazdir([("a", "PASS", ""), ("b", "WARN", "x")], cikti=lambda *_: None), 0)


class BakimDiskTests(unittest.TestCase):
    def test_disk_dolu_ise_yedek_alinmaz_veri_silinmez(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        con = depo.baglan(str(veri / "tarama.sqlite"))
        depo.rapor_ekle(con, "t", "postgresql", "tr", {"a": 1})
        con.close()
        D = type("D", (), {"total": 1000, "free": 10})
        self.assertFalse(bakim.disk_yeterli(veri, yedek, lambda _: D)[0])
        with mock.patch.object(bakim, "disk_yeterli", return_value=(False, "dolu")):
            self.assertEqual(bakim.main(["--veri", str(veri), "--yedek", str(yedek)]), 1)
        self.assertEqual(list(yedek.iterdir()), [])
        self.assertEqual(depo.baglan(str(veri / "tarama.sqlite")).execute("SELECT count(*) FROM rapor").fetchone()[0], 1)

    def test_buyuk_diskte_oran_dusuk_ama_yer_yeterliyse_yedek_alinir(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        D = type("D", (), {"total": 2000 << 30, "free": 40 << 30})  # %2 bos ama 40 GB yer var
        yeterli, mesaj = bakim.disk_yeterli(veri, yedek, lambda _: D)
        self.assertTrue(yeterli)
        self.assertTrue(mesaj.startswith("UYARI"))

    def test_yeterli_yer_varsa_gecer(self):
        veri, yedek = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        D = type("D", (), {"total": 1 << 30, "free": 1 << 29})
        self.assertTrue(bakim.disk_yeterli(veri, yedek, lambda _: D)[0])


class DumanTests(unittest.TestCase):
    def test_paketlenmis_site_gecer_ve_eksik_basarisiz(self):
        paket, _ = paketle.paketle("1.2.3", "https://alig.tech", out_dir=tempfile.mkdtemp())
        kok = Path(tempfile.mkdtemp())
        with tarfile.open(paket) as tar:
            tar.extractall(kok, filter="data")

        class H(SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def end_headers(self):  # nginx'in verdigi basliklari taklit et
                for k, v in (("Content-Security-Policy", "default-src 'self'"), ("X-Content-Type-Options", "nosniff"),
                             ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY")):
                    self.send_header(k, v)
                super().end_headers()

            def do_GET(self):
                if self.path in ("/healthz", "/api/tarama/saglik"):
                    self.send_response(200)
                    self.send_header("Content-Length", "3")
                    self.end_headers()
                    self.wfile.write(b"ok\n")
                    return
                super().do_GET()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(kok / "site")))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        taban = "http://127.0.0.1:%d" % srv.server_port
        self.assertEqual(duman_testi.calistir(taban, surum="1.2.3"), [])
        self.assertTrue(duman_testi.calistir(taban, surum="9.9.9"))
        (kok / "site" / "demo" / "index.html").unlink()
        self.assertTrue(any("/demo/" in h for h in duman_testi.calistir(taban)))


if __name__ == "__main__":
    unittest.main()


class YapilandirmaTests(unittest.TestCase):
    """Sunucuya gitmeden yakalanabilecek yapilandirma hatalari."""
    SABLON = ROOT / "deploy" / "ansible" / "roles"

    def test_nginx_konumlari_ortak_basliklari_icerir(self):
        konum = (self.SABLON / "web" / "templates" / "alig-konumlar.conf.j2").read_text()
        self.assertEqual(konum.count("location "), konum.count("include snippets/alig-basliklar.conf"))
        https = (self.SABLON / "web" / "templates" / "alig-https.conf.j2").read_text()
        self.assertNotIn("http2 on", https)  # Ubuntu 24.04 nginx 1.24 tanimaz
        self.assertIn("proxy_set_header X-Real-IP $remote_addr", konum)
        self.assertIn("client_max_body_size 6m", konum)

    def test_musteri_portali_kapali_varsayilan_ve_yalniz_dogrulamayla(self):
        var = (ROOT / "deploy" / "ansible" / "group_vars" / "all.yml").read_text()
        self.assertRegex(var, r"(?m)^musteri_portali: false$")
        konum = (self.SABLON / "web" / "templates" / "alig-konumlar.conf.j2").read_text()
        blok = konum[konum.index("location /portal"):konum.index("location /yonetim")]
        self.assertIn("{% if musteri_portali %}", blok)
        self.assertIn("return 404", blok)                      # kapaliyken nginx hicbir sey iletmez
        self.assertIn("proxy_set_header Host $host", blok)     # Origin denetimi icin
        self.assertIn("include snippets/alig-basliklar.conf", blok)
        birim = (self.SABLON / "servisler" / "templates" / "alig-tarama.service.j2").read_text()
        self.assertIn("{% if musteri_portali %}", birim)
        self.assertIn("ALIG_PORTAL=1", birim)
        gorev = (self.SABLON / "servisler" / "tasks" / "main.yml").read_text()
        self.assertIn("musteri_portali: true icin eposta_dogrulama: true olmali", gorev)

    def test_hsts_her_konumda(self):
        self.assertIn("Strict-Transport-Security", (self.SABLON / "web" / "templates" / "alig-basliklar.conf.j2").read_text())

    def test_systemd_birimleri_sertlestirilmis(self):
        for ad in ("alig-form.service.j2", "alig-tarama.service.j2"):
            t = (self.SABLON / "servisler" / "templates" / ad).read_text()
            for ayar in ("NoNewPrivileges=true", "ProtectSystem=strict", "IPAddressDeny=any", "CapabilityBoundingSet=", "--host 127.0.0.1"):
                self.assertIn(ayar, t, ad)

    def test_posta_birimi_sertlestirilmis_ic_aga_kapali(self):
        t = (self.SABLON / "servisler" / "templates" / "alig-posta.service.j2").read_text()
        for ayar in ("NoNewPrivileges=true", "ProtectSystem=strict", "CapabilityBoundingSet=", "UMask=0077",
                     "InaccessiblePaths={{ yedek_dizini }}", "IPAddressDeny=localhost link-local multicast 10.0.0.0/8"):
            self.assertIn(ayar, t)
        self.assertNotIn("Environment=ALIG_SMTP_PAROLA", t)  # parola sablonda degil, /etc/alig/env icinde
        tarama = (self.SABLON / "servisler" / "templates" / "alig-tarama.service.j2").read_text()
        self.assertIn("{% if eposta_dogrulama %}", tarama)
        self.assertIn("IPAddressDeny=any", tarama)  # web sureci posta icin aga acilmaz

    def test_eposta_dogrulamasi_varsayilan_kapali(self):
        self.assertIs(hazirlik.yukle_degiskenler()["eposta_dogrulama"], False)

    def test_gorev_adlarinda_iki_nokta_ust_uste_yok(self):
        import re
        for yol in (ROOT / "deploy" / "ansible").rglob("*.yml"):
            for s in yol.read_text().splitlines():
                m = re.match(r"^\s*-?\s*name:\s*(.*)$", s)
                if m and ": " in m.group(1) and not m.group(1).startswith(('"', "'")):
                    self.fail(f"{yol.name}: ad tirnaksiz ve ': ' iceriyor -> {s.strip()}")

    def test_sirlar_depoda_degil(self):
        for yol in (ROOT / "deploy").rglob("*"):
            if yol.is_file() and yol.suffix in (".yml", ".j2", ".ini", ".py"):
                self.assertNotRegex(yol.read_text(), r"BEGIN (RSA |OPENSSH )?PRIVATE KEY", yol.name)
        self.assertNotIn("inventory.ini", [p.name for p in (ROOT / "deploy" / "ansible").iterdir()])
