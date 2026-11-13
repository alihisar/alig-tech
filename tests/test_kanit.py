"""Ortak kanit modeli (tarama/kanit.py): her kural her taramada tek bir durum uretir, veri yokken PASS cikmaz."""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import kanit, katalog, kurallar, kurallar_mssql, rapor, uret_kurallar  # noqa: E402
import test_mssql  # noqa: E402
import test_tarama  # noqa: E402

TUM = kurallar.KURALLAR + kurallar_mssql.KURALLAR
MOTOR_KURALLARI = {"postgresql": kurallar.KURALLAR, "mssql": kurallar_mssql.KURALLAR}
TEMIZ = {"postgresql": test_tarama.temiz_belge, "mssql": test_mssql.temiz_mssql}
BILGI = {"postgresql": kurallar.BILGI, "mssql": kurallar_mssql.BILGI}
KATALOG = {"postgresql": katalog.PG_BY_ID, "mssql": katalog.MSSQL_BY_ID}
TOPLAYICI_KAYNAGI = {"postgresql": ROOT / "tarama" / "toplayici" / "sablon.py", "mssql": ROOT / "tarama" / "toplayici" / "sablon_mssql.py"}


def kayitlar(belge):
    return {k["kural"]: k for k in kurallar.incele(belge).kayitlar}


def durum(belge, kimlik):
    k = kayitlar(belge)[kimlik]
    return k["durum"], k["neden"]


class KuralTablosuTests(unittest.TestCase):
    def test_kimlikler_tekil_kalici_bicimde(self):
        kimlikler = [k.kimlik for k in TUM]
        self.assertEqual(len(kimlikler), len(set(kimlikler)))
        for k in TUM:
            m = re.match(r"^(PG|MS)-([A-Z]+)-(\d{3})$", k.kimlik)
            self.assertTrue(m, k.kimlik)
            self.assertEqual(m.group(1), {"postgresql": "PG", "mssql": "MS"}[k.motor], k.kimlik)
            self.assertEqual(m.group(2), kanit.KATEGORI_KISALTMA[k.kategori], k.kimlik)   # kategori degisirse kimlik degismez: istisna buraya yazilir

    def test_alanlar_gecerli(self):
        for k in TUM:
            self.assertIn(k.kategori, kanit.KATEGORILER, k.kimlik)
            self.assertIn(k.guven, kanit.GUVENLER, k.kimlik)
            self.assertTrue(k.kaynaklar and not k.kaynaklar[0].ek, k.kimlik)   # ilk kaynak birincildir
            for alan in (k.ad, k.beklenen):
                self.assertTrue(alan["tr"].strip() and alan["en"].strip(), k.kimlik)
            for kay in k.kaynaklar:
                self.assertIn(kay.satir, kanit.SATIR, k.kimlik)
                if kay.kontrol == kanit.TOPLAYICI:
                    self.assertEqual(kay.zorunlu, ("superuser",))
                    continue
                c = KATALOG[k.motor].get(kay.kontrol)
                self.assertIsNotNone(c, "%s: %s katalogda yok" % (k.kimlik, kay.kontrol))
                self.assertTrue(set(kay.zorunlu) <= set(c["kolonlar"]), k.kimlik)

    def test_her_katalog_denetimi_bir_kurala_ya_da_bilgiye_bagli(self):
        for motor, liste in MOTOR_KURALLARI.items():
            kaynak = {kay.kontrol for k in liste for kay in k.kaynaklar} - {kanit.TOPLAYICI}
            self.assertEqual(kaynak & set(BILGI[motor]), set(), motor)
            self.assertEqual(kaynak | set(BILGI[motor]), set(KATALOG[motor]), motor)

    def test_kaynak_adlari_sorguda_geciyor(self):
        for motor, by_id in KATALOG.items():
            for cid, c in by_id.items():
                self.assertTrue(c.get("kaynak"), cid)
                for ad in c["kaynak"]:
                    self.assertIn(ad, c["sql"], "%s: %s" % (cid, ad))
        for k in TUM:
            for ad in k.kaynak:
                metinler = [TOPLAYICI_KAYNAGI[k.motor].read_text(encoding="utf-8") if kay.kontrol == kanit.TOPLAYICI
                            else KATALOG[k.motor][kay.kontrol]["sql"] for kay in k.kaynaklar]
                self.assertTrue(any(ad in m for m in metinler), "%s: %s" % (k.kimlik, ad))

    def test_kural_katalogu_belgesi_guncel(self):
        yol = ROOT / "docs" / "kural-katalogu.md"
        self.assertEqual(yol.read_text(encoding="utf-8"), uret_kurallar.uret(), "python3 tarama/uret_kurallar.py calistirin")


class DurumTests(unittest.TestCase):
    def test_her_kural_tek_kayit_uretir(self):
        for motor, liste in MOTOR_KURALLARI.items():
            bos = {"format": katalog.FORMAT, "motor": motor, "olusturma_utc": "2026-11-10T12:00:00Z", "kontroller": {}}
            bozuk = dict(bos, kontroller="x")
            for belge in (TEMIZ[motor](), bos, bozuk):
                kay = kurallar.incele(belge).kayitlar
                self.assertEqual([k["kural"] for k in kay], [k.kimlik for k in liste], motor)
                for k in kay:
                    self.assertIn(k["durum"], kanit.DURUMLAR, k["kural"])
            for k in kurallar.incele(bos).kayitlar:
                self.assertEqual((k["durum"], k["neden"]), ("UNAVAILABLE", "calistirilmadi"), k["kural"])

    def test_temiz_belgede_kurallar_gecer(self):
        uygulanmaz = {"PG-HA-001": "slot_yok", "PG-HA-002": "replika_yok", "MS-HA-002": "ag_yok"}
        for motor in MOTOR_KURALLARI:
            for k in kurallar.incele(TEMIZ[motor]()).kayitlar:
                beklenen = ("NOT_APPLICABLE", uygulanmaz[k["kural"]]) if k["kural"] in uygulanmaz else ("PASS", None)
                self.assertEqual((k["durum"], k["neden"]), beklenen, k["kural"])
                self.assertIn(k["guven"], kanit.GUVENLER, k["kural"])
                self.assertEqual(k["bulgular"], [])

    def _varyantlar(self, motor, kay):
        """Kaynagin verisini bozan ya da kaldiran degisiklikler: (ad, belge)."""
        temiz = TEMIZ[motor]()
        if kay.kontrol == kanit.TOPLAYICI:
            b = copy.deepcopy(temiz)
            del b["superuser"]
            yield "superuser yok", b
            return
        c = KATALOG[motor][kay.kontrol]

        def ile(e):
            b = copy.deepcopy(temiz)
            if e is None:
                del b["kontroller"][kay.kontrol]
            else:
                b["kontroller"][kay.kontrol] = e
            return b
        yield "yok", ile(None)
        for neden in sorted(kanit.ERISILEMEZ):
            yield "hata " + neden, ile({"durum": "hata", "neden": neden})
        yield "kayit bozuk", ile("x")
        yield "satirlar bozuk", ile({"durum": "ok", "satirlar": "x"})
        yield "satir bozuk", ile({"durum": "ok", "satirlar": ["x"]})
        satirlar = temiz["kontroller"][kay.kontrol]["satirlar"] or [{}]
        yield "degerler bos", ile({"durum": "ok", "satirlar": [{x: None for x in c["kolonlar"]} for _ in satirlar]})
        if kay.satir != "herhangi":
            yield "satir yok", ile({"durum": "ok", "satirlar": []})
        if kay.satir == "tek":
            yield "iki satir", ile({"durum": "ok", "satirlar": satirlar * 2})
        if c.get("kapsam") == "veritabani":
            yield "atlanan", ile({"durum": "ok", "satirlar": temiz["kontroller"][kay.kontrol]["satirlar"],
                                  "atlanan": [{"veritabani": "arsiv", "neden": "yetki"}]})

    def test_veri_yokken_pass_cikmaz(self):
        for k in TUM:
            for kay in k.kaynaklar:
                for ad, belge in self._varyantlar(k.motor, kay):
                    d, neden = durum(belge, k.kimlik)
                    with self.subTest(kural=k.kimlik, kaynak=kay.kontrol, varyant=ad):
                        self.assertNotIn(d, ("PASS", "NOT_APPLICABLE"))
                        self.assertTrue(neden or d in ("FAIL", "WARNING"))

    def test_erisilemeyen_kaynak_unavailable_ek_kaynak_unknown(self):
        for k in TUM:
            for kay in k.kaynaklar:
                if kay.kontrol == kanit.TOPLAYICI:
                    continue
                for neden in kanit.ERISILEMEZ:
                    b = TEMIZ[k.motor]()
                    b["kontroller"][kay.kontrol] = {"durum": "hata", "neden": neden}
                    self.assertEqual(durum(b, k.kimlik), ("UNKNOWN" if kay.ek else "UNAVAILABLE", neden), (k.kimlik, kay.kontrol))

    def test_bulgu_varken_kismi_kapsam_sonucu_gizlemez(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_gecersiz_indeks"] = {"durum": "ok", "satirlar": [{"veritabani": "a", "schemaname": "s", "indexrelname": "i"}],
                                                 "atlanan": [{"veritabani": "arsiv", "neden": "yetki"}]}
        k = kayitlar(b)["PG-MAINT-004"]
        self.assertEqual((k["durum"], k["onem"], len(k["bulgular"])), ("FAIL", "yuksek", 1))

    def test_durum_bulgunun_oneminden(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_xid_yasi"]["satirlar"] = [{"datname": "x", "yas": 1700000000, "mxid_yas": 1, "freeze_max_age": 200000000}]
        b["kontroller"]["pg_olu_satir"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "relname": "t", "canli": 10, "olu": 50000, "son_autovacuum": None}]
        b["kontroller"]["pg_kullanilmayan_indeks"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "indexrelname": "i", "bayt": 20000000}]
        k = kayitlar(b)
        self.assertEqual((k["PG-MAINT-002"]["durum"], k["PG-MAINT-002"]["onem"]), ("FAIL", "kritik"))
        self.assertEqual((k["PG-MAINT-003"]["durum"], k["PG-MAINT-003"]["onem"]), ("WARNING", "orta"))
        self.assertEqual((k["PG-MAINT-005"]["durum"], k["PG-MAINT-005"]["onem"]), ("WARNING", "dusuk"))
        m = test_mssql.temiz_mssql()
        m["kontroller"]["ms_sysadmin"]["satirlar"] = [{"giris": "dba", "tur": "SQL_LOGIN", "devre_disi": 0}]
        self.assertEqual(kayitlar(m)["MS-SEC-004"]["durum"], "WARNING")   # bilgi: gozden gecirilecek liste
        self.assertEqual(set(kanit.BULGU_DURUMU), set(kurallar.ONEM))

    def test_bulgular_kural_bilgisini_tasir(self):
        b = test_tarama.temiz_belge()
        b["superuser"] = True
        b["kontroller"]["pg_tls_parola"]["satirlar"] = [{"ssl": "off", "password_encryption": "md5", "ssl_min_protocol_version": "TLSv1.2"}]
        s = kurallar.incele(b)
        self.assertEqual({x["kural"] for x in s.bulgular}, {"PG-SEC-001", "PG-SEC-002", "PG-SEC-005"})
        for kay in s.kayitlar:
            for x in kay["bulgular"]:
                self.assertEqual((x["kural"], x["kategori"], x["guven"], x["kaynak"]), (kay["kural"], kay["kategori"], kay["guven"], kay["kaynak"]))
                self.assertEqual(x["durum"], kanit.BULGU_DURUMU[x["onem"]])
        self.assertEqual(s.bulgular, sorted(s.bulgular, key=lambda x: kurallar.ONEM.index(x["onem"])))

    def test_guven_yalniz_kaniti_olan_durumda(self):
        for motor in MOTOR_KURALLARI:
            b = TEMIZ[motor]()
            b["kontroller"] = {cid: {"durum": "hata", "neden": "yetki"} for cid in b["kontroller"]}
            for k in kurallar.incele(b).kayitlar:
                if k["durum"] in ("UNKNOWN", "UNAVAILABLE"):
                    self.assertIsNone(k["guven"], k["kural"])
        for k in kurallar.incele(test_mssql.temiz_mssql()).kayitlar:
            self.assertNotEqual(k["guven"], "HIGH", k["kural"])   # on surum: sorgular gercek sunucuda sinanmadi

    def test_kayit_alanlari(self):
        for motor in MOTOR_KURALLARI:
            b = TEMIZ[motor]()
            for k in kurallar.incele(b).kayitlar:
                self.assertEqual(k["toplama_utc"], b["olusturma_utc"])
                self.assertEqual(k["motor"], motor)
                self.assertTrue(k["kaynak"] and all(isinstance(x, str) for x in k["kaynak"]), k["kural"])
                self.assertTrue(k["kontroller"], k["kural"])
                self.assertTrue(set(kanit.KAYIT_ALANLARI) == set(k), k["kural"])
                json.dumps(k)   # disa aktarilabilir

    def test_veritabani_kapsami_eksikse_bilinmiyor(self):
        vt_kurallari = {k.kimlik for k in kurallar.KURALLAR if any(katalog.PG_BY_ID.get(kay.kontrol, {}).get("kapsam") == "veritabani" for kay in k.kaynaklar)}
        self.assertIn("PG-MAINT-004", vt_kurallari)
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_kapsam"]["satirlar"][0]["veritabani_sayisi"] = 3   # --veritabanlari ile secilmeyenler
        del_kapsam = test_tarama.temiz_belge()
        del del_kapsam["kontroller"]["pg_kapsam"]
        for belge in (b, del_kapsam):
            for kimlik, k in kayitlar(belge).items():
                if kimlik in vt_kurallari:
                    self.assertEqual(k["durum"], "UNKNOWN", kimlik)
                elif kimlik not in ("PG-HA-001", "PG-HA-002"):   # temiz belgede slot ve replika yok: uygulanmaz
                    self.assertEqual(k["durum"], "PASS", kimlik)

    def test_gozlem_nesne_adi_tasimaz(self):
        b = test_tarama.temiz_belge()
        k = b["kontroller"]
        k["pg_gecersiz_indeks"]["satirlar"] = [{"veritabani": "GIZLI_VT", "schemaname": "GIZLI_SEMA", "indexrelname": "GIZLI_INDEKS"}]
        k["pg_super_roller"]["satirlar"] = [{"rolname": "GIZLI_ROL", "rolcanlogin": True}]
        k["pg_slot"]["satirlar"] = [{"slot_name": "GIZLI_SLOT", "active": False, "wal_status": "reserved", "geri_bayt": 1}]
        for kay in kurallar.incele(b).kayitlar:
            self.assertNotIn("GIZLI", json.dumps(kay["gozlem"]), kay["kural"])
            for v in kay["gozlem"].values():
                self.assertIsInstance(v, (str, int, float, bool, type(None)), kay["kural"])

    def test_olculemeyen_listesi_kurala_gore(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_md5_roller"] = {"durum": "hata", "neden": "yetki"}
        bulgu, olcul = kurallar.degerlendir(b)
        self.assertEqual(olcul, [("PG-SEC-003", "yetki")])
        self.assertEqual(bulgu, [])


class KuralMantigiTests(unittest.TestCase):
    def pg(self, **kontroller):
        b = test_tarama.temiz_belge()
        for cid, satirlar in kontroller.items():
            b["kontroller"][cid] = {"durum": "ok", "satirlar": satirlar}
        return b

    def test_baglanti_gunlugu_postgresql_18_degerleri(self):
        def log(baglanti, kesme="on"):
            return self.pg(pg_log_ayarlari=[{"name": "log_connections", "setting": baglanti}, {"name": "log_disconnections", "setting": kesme}])
        self.assertEqual(durum(log(""), "PG-SEC-007")[0], "WARNING")                    # 18: bos liste kapali demek
        self.assertEqual(durum(log("off"), "PG-SEC-007")[0], "WARNING")
        self.assertEqual(durum(log("on", "off"), "PG-SEC-007")[0], "WARNING")
        self.assertEqual(durum(log("receipt,authentication,authorization"), "PG-SEC-007"), ("PASS", None))
        self.assertEqual(durum(log("belki"), "PG-SEC-007"), ("UNKNOWN", "gecersiz_veri"))
        self.assertEqual(durum(self.pg(pg_log_ayarlari=[{"name": "log_connections", "setting": "on"}]), "PG-SEC-007"), ("UNKNOWN", "eksik_veri"))

    def test_arsiv_kaniti_yoksa_gecmez(self):
        def arsiv(mode, basari, hata):
            return self.pg(pg_arsiv=[{"archive_mode": mode, "basarili": 0, "hatali": 0, "son_basari_utc": basari, "son_hata_utc": hata}])
        self.assertEqual(durum(arsiv("on", None, None), "PG-BACKUP-001"), ("UNKNOWN", "arsiv_kaniti_yok"))
        self.assertEqual(durum(arsiv("off", None, None), "PG-BACKUP-001")[0], "WARNING")
        self.assertEqual(durum(arsiv("on", "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"), "PG-BACKUP-001")[0], "FAIL")
        self.assertEqual(durum(arsiv("on", "2026-11-02T00:00:00Z", "2026-11-01T00:00:00Z"), "PG-BACKUP-001"), ("PASS", None))
        self.assertEqual(durum(arsiv("on", "dun", None), "PG-BACKUP-001"), ("UNKNOWN", "gecersiz_veri"))

    def test_tarama_hesabi_ayri_kural(self):
        b = test_tarama.temiz_belge()
        b["superuser"] = True
        k = kayitlar(b)
        self.assertEqual((k["PG-SEC-005"]["durum"], k["PG-SEC-005"]["bulgular"][0]["sablon"]), ("WARNING", "pg_tarama_super"))
        self.assertEqual(k["PG-SEC-004"]["durum"], "PASS")
        m = test_mssql.temiz_mssql()
        m["superuser"] = True
        self.assertEqual(kayitlar(m)["MS-SEC-008"]["bulgular"][0]["sablon"], "ms_sysadmin_ile_tarama")

    def test_slot_yoksa_uygulanmaz_bozuksa_bilinmiyor(self):
        self.assertEqual(durum(self.pg(pg_slot=[]), "PG-HA-001"), ("NOT_APPLICABLE", "slot_yok"))
        self.assertEqual(durum(self.pg(pg_slot=[{"slot_name": "s", "active": None, "wal_status": None, "geri_bayt": None}]), "PG-HA-001"),
                         ("UNKNOWN", "eksik_veri"))
        self.assertEqual(durum(self.pg(pg_slot=[{"slot_name": "s", "active": True, "wal_status": "reserved", "geri_bayt": 1}]), "PG-HA-001"), ("PASS", None))

    def test_tls_ve_parola_degerleri(self):
        def tls(ssl, en_az, pe="scram-sha-256"):
            return self.pg(pg_tls_parola=[{"ssl": ssl, "password_encryption": pe, "ssl_min_protocol_version": en_az}])
        self.assertEqual(durum(tls("off", None), "PG-SEC-001")[0], "FAIL")
        self.assertEqual(durum(tls("on", "TLSv1.1"), "PG-SEC-001")[0], "FAIL")
        self.assertEqual(durum(tls("on", "TLSv1.3"), "PG-SEC-001"), ("PASS", None))
        self.assertEqual(durum(tls("on", None), "PG-SEC-001"), ("UNKNOWN", "eksik_veri"))
        self.assertEqual(durum(tls("belki", "TLSv1.2"), "PG-SEC-001"), ("UNKNOWN", "gecersiz_veri"))
        self.assertEqual(durum(tls("on", "TLSv9"), "PG-SEC-001"), ("UNKNOWN", "gecersiz_veri"))   # taninmayan surum temiz sayilmaz
        self.assertEqual(durum(tls("on", "TLSv1.2", "md5"), "PG-SEC-002")[0], "WARNING")
        self.assertEqual(durum(tls("on", "TLSv1.2", "duz"), "PG-SEC-002"), ("UNKNOWN", "gecersiz_veri"))

    def test_baglanti_ust_siniri_sifirsa_bilinmiyor(self):
        for ust in (0, -100):
            self.assertEqual(durum(self.pg(pg_baglanti=[{"kullanilan": 1, "ust": ust}]), "PG-CAP-001"), ("UNKNOWN", "gecersiz_veri"))

    def test_okunamayan_sequence_ek_kaynak(self):
        b = self.pg(pg_sequence_gorunurluk=[{"veritabani": "postgres", "toplam": 5, "okunamayan": 2}])
        self.assertEqual(durum(b, "PG-CAP-002"), ("UNKNOWN", "kismi_yetki"))
        b["kontroller"]["pg_sequence"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "sequencename": "q", "oran": 0.99}]
        self.assertEqual(durum(b, "PG-CAP-002")[0], "FAIL")   # gorunen sequence'taki sorun yine raporlanir

    def test_mssql_ozel_durumlar(self):
        m = test_mssql.temiz_mssql()
        m["kontroller"]["ms_surum"]["satirlar"][0]["motor_turu"] = 5
        self.assertEqual(durum(m, "MS-MAINT-001"), ("NOT_APPLICABLE", "yonetilen_hizmet"))
        m = test_mssql.temiz_mssql()
        m["kontroller"]["ms_sunucu_ayar"]["satirlar"] = [x for x in m["kontroller"]["ms_sunucu_ayar"]["satirlar"] if x["ad"] != "xp_cmdshell"]
        k = kayitlar(m)
        self.assertEqual((k["MS-SEC-002"]["durum"], k["MS-SEC-002"]["neden"]), ("UNKNOWN", "eksik_veri"))
        self.assertEqual(k["MS-CONFIG-003"]["durum"], "PASS")
        m = test_mssql.temiz_mssql()
        m["kontroller"]["ms_sifreleme"]["satirlar"] = [{"toplam": 0, "sifreli": 0}]
        self.assertEqual(durum(m, "MS-SEC-006"), ("NOT_APPLICABLE", "tcp_baglanti_yok"))
        m = test_mssql.temiz_mssql()
        m["kontroller"]["ms_checkdb"]["satirlar"].append({"veritabani": "b", "gun": None})   # bilinmeyen tarih temiz sayilmaz
        self.assertEqual(durum(m, "MS-MAINT-002"), ("UNKNOWN", "eksik_veri"))
        m["kontroller"]["ms_tempdb"]["satirlar"] = [{"veri_dosyasi": "1", "cpu": 8}]          # tur denetimi (SQL Server yuklemede tur denetlenmez)
        self.assertEqual(durum(m, "MS-PERF-002"), ("UNKNOWN", "gecersiz_veri"))
        m = test_mssql.temiz_mssql()
        m["kontroller"]["ms_db_ayar"]["satirlar"][0]["trustworthy"] = "1"   # metin "1" sayi 1 ile eslesmez: temiz sanilmasin
        self.assertEqual(durum(m, "MS-SEC-001"), ("UNKNOWN", "gecersiz_veri"))


class RaporTests(unittest.TestCase):
    def rapor(self, belge, dil="tr"):
        r = {"id": 1, "olusturma_utc": "2026-11-10T12:00:00Z", "bitis_utc": "2026-12-10T12:00:00Z", "motor": belge["motor"], "dil": dil, "belge": belge}
        return rapor.sayfa(r, dil, "T" * 43)

    def test_durum_tablosu_iki_dilde(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_md5_roller"] = {"durum": "hata", "neden": "yetki"}
        tr, en = self.rapor(b), self.rapor(b, "en")
        for metin in ("Denetim sonuçları", "PG-SEC-003", "Alınamadı", "yetki yok", "Geçti", "Uygulanmaz", "replikasyon slotu yok"):
            self.assertIn(metin, tr)
        for metin in ("Check results", "PG-SEC-003", "Unavailable", "no permission", "Pass", "Not applicable", "no replication slots"):
            self.assertIn(metin, en)
        tablo = tr[tr.index("<table class=\"tiers durumlar\">"):]
        tablo = tablo[:tablo.index("</table>")]
        self.assertEqual(tablo.count("<th scope=\"row\">"), len(kurallar.KURALLAR))   # her kural bir satir
        self.assertEqual(tablo.count("<td data-label"), len(kurallar.KURALLAR) * 5)

    def test_bulgu_kartinda_kural_durum_guven_kaynak(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_gecersiz_indeks"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "s", "indexrelname": "i"}]
        html = self.rapor(b)
        kart = html[html.index("finding-card"):]
        kart = kart[:kart.index("</section>")]
        for metin in ("PG-MAINT-004", "Başarısız", "Bakım", "pg_index"):
            self.assertIn(metin, kart)

    def test_ozet_durum_sayilari(self):
        html = self.rapor(test_mssql.temiz_mssql())
        n = len(kurallar_mssql.KURALLAR)
        self.assertIn("Geçti: %d" % (n - 1), html)
        self.assertIn("Uygulanmaz: 1", html)

    def test_gozlem_ve_neden_kacisli(self):
        b = test_tarama.temiz_belge()
        b["kontroller"]["pg_log_ayarlari"]["satirlar"][0]["setting"] = "<script>x</script>"
        html = self.rapor(b)
        self.assertNotIn("<script>x", html)
        self.assertIn("&lt;script&gt;x", html)


if __name__ == "__main__":
    unittest.main()
