# Yol haritası

Çalışma kuralı: her adımda **tek madde** yapılır (önce test, sonra kod, sonra tüm denetimler), bitince bu dosyada işaretlenir.
Onay bekleyen ama işi engellemeyen konularda varsayılan değerle ilerlenir; varsayılan "Varsayılanla ilerleyenler" tablosuna yazılır ve
tek satırla değiştirilebilir olur. Engelleyen kararlar kodlanmaz. Gece görevi de bu sırayı izler.

## Sıradaki maddeler

Sıra `docs/master-prompt-v2.md` belgesindeki önceliklere göredir (P0 önce). Mevcut durumun dökümü: `docs/faz0-analiz.md`.

| # | Öncelik | Madde | Bitti sayılır | Durum |
| --- | --- | --- | --- | --- |
| 1 | P3 | Kip B ayrı çalıştırıcı servisi | Çalıştırıcı, istemci, systemd birimi, testler | yapıldı (gerçek sunucuda sınanmadı) |
| 2 | P0 | Yükleme ayrıştırıcısını sertleştirme: derinlik sınırı, standart dışı JSON reddi | Düşmanca JSON testleri, sunucu düşmez | yapıldı |
| 3 | P0 | Denetim zincirini anahtarlı doğrulama: `ALIG_DENETIM_ANAHTARI` ile HMAC, zincir başını dışa aktarma komutu, panelde doğrulama durumu | Anahtarsız yeniden üretilen zincir doğrulamada yakalanır; eski kayıtlar bozulmaz | **tamam** (anahtarlı HMAC, sürüm dusurme denetimi, `bas`/`--bas`, panel durumu; zincir başının dış hedefi Ali'den bekliyor) |
| 4 | P0 | Veri sınıfları ve yapılandırılabilir saklama: firma kaydı (varsayılan 12 ay), rapor, talep, denetim, oturum; bakım işinde silme; yedeklerden silme politikası belgesi | Saklama tablosu tek yerde, silme denetime yazılır, test | **tamam** (`tarama/saklama.py`, firma 12 ay, talep, günlük bakım, panel tablosu, `docs/saklama-politikasi.md`; süreler hukuk onayı bekliyor) |
| 5 | P0 | Silme ve erişim negatif testleri: silinen rapora API, bağlantı ve eski bağlantıyla erişilemez; yinelenen yükleme denetimi | Testler, aynı dosya ikinci hak harcamaz | **tamam** (silinen/süresi dolan/firma silinince bağlantı 404, ikinci silme 404, aynı dosya hak harcamaz; ek: aynı dosya yine de yeni rapor bağlantısı üretir) |
| 6 | P0 | Yedekten geri yükleme: `deploy/bakim.py geri-yukle`, bütünlük denetimi, test, runbook | Yedek alınır, bozulur, geri yüklenir, zincir sağlam | **tamam** (`bakim.py geri-yukle`, kuru çalıştırma, doğrulama, önceki dosya korunur; gerçek sunucuda denenmedi) |
| 7 | P0 | Kimlik doğrulama eksikleri: yeni IP'den girişin denetim kaydı, denetim kaydında yapısal alanlar (firma, hedef, sonuç) | Testler | **tamam** (yeni IP'den giriş uyarısı, `alanlar` sütunu özete dahil: firma, hedef, sonuc, neden, ip_ozeti; düz IP yazılmaz; panelde Alanlar sütunu) |
| 8 | P0 | Canlıya alma doğrulama raporu: sözdizimi, kuru çalıştırma ve gerçek dağıtımı ayrı gösteren denetim listesi; servis kullanıcıları, izinler, disk doluluk denetimi | `docs/runbook.md` güncel, her satır DONE ya da NOT_TESTED | bekliyor |
| 9 | P1 | Ortak kanıt modeli ve durumlar: kural kimliği, kategori, PASS, FAIL, WARNING, UNKNOWN, NOT_APPLICABLE, UNAVAILABLE, güven düzeyi, kaynak | Her denetim bir durum üretir, veri yokken PASS çıkmaz | bekliyor |
| 10 | P1 | Sürüm yetenek matrisi PostgreSQL 12–18: denetim başına desteklenen sürüm ve gereken yetki; desteklenmeyen sürümde sorgu çalışmaz | Matris, toplayıcı sürüme göre atlar, test | bekliyor |
| 11 | P1 | Sağlık puanı ve kanıt kapsamı: 0–100, kategori bazında, katsayılar yapılandırılabilir | Bilinmeyen durum puanı yükseltmez, test | bekliyor |
| 12 | P1 | Katalog genişletme: replikasyon gecikmesi, wraparound ve freeze yaşı, autovacuum, `pg_stat_statements` erişilebilirliği, geçici dosyalar | Kural, test, gerçek PostgreSQL 16 denemesi | bekliyor |
| 13 | P1 | Geçmiş karşılaştırması: NEW, PERSISTING, RESOLVED, REGRESSED, UNKNOWN; kaybolan kanıt çözülmüş sayılmaz | Veritabanı kimliği, karşılaştırma, test | bekliyor |
| 14 | P1 | Rapor: yönetici özeti ve teknik rapor görünümleri, yazdırma düzeni | TR ve EN, kanıt ile yorum ayrı | bekliyor |
| 15 | P1 | E-posta doğrulamasının gönderimden bağımsız kısmı: tek kullanımlık süreli kod, takılabilir gönderici | Gönderici yokken canlıda açılmaz | bekliyor |
| 16 | P1 | Müşteri portalı 1: giriş, firma izolasyonu veri erişim katmanında, izolasyon testleri | Başka firmanın kaydına tahmin edilen kimlikle erişilemez | bekliyor |
| 17 | P1 | Müşteri portalı 2: tarama geçmişi, rapor silme, hizmet talebi, kullanım hakkı, veri silme talebi | TR ve EN, test | bekliyor |
| 18 | P1 | Ana sayfa: hizmet kartları, "nasıl çalışır", güvenlik yaklaşımı, SSS | Kanıtsız iddia yok, boyut bütçesi içinde | bekliyor |
| 19 | P1 | Örnek rapor sayfası: test verisinden üretilmiş ve öyle etiketlenmiş | Sayfa, i18n, test | bekliyor |
| 20 | P1 | Yönetim paneli: gösterge sayıları ve ticari süreç durumları (basit durum makinesi ve not) | Test | bekliyor |
| 21 | P1 | İş kuyruğu: yalnızca doğrudan bağlantı için, SQLite tabanlı, ayrı işçi | Durum geçişleri idempotent, yeniden başlatmada toparlanır | bekliyor |
| 22 | P2 | SQL Server: yetenek tablosu ve gerçek sunucu çıktısına göre düzeltme | Ali'nin gönderdiği `ok` / `ATLANDI` listesi | Ali'yi bekliyor |
| 23 | P2 | LLM rapor özeti: varsayılan kapalı, kanıt üretemez, puanı değiştiremez | Sağlayıcı yokken rapor aynen çalışır | bekliyor |
| 24 | P3 | Kip B kalanları: istek listesi panelde, sunucu sertifikası doğrulaması, yanıt süresini sabitleme, kılavuz bölümü | Ayrı kabul kapısı | bekliyor |

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
