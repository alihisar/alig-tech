#!/usr/bin/env python3
"""Generates the body of the example report page: site/uretilen/ornek-rapor-<view>.<lang>.html (not edited by hand).

The input is a synthetic scan document: it does not come from a real server or customer, and the object names are plainly fake (ornek_*).
The report is produced through the same code path (tarama/rapor.py) as the report the customer sees; the score and findings come from the document.
There are no actions (deletion, verification) and no deletion date is written. The same input gives the same output.

  python3 tarama/uret_ornek_rapor.py            # writes
  python3 tarama/uret_ornek_rapor.py --kontrol  # returns 1 if out of date (used by CI and tests)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import katalog, rapor, uret_toplayici  # noqa: E402

HEDEF = ROOT / "site" / "uretilen"
DILLER = ("tr", "en")
# Tab addresses: the page names match the page names in build/build.py (/ornek-rapor/, /ornek-rapor-teknik/)
SAYFA = {"yonetici": "ornek-rapor", "teknik": "ornek-rapor-teknik"}


def belge():
    """Synthetic scan document: a PostgreSQL 16 primary server, three kinds of findings, the remaining checks clean."""
    k = {c["id"]: {"durum": "ok", "satirlar": []} for c in katalog.PG}
    k["pg_surum"]["satirlar"] = [{"surum_num": 160015}]
    k["pg_sunucu_rolu"]["satirlar"] = [{"yedek": False}]
    k["pg_kume_kimligi"]["satirlar"] = [{"kume": "0" * 64}]   # fake digest
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
    # Synthetic rows that will produce findings
    k["pg_olu_satir"]["satirlar"] = [{"veritabani": "ornek_veritabani", "schemaname": "ornek_sema", "relname": "ornek_tablo",
                                      "canli": 50000, "olu": 40000, "son_autovacuum": None}]
    k["pg_kullanilmayan_indeks"]["satirlar"] = [{"veritabani": "ornek_veritabani", "schemaname": "ornek_sema",
                                                 "indexrelname": "ornek_indeks", "bayt": 52428800}]
    return {"format": katalog.FORMAT, "motor": katalog.MOTOR, "katalog_sha256": uret_toplayici.katalog_ozeti(),
            "olusturma_utc": "2026-11-10T12:00:00Z", "maskeli": False, "superuser": False, "kontroller": k}


def _adres(dil, gorunum):
    return ("/en/" if dil == "en" else "/") + SAYFA[gorunum] + "/"


def uret():
    """{file name: text}. The report body has no actions and no deletion date; the tabs link to static pages."""
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
        print("example report is out of date: %s: python3 tarama/uret_ornek_rapor.py" % ", ".join(eski))
        return 1
    print("example report: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
