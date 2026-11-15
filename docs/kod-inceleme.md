# Kod incelemesi (2026-11-13)

Kapsam: tüm depo (form, tarama, yönetim, depo ve göçler, kural motoru, rapor, Kip B, toplayıcı, bakım ve dağıtım betikleri, CI, istemci JS, Ansible şablonları). Yöntem: düşmanca okuma, `kod-disiplini/kontrol.py`, `ruff`, `mypy`, çalışan sunuculara karşı sondalar, gerçek PostgreSQL 16 kümesine karşı toplayıcı çalıştırma, güvenlik testlerine mutasyon denemesi (koruma kaldırılınca test kırmızıya düşüyor mu).

Seviyeler etkiye göredir: **KRİTİK** kesinti, veri kaybı ya da yetkisiz erişim; **YÜKSEK** yanlış sonuç ya da zayıflayan koruma; **ORTA** belirli koşulda kırılma ya da bakım maliyeti; **DÜŞÜK** tutarlılık ve okunabilirlik.

## Özet

| Seviye | Bulunan | Düzeltildi | Açık |
| --- | --- | --- | --- |
| KRİTİK | 1 | 1 | 0 |
| YÜKSEK | 5 | 5 | 0 (Y5'in kodu hazır, açılması SMTP sağlayıcısı seçimini bekliyor) |
| ORTA | 12 | 12 | 0 (O12 hızlandırıldı; çapraz dosya işlemleri sıralı kaldı, aşağıda) |
| DÜŞÜK | 12 | 11 | 0 (D12 yanlış pozitif, açık sayılmadı) |

İlk tur (aynı gün): KRİTİK ve ilk üç YÜKSEK bulgu ile altı ORTA bulgu düzeltildi. İkinci tur ("Bulguları düzelt"): kalan tüm bulgular düzeltildi; ayrıntı "İkinci tur" bölümünde.

Canlıya çıkışı engelleyen kod bulgusu kalmadı. Engelleyen kararlar kodun dışında: e-posta doğrulamasını açmak için SMTP sağlayıcısı ve gönderen adres; sunucu, hukuki metinler (`docs/yol-haritasi.md`).

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

### Y4 Tablo, indeks ve sequence denetimleri yalnız bağlanılan veritabanını kapsıyor — DÜZELTİLDİ (ikinci tur)

- **BULGU:** Bu denetimler bağlanılan veritabanının kataloğunu okur. Kılavuz `--dbname postgres` öneriyordu; uygulama tabloları başka veritabanındadır. Rapor bu sınırı yazmıyordu.
- **RİSK:** Uygulama veritabanındaki ölü satır, geçersiz indeks ve sequence sorunları "bulgu yok" görünür.
- **DÜZELTME (yapılan):** `pg_kapsam` denetimi bağlanılan veritabanını ve sunucudaki veritabanı sayısını verir; rapor özette kapsamı yazar, birden çok veritabanı varsa "bu tarama neye bakmaz" bölümünde söyler; kılavuz `--dbname uygulama_db` kullanır ve kapsamı açıklar (TR, EN).
- **İKİNCİ TUR:** Toplayıcı bağlanabildiği her veritabanını dolaşır (en çok 50; Kip B'de 20). CONNECT yetkisi olmayan veritabanına bağlanmaya çalışmaz, "yetki" ile atlar; sınırı aşanlar "sınır" ile atlanır. Rapor kaç veritabanında çalıştığını ve atlananları yazar. Kip B'de adı güvenli kalıba uymayan veritabanı bağlantı dizgisine hiç girmez. Gerçek PostgreSQL 16'da boşluklu adlı veritabanında ölü satır bulgusu raporlandı, yetkisiz veritabanı atlandı.

### Y5 E-posta doğrulaması yok — KODU HAZIR, VARSAYILAN KAPALI (ikinci tur)

- **BULGU:** Yükleme formundaki e-posta doğrulanmaz. Firma anahtarı alan adıdır.
- **RİSK:** Biri `x@kurban.com` yazarak kurbanın 30 günlük ücretsiz hakkını tüketebilir, firma kaydındaki e-postayı değiştirebilir ve kendi veritabanının raporunu kurban adına panelde gösterebilir. Şirket başına sınır koruması böylece zayıflar.
- **İKİNCİ TUR:** Ara önlemler her durumda açık: doğrulanmamış yükleme kayıtlı firma e-postasını değiştirmez, her raporda yükleyen adres ayrı tutulur, panel "doğrulanmamış" etiketini gösterir. Doğrulama açıkken (`ALIG_EPOSTA_DOGRULAMA=1`): rapor bağlantısı yalnız e-postayla gider; bağlantıyı açmak (GET) hiçbir şey değiştirmez, hak sayfadaki düğmeyle (POST) harcanır; adrese 24 saatte 3, firmaya 5 bekleyen bağlantı sınırı; doğrulanmayan rapor 24 saatte silinir. Web süreci ağa çıkmaz: giden kutusu + ayrı `alig-posta` servisi, SMTP yalnız TLS ile. Açmak için SMTP sağlayıcısı ve gönderen adres gerekir. Gerçek SMTP sunucusuyla denenmedi.

## ORTA

| # | Yer | Bulgu ve kanıt | Durum |
| --- | --- | --- | --- |
| O1 | `tarama/depo.py`, `yonetim/depo.py` `baglan` | Göçler kilitsiz: aynı anda açılan süreçler çöküyordu. Sonda: 120 açılışın 90'ı `table ... already exists` ya da `database is locked`. Yeni sürüm dağıtımında servisler birlikte yeniden başlar. | DÜZELTİLDİ: göç tek yazma kilidi altında, sürüm kilit içinde yeniden okunur; WAL geçişi kilit boşalana kadar bekler. Test: `test_eszamanli_ilk_acilis_ve_goc_cokmez` |
| O2 | `form/server.py` `RateLimiter` | Anahtarlar hiç silinmiyordu (sonda: pencere dolduktan sonra 100.001 anahtar). IPv6 ile her istek yeni adresten gelebilir; bellek sınırsız büyür. Kilitsizdi (yarış sondada üretilemedi). | DÜZELTİLDİ: pencere başına temizlik ve kilit. Testler `test_limiter_*` |
| O3 | `tarama/server.py` `_sil` | Kimliksiz `POST /rapor/<herhangi>/sil` her seferinde silinmeyen denetim zincirine satır yazıyordu. | DÜZELTİLDİ: olmayan rapor için yalnız günlük satırı |
| O4 | `deploy/bakim.py` `disk_yeterli` (bu oturumda yazıldı) | Disk %10'dan az boşsa yer olsa bile yedek durduruluyordu: büyük diskte yer daralırken yedeksiz kalınırdı. | DÜZELTİLDİ: ölçüt DB boyutunun iki katı ve 64 MB pay; %10 altı yalnız uyarı |
| O5 | `deploy/bakim.py` `geri_yukle` (bu oturumda yazıldı) | WAL kipinde `BEGIN EXCLUSIVE` okuyucuları engellemez: istekler arasında bağlantı tutan çalışan servis görülmüyordu. | DÜZELTİLDİ: `/proc` üzerinden dosyayı açık tutan süreç denetimi. Test: `test_bosta_baglanti_tutan_surec_varken_durur` |
| O6 | `deploy/hazirlik.py` (bu oturumda yazıldı) | `jinja2` içe aktarıyordu; yalnız standart kütüphane kuralına aykırı. | DÜZELTİLDİ: birimler Ansible'ın kendisiyle işlenir; bozuk birim FAIL verdiği denendi |
| O7 | `yonetim/server.py` firma silme | İletişim talepleri silinmez (arayüz söylüyor); KVKK silme talebinde kişisel veri `form.sqlite`'ta kalır. | DÜZELTİLDİ (ikinci tur): silme formunda "İletişim taleplerini de sil" seçeneği; önce talepler, sonra firma; denetime adres yazılmaz |
| O8 | toplayıcı `--maskele` | Takma ad → gerçek ad eşlemesi müşteriye verilmiyor; maskeli raporda `nesne-3`'ün hangi tablo olduğu bilinemez. | DÜZELTİLDİ (ikinci tur): `<çıktı>-maske.json` yalnız müşteride, 0600; yüklenirse reddedilir |
| O9 | `tarama/baglanti.py` | Kip B `sslmode=require` sunucu sertifikasını doğrulamaz; `channel_binding=require` parolanın açık ya da MD5 ile gönderilmesini ve SCRAM aktarma saldırısını önler. Kip B kapalı. | DÜZELTİLDİ (ikinci tur): `channel_binding=require`; bedeli md5/password doğrulamalı hesabın Kip B'de çalışmaması |
| O10 | iş eylemi ile denetim kaydı | Aynı işlemde değil: ikisi arasında süreç ölürse eylem denetimsiz kalır. | DÜZELTİLDİ (ikinci tur): `depo.islem` ile yükleme, doğrulama, silme, firma işlemleri, kullanıcı işlemleri, giriş ve saklama silmesi tek işlemde. Kalan: `form.sqlite` ile `yonetim.sqlite` ayrı dosyalar, tek işlemde olamaz; önce silme, sonra denetim kaydı |
| O11 | `yonetim/server.py` `_firma_esitle` | Her özet ve firma sayfasında 500'e kadar talep için ayrı commit (GET yan etkili, her commit fsync). | DÜZELTİLDİ (ikinci tur): yalnız son eşitlemeden sonraki talepler, tek işlemde |
| O12 | `tarama/server.py` yükleme | `_derinlik_denetle` 5 MB'ı saf Python döngüsüyle tarar; nginx sınırı (dakikada 6) ve IP sınırı var. | DÜZELTİLDİ (ikinci tur): yapı, tırnak ve kaçış sayısı C hızında sınırlanır, döngü yalnız bu baytlarda; 4,5 MB kötü dosya 0,01 sn'de reddedilir |

## DÜŞÜK

| # | Yer | Bulgu | Durum |
| --- | --- | --- | --- |
| D1 | `tests/test_yonetim.py` | Statik dosya yol denetiminin testi yoktu (mutasyon kaçtı): izinli uzantılı ama `assets` dışı yol denenmiyordu. | DÜZELTİLDİ |
| D2 | `yonetim/server.py` | Olmayan raporu silmeye çalışmak yönetim zincirine "silindi" yazıyordu. | DÜZELTİLDİ |
| D3 | `ci/run_all.py` | Test ve toplayıcı çağrılarında zaman aşımı yoktu; asılı test CI'yi sonsuza dek bekletirdi. | DÜZELTİLDİ |
| D4 | çeşitli | Kullanılmayan içe aktarma ve değişkenler (`ruff`). | DÜZELTİLDİ |
| D5 | toplayıcı | `dbname=%s sslmode=%s` birleştirme: boşluk ya da tırnaklı veritabanı adı bozulur (müşterinin kendi girdisi). | DÜZELTİLDİ (ikinci tur): değerler libpq kurallarıyla tırnaklanır; gerçek kümede boşluklu adla denendi |
| D6 | toplayıcı | Varsayılan `sslmode=prefer`; bağlantı şifresiz kurulduysa uyarı yok. | DÜZELTİLDİ (ikinci tur): `pg_stat_ssl` ile denetlenir, şifresizse uyarı; çıktı dosyası da 0600 |
| D7 | `yonetim/server.py` | Talep listesi ve CSV 500 satırla sessizce sınırlı. | DÜZELTİLDİ (ikinci tur): talep sayfası 100'erli sayfalı, CSV tüm satırlar |
| D8 | `tarama/depo.py` | Firma kimliği silmeden sonra yeniden kullanılabiliyor (`AUTOINCREMENT` yok); denetimde aynı numara iki firmayı gösterebilir. | DÜZELTİLDİ (ikinci tur): firma ve rapor tabloları `AUTOINCREMENT` ile yeniden kuruldu, kimlikler korunarak |
| D9 | `yonetim/server.py` | SSH tüneliyle (nginx'siz) açılan panelde CSP başlığı yok. | DÜZELTİLDİ (ikinci tur): panel kendi CSP başlığını gönderir (betik yok, satır içi stil yok) |
| D10 | `tarama/hata.py` | "30 günde 2 tarama" metni sabit; `SINIR_ADET` değişirse yanlış kalır. | DÜZELTİLDİ (ikinci tur): hata sayfası sabitten yazar; statik metinleri sabitlerle karşılaştıran test |
| D11 | `yonetim/depo.py` `giris` | Aynı TOTP kodu eşzamanlı iki girişte iki kez kabul edilebilir (yarış penceresi; parola da gerekir). | DÜZELTİLDİ (ikinci tur): kod ve sayaç yazma kilidi altında; aynı kodla eşzamanlı iki girişten biri geçer (test) |
| D12 | `kontrol.py` | "Gömülü gizli veri" (test parolaları) ve "SQL birleştirme" (sabit katalog, sabit kolon listeleri) uyarıları yanlış pozitif. | Not edildi |

## Doğrulama

- Tüm testler ve 13 CI denetimi geçti.
- Gerçek PostgreSQL 16: toplayıcı çıktısı yeni tür denetiminden geçti; `pg_kapsam` ve `pg_sequence_gorunurluk` beklenen değerleri verdi; `GercekPgTests` geçti.
- Sondalar (yükleme, panel, eşzamanlı zincir, eşzamanlı göç, firma geri gelme) düzeltmeden sonra yeniden çalıştırıldı: hepsi temiz.
- Gerçek sunucuda, systemd altında ve canlı trafikte hiçbir şey denenmedi.

## İkinci tur: kalan bulguların düzeltilmesi

| Bulgu | Yapılan | Kanıt |
| --- | --- | --- |
| Y5 | E-posta doğrulaması (varsayılan kapalı) ve her durumda açık ara önlemler | `EpostaDogrulamaTests`, `tests/test_posta.py`, panel etiketi testi |
| Y4 | Tüm veritabanlarını dolaşma; rapor kapsamı | `VeritabaniKapsamTests`, `ToplayiciVeritabaniTests` (sahte `psql`), gerçek PostgreSQL 16 (aşağıda) |
| O7 | Firma silmede talepleri de silme seçeneği | `test_firma_silinirken_talepleri_de_silinebilir` |
| O8 | Maske eşlemesi yalnız müşteride | `test_maske_eslemesi_yalniz_yerelde`, gerçek PostgreSQL 16 |
| O9 | `channel_binding=require` | `test_baglanti_dogrulanan_ipye_sabitlenir_ve_tls_ister`, gerçek PostgreSQL 16 (TLS + SCRAM) |
| O10 | `depo.islem`: eylem ve denetim kaydı birlikte | `IslemTests`, `test_denetim_yazilamazsa_yukleme_ve_silme_geri_alinir`, `test_saklama_silmesi_denetimsiz_kalmaz` |
| O11 | Firma eşitleme yalnız yeni talepler, tek işlemde | `test_firma_esitleme_yalniz_yeni_talepleri_isler` |
| O12 | Hızlı yapı denetimi | `test_cok_sayida_yapi_hizla_reddedilir` |
| D5, D6 | Bağlantı dizgisi kaçışı, şifresiz bağlantı uyarısı, çıktı 0600 | `ToplayiciVeritabaniTests` |
| D7 | Talep sayfalama, tam CSV | `test_talepler_sayfali_csv_eksiksiz` |
| D8 | `AUTOINCREMENT` göçü | `test_silinen_firma_ve_rapor_kimligi_yeniden_kullanilmaz`, `test_eski_firma_ve_rapor_tablosu_kimlikleri_korunarak_tasinir` |
| D9 | Panelde CSP | `test_panel_kendi_csp_basligini_gonderir` |
| D10 | Sınır metni sabitten | `MetinTests` |
| D11 | TOTP kilidi | `test_ayni_dogrulama_kodu_es_zamanli_iki_giriste_bir_kez_gecer` |

Gerçek PostgreSQL 16 denemeleri (yerel küme, sunucu değil):

- Toplayıcı, `alig_hc` (yalnız `pg_monitor`) ile 4 veritabanlı kümede: `"satis db"` (boşluklu ad) tarandı ve oradaki ölü satır bulgusu `satis db.public.siparis` olarak raporlandı; CONNECT yetkisi kaldırılmış `gizli` veritabanına bağlanılmadı, "yetki yok" ile atlandı; çıktı ve maske eşleme dosyaları 0600.
- Kip B: TLS açık, `pg_hba` yalnız `hostssl ... scram-sha-256`, bağlantı dizgisinde `channel_binding=require`: tarama tamamlandı, yanlış parola "baglanti" hatası verdi. Boşluklu adlı veritabanı Kip B'de bağlantı dizgisine girmedi, "ad" nedeniyle atlandı.

Kalan sınırlar (bulgu değil, tasarım): `form.sqlite` ve `yonetim.sqlite` ayrı dosyalar olduğundan talep silme ile yönetim denetim kaydı tek işlemde yapılamaz (önce silme, sonra kayıt). E-posta gönderimi gerçek bir SMTP sunucusuyla denenmedi. Hiçbir şey gerçek sunucuda, systemd altında çalıştırılmadı.

## Mutasyon denemesi

Her satırda koruma geçici bir kopyada kaldırıldı ve ilgili test modülü çalıştırıldı.

| Koruma | Sonuç |
| --- | --- |
| CSRF, Origin, oturum süresi, TOTP tekrar koruması, HMAC karşılaştırması, yinelenen JSON anahtarı, bilinmeyen kolon, şirket sınırı, rapor süresi, rapor kaçışı, CSV formül koruması, SSRF iç adres denetimi, geri yüklemede zincir denetimi | 13/13 yakalandı |
| Statik dosya yol denetimi | Önce kaçtı (D1); test eklendikten sonra yakalandı |
| Bu incelemenin düzeltmeleri: kural yalıtımı, yüklemede tür denetimi, eksik kolon, zincir yazma kilidi, göç kilidi, silinen firma izi, hız sınırı temizliği, açık dosya denetimi, sequence kısmi yetki, panel kalkanı, kimliksiz silmenin denetime yazılmaması | 11/11 yakalandı |
| Sonsuz sayı denetimi (`_skaler`) | Önce kaçtı: PostgreSQL'de tür denetimi de yakaladığı için tek başına sınanmıyordu. Tür tablosu olmayan SQL Server yolu için test eklendi; koruma kaldırılınca kırmızıya düştüğü doğrulandı |
| İkinci tur düzeltmeleri: doğrulamada hak harcanması, posta sınırı, doğrulanmamış raporun gizliliği, firma e-postasının korunması, gönderilen metnin silinmesi, STARTTLS, veritabanı dolaşma, Kip B ad denetimi, firma silmede talepler, `AUTOINCREMENT`, panel CSP, yapı sayısı sınırı, yükleme/firma işlemi/kullanıcı ekleme işlem içinde, sınır metni | 17/17 yakalandı |
| `channel_binding` ve firma eşitleme işareti | Önce kaçtı: ilkinde mutasyon kalıbı koddaki değil yorumdaki metne denk geldi; ikincisinde test verisi tek talep içerdiği için fark görünmüyordu. Kalıp düzeltildi, test beş talebe çıkarıldı; ikisi de yakalandı |
| TOTP girişinde kilit | Önce üç denemenin yalnız birinde yakalandı (yarışa bağlı). Test, kod denetimini yavaşlatarak yarış penceresini genişletecek biçimde değiştirildi; üç denemenin üçünde yakalandı |


## ALIG-SEC-001: yönetim ve rapor erişim güvenliği denetimi (2026-11-16)

Kapsam: `tarama/server.py` rapor uçları, `tarama/portal.py` ve `portal_depo.py`, `yonetim/server.py`, `yonetim/depo.py`, `yonetim/guvenlik.py`, `yonetim/kullanici.py`, `tarama/rapor.py` kaçışı. Yöntem: düşmanca okuma ve negatif testler (`tests/test_erisim_guvenligi.py`, 47 test): erişimin olmaması gereken her yol sınandı, sonra koruma geçici bir kopyada kaldırılıp testin kırmızıya düşüp düşmediğine bakıldı (aşağıda). Çalışma zamanı SQLite'tır; PostgreSQL'e dokunulmadı.

Özet: 1 açık bulgu (ORTA, karar bekliyor), 1 düzeltilen (DÜŞÜK), 3 kabul edilen sınır (BİLGİ/DÜŞÜK), 1 belge eksiği (kapatıldı). Firma izolasyonunda, belirteç ömründe, CSV'de, oturumsuz erişimde ve kaçışta açık bulunmadı: bunlar "doğrulandı" tablosunda testle kanıtlıdır.

### S1 `yonetim/depo.py` `kullanici.totp` — TOTP sırrı veritabanında düz metin — AÇIK (karar SEC-K1, ORTA)

- **BULGU:** `kullanici.totp` sütunu base32 sırrı olduğu gibi tutar. Parola scrypt ile özetlenir; TOTP (HMAC-SHA1, RFC 6238) ise sunucuda sırrın kendisini ister, özetlenemez. Standart kütüphanede simetrik şifre yoktur (`hashlib`, `hmac`, `secrets` var; AES yok), bu yüzden bu iş kod yazılarak çözülmedi. `yonetim/kullanici.py kod <ad>` komutu da sırrı veritabanından okuyup anlık kod basar (yalnız yerel deneme için yazılmıştır).
- **KANIT:** `tests/test_erisim_guvenligi.py::TotpSirriSizmazTests::test_sir_veritabaninda_duz_metin_oldugu_belgelenmis_bulgudur`: sütun, `kullanici_ekle`in döndürdüğü sırla aynıdır. Sızdırmama yönü de sınandı (`test_sir_panelde_csvde_denetimde_ve_cli_listesinde_yok`): sır panel sayfalarında, CSV'lerde, iki denetim zincirinde ve `liste` çıktısında yoktur; yalnız `ekle` ve `totp-yenile` çıktısında bir kez yazılır. Yedekler `deploy/bakim.py` ile 0600 alınır ama içerik düz sırdır (runbook: başka yere kopyalarken şifreleyin). `veri_dizini` Ansible'da 0750, servisler `UMask=0077`.
- **RİSK:** `yonetim.sqlite` dosyasına (disk, yedek kopyası, sökülen ya da elden çıkan disk, kök erişimi) ulaşan biri TOTP kodlarını üretebilir. Tek başına giriş sağlamaz: parola scrypt ile korunur (`n=2^15`), ikinci etken olarak yalnız TOTP düşer. Parola özeti de aynı dosyadadır; ikisi birlikte kırılırsa panel (müşteri raporları, CSV'ler) açılır.
- **ÖNERİ:** Seçenekler, artı ve eksileriyle:
  1. **Veri dizini 0700 ve dosya 0600** (kod gerektirmez; `veri_dizini` 0750'den 0700'e, dosyalar `UMask=0077` ve S2 düzeltmesiyle 0600). Yedekleme ve kök kullanıcıya karşı koruma sağlamaz.
  2. **Disk şifreleme** (LUKS ya da sağlayıcının birim şifrelemesi) ve yedeklerin şifreli kopyalanması: çalınan ya da elden çıkan diske ve yedek ortamına karşı koruma sağlar; çalışan sunucuda kök erişimine karşı sağlamaz. Kod gerektirmez.
  3. **systemd-creds ile sır dosyası** (`systemd-creds encrypt`, birimde `LoadCredentialEncrypted=`): sırlar veritabanından çıkıp sunucunun anahtarıyla (TPM2 varsa onunla) şifrelenmiş bir kimlik bilgisi dosyasına gider, yalnız servis süreci çözülmüş hâlini `$CREDENTIALS_DIRECTORY` altında görür. Kod değişikliği ister (`kullanici.py` sırları o dosyaya yazar, `giris` oradan okur; sır yenilemede servis yeniden başlar), systemd sürümü ve sunucu işletim sistemi bilinmeden (WEB-K4) seçilemez.
  Varsayılan (SEC-K1, Ali'yi bekliyor): seçenek 1 ve 2; disk şifreleme önerisi `docs/runbook.md`de, kod yok. Seçenek 3 Ali kararından sonra ayrı madde olur.

### S2 `yonetim/kullanici.py` — CLI, gevşek umask'ta `yonetim.sqlite`'ı herkesçe okunur oluşturuyordu — DÜZELTİLDİ (DÜŞÜK)

- **BULGU:** Uygulama dosya izni ayarlamaz; izni umask belirler. Servisler `UMask=0077` ile çalışır, ama runbook'taki `sudo -u alig-web python3 .../kullanici.py ...` çağrısı çağıranın umask'ını (çoğunlukla 022) devralır. Veritabanını ilk oluşturan CLI ise dosya 0644 olur.
- **KANIT:** Sonda: `umask 022; python3 yonetim/kullanici.py --db y.sqlite liste` → `-rw-r--r--`. Dosya parola özetlerini ve TOTP sırlarını (S1) taşır. Hafifletici: `veri_dizini` 0750 ve sahibi servis kullanıcısı, yani dosyaya yalnız o grup ulaşırdı.
- **RİSK:** Dizin izni gevşetilirse ya da dosya başka yere taşınırsa sırlar herkesçe okunurdu; savunma tek katmana düşüyordu.
- **ÖNERİ / DÜZELTME:** `kullanici.py` başlarken `os.umask(0o077)` (yalnız komut satırı çalıştırmasında; kütüphane olarak içe aktarılınca süreç umask'ı değişmez). Test: `CliDosyaIzniTests` (alt süreç, umask 022 → hiçbir dosyada grup ya da diğer biti yok). Mutasyonda koruma kaldırılınca kırmızı.

### S3 `yonetim/server.py` — rol ayrımı yok: "yetkili" geçerli oturum demektir — KABUL EDİLDİ (BİLGİ)

- **BULGU:** Her panel kullanıcısı her sayfayı, iki CSV'yi, rapor silmeyi ve firma silmeyi kullanabilir; salt okunur ya da yalnız-CSV rolü yoktur.
- **KANIT:** `YonetimOturumsuzTests::test_yetki_modeli_tek_rol_belgelenmis_varsayim` (ikinci kullanıcı da CSV alır). Her CSV indirmesi yönetim denetim zincirine satır sayısıyla yazılır (`firmalar csv indirildi, N satir`); denetime yetkisiz deneme yazılmaz (`test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir`).
- **RİSK:** Bugün tek yönetici olduğu için etkisi yok. Kullanıcı sayısı artarsa, kişisel veri (iletişim talepleri, e-postalar) içeren CSV'yi alabilecek kişi sayısı da artar.
- **ÖNERİ:** İkinci kullanıcı eklenmeden önce rol tasarımı (en az: yalnız görüntüleme, CSV ve silme ayrı hak). Şimdilik `kullanici.py liste` ile kullanıcılar gözden geçirilir.

### S4 `yonetim/depo.py` `giris_engelli` — kullanıcı başına kilit, adı bilinen yöneticiyi 15 dakika dışarıda tutabilir — KABUL EDİLDİ (DÜŞÜK)

- **BULGU:** 15 dakikada 5 hatalı denemeden sonra kullanıcı, doğru bilgiyle bile girişten engellenir. Kullanıcı adını bilen biri yöneticiyi kilitleyebilir.
- **KANIT:** `GirisTests::test_kilitleme`; `TotpKurtarmaTests::test_kilitli_kullanici_yenilemeden_sonra_sure_dolana_kadar_kilitli_kalir`: `totp-yenile` deneme sayacını sıfırlamaz, engel süre dolunca kalkar.
- **RİSK:** Yalnız erişilebilirlik; kapı nginx IP izin listesi ya da SSH tünelinin arkasındadır (`yonetim_izinli_ipler`). IP başına sınır (10) ayrıca vardır. Parola tahmini bu yolla hızlanmaz.
- **ÖNERİ:** Kabul; brute force'a karşı bilinçli takas. Kilitte beklemek 15 dakika sürer (runbook'ta yazılı); sayacı sıfırlayan bir CLI komutu eklenmedi, çünkü saldırgan kilidi kaldırtmaya zorlayamaz ama komut yanlış kullanılırsa korumayı zayıflatır.

### S5 `tarama/server.py` `_sil` — süresi dolmuş belirteçle silme ucu, temizlik çalışana kadar satırı siler — KABUL EDİLDİ (BİLGİ)

- **BULGU:** Okuma ucu ve `/dogrula` ucu `bitis_utc > şimdi` arar; `rapor_sil` aranmaz. Süresi dolmuş ama henüz `suresi_dolanlari_sil` ile temizlenmemiş raporun `/sil` ucu `303` döner ve satırı siler.
- **KANIT:** `RaporBelirteciTests::test_bitis_sonrasi_hicbir_uc_veri_vermez`: bitişten sonra GET (iki görünüm), `/dogrula` `404`; `/sil` yanıtında rapor içeriği yok ve sonrasında yine `404`.
- **RİSK:** Veri sızmaz; silme istenen sonuçtur (saklama süresi zaten dolmuştur). Belirteç sahibi için "var mıydı" farkı görünür, belirteç zaten sahibindedir.
- **ÖNERİ:** Değişiklik gerekmez. Test yalnız "içerik gelmez" der; durum kodunu sabitlemez, ileride `404`e çevrilirse test kırılmaz.

### S6 `docs/runbook.md` — TOTP cihazı kaybı prosedürü tek cümleydi — DÜZELTİLDİ (ORTA, belge)

- **BULGU:** Runbook yalnız "telefon kaybolursa `totp-yenile` ile yeni anahtar üretin" diyordu. Hangi kullanıcıyla, hangi sırayla, kaybolan cihaz çalınmış olabilirse ne yapılacağı, kilit süresi ve doğrulama yoktu.
- **KANIT:** `yonetim/kullanici.py` `totp-yenile` yeni sırrı üretir, sayacı sıfırlar, kullanıcının açık oturumlarını kapatır ve `cli` aktörüyle denetime yazar (`TotpKurtarmaTests`: eski cihaz girmez, yeni anahtar girer, parola aynı kalır, olmayan ya da geçersiz ad kayıt bırakmaz). Kod yeterliydi; eksik yalnız prosedürdü.
- **RİSK:** Acil durumda yanlış sıra (örneğin cihaz çalınmışken yalnız TOTP yenilemek, parolayı bırakmak) ya da anahtarın terminal kaydına düşmesi.
- **ÖNERİ / DÜZELTME:** `docs/runbook.md` "Doğrulama cihazı kaybı" bölümü eklendi (kimlik doğrulama, komut sırası, çalıntı cihaz için parola yenileme, kilit, doğrulama, denetim kaydı).

### ALIG-SEC-001: erişimin olmaması gereken yollar — doğrulandı (açık bulunmadı)

| Gereklilik | Sonuç | Kanıt (`tests/test_erisim_guvenligi.py`, ek olarak mevcut `test_portal.py`) |
| --- | --- | --- |
| Firma A belirteci firma B raporunu açamaz | Doğrulandı | `RaporBelirteciTests` (43 konumda tek karakter değişimi, kısaltma, uzatma, büyük/küçük harf, yol ve sorgu hileleri, A belirteciyle B silinemez/doğrulanamaz); portal: `IzolasyonTests`, `test_rapor_izolasyonu_http` |
| Rapor belirteci ömrü: `bitis_utc` sonrası erişim yok; silinen rapor yeniden açılmaz | Doğrulandı | `test_bitis_sonrasi_hicbir_uc_veri_vermez`, `test_bitis_siniri_saniye_hassasiyetinde`, `test_silinen_rapor_belirteci_yeniden_yuklemeyle_dirilmez`, `BekleyenRaporSureTests` (bekleyen rapor: süre dolunca onay sayfası da `404`, doğrulama hak harcamaz) |
| Yönetim CSV yalnız oturumlu | Doğrulandı | `test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir`, `test_oturum_baska_yollarla_gecersiz_olunca_acilmaz` (kullanıcı silindi, parola değişti, anahtar yenilendi) |
| Yönetim uçlarının tamamı oturumsuz kapalı | Doğrulandı | Tablo güdümlü: menü ve kaynak yolları tabloda olmak zorundadır (`test_tablo_menu_ve_kaynak_yollarini_kapsar`); 25 GET ve 10 POST yolu × 10 geçersiz kimlik durumu (çerezsiz, sahte, boş, bozuk, `__Host-` önekisiz, özet çerezi, boşta ve toplam süresi dolmuş, çıkış yapılmış) |
| Rapor HTML'inde kaçış | Doğrulandı | `RaporKacisTests`, `RaporKacisSunucuTests`, `PortalKacisTests`, `YonetimKacisTests`: tüm denetimlerin her metin kolonunda etiket, tırnak ve varlık içeren nesne adı; iki dil, iki görünüm, müşteri/portal/yönetim, depolanmış ve yansıyan değerler |
| TOTP tekrar kullanım engeli | Doğrulandı | `TotpTekrarVeOturumOzetiTests` (aynı kod iki IP'den, daha eski pencere kodu, yanlış parola kodu yakmaz, anahtar yenilenince sayaç sıfırlanır); mevcut yarış testi `test_ayni_dogrulama_kodu_es_zamanli_iki_giriste_bir_kez_gecer` |
| Oturum kodu yalnız SHA-256 özetiyle saklanır | Doğrulandı | `test_oturum_kodu_yalniz_sha256_ozetiyle_saklanir` (veritabanı dosyalarında ham kod baytı yok; özet çerez olarak kabul edilmez), `test_portal_oturum_kodu_da_yalniz_ozetle_saklanir` |

Sınırlar: testler SQLite çalışma zamanına karşıdır; PostgreSQL'de aynı davranış `ALIG-DB-003` maddelerinde yeniden sınanacak. Gerçek bir tarayıcı, nginx ya da gerçek sunucu kullanılmadı: HTTP testleri yerel `ThreadingHTTPServer`'a karşıdır (nginx IP izin listesi, `X-Real-IP` yazımı sınanmadı).

### ALIG-SEC-001 mutasyon denemesi

Her satırda koruma geçici bir kopyada kaldırıldı ve `tests.test_erisim_guvenligi` çalıştırıldı.

| Koruma | İlk kırılan test |
| --- | --- |
| Rapor okumada `bitis_utc` denetimi (`rapor_getir`) | `test_bitis_siniri_saniye_hassasiyetinde` |
| Bekleyen raporda `bitis_utc` denetimi (`rapor_bekleyen_getir`) | `test_suresi_dolan_bekleyen_rapor_dogrulanamaz_ve_hak_harcamaz` |
| Yönetim GET uçlarında oturum denetimi | `test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir` |
| Yönetim POST'ta CSRF kodu | `test_oturumlu_ama_csrf_ya_da_kaynak_yanlis_post_reddedilir` |
| Oturum özetinin çerez olarak reddi | `test_oturum_kodu_yalniz_sha256_ozetiyle_saklanir` |
| TOTP tekrar koruması (`s > son_sayac`) | `test_ayni_kod_ikinci_kez_hicbir_yolla_gecmez` |
| Rapor kanıt listesinde kaçış | `test_portal_sayfalari` |
| `totp-yenile` oturumları kapatması | `test_totp_yenile_yeni_anahtar_verir_oturumlari_kapatir_parolayi_degistirmez` |
| CLI `umask` (S2) | `test_cli_gevsek_umask_altinda_bile_dosyayi_0600_olusturur` |
| CSV indirmesinin denetime yazılması | `test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir` |

10/10 yakalandı (test koşusu ilk hatada durduruldu; her satırda yalnız ilk kırılan test yazıldı). Kaçan mutasyon olmadı. Mutasyon betiği depoya girmedi (geçici kopyada çalıştı).
## ALIG-SCAN-001: tarama güvenliği denetimi (2026-11-15)

Kapsam: Kip A toplayıcı (`tarama/toplayici/sablon.py`, üretilen `site/assets/alig-toplayici.py`, `tarama/onsurum/`) ve Kip B (`tarama/hedef.py`, `tarama/baglanti.py`, `tarama/calistirici.py`, ilgili uçlar). Yöntem: kodu okuma, sondalar, mutasyon denemesi, PG16 geçici kümesi. Testler: `tests/test_tarama_guvenlik.py`. Toplayıcı kaynağı değiştirilmedi; `uret_toplayici.py --kontrol` 0 döner.

### S1 `tarama/hedef.py` ve `tarama/baglanti.py` — IPv6 kapsam kimliği bağlantı dizgisine enjekte edilip SSRF reddini atlatıyordu — DÜZELTİLDİ

- **BULGU:** `[...]` içindeki IPv6 yazımı `ipaddress.IPv6Address` ile ayrıştırılıyordu. Python 3.9+ `%` sonrası kapsam kimliğini (`scope_id`) her metinle kabul eder (boşluk ve `=` dahil) ve `str(ip)` kimliği geri yazar. `Hedef.ad` ve `Hedef.ip` bu metni taşıyor, `baglanti_dizgisi` `host=%s hostaddr=%s` ile doğrudan birleştiriyordu. Adres kısmı genel IP olduğundan `adres_uygun` geçiyordu.
- **KANIT:** `hedef.dogrula("[2606:2800:220:1::1%x hostaddr=127.0.0.1 sslmode=disable]", 5432)` kabul edildi; dizgi `host=2606:...%x hostaddr=127.0.0.1 sslmode=disable hostaddr=2606:...%x hostaddr=127.0.0.1 sslmode=disable port=54329 ...` oldu. `psql` bu dizgiyle PG16 geçici kümesinde 127.0.0.1:54329'a bağlandı; bağlantıyı yalnız `channel_binding=require` kesti ("channel binding required"; küme `trust` kimlik doğrulamalıydı). Aynı yol `calistirici.py` içinde `ipaddress.ip_address(i["ip"])` ile de açıktı.
- **RİSK:** Müşteri formundaki "sunucu" alanıyla loopback, RFC1918 ya da bulut meta veri adreslerine bağlantı denenebilir; ek anahtarlarla (`options=-c default_transaction_read_only=off`, `sslmode=disable`) salt okunur ve TLS korumaları da ezilebilirdi. Kip B varsayılan kapalıdır ve çalıştırıcı birimi iç ağa `IPAddressDeny` ile kapalıdır (ikinci katman); ilk katman yine de delikti.
- **DÜZELTME:** (1) `adres_uygun`: kapsam kimlikli adres hiçbir zaman uygun değil; `dogrula`: kimlikli iç adres `ic_adres`, kimlikli genel adres `ad` ile reddedilir. (2) `baglanti_dizgisi`: `host` ve `hostaddr` yalnız `[0-9A-Za-z.:-]`, port 1-65535 tam sayı değilse `BaglantiHatasi("bicim")` (çalıştırıcı soketinden gelen hedef için de geçerli). (3) `AD` kalıbında `$` yerine `\Z` (sondaki satır sonu). Testler: `HedefTablosuTests`, `BaglantiDizgisiSavunmasi`, `CalistiriciHedefTests`; ilgili korumalar kaldırılınca kırmızıya düştü.
- **ÖNERİ:** `ALIG_YASAK_AGLAR` ve çalıştırıcı birimindeki `IPAddressDeny` açık kalsın; tek katmana güvenilmemeli.

### S2 `tarama/baglanti.py` `_calistir` — psql çıktısı sınırsız bellekte toplanıyordu — DÜZELTİLDİ

- **BULGU:** `subprocess.run(capture_output=True)` stdout'u süre sınırı dolana kadar (30 sn) bellekte biriktirir. Kip B'de sunucuyu müşteri seçer; düşmanca bir sunucu `LIMIT` ve `statement_timeout` dışında istediği büyüklükte yanıt gönderebilir.
- **KANIT:** Sahte `psql` 200 MB yazarken test, `CIKTI_SINIRI` olmadığından kırmızıydı. Yeni `_surec_calistir`: stdout 2 MB'ı aşarsa süreç öldürülür, sonuç `hata`.
- **RİSK:** Çalıştırıcı bellek tüketimiyle düşürülebilir; eşzamanlı iki tarama sınırı bunu hafifletmez.
- **DÜZELTME:** `selectors` ile sınırlı okuma: stdout 2 MB, stderr 64 KB, toplam süre sınırı, her durumda `kill`. Test: `CiktiSiniriTests`. Kip A'da değişiklik gerekmedi: toplayıcı müşterinin kendi makinesinde, kendi sunucusuna karşı çalışır.

### S3 Toplayıcı ve Kip B: yalnız okuma, allowlist, oturum ayarları — DOĞRULANDI (eksik testler eklendi)

- **BULGU:** Mevcut `KatalogTests` yalnız `katalog.PG` sorgularını denetliyordu; `YASAKLI` listesinde `into`, `set_config`, `nextval`/`setval`, `for update`, `pg_advisory_*`, `pg_stat_reset*` yoktu; veritabanı listesi sorgusu, ilk bağlantı sorguları (Kip A ve Kip B), üretilmiş toplayıcının gömülü katalogu, `sorgu-katalogu*.txt` ve SQL Server toplayıcısı bu allowlist'ten geçmiyordu.
- **KANIT:** Yeni `TumSqlAllowlistTests`: yalnız `SELECT`/`SHOW`/`WITH ... SELECT`, tek deyim, yorum yok, geniş yasak kalıp listesi (INSERT/UPDATE/DELETE/ALTER/CREATE/DROP/TRUNCATE/GRANT/COPY/`pg_terminate_backend`/`pg_cancel_backend`/`pg_reload_conf`/`set_config`/`SELECT INTO`/`FOR UPDATE` vb.); denetleyici önce 38 kötü örnekle kendini sınar. Kapsam: katalog (eski sürüm biçimleri dahil, 26 denetim), `VT_LISTE_SQL`, `ILK_SORGU`, üretilen toplayıcının AST'deki tüm SQL sabitleri ve gömülü `KATALOG`, `sorgu-katalogu.txt`, SQL Server toplayıcısı ve `sorgu-katalogu-mssql.txt`; `calistir()` çağrılarının SQL'inin yalnız sabit ya da katalogdan geldiği AST ile denetlenir. Hepsi geçti, hiçbir sorgu değişmedi. Oturum: iki yol da her `psql` çağrısında `PGOPTIONS` ile `default_transaction_read_only=on`, `statement_timeout=15000`, `lock_timeout=2000` verir ve ortamdaki düşmanca `PGOPTIONS` ezilir (mock testleri; mutasyonla doğrulandı). PG16'da: toplayıcı oturumu `on / 15s / 2s` döndü, sarmalı kırıp `CREATE TABLE` ekleyen metin salt okunur oturumda reddedildi ve tablo oluşmadı, 26 denetimin hepsi salt okunur oturumda çalıştı. Kip B: toplam süre bütçesi bitince katalog denetimleri çalışmıyor.
- **RİSK:** `default_transaction_read_only` bir güvenlik sınırı değil, kazaya karşı ağdır: oturumdaki SQL `SET` ile aşabilir. Gerçek sınır, SQL metninin sabit katalogdan gelmesi ve allowlist testidir. Hesabın yetkisiz olması (öneri: `pg_monitor`) üçüncü katmandır.
- **ÖNERİ:** Toplayıcı kaynağında değişiklik gerekmedi. `BEGIN READ ONLY` eklemek, ilk sorgudan önce `SET TRANSACTION READ WRITE` ile aşılabileceğinden anlamlı ek koruma sağlamaz.

### S4 SQL Server toplayıcısı (ön sürüm): oturum düzeyinde salt okunur kip yok — AÇIK, KABUL EDİLEN

- **BULGU:** `ON_EK` yalnız `SET NOCOUNT ON`, `SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED`, `SET LOCK_TIMEOUT 2000`, `SET DEADLOCK_PRIORITY LOW`, `DECLARE @j`; sorgu zaman aşımı `sqlcmd -t 15`, bağlantı `-l 15`.
- **KANIT:** `test_mssql_sabit_on_ek_yalniz_oturum_ayari` ön eki sabitler. SQL Server'da `default_transaction_read_only` karşılığı yoktur (`ApplicationIntent=ReadOnly` yalnız kullanılabilirlik grubu yönlendirmesidir, yazmayı engellemez).
- **RİSK:** Koruma yalnız sabit SELECT'ler ve hesabın yetkisidir (`alig-giris-mssql.sql`: `VIEW SERVER STATE`, `VIEW ANY DEFINITION`).
- **ÖNERİ:** Yetki betiğinin dışında yetki verilmesin; `ALIG_MSSQL` zaten varsayılan kapalı. Gerçek SQL Server'da sınanmadı.

### S5 Kip B hedef doğrulaması, kaynak sınırları, varsayılan kapalı — DOĞRULANDI (tablo güdümlü testler eklendi)

- **BULGU:** Mevcut testler iyiydi; eksikler: IPv6 kapsam kimliği, IPv4-mapped onaltılık yazımlar (`::ffff:7f00:1`), `::ffff:0:a.b.c.d`, tam genişlikli rakamlar ve kontrol karakterleri, çözümleyicinin bozuk kayıt döndürmesi, port tabloları (`"05432"`, `"+5432"`, Arapça rakam, `True`), hedefin çalıştırıcı soketinden gelmesi, kaynak sınırlarının sınırda ve sınırın üstünde sınanması (5 MB, derinlik 8, 200 ve 5000 satır, 1000 atlanan, yapı/tırnak/kaçış sayısı), `TARAMA_YUVASI` ve çalıştırıcı eşzamanlılığı (2), çerçeve boyutu, Kip B kapalıyken uçların 404'ü.
- **KANIT:** `HedefTablosuTests` (90 doğrudan girdi, 22 çözümleme senaryosu, port tabloları), `CalistiriciHedefTests`, `SinirTests`, `KapaliTests`, `KapaliUclarTests` (kapalıyken `GET`/`POST` `/api/tarama/baglan` ve `/api/tarama/baglan/<belirteç>` 404; `baglanti.tara` ve çalıştırıcı çağrılmıyor). `ALIG_DOGRUDAN` yalnız tam `1` ve çalıştırıcı soketiyle açılır; `deploy/` ve `config.example` içinde koşulsuz `ALIG_DOGRUDAN=1` yoktur.
- **RİSK (tasarım, bulgu değil):** İzinli port aralığı 1024-65535 ile 5432/1433; internete açık herhangi bir adresin yüksek portu denenebilir. Yanıt tek tip olduğundan port taraması için işe yaramaz; firma başına istek ve deneme sınırları ek frendir.
- **ÖNERİ:** İş gereği genişse müşteri başına izinli port listesi düşünülebilir; şimdilik değişiklik yok.

Mutasyon: kapsam kimliği denetimi, `baglanti_dizgisi` doğrulaması, psql çıktı sınırı, Kip A `lock_timeout` ve Kip A `default_transaction_read_only=on` satırları geçici olarak bozuldu; her biri ilgili testi kırmızıya düşürdü, sonra geri alındı.

