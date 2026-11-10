# Sağlık taraması: tasarım ve tehdit modeli

Durum: ilk dilim kodlandı (Kip A, PostgreSQL). Kip B, SQL Server, e-posta doğrulama ve dil modeli özeti sonraki dilimlerde.

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
4. Sunucu dosyayı katı şemayla doğrular, kurallarla bulgu üretir, raporu saklar, rastgele bağlantı verir.
5. Her adım SHA-256 zincirli denetim kaydına yazılır.

Web süreci hiçbir müşteri veritabanına bağlanmaz. Kip A'da bağlanan tek şey firmanın kendi makinesindeki betiktir.

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

Kip B (doğrudan bağlantı) için SSRF, DNS rebinding, kimlik bilgisi saklama ve rol sahipliği kanıtı ayrı dilimde ele alınacak; kod yazılmadan önce bu tabloya eklenir.

## Bilinen sınırlar

- `pg_authid` (MD5 roller) ve `pg_hba_file_rules` yalnız süper kullanıcıyla okunur. `pg_monitor` yetkili rolde bu denetimler "ölçülemedi: yetki" döner. Bu bilerek böyle: temiz değil, ölçülemedi.
- Yedeğin geri dönülebilirliği, işletim sistemi, ağ ve uygulama sorguları taramanın dışındadır; raporda yazar.
- Bazı eşikler resmî belgede yoktur; `tarama/kurallar.py` içinde `MUHENDISLIK` işaretlidir ve `docs/doldurulacak.md` listesindedir.
