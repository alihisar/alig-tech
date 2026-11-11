#!/usr/bin/env python3
"""README'nin koddan turetilen bolumlerini gunceller (yalnizca standart kutuphane).

  python3 ci/uret_readme.py            # README.md icindeki otomatik bolumleri yazar
  python3 ci/uret_readme.py --kontrol  # guncel degilse 1 doner (CI bunu kullanir)

Otomatik bolumler `<!-- oto:basla ad -->` ... `<!-- oto:bitis ad -->` isaretleri
arasindadir; isaretlerin disindaki metin elle yazilir ve bu betik dokunmaz.
Bir yol, sunucu kaynaginda bulunmazsa betik hata verir: rota silinince README da
uyari verir.
"""
import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
sys.path.insert(0, str(ROOT / "build"))

import build as site_build  # noqa: E402

# Dizin aciklamalari: dizin yoksa betik hata verir.
DIZINLER = [
    ("site/", "Kaynak: `i18n/` (TR, EN metinler), `partials/`, `pages/`, `themes/`, `assets/`"),
    ("build/", "`build.py`, tekrarlanabilir derleme ve SHA-256 manifest"),
    ("ci/", "Denetim betikleri, `run_all.py`, bu README'nin uretici betigi"),
    ("tests/", "Birim testleri"),
    ("docs/", "Tasarim notlari, plan, runbook, DNS, doldurulacak alanlar"),
    ("form/", "İletişim formu uç noktası (stdlib, SQLite)"),
    ("tarama/", "Sağlık taraması: toplayıcı şablonları, katalog, kurallar, sunucu, depo; `onsurum/` SQL Server ön sürümü"),
    ("yonetim/", "Yönetim paneli (TOTP girişli, denetim zincirli)"),
    ("deploy/", "Paketleme, bakım, duman testi, Ansible"),
]

# (yol, kaynak dosya, aciklama). Yol kaynak dosyada gecmeli.
ROTALAR = [
    ("/", "site", "Statik site (TR), `/en/` İngilizce"),
    ("/demo/", "site", "Portal demosu (istemci tarafı, sunucu yok)"),
    ("/saglik-taramasi/", "site", "Tarama yükleme sayfası"),
    ("/tarama-hazirlik/", "site", "Müşteri hazırlık kılavuzu (tarama hesabı, adımlar)"),
    ("/api/iletisim", "form/server.py", "İletişim formu (POST)"),
    ("/healthz", "form/server.py", "Form sağlık denetimi"),
    ("/api/tarama/yukle", "tarama/server.py", "Tarama dosyası yükleme (POST)"),
    ("/rapor/<token>/", "tarama/server.py", "Rapor sayfası (rastgele bağlantı)"),
    ("/rapor/<token>/sil", "tarama/server.py", "Raporu hemen silme (POST)"),
    ("/api/tarama/saglik", "tarama/server.py", "Tarama sunucu sağlık denetimi"),
    ("/yonetim/giris", "yonetim/server.py", "Yönetici girişi (parola + TOTP)"),
    ("/yonetim/", "yonetim/server.py", "Özet"),
    ("/yonetim/firmalar", "yonetim/server.py", "Firmalar: liste, aktif/pasif"),
    ("/yonetim/firmalar/<id>", "yonetim/server.py", "Firma ayrıntısı, not, tarama hakkı, silme"),
    ("/yonetim/talepler", "yonetim/server.py", "İletişim talepleri"),
    ("/yonetim/firmalar.csv", "yonetim/server.py", "Firma listesi CSV dışa aktarımı"),
    ("/yonetim/talepler.csv", "yonetim/server.py", "Talep listesi CSV dışa aktarımı"),
    ("/yonetim/taramalar", "yonetim/server.py", "Tarama raporları"),
    ("/yonetim/denetim", "yonetim/server.py", "Denetim kaydı ve zincir doğrulaması"),
    ("/yonetim/sistem", "yonetim/server.py", "Sistem durumu"),
]

def denetim_adimlari():
    kaynak = (ROOT / "ci" / "run_all.py").read_text(encoding="utf-8")
    return re.findall(r'step\("([^"]+)"', kaynak)


def test_sayisi():
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    return suite.countTestCases()


def bolumleri_uret(hatalar):
    bolum = {}

    tema_metni = ", ".join(f"`{t}`" for t in site_build.THEMES)
    bolum["temalar"] = f"Tasarım temaları: {tema_metni}. Varsayılan tema `c` (`--theme c`)."

    adimlar = denetim_adimlari()
    satirlar = [f"{i}. {ad}" for i, ad in enumerate(adimlar, 1)]
    bolum["denetimler"] = (
        f"`run_all.py` şu {len(adimlar)} denetimi sırayla çalıştırır:\n\n"
        + "\n".join(satirlar)
    )
    bolum["testler"] = f"Birim testleri: {test_sayisi()} test (gerçek PostgreSQL testleri `ALIG_TEST_PG_HOST` olmadan atlanır)."

    dizin_satirlari = ["| Dizin | İçerik |", "| --- | --- |"]
    for dizin, aciklama in DIZINLER:
        if not (ROOT / dizin).is_dir():
            hatalar.append(f"dizin yok: {dizin}")
        dizin_satirlari.append(f"| `{dizin}` | {aciklama} |")
    bolum["dizinler"] = "\n".join(dizin_satirlari)

    rota_satirlari = ["| Yol | Kaynak | Açıklama |", "| --- | --- | --- |"]
    for yol, kaynak, aciklama in ROTALAR:
        if kaynak != "site":
            dosya = ROOT / kaynak
            if not dosya.is_file():
                hatalar.append(f"kaynak dosya yok: {kaynak}")
                continue
            metin = dosya.read_text(encoding="utf-8")
            ana_yol = yol.split("<")[0].rstrip("/") or "/"
            if ana_yol not in metin:
                hatalar.append(f"rota kaynakta bulunamadı: {yol} ({kaynak})")
        rota_satirlari.append(f"| `{yol}` | `{kaynak}` | {aciklama} |")
    bolum["rotalar"] = "\n".join(rota_satirlari)

    roller = sorted(p.name for p in (ROOT / "deploy" / "ansible" / "roles").iterdir() if p.is_dir())
    bolum["ansible"] = "Ansible rolleri: " + ", ".join(f"`{r}`" for r in roller) + "."
    return bolum


def isaretli_yaz(metin, bolum):
    for ad, icerik in bolum.items():
        desen = re.compile(
            rf"(<!-- oto:basla {ad} -->)(.*?)(<!-- oto:bitis {ad} -->)", re.S)
        if not desen.search(metin):
            raise SystemExit(f"README'de isaret yok: {ad}")
        metin = desen.sub(lambda m: m.group(1) + "\n" + icerik + "\n" + m.group(3), metin, count=1)
    return metin


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kontrol", action="store_true", help="guncel degilse 1 don")
    args = ap.parse_args(argv)

    hatalar = []
    bolum = bolumleri_uret(hatalar)
    if hatalar:
        for h in hatalar:
            print(f"  - {h}")
        return 1

    mevcut = README.read_text(encoding="utf-8")
    yeni = isaretli_yaz(mevcut, bolum)
    if args.kontrol:
        if yeni != mevcut:
            print("  - README otomatik bölümleri güncel değil: python3 ci/uret_readme.py")
            return 1
        return 0
    if yeni != mevcut:
        README.write_text(yeni, encoding="utf-8")
        print("README güncellendi.")
    else:
        print("README zaten güncel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
