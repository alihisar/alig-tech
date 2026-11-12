# Yol haritası

Çalışma kuralı: her adımda **tek madde** yapılır (önce test, sonra kod, sonra tüm denetimler), bitince bu dosyada işaretlenir.
Onay bekleyen ama işi engellemeyen konularda varsayılan değerle ilerlenir; varsayılan "Varsayılanla ilerleyenler" tablosuna yazılır ve
tek satırla değiştirilebilir olur. Engelleyen kararlar kodlanmaz. Gece görevi de bu sırayı izler.

## Sıradaki maddeler

| # | Madde | Bitti sayılır | Durum |
| --- | --- | --- | --- |
| 1 | Kip B ayrı çalıştırıcı servisi: tarama web sürecinden ayrı, yetkisi kısıtlı bir süreçte çalışır; parola yalnızca yerel soket üzerinden bellekte taşınır | Çalıştırıcı, istemci, systemd birimi (varsayılan kurulmaz), testler | yapıldı |
| 2 | Firma kayıtlarının saklama süresi: son etkinlikten 12 ay sonra otomatik silme, bakım işinde | Bakım silmesi, panelde kalan süre, test | bekliyor |
| 3 | Yönetim panelinde doğrudan bağlantı istekleri: kim, ne zaman, sonuç (adres yok, yalnız özet) | Liste sayfası, test | bekliyor |
| 4 | Kip B sunucu sertifikası doğrulaması: müşteri CA sertifikası verirse `verify-full` | Form alanı, doğrulama, gerçek PostgreSQL + TLS denemesi | bekliyor |
| 5 | Kip B yanıt süresini sabitleme (port tarama zamanlamasına karşı) | Başarısız bağlantıda sabit alt süre, test | bekliyor |
| 6 | E-posta doğrulamasının gönderimden bağımsız kısmı: tek kullanımlık kod, süre, deneme sınırı, doğrulanmış firma işareti; gönderici takılabilir | Kod üretimi ve doğrulama, panelde durum; gönderim yöntemi seçilince tek sınıf eklenir | bekliyor |
| 7 | Hazırlık kılavuzuna doğrudan bağlantı bölümü (yalnızca özellik açıkken görünür sayfa) | TR ve EN metin, test | bekliyor |
| 8 | Ana sayfada sağlık taraması bölümü: ne verir, ne almaz, örnek rapor görüntüsü | TR ve EN, boyut bütçesi içinde | bekliyor |
| 9 | Örnek rapor sayfası (`/ornek-rapor/`): uydurma olmayan, test verisinden üretilmiş ve öyle etiketlenmiş rapor | Sayfa, i18n, test | bekliyor |
| 10 | Tarama raporunu yazdırılabilir özet olarak indirme (yalnız yazdırma stili, PDF üretimi yok) | Yazdırma düzeni testi | bekliyor |
| 11 | PostgreSQL katalog genişletmesi: replikasyon gecikmesi, `pg_hba` özeti, uzun süren sorgular, şişkinlik tahmini | Her denetim için kural, test, gerçek PostgreSQL 16 denemesi | bekliyor |
| 12 | Dağıtım: çalıştırıcı ve Kip B için Ansible değişkenleri, runbook bölümü, duman testi | `ansible-lint` temiz, runbook güncel | bekliyor |
| 13 | SQL Server ön sürümünü gerçek sunucu çıktısına göre düzeltme | Ali'nin gönderdiği `ok` / `ATLANDI` listesi | Ali'yi bekliyor |

## Varsayılanla ilerleyenler (onay bekliyor, engellemiyor)

| Konu | Varsayılan | Nerede değişir |
| --- | --- | --- |
| Ücretsiz tarama sınırı | Şirket başına 30 günde 2 | `tarama/depo.py` `SINIR_ADET`, `SINIR_GUN` |
| Rapor saklama | 30 gün | `tarama/depo.py` `SAKLAMA_GUN` |
| Firma kaydı saklama | Son etkinlikten 12 ay sonra silinir (madde 2 ile gelir) | `tarama/depo.py` `FIRMA_SAKLAMA_GUN` |
| Kip B parola | Saklanmaz, her taramada sorulur | tasarım kararı |
| Kip B sınırları | İstek 30 dk, 3 deneme, saatte 5 istek, aynı anda 2 tarama | `tarama/depo.py` `ISTEK_*`, `tarama/calistirici.py` |
| Kip B kimlik | E-posta doğrulaması yerine yönetici izni | panel, firma ayrıntısı |
| Doğrudan bağlantı ve SQL Server | Kapalı | `ALIG_DOGRUDAN`, `ALIG_MSSQL` |

## Engelleyen kararlar (Ali)

| Karar | Neyi engelliyor |
| --- | --- |
| E-posta gönderim yöntemi (sağlayıcı ya da kendi sunucu) | Kayıt e-postası, firma doğrulamasının gönderimi, Kip B'nin genel açılışı |
| Barındırma sağlayıcısı, sunucu IP adresi, sabit çıkış IP | Canlıya alma, Kip B için müşteri güvenlik duvarı izni |
| Hukuki metinler: KVKK aydınlatma, kullanım koşulları, Kip B bağlantı onayı | Canlıya alma |
| Gerçek iletişim e-postası ve şirket bilgileri | Sürüm etiketi (`--release` denetimi) |
| SQL Server'ın gerçek sunucuda denenmesi | SQL Server taramasının yayımlanması |
| Logo ve arka plan görselleri | Tasarımın son hâli |
