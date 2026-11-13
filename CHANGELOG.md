# Değişiklik günlüğü

## Yayınlanmadı

- Sağlık taraması: ortak kanıt modeli (`tarama/kanit.py`). Her kural kalıcı bir kimlikle (PG-SEC-001 gibi) her taramada
  tek durum üretir: FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE, PASS; kategori, güven düzeyi, kaynak, gözlenen
  değerler. Veri eksik, kısmi ya da bozukken PASS çıkmaz. Raporda denetim sonuçları tablosu, bulgu kartında kural ve kaynak.
  Kural listesi `docs/kural-katalogu.md` dosyasına üretilir. PostgreSQL 18'in `log_connections` liste değerleri tanınır.
- Depo iskeleti, standart kütüphane derleyicisi (TR/EN), yerel OFL yazı tipleri.
- CI denetimleri: dış kaynak, boyut bütçesi, sır, doldurulacak alan, dil eşliği,
  bağlantı, HTML yapısı, yasaklı kalıplar.
- Ana sayfa için iki tasarım yönü taslağı (A: Konsol, B: Rapor).
