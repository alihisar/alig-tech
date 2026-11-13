#!/usr/bin/env python3
"""Kural kayitlarindan docs/kural-katalogu.md, katalog ve dogrulama sonucundan docs/surum-matrisi.md uretir.
Belgeler elle duzenlenmez; tests/test_kanit.py ve tests/test_surum.py gunceligini denetler.

  python3 tarama/uret_kurallar.py            # yazar
  python3 tarama/uret_kurallar.py --kontrol  # guncel degilse 1 doner
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import kanit, katalog, kurallar, kurallar_mssql, puan, rapor  # noqa: E402

HEDEF = ROOT / "docs" / "kural-katalogu.md"
MATRIS = ROOT / "docs" / "surum-matrisi.md"
DOGRULAMA = ROOT / "docs" / "surum-dogrulama.json"
BELGELER = ROOT / "tests" / "veri" / "surum"   # dogrulamada toplanan ham belgeler: <ana surum>/<hesap>.json
HESAP_AD = {"pg_monitor": "pg_monitor hesabı", "yetkisiz": "Yetkisiz hesap", "super": "Süper kullanıcı", "yedek": "Yedek sunucu (pg_monitor)"}
YETKI_AD = {"herkes": "herkes", "pg_read_all_stats": "pg_read_all_stats (pg_monitor)",
            "pg_read_all_settings": "pg_read_all_settings (pg_monitor)", "superuser": "süper kullanıcı"}
YETKI_YOKSA = {"herkes": "-",
               "pg_read_all_stats": "Sorgu çalışır ama başka kullanıcıların oturumları görünmez; kural Bilinmiyor olur.",
               "pg_read_all_settings": "Sorgu yetki hatası verir; kural Alınamadı olur.",
               "superuser": "Sorgu yetki hatası verir; kural Alınamadı olur."}
SATIR_AD = {"tek": "tek satır", "en_az_bir": "en az bir satır", "herhangi": "boş sonuç geçerli"}

DURUM_ACIKLAMA = {
    "FAIL": "Kural en az bir kritik ya da yüksek önemli bulgu üretti.",
    "WARNING": "Kural yalnız orta, düşük ya da bilgi önemli bulgu üretti.",
    "UNKNOWN": "Veri geldi ama sonuca yetmiyor: biçim ya da tür geçersiz, zorunlu değer boş, beklenen satır yok, "
               "sunucudaki bazı veritabanları taranmadı ya da ek kaynak gelmedi.",
    "UNAVAILABLE": "Veri alınamadı: çalıştırılmadı, yetki yok, zaman aşımı, sürümde yok, yedek sunucu, hata, sınır.",
    "NOT_APPLICABLE": "Veri, kuralın konusunun sunucuda olmadığını gösteriyor (örneğin replikasyon slotu yok).",
    "PASS": "Bütün kaynaklar eksiksiz geldi, kural çalıştı ve bulgu yok. Veri yokken PASS çıkmaz.",
}
GUVEN_ACIKLAMA = {
    "HIGH": "Ayar ya da katalog durumu doğrudan okundu.",
    "MEDIUM": "İstatistik tahmini ya da tarama anının görüntüsü: istatistik sıfırlama ve tarama zamanı sonucu etkiler.",
    "LOW": "Dolaylı işaret: karar için ek bağlam gerekir (örneğin replikalardaki kullanım).",
}


def _kaynaklar(k, by_id):
    out = []
    for kay in k.kaynaklar:
        notlar = (["ek"] if kay.ek else []) + (["her veritabanında"] if by_id.get(kay.kontrol, {}).get("kapsam") == "veritabani" else [])
        ad = "belge: `superuser`" if kay.kontrol == kanit.TOPLAYICI else "`%s`" % kay.kontrol
        out.append("%s (%s)" % (ad, ", ".join(notlar + [SATIR_AD[kay.satir]])))
    return "<br>".join(out)


def _tablo(liste, by_id):
    m = rapor.M["tr"]
    satirlar = ["| Kimlik | Denetim | Kategori | Risk | Güven | Toplama denetimi | Okunan kaynak | Geçme koşulu |",
                "|---|---|---|---|---|---|---|---|"]
    for k in sorted(liste, key=lambda x: x.kimlik):
        kaynak = list(k.kaynak) or sorted({a for kay in k.kaynaklar for a in by_id.get(kay.kontrol, {}).get("kaynak", ())})
        guven = k.guven
        tavan = kanit.GUVEN_TAVANI.get(k.motor)
        if tavan and kanit.GUVENLER.index(tavan) > kanit.GUVENLER.index(guven):
            guven = "%s (gösterilen: %s)" % (guven, tavan)
        satirlar.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k.kimlik, k.ad["tr"], m["kategori"][k.kategori], m["onem"][k.risk], guven, _kaynaklar(k, by_id),
            ", ".join("`%s`" % a for a in kaynak), k.beklenen["tr"]))
    return "\n".join(satirlar)


def _sayi(v):
    return ("%g" % v).replace(".", ",")


def _puan_bolumu():
    m, v = rapor.M["tr"], puan.VARSAYILAN
    p = ["## Sağlık puanı", "",
         "Puan (0–100) uygulanabilir kuralların ağırlıklı kredi oranıdır (`tarama/puan.py`):", "",
         "```text", "puan = 100 × Σ(kategori çarpanı × ağırlık × kredi) / Σ(kategori çarpanı × ağırlık)", "```", "",
         "Ağırlık kuralın risk düzeyinden gelir. Risk düzeyi, kuralın üretebileceği en yüksek bulgu önemidir "
         "(`tests/test_puan.py` rastgele belgelerle denetler). Kredi kuralın durumundan gelir:", "",
         "| Risk düzeyi | Varsayılan ağırlık |", "|---|---|"]
    p += ["| %s | %s |" % (m["onem"][o], _sayi(w)) for o, w in v["agirlik"].items()]
    p += ["", "| Durum | Kredi |", "|---|---|"]
    for d in kanit.DURUMLAR:
        if d == "WARNING":
            kredi = "bulgunun önemine göre, varsayılan: " + "; ".join("%s %s" % (m["onem"][o].lower(), _sayi(c)) for o, c in v["kredi_uyari"].items())
        elif d == "NOT_APPLICABLE":
            kredi = "hesaba girmez"
        else:
            kredi = "%s (sabit)" % _sayi(puan.KREDI[d])
        p.append("| %s | %s |" % (d, kredi))
    p += ["", "Kategori çarpanlarının varsayılanı %s." % ", ".join(sorted({_sayi(c) for c in v["kategori_carpani"].values()})), "",
          "Bilinmeyen durum puanı yükseltmez: kanıtı olmayan kural, başarısız kural kadar puan kaybettirir; kanıtı kaybolan "
          "kural puanı iyileştirmez. Bu yüzden puan her zaman kanıt kapsamıyla (kanıtı olan uygulanabilir kuralların oranı, "
          "ağırlıksız) birlikte gösterilir ve rapor her kaybın bulgudan mı kanıt eksikliğinden mi geldiğini ayırır. Puana "
          "giren kuralların hiçbirinde kanıt yoksa puan hesaplanmaz. Gösterilen tamsayılar aşağı yuvarlanır: 100 yalnız kayıp "
          "yoksa, %100 kapsam yalnız her kuralın kanıtı varsa görünür. Kategori puanı aynı formülle, yalnız o kategorinin "
          "kurallarıyla ve çarpansız hesaplanır.", "",
          "Ağırlık, uyarı kredisi ve kategori çarpanları `%s` ile verilen JSON dosyasından ayarlanabilir (`docs/runbook.md`); "
          "durum kredileri sabittir. Varsayılan değerler mühendislik seçimidir, bir standarttan gelmez." % puan.ORTAM, ""]
    return p


def uret():
    p = ["# Kural kataloğu", "",
         "<!-- Bu dosya `python3 tarama/uret_kurallar.py` ile üretilir; elle düzenlemeyin. -->", "",
         "Her kural her taramada tek bir kanıt kaydı üretir (`tarama/kanit.py`): durum, önem, güven düzeyi, kaynak, "
         "toplama zamanı, gözlenen değerler ve bulgular. Kimlikler kalıcıdır: kural kaldırılırsa kimliği yeniden kullanılmaz, "
         "kategori değişse de kimlik aynı kalır.", "",
         "## Durumlar", "", "| Durum | Rapordaki adı | Anlamı |", "|---|---|---|"]
    p += ["| %s | %s | %s |" % (d, rapor.M["tr"]["durum"][d], DURUM_ACIKLAMA[d]) for d in kanit.DURUMLAR]
    p += ["", "Bulgu varsa kapsam kısmi olsa bile durum FAIL ya da WARNING olur: bulunan sorun gerçektir. "
          "Önem ile durum eşlemesi: kritik ve yüksek FAIL; orta, düşük ve bilgi WARNING.", "",
          "## Güven düzeyleri", "", "| Düzey | Anlamı |", "|---|---|"]
    p += ["| %s | %s |" % (g, GUVEN_ACIKLAMA[g]) for g in kanit.GUVENLER]
    p += ["", "Güven yalnız kanıtı olan durumlarda verilir (FAIL, WARNING, NOT_APPLICABLE, PASS). "
          "SQL Server kuralları ön sürümdür: sorgular gerçek sunucuda sınanmadı, raporda güven en çok MEDIUM gösterilir.", ""]
    p += _puan_bolumu()
    p += ["## Veri koşulları", "",
          "Veri koşulu: *tek satır* kaynakta tam bir satır beklenir; *en az bir satır* kaynakta boş sonuç veri yok demektir; "
          "*boş sonuç geçerli* kaynakta boş sonuç sorun yok demektir. Zorunlu değeri boş ya da türü yanlış satır "
          "değerlendirmeye girmez ve sonucu kısmi yapar. *Ek* kaynak gelmezse kural yine çalışır, bulguyu raporlar, ama PASS veremez. "
          "*Her veritabanında* çalışan kaynakta PASS için sunucudaki bağlanılabilir bütün veritabanlarının taranmış olması gerekir "
          "(`pg_kapsam`); atlanan ya da seçilmeyen veritabanı varsa sonuç kısmidir.", "",
          "## PostgreSQL (%d kural)" % len(kurallar.KURALLAR), "", _tablo(kurallar.KURALLAR, katalog.PG_BY_ID), "",
          "Kural kaynağı olmayan bilgi denetimleri: %s." % ", ".join("`%s`" % x for x in kurallar.BILGI), "",
          "Yalnız birincil sunucuda değerlendirilen kurallar: %s. Yedek sunucuda tablo istatistikleri (ölü satır, indeks kullanımı) "
          "tutulmaz ve arşivlemeyi birincil yapar; bu kurallar yedekte Uygulanmaz olur. Sunucunun rolü `pg_sunucu_rolu` "
          "denetiminden okunur; okunamazsa bu kurallar Geçti olamaz." % ", ".join(sorted(k.kimlik for k in kurallar.KURALLAR if k.birincil)), "",
          "## SQL Server, ön sürüm (%d kural)" % len(kurallar_mssql.KURALLAR), "", _tablo(kurallar_mssql.KURALLAR, katalog.MSSQL_BY_ID), ""]
    return "\n".join(p)


def dogrulama():
    return json.loads(DOGRULAMA.read_text(encoding="utf-8")) if DOGRULAMA.exists() else {"surumler": {}}


def sinandigi_surumler(cid, kayit):
    """Denetimin sorgusunun gercek sunucuda calistigi ana surumler (superuser denetiminde super hesapla)."""
    hesap = "super" if katalog.PG_BY_ID[cid]["yetki"] == "superuser" else "pg_monitor"
    return sorted(int(v) for v, s in kayit["surumler"].items()
                  if s["hesaplar"][hesap]["kontroller"].get(cid, {}).get("durum") == "ok")


def _surumler(c):
    if c["en_az"] == 0:
        metin = "her sürüm"
    elif c.get("en_cok"):
        metin = "%d–%d" % (c["en_az"], c["en_cok"])
    else:
        metin = "%d ve üstü" % c["en_az"]
    for v in c.get("eski_surum", ()):
        metin += "; %d ve öncesinde ayrı sorgu (%s)" % (v["en_cok"], v["not"])
    return metin


def _hucre(e):
    if e["durum"] != "ok":
        return "Alınamadı: %s" % rapor.M["tr"]["nedenler"].get(e["neden"], e["neden"])
    metin = "%d satır" % e["satir"] + (", %d veritabanı atlandı" % e["atlanan"] if e["atlanan"] else "")
    if "deger" in e:
        metin += "; " + ", ".join("%s: `%s`" % (k, {None: "-", True: "evet", False: "hayır"}.get(v, v) if not isinstance(v, int) or isinstance(v, bool) else v)
                                  for k, v in sorted(e["deger"].items()))
    return metin


def uret_matris():
    kayit = dogrulama()
    sinanan = ", ".join(str(v) for v in katalog.SINANAN) or "yok"
    p = ["# PostgreSQL sürüm ve yetki matrisi", "",
         "<!-- Bu dosya `python3 tarama/uret_kurallar.py` ile üretilir; elle düzenlemeyin. Kaynak: tarama/katalog.py, "
         "docs/surum-dogrulama.json -->", "",
         "Toplayıcı ve doğrudan bağlantı (Kip B) sunucunun ana sürümünü okur, her denetim için o sürümün sorgusunu seçer. "
         "Denetimin desteklemediği sürümde sorgu hiç çalışmaz; denetim raporda \"Alınamadı: bu sürümde desteklenmiyor\" olur. "
         "Matris PostgreSQL %d–%d'i kapsar; daha yeni sürümde ana sorgu çalışır." % (katalog.SURUM_ALT, katalog.SURUM_UST), "",
         "Bütün sorguların gerçek sunucuda sınandığı sürümler: **%s**. Sınanmayan sürümde rapordaki kanıt güveni en çok orta "
         "(MEDIUM) gösterilir ve raporun özetinde yazar." % sinanan, "",
         "Önerilen tarama hesabı yalnız `pg_monitor` üyesidir (`alig-rol.sql`). Bir denetim `pg_monitor` içindeki bir rolü "
         "gerektiriyorsa ve hesapta yoksa kanıt motoru sonucu kısmi sayar (`pg_hesap` denetimi hesabın rollerini okur): "
         "o kural Geçti olamaz.", "",
         "## Denetimler", "",
         "| Denetim | Sürümler | Gereken yetki | Yetki yoksa | Gerçek sunucuda çalıştığı sürüm |", "|---|---|---|---|---|"]
    for c in katalog.PG:
        p.append("| `%s` | %s | %s | %s | %s |" % (c["id"], _surumler(c), YETKI_AD[c["yetki"]], YETKI_YOKSA[c["yetki"]],
                                                    ", ".join(str(v) for v in sinandigi_surumler(c["id"], kayit)) or "sınanmadı"))
    for v, s in sorted(kayit["surumler"].items(), key=lambda x: int(x[0])):
        h = s["hesaplar"]
        p += ["", "## PostgreSQL %s doğrulaması" % v, "",
              "%s, %s. Katalog özeti `%s`." % (s["tam_surum"].split(" on ")[0], s["tarih"], s["katalog_sha256"][:16]), "",
              "Geçici bir kümede senaryo nesneleri kuruldu (geçersiz indeks, birincilde ve yedekte etkin olmayan replikasyon "
              "slotu, ölü satır ve autovacuum'u kapatılmış tablo, sınıra yakın ve tarama hesabının okuyamadığı sequence, 10 MB "
              "üstü kullanılmamış indeks, boşta açık işlem, MD5 parolalı rol, bağlanma yetkisi olmayan veritabanı, PUBLIC'e "
              "CREATE verilmiş public şeması, geçici dosyaya yazan sıralama, pakette varsa pg_stat_statements). pg_basebackup "
              "ile akışlı bir yedek sunucu başlatıldı, yeniden oynatması duraklatılarak geride bırakıldı. Toplayıcı birincilde "
              "üç hesapla, yedekte pg_monitor hesabıyla çalıştırıldı.", "",
              "| Denetim | %s |" % " | ".join(HESAP_AD.values()), "|---|---|---|---|---|"]
        for cid in [c["id"] for c in katalog.PG]:
            p.append("| `%s` | %s |" % (cid, " | ".join(_hucre(h[a]["kontroller"][cid]) if cid in h[a]["kontroller"] else "yok" for a in HESAP_AD)))
        durumlar = {a: {k["kural"]: k for k in kurallar.incele(json.loads((BELGELER / v / ("%s.json" % a)).read_text(encoding="utf-8"))).kayitlar}
                    for a in HESAP_AD if (BELGELER / v / ("%s.json" % a)).exists()}
        if len(durumlar) == len(HESAP_AD):
            p += ["", "Kuralların durumu: aynı belgeler bugünkü kural motoruyla değerlendirildi (`tests/veri/surum/%s/`)." % v, "",
                  "| Kural | %s |" % " | ".join(HESAP_AD.values()), "|---|---|---|---|---|"]
            for kural in sorted(durumlar["pg_monitor"]):
                p.append("| %s | %s |" % (kural, " | ".join(
                    rapor.M["tr"]["durum"][durumlar[a][kural]["durum"]] +
                    (": " + rapor.M["tr"]["nedenler"].get(durumlar[a][kural]["neden"], durumlar[a][kural]["neden"]) if durumlar[a][kural]["neden"] else "")
                    for a in HESAP_AD)))
    p += ["", "## Doğrulamayı yinelemek", "",
          "Her PostgreSQL sürümünün `initdb`, `pg_ctl` ve `postgres` dosyalarının bulunduğu dizinle, root olmayan bir kullanıcıyla:", "",
          "```sh",
          "python3 tarama/surum_dogrula.py --pg-bin /usr/lib/postgresql/18/bin --cikti docs/surum-dogrulama.json --belge-dizini tests/veri/surum",
          "python3 tarama/uret_kurallar.py",
          "```", "",
          "Araç yalnız kendi kurduğu geçici kümeye bağlanır ve sonunda siler. Sonuç `docs/surum-dogrulama.json` dosyasına eklenir; "
          "bütün sorgular o sürümde çalıştıysa sürüm `tarama/katalog.py` içindeki `SINANAN` listesine eklenir (`tests/test_surum.py` "
          "kanıtı denetler).", ""]
    return "\n".join(p)


def main(argv):
    hedefler = [(HEDEF, uret()), (MATRIS, uret_matris())]
    if "--kontrol" in argv:
        eski = [str(h.relative_to(ROOT)) for h, m in hedefler if not h.exists() or h.read_text(encoding="utf-8") != m]
        if eski:
            print("guncel degil, calistirin: python3 tarama/uret_kurallar.py ->", ", ".join(eski))
            return 1
        return 0
    for h, m in hedefler:
        h.write_text(m, encoding="utf-8")
        print("yazildi", h)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
