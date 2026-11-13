# Değişiklik günlüğü

## Yayınlanmadı

- Sağlık taraması: geçmiş karşılaştırması (`tarama/gecmis.py`). Toplayıcı küme tanımlayıcısının yalnız SHA-256 özetini
  gönderir; aynı firmanın aynı sunucudan (aynı rol) yaptığı önceki tarama, saklama süresi dolmadıysa raporda
  karşılaştırılır: önceki ve yeni puan, kapsam değişimi, her denetim için yeni, kötüleşen, süren, çözülen, bilinmeyen.
  Önceki sorun bu taramada ölçülemiyorsa çözüldü sayılmaz. Panelde de görünür; görüntüleme denetim kaydına yazılır.
- Sağlık taraması: altı yeni PostgreSQL kuralı: autovacuum ve track_counts, tablo düzeyinde kapatılmış autovacuum,
  multixact yaşı, replikasyon gecikmesi (süre ve bayt), pg_stat_statements, geçici dosyalar. Toplayıcı sunucunun
  birincil mi yedek mi olduğunu kaydeder; yedekte tablo istatistiğine ve arşivlemeye dayanan kurallar Uygulanmaz
  (yedekte ölü satır kuralı veri yokken temiz çıkıyordu). Slot sorgusu yedek sunucuda hata veriyordu, düzeltildi. Hepsi
  gerçek PostgreSQL 16 birincil ve akışlı yedek sunucuda sınandı; raporda sunucu rolü satırı.
- Sağlık taraması: sağlık puanı (0–100) ve kanıt kapsamı (`tarama/puan.py`). Her kural bir risk düzeyi taşır; puan risk
  ağırlıklı kredi oranıdır. Bilinmiyor ve Alınamadı, Başarısız kadar puan kaybettirir: eksik ya da kaybolan veri puanı
  yükseltmez. Raporda özet satırları, kategori tablosu ve puanı düşüren denetimler (bulgu ve kanıt eksikliği ayrı);
  yönetim panelinde Puan sütunu ve etkin katsayılar. Katsayılar `ALIG_PUAN_AYARI` ile verilen JSON dosyasından
  ayarlanır, geçersiz dosyayla servisler başlamaz. Raporun kanıt listesinde evet/hayır değerleri artık Türkçe/İngilizce
  yazılır; bulgusuz raporda Bulgular başlığının altı boş kalmaz.
- Sağlık taraması: PostgreSQL sürüm ve yetki matrisi. Toplayıcı ve doğrudan bağlantı sunucunun ana sürümünü okur, o sürümün
  sorgusunu seçer, desteklenmeyen sürümde sorguyu hiç çalıştırmaz (PostgreSQL 12 için ayrı slot sorgusu). Yeni `pg_hesap`
  denetimi tarama hesabının rollerini okur; `pg_monitor` içindeki gerekli rol yoksa kural Geçti olamaz (gerçek PostgreSQL 16'da
  yetkisiz hesap başka oturumları göremiyordu). Sınanmayan sürümde kanıt güveni en çok orta. `tarama/surum_dogrula.py` gerçek
  sunucuda üç hesapla doğrulama yapar; sonuç `docs/surum-matrisi.md`.
- Sağlık taraması: ortak kanıt modeli (`tarama/kanit.py`). Her kural kalıcı bir kimlikle (PG-SEC-001 gibi) her taramada
  tek durum üretir: FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE, PASS; kategori, güven düzeyi, kaynak, gözlenen
  değerler. Veri eksik, kısmi ya da bozukken PASS çıkmaz. Raporda denetim sonuçları tablosu, bulgu kartında kural ve kaynak.
  Kural listesi `docs/kural-katalogu.md` dosyasına üretilir. PostgreSQL 18'in `log_connections` liste değerleri tanınır.
- Depo iskeleti, standart kütüphane derleyicisi (TR/EN), yerel OFL yazı tipleri.
- CI denetimleri: dış kaynak, boyut bütçesi, sır, doldurulacak alan, dil eşliği,
  bağlantı, HTML yapısı, yasaklı kalıplar.
- Ana sayfa için iki tasarım yönü taslağı (A: Konsol, B: Rapor).
