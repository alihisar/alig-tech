# Kod incelemesi (2026-11-13)

Kapsam: tüm depo (form, tarama, yönetim, depo ve göçler, kural motoru, rapor, Kip B, toplayıcı, bakım ve dağıtım betikleri, CI, istemci JS, Ansible şablonları). Yöntem: düşmanca okuma, `kod-disiplini/kontrol.py`, `ruff`, `mypy`, çalışan sunuculara karşı sondalar, gerçek PostgreSQL 16 kümesine karşı toplayıcı çalıştırma, güvenlik testlerine mutasyon denemesi (koruma kaldırılınca test kırmızıya düşüyor mu).

Seviyeler etkiye göredir: **KRİTİK** kesinti, veri kaybı ya da yetkisiz erişim; **YÜKSEK** yanlış sonuç ya da zayıflayan koruma; **ORTA** belirli koşulda kırılma ya da bakım maliyeti; **DÜŞÜK** tutarlılık ve okunabilirlik.

## Özet

| Seviye | Bulunan | Düzeltildi | Açık |
| --- | --- | --- | --- |
| KRİTİK | 1 | 1 | 0 |
| YÜKSEK | 5 | 3 | 2 (Y4 kısmen, Y5 Ali'nin kararını bekliyor) |
| ORTA | 12 | 6 | 6 |
| DÜŞÜK | 12 | 4 | 7 (biri yanlış pozitif, açık sayılmadı) |

Canlıya çıkışı engelleyen kod bulgusu: **Y5** (e-posta doğrulaması yok). Y4'ün tam çözümü (tüm veritabanlarını dolaşma) canlıdan önce önerilir; şu an rapor ve kılavuz kapsamı açıkça söylüyor.

Mutasyon denemesi: mevcut 14 güvenlik korumasından 13'ü kaldırıldığında testler kırmızıya düştü; statik dosya yol denetimi kaldırıldığında hiçbir test düşmedi (D1, düzeltildi). Bu incelemede eklenen her düzeltme için de aynı deneme yapıldı (sonuç en altta).

## KRİTİK

### K1 `tarama/kurallar.py` — türü yanlış tek bir yükleme raporu ve yönetim panelini 30 gün düşürüyordu — DÜZELTİLDİ

- **BULGU:** Yükleme denetimi kolon adlarını ve değerin skaler olduğunu denetliyordu, türünü ve kolonun varlığını denetlemiyordu. Kural motoru `r[0]["surum_num"] // 10000`, `kullanilan / ust` gibi işlemlerde türe güveniyordu.
- **KANIT:** Sonda: kimliksiz yükleme `303`; ardından müşteri raporu, `/yonetim/`, `/yonetim/taramalar`, `/yonetim/taramalar/1`, `/yonetim/firmalar/1` bağlantıyı kopardı (`TypeError`, `KeyError`). İnceleme anındaki 16 PostgreSQL denetiminin 8'i bozuk değerle çöküyordu.
- **RİSK:** E-posta doğrulaması olmadığından herkes tek bir dosyayla yönetim panelinin ana sayfalarını rapor süresi (30 gün) boyunca kullanılamaz hâle getirebilirdi; bozuk raporu panelden bulup silmek de mümkün değildi.
- **DÜZELTME:** (1) `tarama/yukleme.py` `TURLER`: her PostgreSQL kolonu için tür; tür dışı değer, eksik kolon ve sonsuz sayı (`1e999`) yüklemede reddedilir. (2) Kural motorunda her denetim yalıtıldı: veri hatası o denetimi "değer biçimi geçersiz" ile ölçülemeyen sayar, rapor düşmez. (3) Panelde rapor başına kalkan: beklenmeyen bir hata bile sayfayı düşürmez, bozuk rapor silinebilir. Testler: `BozukDegerTests`, `test_zehirli_rapor_paneli_dusurmez`, `test_beklenmeyen_kural_hatasi_paneli_dusurmez`. Gerçek PostgreSQL 16 çıktısı yeni tür denetiminden geçti.

## YÜKSEK

### Y1 `tarama/depo.py` `denetim_ekle` — eşzamanlı yazıcılar denetim kaydı kaybediyordu — DÜZELTİLDİ

- **BULGU:** Son kayıt kilitsiz okunup `seq+1` yazılıyordu. Tarama sunucusu, yönetim paneli ve bakım aynı `tarama.sqlite` zincirine yazar.
- **KANIT:** Sonda: 3 süreç × 300 kayıt → 896/900 yazıldı, 4 `IntegrityError: UNIQUE constraint failed: denetim.seq`.
- **RİSK:** İş eylemi (yükleme, silme) yapılmış ama denetim kaydı kaybolmuş ve istek 500 ile bitmiş olur: denetim güvencesi delinir.
- **DÜZELTME:** Okuma ve ekleme `BEGIN IMMEDIATE` altında. Test: `test_eszamanli_surecler_zinciri_bozmaz_kayit_kaybetmez` (3 süreç, 360/360, zincir sağlam).

### Y2 `yonetim/server.py` `_firma_esitle` — silinen firma eski iletişim talebinden geri geliyordu — DÜZELTİLDİ

- **BULGU:** Panel her açılışta iletişim taleplerinden firma kaydı oluşturur. Silinen firmanın talebi durduğu için kayıt bir sonraki sayfa görüntülemesinde yeniden oluşuyordu.
- **KANIT:** Sonda: `pasif` → sil → `[]` → özet sayfası → `[(1, 'kurban.com', 'aktif')]`.
- **RİSK:** Yönetici silmesi ve saklama süresiyle silme sessizce geri alınır; pasif edilmiş firma aktif olarak geri gelir; KVKK silme talebi karşılanamaz.
- **DÜZELTME:** `firma_silinen` tablosu (düz anahtar değil özeti). Silmeden önceki talepler kaydı geri getirmez; silmeden sonra gelen yeni talep yeni kayıt açar. İzler talep saklama süresi dolunca silinir. Testler: `test_silinen_firma_talepten_geri_gelmez`, `test_saklamayla_silinen_firma_eski_talepten_geri_gelmez`.

### Y3 `tarama/katalog.py` `pg_sequence` — önerilen tarama hesabıyla dolu sequence görünmüyordu — DÜZELTİLDİ

- **BULGU:** `pg_sequences.last_value`, rolün USAGE ya da SELECT yetkisi olmayan sequence için boş döner. Kılavuzdaki `alig_hc` (yalnız `pg_monitor`) hiçbir sequence değerini okuyamaz; denetim boş liste döndürüp "sorun yok" sayılıyordu.
- **KANIT:** Gerçek PostgreSQL 16: `MAXVALUE 100`, değeri 99 olan sequence. Süper kullanıcı: `oran 0.99`; `alig_hc`: `satirlar: []`.
- **RİSK:** Ekleme işlemlerini durduracak bir sequence raporda temiz görünür (yanlış negatif).
- **DÜZELTME:** Yeni `pg_sequence_gorunurluk` denetimi okunamayan sequence sayısını verir; sayı sıfırdan büyükse `pg_sequence` "kısmen ölçüldü" olarak ölçülemeyenlerde görünür. Gerçek kümede doğrulandı (`okunamayan: 2`).

### Y4 Tablo, indeks ve sequence denetimleri yalnız bağlanılan veritabanını kapsıyor — KISMEN DÜZELTİLDİ

- **BULGU:** Bu denetimler bağlanılan veritabanının kataloğunu okur. Kılavuz `--dbname postgres` öneriyordu; uygulama tabloları başka veritabanındadır. Rapor bu sınırı yazmıyordu.
- **RİSK:** Uygulama veritabanındaki ölü satır, geçersiz indeks ve sequence sorunları "bulgu yok" görünür.
- **DÜZELTME (yapılan):** `pg_kapsam` denetimi bağlanılan veritabanını ve sunucudaki veritabanı sayısını verir; rapor özette kapsamı yazar, birden çok veritabanı varsa "bu tarama neye bakmaz" bölümünde söyler; kılavuz `--dbname uygulama_db` kullanır ve kapsamı açıklar (TR, EN).
- **AÇIK:** Toplayıcının bağlanabildiği tüm veritabanlarını dolaşması (yol haritası madde 25).

### Y5 E-posta doğrulaması yok — AÇIK (Ali'nin kararını bekliyor)

- **BULGU:** Yükleme formundaki e-posta doğrulanmaz. Firma anahtarı alan adıdır.
- **RİSK:** Biri `x@kurban.com` yazarak kurbanın 30 günlük ücretsiz hakkını tüketebilir, firma kaydındaki e-postayı değiştirebilir ve kendi veritabanının raporunu kurban adına panelde gösterebilir. Şirket başına sınır koruması böylece zayıflar.
- **ÖNERİ:** Yol haritası madde 15 (gönderim yöntemi seçilince). O zamana kadar panelde "doğrulanmamış" etiketi.

## ORTA

| # | Yer | Bulgu ve kanıt | Durum |
| --- | --- | --- | --- |
| O1 | `tarama/depo.py`, `yonetim/depo.py` `baglan` | Göçler kilitsiz: aynı anda açılan süreçler çöküyordu. Sonda: 120 açılışın 90'ı `table ... already exists` ya da `database is locked`. Yeni sürüm dağıtımında servisler birlikte yeniden başlar. | DÜZELTİLDİ: göç tek yazma kilidi altında, sürüm kilit içinde yeniden okunur; WAL geçişi kilit boşalana kadar bekler. Test: `test_eszamanli_ilk_acilis_ve_goc_cokmez` |
| O2 | `form/server.py` `RateLimiter` | Anahtarlar hiç silinmiyordu (sonda: pencere dolduktan sonra 100.001 anahtar). IPv6 ile her istek yeni adresten gelebilir; bellek sınırsız büyür. Kilitsizdi (yarış sondada üretilemedi). | DÜZELTİLDİ: pencere başına temizlik ve kilit. Testler `test_limiter_*` |
| O3 | `tarama/server.py` `_sil` | Kimliksiz `POST /rapor/<herhangi>/sil` her seferinde silinmeyen denetim zincirine satır yazıyordu. | DÜZELTİLDİ: olmayan rapor için yalnız günlük satırı |
| O4 | `deploy/bakim.py` `disk_yeterli` (bu oturumda yazıldı) | Disk %10'dan az boşsa yer olsa bile yedek durduruluyordu: büyük diskte yer daralırken yedeksiz kalınırdı. | DÜZELTİLDİ: ölçüt DB boyutunun iki katı ve 64 MB pay; %10 altı yalnız uyarı |
| O5 | `deploy/bakim.py` `geri_yukle` (bu oturumda yazıldı) | WAL kipinde `BEGIN EXCLUSIVE` okuyucuları engellemez: istekler arasında bağlantı tutan çalışan servis görülmüyordu. | DÜZELTİLDİ: `/proc` üzerinden dosyayı açık tutan süreç denetimi. Test: `test_bosta_baglanti_tutan_surec_varken_durur` |
| O6 | `deploy/hazirlik.py` (bu oturumda yazıldı) | `jinja2` içe aktarıyordu; yalnız standart kütüphane kuralına aykırı. | DÜZELTİLDİ: birimler Ansible'ın kendisiyle işlenir; bozuk birim FAIL verdiği denendi |
| O7 | `yonetim/server.py` firma silme | İletişim talepleri silinmez (arayüz söylüyor); KVKK silme talebinde kişisel veri `form.sqlite`'ta kalır. | AÇIK: madde 26 |
| O8 | toplayıcı `--maskele` | Takma ad → gerçek ad eşlemesi müşteriye verilmiyor; maskeli raporda `nesne-3`'ün hangi tablo olduğu bilinemez. | AÇIK: madde 27 |
| O9 | `tarama/baglanti.py` | Kip B `sslmode=require` sunucu sertifikasını doğrulamaz; `channel_binding=require` parolanın açık ya da MD5 ile gönderilmesini ve SCRAM aktarma saldırısını önler. Kip B kapalı. | AÇIK: madde 24'e eklendi |
| O10 | iş eylemi ile denetim kaydı | Aynı işlemde değil: ikisi arasında süreç ölürse eylem denetimsiz kalır. | AÇIK: madde 28 |
| O11 | `yonetim/server.py` `_firma_esitle` | Her özet ve firma sayfasında 500'e kadar talep için ayrı commit (GET yan etkili, her commit fsync). | AÇIK: madde 28 |
| O12 | `tarama/server.py` yükleme | `_derinlik_denetle` 5 MB'ı saf Python döngüsüyle tarar; nginx sınırı (dakikada 6) ve IP sınırı var. | AÇIK, düşük öncelik |

## DÜŞÜK

| # | Yer | Bulgu | Durum |
| --- | --- | --- | --- |
| D1 | `tests/test_yonetim.py` | Statik dosya yol denetiminin testi yoktu (mutasyon kaçtı): izinli uzantılı ama `assets` dışı yol denenmiyordu. | DÜZELTİLDİ |
| D2 | `yonetim/server.py` | Olmayan raporu silmeye çalışmak yönetim zincirine "silindi" yazıyordu. | DÜZELTİLDİ |
| D3 | `ci/run_all.py` | Test ve toplayıcı çağrılarında zaman aşımı yoktu; asılı test CI'yi sonsuza dek bekletirdi. | DÜZELTİLDİ |
| D4 | çeşitli | Kullanılmayan içe aktarma ve değişkenler (`ruff`). | DÜZELTİLDİ |
| D5 | toplayıcı | `dbname=%s sslmode=%s` birleştirme: boşluk ya da tırnaklı veritabanı adı bozulur (müşterinin kendi girdisi). | AÇIK: madde 29 |
| D6 | toplayıcı | Varsayılan `sslmode=prefer`; bağlantı şifresiz kurulduysa uyarı yok. | AÇIK: madde 29 |
| D7 | `yonetim/server.py` | Talep listesi ve CSV 500 satırla sessizce sınırlı. | AÇIK: madde 30 |
| D8 | `tarama/depo.py` | Firma kimliği silmeden sonra yeniden kullanılabiliyor (`AUTOINCREMENT` yok); denetimde aynı numara iki firmayı gösterebilir. | AÇIK: madde 30 |
| D9 | `yonetim/server.py` | SSH tüneliyle (nginx'siz) açılan panelde CSP başlığı yok. | AÇIK: madde 30 |
| D10 | `tarama/hata.py` | "30 günde 2 tarama" metni sabit; `SINIR_ADET` değişirse yanlış kalır. | AÇIK: madde 30 |
| D11 | `yonetim/depo.py` `giris` | Aynı TOTP kodu eşzamanlı iki girişte iki kez kabul edilebilir (yarış penceresi; parola da gerekir). | AÇIK: madde 30 |
| D12 | `kontrol.py` | "Gömülü gizli veri" (test parolaları) ve "SQL birleştirme" (sabit katalog, sabit kolon listeleri) uyarıları yanlış pozitif. | Not edildi |

## Doğrulama

- Tüm testler ve 13 CI denetimi geçti.
- Gerçek PostgreSQL 16: toplayıcı çıktısı yeni tür denetiminden geçti; `pg_kapsam` ve `pg_sequence_gorunurluk` beklenen değerleri verdi; `GercekPgTests` geçti.
- Sondalar (yükleme, panel, eşzamanlı zincir, eşzamanlı göç, firma geri gelme) düzeltmeden sonra yeniden çalıştırıldı: hepsi temiz.
- Gerçek sunucuda, systemd altında ve canlı trafikte hiçbir şey denenmedi.

## Mutasyon denemesi

Her satırda koruma geçici bir kopyada kaldırıldı ve ilgili test modülü çalıştırıldı.

| Koruma | Sonuç |
| --- | --- |
| CSRF, Origin, oturum süresi, TOTP tekrar koruması, HMAC karşılaştırması, yinelenen JSON anahtarı, bilinmeyen kolon, şirket sınırı, rapor süresi, rapor kaçışı, CSV formül koruması, SSRF iç adres denetimi, geri yüklemede zincir denetimi | 13/13 yakalandı |
| Statik dosya yol denetimi | Önce kaçtı (D1); test eklendikten sonra yakalandı |
| Bu incelemenin düzeltmeleri: kural yalıtımı, yüklemede tür denetimi, eksik kolon, zincir yazma kilidi, göç kilidi, silinen firma izi, hız sınırı temizliği, açık dosya denetimi, sequence kısmi yetki, panel kalkanı, kimliksiz silmenin denetime yazılmaması | 11/11 yakalandı |
| Sonsuz sayı denetimi (`_skaler`) | Önce kaçtı: PostgreSQL'de tür denetimi de yakaladığı için tek başına sınanmıyordu. Tür tablosu olmayan SQL Server yolu için test eklendi; koruma kaldırılınca kırmızıya düştüğü doğrulandı |

