# Doldurulması gereken alanlar

Bu liste `python3 ci/check_placeholders.py --write docs/doldurulacak.md` ile üretilir.
Üretim etiketinde (`--release`) bu alanlardan biri kalırsa CI kırılır.

| Dil | Anahtar | Alan |
| --- | --- | --- |
| tr | `sec_v_kvkk` | [doldurulacak: hukuk onayı] |
| tr | `about_todo` | [doldurulacak: kurucunun adı, deneyim yılı, profil bağlantısı] |
| tr | `foot_mail` | [doldurulacak: e-posta adresi] |
| tr | `page_pending` | [doldurulacak] |
| en | `sec_v_kvkk` | [doldurulacak: legal review] |
| en | `about_todo` | [doldurulacak: founder's name, years of experience, profile link] |
| en | `foot_mail` | [doldurulacak: email address] |
| en | `page_pending` | [doldurulacak] |

Diğer açık kararlar (metinde değil, yapılandırmada):

- İletişim e-posta adresi, CI sağlayıcısı, barındırma sağlayıcısı, hedef müşteri kesimi
- KVKK aydınlatma ve çerez metinleri (hukukçu onayı)

## Sağlık taraması: onay bekleyen eşikler (resmî belgede yok, mühendislik seçimi)

- `pg_bosta_islem`: idle in transaction suresi: >=600 sn orta, >=3600 sn yuksek
- `pg_baglanti`: baglanti doluluk: >=75% orta, >=90% yuksek
- `pg_xid_yasi`: orta esik: yas >= 2 x autovacuum_freeze_max_age
- `pg_sequence`: sequence doluluk: >0.8 yuksek, >0.95 kritik
- `pg_slot`: etkin olmayan slot: yuksek
- `pg_kullanilmayan_indeks`: 10 MB ustu ve idx_scan=0: dusuk (istatistik sifirlanmis olabilir)
- PostgreSQL destek sonu tarihleri (`tarama/kurallar.py` `PG_EOL`): her yıl postgresql.org/support/versioning ile doğrulayın.
- Sürüm doğrulaması: PostgreSQL 12, 13, 14, 15, 17 ve 18'de `tarama/surum_dogrula.py` çalıştırılmalı (bu ortamda indirilen ikilileri çalıştırma izni çıkmadı). Sonuç `docs/surum-dogrulama.json` ve `tests/veri/surum/` altına girer, sürüm `katalog.SINANAN` listesine eklenir.
- Sağlık puanı katsayıları (onay bekliyor, işi engellemiyor): ağırlıklar kritik 10, yüksek 6, orta 3, düşük 1, bilgi 0; uyarı kredisi orta 0,5, düşük 0,75, bilgi 1; kategori çarpanları 1; kuralların risk düzeyleri (`docs/kural-katalogu.md`). Değiştirmek için `ALIG_PUAN_AYARI` (`docs/runbook.md`).
- Kanıt modeli seçimleri (onay bekliyor, işi engellemiyor): kural kategorileri ve güven düzeyleri (`docs/kural-katalogu.md`), önemden duruma eşleme (kritik ve yüksek FAIL, diğerleri WARNING), bağlanılamayan bir veritabanı varken veritabanı başına kuralların UNKNOWN sayılması.
- Hukuki metinler: sağlık taraması kullanım koşulları, KVKK eki, veri konumu ve saklama sağlayıcısı, e-posta doğrulama ve gönderim yöntemi.
- E-posta doğrulamasını açmak için: SMTP sağlayıcısı (587 STARTTLS ya da 465 TLS), kullanıcı adı ve parolası, gönderen adres (`deploy/ansible/group_vars/all.yml` ve `/etc/alig/env`). Kod hazır, varsayılan kapalı.

## Firma kaydı (KVKK metnine girmeli)

- Sağlık taraması yüklenirken şirket adı ve e-posta adresi **düz metin** olarak saklanır (`tarama.sqlite`, `firma` tablosu) ve raporla eşleştirilir. Önceki tasarımda yalnız geri döndürülemez özet tutuluyordu; sayfadaki not buna göre değiştirildi.
- Firma kaydı 365 gün (ayarlanabilir) sonra silinir; süre ve müşteri silme talebi yolu onay bekliyor. `[doldurulacak: firma kaydı saklama süresi ve silme talebi yolu]`
- Aydınlatma metninde yazılmalı: toplanan veri (şirket adı, e-posta), amaç (kayıt eşleştirme, sınır, iletişim), saklama süresi, silme hakkı.

## SQL Server taraması (ön sürüm)

- Gerçek bir SQL Server üzerinde sınama: `docs/mssql-onsurum.md` içindeki adımlar. Sınanmadan genel sayfada yayımlanmaz.
- `tarama/kurallar_mssql.py` içindeki `MSSQL_EOL` tarihleri Microsoft yaşam döngüsü sayfalarından alındı (Kasım 2026). Her yıl doğrulanmalı.
- MUHENDISLIK eşikleri (`kurallar_mssql.MUHENDISLIK`): tam yedek 168 saat, log yedeği 24 saat, CHECKDB 14 gün, açık işlem 600 ve 3600 saniye, paralellik maliyet eşiği 5.

## Doğrudan bağlantı (Kip B)

- Canlıya almadan önce: ayrı çalıştırıcı süreci, sunucu sertifikası doğrulaması, sabit çıkış IP adresi, müşteri onay metni. Ayrıntı: `docs/kip-b-tasarim.md`.
- Sınırlar (onay bekliyor): istek 30 dakika geçerli, istek başına 3 deneme, firma başına saatte 5 istek, aynı anda 2 tarama.
