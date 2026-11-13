# Sağlık taraması: tasarım ve tehdit modeli

Durum: Kip A PostgreSQL için yayında. SQL Server için Kip A ön sürüm olarak kodlandı, gerçek sunucuda sınanmadı ve varsayılan olarak kapalı (`docs/mssql-onsurum.md`). Kip B, e-posta doğrulama ve dil modeli özeti sonraki dilimlerde.

## Varsayılan kararlar (sizden yanıt gelene kadar)

| Konu | Varsayılan | Değiştirmek için |
| --- | --- | --- |
| Ürün adı | Yok, sayfada "alig.tech Sağlık taraması" | i18n anahtarları `tarama_*` |
| Dil modeli | Kapalı (`LLM_PROVIDER=none`), kod yok | Sonraki dilim |
| Ücretsiz tarama sınırı | IP başına saatte 5 yükleme. Şirket başına sınır e-posta doğrulamasıyla gelecek | `tarama/server.py` `RateLimiter` |
| Rapor saklama | 30 gün, "şimdi sil" düğmesi | `SAKLAMA_GUN` |
| Çıkış IP adresi | Kip B yok, gerekmiyor | Kip B dilimi |
| E-posta gönderimi | Yok. Rapor bağlantısı yükleme yanıtında gösterilir | Gönderim yöntemi seçilince |
| MySQL | Yok, arayüzde "yol haritasında" | Katalog motor başına, eklemesi kolay |

## Veri akışı (Kip A)

1. Firma `alig-toplayici.py` dosyasını siteden indirir (sabit SHA-256 sayfada yazar) ve kendi ağında çalıştırır.
2. Betik `psql` ile sabit sorgu kataloğunu çalıştırır, tek bir JSON dosyası yazar. Ağa hiçbir şey göndermez.
3. Firma dosyayı okur (isterse `--maskele` ile nesne adlarını takma adla değiştirmiştir) ve siteye yükler.
4. Sunucu dosyayı katı şemayla doğrular, kurallarla bulgu ve her kural için bir kanıt kaydı üretir (aşağıda), raporu saklar, rastgele bağlantı verir.
5. Her adım SHA-256 zincirli denetim kaydına yazılır.

Web süreci hiçbir müşteri veritabanına bağlanmaz. Kip A'da bağlanan tek şey firmanın kendi makinesindeki betiktir.

## Kanıt modeli ve durumlar

Her kural (`PG-SEC-001` gibi kalıcı kimlikle) her taramada tek bir kanıt kaydı üretir: durum, önem, kategori, güven
düzeyi, okunan kaynak, toplama zamanı, gözlenen değerler ve bulgular (`tarama/kanit.py`). İki motor aynı biçimi kullanır.
Kural listesi, kategoriler, güven düzeyleri ve geçme koşulları: `docs/kural-katalogu.md` (koddan üretilir, test denetler).

- **PASS** yalnızca bütün kaynaklar eksiksiz geldiğinde ve bulgu olmadığında çıkar. Toplama denetimi çalışmadıysa
  **UNAVAILABLE**; veri geldi ama biçim bozuk, zorunlu değer boş, beklenen satır yok, bir veritabanı taranmadı ya da ek
  kaynak gelmediyse **UNKNOWN**. Geçmiş karşılaştırmasında kaybolan kanıt bu yüzden çözülmüş sayılmaz.
- Bulgu varsa kapsam kısmi olsa da **FAIL** (kritik, yüksek) ya da **WARNING** (orta, düşük, bilgi) döner.
- **NOT_APPLICABLE** yalnız veriye dayanır: replikasyon slotu yok, Always On yok, Azure yönetilen hizmet, TCP bağlantısı yok.
- Güven düzeyi kanıtı olan durumlarda verilir. SQL Server ön sürüm olduğu için raporda en çok MEDIUM gösterilir.
- Kayıtlar saklanmaz; bulgular gibi okunurken `belge_json` üzerinden yeniden üretilir.

## Sürüm ve yetki matrisi

Toplayıcı ve Kip B sunucunun ana sürümünü okur; her denetimin `en_az`, `en_cok` ve `eski_surum` alanlarına göre o sürümün
sorgusunu seçer, desteklenmeyen sürümde sorguyu hiç çalıştırmaz (`desteklenmiyor`). Her denetimin `yetki` alanı doğru sonuç
için gereken rolü yazar; `pg_hesap` denetimi tarama hesabının rollerini okur ve rol eksikse o kaynağı kullanan kural Geçti
olamaz. Gerçek PostgreSQL 16'da yetkisiz bir hesap başka kullanıcıların oturumlarını göremedi; bu yüzden boşta işlem ve
bağlantı doluluğu kuralları `pg_read_all_stats` ister. Matris ve doğrulama: `docs/surum-matrisi.md`.

## Veri modeli (SQLite, WAL, UTC)

- `rapor(id, token_sha256, olusturma_utc, bitis_utc, motor, surum_num, dil, belge_json)`: `belge_json` doğrulanmış toplama dosyasıdır. Bulgular okunurken yeniden üretilir; böylece kural düzeltmeleri eski raporlara da uygulanır.
- `firma(id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc)`: anahtar kurumsal adreste alan adı, ücretsiz postada tam adres. `durum` aktif ya da pasif; pasif firma yükleme yapamaz (403). `rapor.firma_id` ile eşleşir.
- `kullanim(anahtar_sha256, zaman_utc)`: 30 günde 2 tarama sınırı için sayım.
- `denetim(seq, zaman_utc, aktor, olay, onceki, ozet)`: ozet = SHA-256(`seq|aktor|olay|onceki`). Doğrulama: `python3 tarama/depo.py dogrula <db>`.
- Şema sürümü `PRAGMA user_version` ile tutulur, yalnız ileri yönlü göç.

## Tehdit modeli

| Tehdit | Önlem | Test |
| --- | --- | --- |
| Müşteri veritabanında yazma | Katalog statik denetimi (yalnız `SELECT`, yasaklı sözcük listesi), `default_transaction_read_only=on`, 15 sn sorgu zaman aşımı | `test_katalog_*` |
| Süper kullanıcıyla çalıştırma | Betik uyarır ve toplama dosyasına `superuser:true` yazar, raporda bulgu olur | `test_superuser_bulgusu` |
| Satır verisi sızıntısı | Kullanıcı tablosu sorgusu katalogda yok; kolonlar şemada sabit; yükleme bilinmeyen kolonu reddeder | `test_yukleme_bilinmeyen_kolon` |
| Nesne adlarında HTML ya da talimat | Rapor tüm değerleri `html.escape` ile yazar. Model yok. Kolon değerleri 200 karakterle sınırlı | `test_rapor_kacis` |
| Kötü niyetli ya da dev yükleme | 5 MB sınırı, içerik türü denetimi, katı şema, satır sayısı sınırı, tür denetimi | `test_yukleme_*` |
| Rapor bağlantısı tahmini | 32 bayt `secrets.token_urlsafe`, veritabanında yalnız SHA-256 | `test_token_saklanmaz` |
| Hizmet engelleme | IP başına hız sınırı, gövde sınırı, tek iş parçacığı CPU'su düşük işlem | `test_hiz_siniri` |
| Denetim kaydı kurcalama | SHA-256 zinciri, doğrulama komutu | `test_zincir_*` |
| Parola sızıntısı | Betik parola almaz (`PGPASSFILE`/ortam), toplama dosyasında bağlantı bilgisi yok | `test_toplayici_dosyasinda_baglanti_yok` |
| Eski toplayıcı sürümü | Katalog özeti uyuşmazsa yükleme reddedilir | `test_yukleme_katalog_ozeti` |

Kip B (doğrudan bağlantı) için tehdit modeli ve karar bekleyenler: `docs/kip-b-tasarim.md`. Kod yazılmadı.

## Bilinen sınırlar

- `pg_authid` (MD5 roller) ve `pg_hba_file_rules` yalnız süper kullanıcıyla okunur. `pg_monitor` yetkili rolde PG-SEC-003 "Alınamadı: yetki yok" (UNAVAILABLE) döner. Bu bilerek böyle: temiz değil, ölçülemedi.
- Tarama hesabının bağlanamadığı veritabanı (yönetilen hizmetlerin iç veritabanları dahil) veritabanı başına kuralları UNKNOWN yapar. Raporun kapsam bölümü atlanan veritabanlarını nedeniyle listeler.
- Yedeğin geri dönülebilirliği, işletim sistemi, ağ ve uygulama sorguları taramanın dışındadır; raporda yazar.
- Bazı eşikler resmî belgede yoktur; `tarama/kurallar.py` içinde `MUHENDISLIK` işaretlidir ve `docs/doldurulacak.md` listesindedir.
- SQL Server'da oturum düzeyinde salt okunur kip yoktur. Yazmayı engelleyen şey girişin yetkileridir (yalnızca `VIEW SERVER STATE` ve `VIEW ANY DEFINITION`) ve kataloğun statik denetimidir (`tests/test_mssql.py`).
