#!/usr/bin/env python3
"""Ornek rapor sayfasinin govdesini uretir: site/uretilen/ornek-rapor-<gorunum>.<dil>.html (elle duzenlenmez).

Girdi sentetik bir tarama belgesidir: gercek bir sunucudan ya da musteriden gelmez, nesne adlari acikca sahte (ornek_*).
Rapor, musterinin gordugu rapor ile ayni kod yolundan (tarama/rapor.py) uretilir; puan ve bulgular belgeden cikar.
Eylem (silme, dogrulama) yoktur, silinme tarihi yazilmaz. Ayni girdi ayni ciktiyi verir.

  python3 tarama/uret_ornek_rapor.py            # yazar
  python3 tarama/uret_ornek_rapor.py --kontrol  # guncel degilse 1 doner (CI ve testler kullanir)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import katalog, rapor, uret_toplayici  # noqa: E402

HEDEF = ROOT / "site" / "uretilen"
DILLER = ("tr", "en")
# Sekme adresleri: sayfa adlari build/build.py'deki sayfa adlariyla eslesir (/ornek-rapor/, /ornek-rapor-teknik/)
SAYFA = {"yonetici": "ornek-rapor", "teknik": "ornek-rapor-teknik"}


def belge():
    """Sentetik tarama belgesi: PostgreSQL 16 birincil sunucu, uc bulgu turu, geri kalan denetimler temiz."""
    k = {c["id"]: {"durum": "ok", "satirlar": []} for c in katalog.PG}
    k["pg_surum"]["satirlar"] = [{"surum_num": 160015}]
    k["pg_sunucu_rolu"]["satirlar"] = [{"yedek": False}]
    k["pg_kume_kimligi"]["satirlar"] = [{"kume": "0" * 64}]   # sahte ozet
    k["pg_hesap"]["satirlar"] = [{"super_kullanici": False, "pg_read_all_stats": True, "pg_read_all_settings": True}]
    k["pg_baglanti"]["satirlar"] = [{"kullanilan": 82, "ust": 100}]
    k["pg_arsiv"]["satirlar"] = [{"archive_mode": "on", "basarili": 5, "hatali": 0, "son_basari_utc": "2026-11-10T10:00:00Z", "son_hata_utc": None}]
    k["pg_tls_parola"]["satirlar"] = [{"ssl": "on", "password_encryption": "scram-sha-256", "ssl_min_protocol_version": "TLSv1.2"}]
    k["pg_public_create"]["satirlar"] = [{"veritabani": "ornek_veritabani", "public_create": False}]
    k["pg_kapsam"]["satirlar"] = [{"veritabani": "ornek_veritabani", "veritabani_sayisi": 1}]
    k["pg_log_ayarlari"]["satirlar"] = [{"name": "log_connections", "setting": "on"}, {"name": "log_disconnections", "setting": "on"}]
    k["pg_md5_roller"]["satirlar"] = [{"sayi": 2}]
    k["pg_xid_yasi"]["satirlar"] = [{"datname": "ornek_veritabani", "yas": 1000, "mxid_yas": 1,
                                     "freeze_max_age": 200000000, "mxid_freeze_max_age": 400000000}]
    k["pg_autovacuum"]["satirlar"] = [{"name": "autovacuum", "setting": "on"}, {"name": "track_counts", "setting": "on"}]
    k["pg_gecici_dosya"]["satirlar"] = [{"datname": "ornek_veritabani", "dosya": 0, "bayt": 0, "sifirlama_utc": None}]
    k["pg_sorgu_istatistigi"]["satirlar"] = [{"shared_preload_libraries": "pg_stat_statements", "izleme": "top"}]
    k["pg_sequence_gorunurluk"]["satirlar"] = [{"veritabani": "ornek_veritabani", "toplam": 0, "okunamayan": 0}]
    # Bulgu uretecek sentetik satirlar
    k["pg_olu_satir"]["satirlar"] = [{"veritabani": "ornek_veritabani", "schemaname": "ornek_sema", "relname": "ornek_tablo",
                                      "canli": 50000, "olu": 40000, "son_autovacuum": None}]
    k["pg_kullanilmayan_indeks"]["satirlar"] = [{"veritabani": "ornek_veritabani", "schemaname": "ornek_sema",
                                                 "indexrelname": "ornek_indeks", "bayt": 52428800}]
    return {"format": katalog.FORMAT, "motor": katalog.MOTOR, "katalog_sha256": uret_toplayici.katalog_ozeti(),
            "olusturma_utc": "2026-11-10T12:00:00Z", "maskeli": False, "superuser": False, "kontroller": k}


def _adres(dil, gorunum):
    return ("/en/" if dil == "en" else "/") + SAYFA[gorunum] + "/"


def uret():
    """{dosya adi: metin}. Rapor govdesi eylemsiz, silinme tarihsiz; sekmeler statik sayfalara baglanir."""
    b = belge()
    cikti = {}
    for dil in DILLER:
        for gorunum in rapor.GORUNUMLER:
            icerik, _, _ = rapor.govde({"belge": b, "bitis_utc": None, "dil": dil}, dil, "", eylemler=False, gorunum=gorunum,
                                       sekme_baglantilari={g: _adres(dil, g) for g in rapor.GORUNUMLER})
            cikti["ornek-rapor-%s.%s.html" % (gorunum, dil)] = icerik + "\n"
    return cikti


def main(argv=None):
    kontrol = "--kontrol" in (argv if argv is not None else sys.argv[1:])
    eski = []
    for ad, metin in sorted(uret().items()):
        yol = HEDEF / ad
        if kontrol:
            if not yol.is_file() or yol.read_text(encoding="utf-8") != metin:
                eski.append(ad)
        else:
            HEDEF.mkdir(parents=True, exist_ok=True)
            yol.write_text(metin, encoding="utf-8")
    if kontrol and eski:
        print("ornek rapor eski: %s: python3 tarama/uret_ornek_rapor.py" % ", ".join(eski))
        return 1
    print("ornek rapor: tamam")
    return 0


if __name__ == "__main__":
    sys.exit(main())
