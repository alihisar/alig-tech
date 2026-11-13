#!/usr/bin/env python3
"""Kural kayitlarindan docs/kural-katalogu.md uretir. Belge elle duzenlenmez; tests/test_kanit.py gunceligini denetler.

  python3 tarama/uret_kurallar.py            # yazar
  python3 tarama/uret_kurallar.py --kontrol  # guncel degilse 1 doner
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import kanit, katalog, kurallar, kurallar_mssql, rapor  # noqa: E402

HEDEF = ROOT / "docs" / "kural-katalogu.md"
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
    satirlar = ["| Kimlik | Denetim | Kategori | Güven | Toplama denetimi | Okunan kaynak | Geçme koşulu |",
                "|---|---|---|---|---|---|---|"]
    for k in sorted(liste, key=lambda x: x.kimlik):
        kaynak = list(k.kaynak) or sorted({a for kay in k.kaynaklar for a in by_id.get(kay.kontrol, {}).get("kaynak", ())})
        guven = k.guven
        tavan = kanit.GUVEN_TAVANI.get(k.motor)
        if tavan and kanit.GUVENLER.index(tavan) > kanit.GUVENLER.index(guven):
            guven = "%s (gösterilen: %s)" % (guven, tavan)
        satirlar.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            k.kimlik, k.ad["tr"], m["kategori"][k.kategori], guven, _kaynaklar(k, by_id), ", ".join("`%s`" % a for a in kaynak), k.beklenen["tr"]))
    return "\n".join(satirlar)


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
          "SQL Server kuralları ön sürümdür: sorgular gerçek sunucuda sınanmadı, raporda güven en çok MEDIUM gösterilir.", "",
          "Veri koşulu: *tek satır* kaynakta tam bir satır beklenir; *en az bir satır* kaynakta boş sonuç veri yok demektir; "
          "*boş sonuç geçerli* kaynakta boş sonuç sorun yok demektir. Zorunlu değeri boş ya da türü yanlış satır "
          "değerlendirmeye girmez ve sonucu kısmi yapar. *Ek* kaynak gelmezse kural yine çalışır, bulguyu raporlar, ama PASS veremez. "
          "*Her veritabanında* çalışan kaynakta PASS için sunucudaki bağlanılabilir bütün veritabanlarının taranmış olması gerekir "
          "(`pg_kapsam`); atlanan ya da seçilmeyen veritabanı varsa sonuç kısmidir.", "",
          "## PostgreSQL (%d kural)" % len(kurallar.KURALLAR), "", _tablo(kurallar.KURALLAR, katalog.PG_BY_ID), "",
          "Kural kaynağı olmayan bilgi denetimleri: %s." % ", ".join("`%s`" % x for x in kurallar.BILGI), "",
          "## SQL Server, ön sürüm (%d kural)" % len(kurallar_mssql.KURALLAR), "", _tablo(kurallar_mssql.KURALLAR, katalog.MSSQL_BY_ID), ""]
    return "\n".join(p)


def main(argv):
    metin = uret()
    if "--kontrol" in argv:
        if not HEDEF.exists() or HEDEF.read_text(encoding="utf-8") != metin:
            print("guncel degil, calistirin: python3 tarama/uret_kurallar.py")
            return 1
        return 0
    HEDEF.write_text(metin, encoding="utf-8")
    print("yazildi", HEDEF)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
