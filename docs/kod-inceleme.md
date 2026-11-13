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

