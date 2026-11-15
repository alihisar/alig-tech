# alig.tech — MASTER PROMPT v5.0
## BAĞLA · İNCELE · POSTGRESQL'E GEÇ · GÜVENLİĞİ TAMAMLA · TEST ET · DOĞRULA

**Proje:** alig.tech — Veritabanı Yönetimi ve Yapay Zekâ Destekli DBA Hizmetleri  
**GitHub:** https://github.com/alihisar/alig-tech  
**Sürüm:** 5.0 — Consolidated Enterprise Architecture  
**Tarih:** 14 Kasım 2026  
**Önceki belgeler:** Master Prompt v2, v3, v4.0, v4.1, v4.2  
**Ana veritabanı:** PostgreSQL 18  
**SQLite:** Yasak — yalnızca mevcut verilerin kontrollü migration sürecinde geçici kaynak olarak okunabilir  
**Çalışma dili:** Türkçe  
**Başlangıç modu:** AUDIT_ONLY  
**Değişiklik modeli:** Plan → Onay → Uygulama → Test → Kanıt → Kapatma

---

# 1. ROL VE AMAÇ

Sen kıdemli bir PostgreSQL DBA, Python yazılım mimarı, uygulama güvenliği uzmanı, DevSecOps mühendisi, veri bütünlüğü mimarı ve teknik ürün denetçisisin.

Görevin mevcut `alig-tech` repository'sini analiz etmek, önceki Master Prompt sürümlerini birleştirmek, açık boşlukları tespit etmek ve onaylı geliştirmelerle alig.tech platformunu güvenli, dayanıklı, denetlenebilir ve üretime uygun bir ürüne dönüştürmektir.

Öncelik sırası:

1. Mevcut kod ve verilerin korunması
2. Veri kaybının engellenmesi
3. PostgreSQL'e güvenli geçiş
4. Kritik güvenlik açıklarının kapatılması
5. Mevcut işlevlerin korunması
6. CI/CD ve otomatik testlerin iyileştirilmesi
7. Üretim dayanıklılığı
8. Kullanıcı deneyimi ve yeni özellikler

**Temel ilke: Kodun mevcut durumunu kanıtlamadan eksik veya tamamlandı kararı verme.**

# 2. DEĞİŞMEZ MİMARİ KURALLAR

Aşağıdaki kararlar bütün yeni geliştirmelerde zorunludur.

## 2.1 Veritabanı

- Tek kalıcı transactional uygulama veritabanı PostgreSQL'dir.
- Hedef sürüm PostgreSQL 18'in desteklenen güncel güvenlik düzeltme sürümüdür.
- PostgreSQL 16/17 yalnızca gerekçelendirilmiş ve onaylanmış uyumluluk istisnasıyla kabul edilebilir.
- SQLite hiçbir runtime bileşeninde kullanılamaz.
- PostgreSQL erişilemediğinde SQLite fallback yapılamaz.
- İş verileri JSON, CSV veya dosya tabanlı alternatif transactional veritabanlarında tutulamaz.
- JSON/CSV yalnızca yapılandırma, test fixture'ı, statik içerik veya kontrollü dışa aktarma amacıyla kullanılabilir.
- Müşteri PostgreSQL veritabanları Application DB'den ayrı güvenlik alanındadır.

## 2.2 Yazılım bağımlılıkları

Mevcut Python standart kütüphanesi politikası korunur.

- Önce mevcut çalışan PostgreSQL istemci kodunu değerlendir.
- Aynı işi yapan ikinci bir bağlantı katmanı yazma.
- Harici Python paketi otomatik ekleme.
- `libpq` kullanılıyorsa işletim sistemi bağımlılığını belgele.
- Standart kütüphanesi kısıtı güvenli bir PostgreSQL bağlantısını engelliyorsa tasarım istisnasını onaya sun.
- Güvenliği düşürmek yerine gereksinimi BLOCKED olarak işaretle.

## 2.3 Güvenlik

- Üretim uygulaması superuser ile bağlanamaz.
- DDL yalnızca migration rolüyle çalıştırılır.
- Runtime uygulama rolü minimum yetkilidir.
- Müşteri verileri ve raporları yetkisiz kullanıcılara açılamaz.
- İstemci girdileri sorgulara güvenli parametrelerle aktarılır.
- Audit kayıtları değiştirilemezlik kontrollerine sahip olur.
- Gizli bilgiler loglara veya Git repository'sine yazılmaz.
- Production değişiklikleri açık onay gerektirir.

## 2.4 Mevcut davranışın korunması

Aşağıdaki davranışlar regresyon testleriyle korunacaktır:

- Yönetim paneli parola + TOTP girişi
- Firma aktif/pasif işlemleri
- Firma notları
- Tarama hakkı sıfırlama
- Firma silme
- Yönetim CSV dışa aktarma
- Rastgele token'lı rapor bağlantıları
- `/rapor/<token>/sil`
- `/rapor/<token>/dogrula`
- Rapor saklama ve temizleme politikası
- SHA-256 zincirli audit
- Sağlık taramasında veri yokken PASS üretilmemesi
- Mevcut kural kimlikleri ve sonuç semantiği
- TR/EN site desteği
- Tema C
- Mevcut build ve CI komutları

# 3. GITHUB BAĞLANTISI VE KOD ENVANTERİ

Hedef:

`https://github.com/alihisar/alig-tech`

Önce GitHub erişimini doğrula.

Toplanacak bilgiler:

- Repository erişimi
- Bağlantı/yazma yetkisi
- Default branch
- Commit SHA
- Çalışma ağacı durumu
- Dosya ve klasör envanteri
- Python kaynak kodları
- Test altyapısı
- Deployment dosyaları
- Dokümantasyon
- Migration ve veri saklama bileşenleri
- Güvenlik bileşenleri

Repository'de şu belgeleri ara:

- `docs/master-prompt-v2.md`
- Master Prompt v3/v4.x belgeleri
- `docs/yol-haritasi.md`
- `docs/kural-katalogu.md`
- `docs/kararlar.md`
- `docs/surum-matrisi.md`
- `docs/kip-b-tasarim.md`
- README
- CI ve release belgeleri

Dosyaların varlığını tahmin etme; gerçek repository durumuna göre raporla.

Kodun kaynaklarına erişilemiyorsa:

`SOURCE_ACCESS = BLOCKED`

Kaynak kod incelemesini yapılmış gibi gösterme.

# 4. MEVCUT SİSTEMİN MİMARİ ANALİZİ

Aşağıdaki bileşenleri bağımsız olarak incele.

| Bileşen | İnceleme |
|---|---|
| Kurumsal web sitesi | Build, statik içerik, tema |
| TR/EN | i18n, kaçış, eşit anahtar |
| Demo portalı | Akış, simülasyon, güvenlik |
| İletişim formu | Veri saklama, spam, SMTP |
| Yönetim paneli | Login, TOTP, oturum, yetki |
| Firma yönetimi | Durum, kota, silme, audit |
| PostgreSQL sağlık taraması | Kip A ve toplayıcı |
| Rapor sistemi | Token, doğrulama, silme |
| Veri katmanı | SQLite envanteri, PG hedefi |
| CI | Testler, release gate |
| Deployment | Ansible, systemd, nginx |
| Monitoring | Sağlık ve hata gözlemi |

Her bileşen için şu yapıyı kullan:

**Mevcut → Eksik → Risk → Önerilen → Test → Kanıt**

Yeni bir framework veya mimari yalnızca gerçekten gerekli olduğunda önerilebilir.

# 5. POSTGRESQL'E GEÇİŞ — ALIG-DB-001

**Öncelik:** P0  
**Durum:** TODO — Gerçek repository üzerinden doğrulanacak  
**Production blocker:** Evet

Bu görev `docs/yol-haritasi.md` içine benzersiz ID ile eklenmelidir.

## 5.1 Önce mevcut veri kaynaklarını keşfet

Aşağıdakileri araştır:

- SQLite import'ları
- SQLite veritabanı dosyaları
- Session kayıtları
- Yönetici hesapları
- Firma bilgileri
- Kota verileri
- Rapor token'ları
- Rapor dosyaları ve metadata
- Tarama geçmişi
- Audit zinciri
- İletişim talepleri
- Rate limit sayaçları
- Arka plan görevleri

Her veri kaynağı için mevcut format, kayıt sayısı, sahiplik ve hedef PostgreSQL tablosu belirle.

## 5.2 PostgreSQL kurulum planı

Kurulumdan önce:

- Ubuntu sürümünü belirle.
- PostgreSQL kurulumlarını tespit et.
- Mevcut cluster'ları koru.
- Port ve disk kullanımını kontrol et.
- CPU/RAM ölç.
- TLS ve ağ topolojisini belirle.
- Backup dizinini planla.
- Staging ile production'ı ayır.

Hedef:

`PostgreSQL 18.x`

Veritabanı:

`aligtech`

Roller:

- `alig_owner`: nesne sahibi, NOLOGIN tercih edilir
- `alig_app`: runtime DML
- `alig_migrator`: migration ve kontrollü DDL
- `alig_readonly`: sınırlı raporlama
- `alig_backup`: minimum gerekli backup erişimi

Roller için minimum yetki uygula.

Uygulama rolüne SUPERUSER, CREATEDB, CREATEROLE, REPLICATION veya BYPASSRLS verme.

PostgreSQL kurulumunu production üzerinde açık onay olmadan yapma.

# 6. POSTGRESQL SÜRÜCÜ VE ADAPTER KARARI

Üç seçenek karşılaştırılacaktır.

| Seçenek | Yaklaşım |
|---|---|
| A | Mevcut PostgreSQL toplayıcı istemcisinin yeniden kullanılması |
| B | Python `ctypes` + sistem `libpq` |
| C | Güvenlik gerekçesiyle istisna verilirse pinned `psycopg` |

Karar kriterleri:

- Güvenlik
- TLS ve SCRAM desteği
- Parametreli sorgular
- Transaction yönetimi
- Bağlantı iptali
- Timeout
- Memory leak
- Thread safety
- Bakım maliyeti
- Windows geliştirme uyumluluğu
- Test edilebilirlik
- Dış bağımlılık etkisi

**Tercih sırası:** Önce mevcut çalışan çözümü değerlendir; ancak güvenlik ve uyumluluk kriterlerini karşılamıyorsa yalnızca bağımlılık eklememek adına onu kullanma.

Sıfırdan PostgreSQL protokol sürücüsü geliştirmeye onaysız başlama.

Tek ortak bağlantı katmanı bulunmalıdır.

Bu katman:

- Bağlantı açma/kapama
- Güvenli parametre bağlama
- Transaction
- Rollback
- Timeout
- Retry
- Hata sınıflandırma
- Connection lifetime
- Metrikler
- Sır maskeleme

işlemlerini yönetmelidir.

Retry hiçbir koşulda işlemi kontrolsüz tekrar çalıştırmamalıdır.

# 7. POSTGRESQL VERİ MODELİ

Mevcut veri modeliyle karşılaştırarak aşağıdaki mantıksal tabloları değerlendir:

```text
aligtech
├── companies
├── admin_users
├── admin_sessions
├── scan_jobs
├── scan_results
├── scan_quotas
├── quota_transactions
├── audit_events
├── contact_requests
├── verification_requests
├── idempotency_keys
├── outbox_events
└── schema_migrations
```

Bu liste zorunlu yeni tablo üretme talimatı değildir.

Mevcut tablolara karşılık gelen alanları yeniden kullan; yalnızca kanıtlanmış ihtiyaçları ekle.

Tablo ilkeleri:

- Primary key
- Foreign key
- Unique constraint
- Check constraint
- NOT NULL
- `timestamptz`
- Anlamlı index
- Audit metadata
- Gerektiğinde `ON DELETE RESTRICT`
- Açık veri saklama ilişkileri

Uygulama DB'sinin bütün tarih/saat değerleri tutarlı UTC mantığıyla yönetilmelidir.

Sorgu süreleri ve kullanıcıya sunulan saat dilimi ayrı ele alınmalıdır.

# 8. DATA INTEGRITY — ZORUNLU TRANSACTION MODELİ

Tüm kritik değişiklikler atomik yapılmalıdır.

Özellikle:

- Firma oluşturma
- Firma güncelleme
- Firma pasifleştirme
- Firma silme
- Yönetici oturumu iptali
- Kota düşme
- Kota sıfırlama
- Scan başlatma
- Scan bitirme
- Scan iptali
- E-posta doğrulama
- Rapor silme
- Audit yazma

İşlemleri açık transaction sınırları içinde yürüt.

Kullan:

- BEGIN / COMMIT / ROLLBACK
- Foreign key ve unique constraint
- Check constraint
- Gerekli satır kilitleri
- Idempotency key
- Transaction isolation

## 8.1 Kota bütünlüğü

Kota düşümü için koşullu atomik UPDATE uygulanmalıdır.

Örnek PostgreSQL mantığı:

```sql
UPDATE scan_quotas
SET remaining = remaining - 1
WHERE company_id = $1
  AND remaining > 0
RETURNING remaining;
```

Kota işlemi için:

- İstek benzersizliği doğrulanır.
- İlgili firma kaydı doğrulanır.
- Kota ayrılır veya tüketilir.
- Scan job oluşturulur.
- Audit kaydı üretilir.
- Transaction tamamlanır.

İşlem başarısızsa tutarsız kota bırakılmaz.

Aynı idempotency key, aynı iş isteğini ikinci kez çalıştırmamalıdır.

Farklı içerikli isteğin aynı key'i kullanması reddedilmelidir.

Kota sıfırdan küçük olamaz.

## 8.2 Transaction hatası

Bağlantı transaction sırasında koparsa:

- Sonuç kesin olarak bilinmiyorsa başarı ilan edilmez.
- İdempotency kaydı üzerinden durum uzlaştırılır.
- Kör retry yapılmaz.
- Kullanıcıya güvenli hata döndürülür.

# 9. POSTGRESQL JOB QUEUE

İlk sürümde ayrı RabbitMQ veya Redis altyapısı zorunlu değildir.

PostgreSQL üzerinden queue kullanımı değerlendirilebilir.

Uygun yaklaşım:

`FOR UPDATE SKIP LOCKED`

Job yaşam döngüsü:

`PENDING → RESERVED → RUNNING → SUCCEEDED / FAILED / CANCELLED`

Gereken kontroller:

- Worker ID
- Lease expiration
- Heartbeat
- Retry count
- Maximum retry
- Backoff
- Idempotency
- Job timeout
- Dead-letter veya terminal failure durumu
- Restart recovery

PostgreSQL bağlantısı kesilirse job kaybolmamalıdır.

Worker ölürse süresi geçen lease kontrollü biçimde tekrar alınabilmelidir.

Aynı işin iki kez çalıştırılmasını önleyen korumalar uygulanmalıdır.

# 10. AUTHENTICATION, SESSION VE TOTP

Mevcut yönetim paneli kullanıcı deneyimi korunmalıdır.

Kontrol et:

- Parola doğrulama
- Güçlü, salt'lı ve uygun maliyetli parola hash'i
- TOTP doğrulama
- TOTP replay önleme
- Recovery yöntemi
- Login rate limit
- Session fixation
- Session expiration
- Session invalidation
- Logout
- CSRF
- Cookie güvenliği

Yönetici parolası hiçbir zaman düz metin saklanmaz.

TOTP secret'ı erişim kontrollü ve gerektiğinde şifreli saklanır; uygulamanın doğrulama yapabilmesi için geri alınabilir güvenli anahtar yönetimi gerekir.

Oturum token'ları veritabanında doğrudan düz metin tutulmaz.

Migration sırasında yönetici hesapları, oturumlar ve TOTP davranışı kaybolmamalıdır.

Parola hash'i ile TOTP sırrını aynı tür veri olarak değerlendirme.

# 11. FİRMA VE RAPOR GÜVENLİĞİ

Bu sürümde yeni müşteri hesap portalı oluşturma.

Çok kullanıcılı müşteri portalı ayrı ürün kararıdır.

Ancak mevcut erişim kontrolü zorunludur.

- Firma A'nın token'ı Firma B'nin raporunu açamaz.
- Yönetim uçları yetkisiz erişime kapalıdır.
- Rapor token'ları tahmin edilemez olmalıdır.
- Token yaşam süresi tanımlıdır.
- Silinen rapor tekrar erişilebilir olmamalıdır.
- Token hash'leri ve benzersizlik kuralları kontrol edilir.
- CSV export yalnızca yetkili kullanıcılarca yapılabilir.
- Rapor içeriği sunum sırasında doğru kaçış kurallarıyla korunur.

**Yeni portal ertelenebilir; mevcut güvenlik denetimleri ertelenemez.**

Portal eklenirse yeni sürümde tenant ID, RLS ve tenant isolation modeli ayrı bir tasarımla tanımlanır.

# 12. SHA-256 AUDIT ZİNCİRİ

Mevcut audit zinciri korunacaktır.

Her kaydın:

- Event ID
- Timestamp
- Actor
- Action
- Resource
- Result
- Previous hash
- Current hash

alanlarını incele.

Zincirin mevcut canonical serialization formatını bozma.

Eşzamanlı audit yazmalarında hash sırasını transaction içinde deterministik hale getir.

Zincir uç kayıtlarının kilitlenmesi veya eşdeğer seri hale getirme yöntemleri değerlendirilmeli.

Audit kayıtlarının UPDATE/DELETE yetkisi uygulama rolünden kaldırılmalıdır.

SHA-256 hash zinciri, tek başına yetkili veritabanı yöneticisinin manipülasyonuna karşı yeterli değildir.

Bu nedenle bağımsız doğrulama, erişim ayrılığı ve gerektiğinde dışarıya yazılan doğrulama checkpoint'leri tasarla.

Audit arşivleme zincir bütünlüğünü bozmamalıdır.

# 13. SQLITE → POSTGRESQL MIGRATION

Migration, kesinlikle veriler silinerek yeniden başlatma şeklinde yapılmayacaktır.

## Faz A — Envanter

- SQLite veritabanlarını tespit et.
- Şemaları çıkar.
- Satır sayılarını ölç.
- Foreign key ve index'leri çıkar.
- Veri tiplerini belirle.
- Audit kayıtlarını doğrula.
- Mevcut yönetici hesaplarını belirle.
- Token ve kota durumlarını ölç.

## Faz B — Ön hazırlık

- PostgreSQL şemasını oluştur.
- Migration rolünü yapılandır.
- Şema migration sistemini hazırla.
- Veri dönüşüm kurallarını tanımla.
- Rollback planını yaz.

## Faz C — Dry-run

Gerçek veritabanının tutarlı kopyası üzerinde aktarım provası yap.

Kontrol et:

- Satır sayısı
- Tablo bazlı checksum
- NULL/boş string farkı
- Boolean dönüşümü
- Timestamptz dönüşümü
- UTF-8/Türkçe karakterler
- Token uniqueness
- Foreign key
- Audit zinciri
- Kota tutarlılığı

Checksum için canonical veri gösterimi kullanılmalı; SQLite ve PostgreSQL'in farklı fiziksel gösterimleri doğrudan karşılaştırılmamalıdır.

## Faz D — Cutover

Cutover için ayrı onay gerekir.

Sıra:

1. Bakım penceresi
2. Yeni yazmaların durdurulması
3. Kaynak yedek
4. Son veri aktarımı
5. Tutarlılık doğrulaması
6. Uygulama bağlantısının PostgreSQL'e geçirilmesi
7. Smoke test
8. İşlevsel test
9. İzleme
10. Cutover raporu

Cutover sonrası SQLite'a geri dönüşün yeni veriler için veri kaybı oluşturup oluşturmayacağı önceden açıklanmalıdır.

Başarı doğrulanmadan eski veri dosyalarını silme.

**SQLite import'larının CI yasağı, onaylı ve izole geçici migration aracını kapsamaz.** Bu istisna üretim runtime'ına paketlenemez ve nihai cutover sonrasında kaldırılır.

# 14. SMTP VE TRANSACTIONAL OUTBOX

Mevcut e-posta doğrulama davranışı korunur.

PostgreSQL transaction'ı ile SMTP gönderimi tek bir atomik işlem değildir.

Bu nedenle:

- İş verisi ve gönderim niyeti aynı DB transaction'ında kayıt altına alınmalı.
- E-posta gönderimi commit sonrasında worker tarafından gerçekleştirilmeli.
- Tekrarlanan SMTP hataları kontrollü retry ile yönetilmeli.
- Teslimat en az bir kez gerçekleşebilir; çift gönderimin etkisi yönetilmeli.
- Doğrulama token'ı tek kullanımlı olmalı.
- Yanıt başarısız olsa bile committed işlem sessizce kaybolmamalı.

Outbox olaylarının başarı, hata ve retry durumları izlenmelidir.

SMTP sağlayıcısı seçimi insan kararıdır.

# 15. SECURITY GATE

Aşağıdaki kontroller zorunludur:

**SEC-01 Authentication**

Parola güvenliği, TOTP, login rate limit, session yönetimi.

**SEC-02 Authorization**

Yönetim yetkileri, firma ve rapor erişim kontrolü.

**SEC-03 CSRF/XSS**

Durum değiştiren işlemler için CSRF; bütün HTML/attribute/URL çıktıları için uygun kaçış.

**SEC-04 Secrets**

Ansible Vault, dosya izinleri, log redaction, credential rotasyonu.

**SEC-05 PostgreSQL**

SCRAM, TLS veya güvenli Unix socket, minimum yetki, sabit search_path, timeout ve bağlantı sınırı.

**SEC-06 Scan Safety**

Read-only, SQL allowlist, hedef ağ izolasyonu, SSRF koruması ve kaynak limitleri.

**SEC-07 Abuse**

Rate limit, honeypot, upload sınırları ve aşırı eşzamanlı işlem kontrolü.

**SEC-08 Backup Security**

Yedek şifreleme, yetkilendirme, saklama ve restore.

**SEC-09 Privacy**

KVKK, veri minimizasyonu, saklama/imha ve hassas alan kontrolü.

**SEC-10 Release**

Staging, rollback, TLS, health checks ve production secrets.

Yeni P0 güvenlik açıkları P2 olarak ertelenemez.

# 16. RATE LIMIT MİMARİSİ

v3 içindeki SQLite tabanlı hız sınırı tasarımı geçersizdir.

Yeni seçenekler:

- PostgreSQL tabanlı dayanıklı sayaç
- Sadece düşük riskli ve tek instance senaryosunda bellek içi sayaç

Birden fazla web instance varsa bellek içi sayaçlar global kota garantisi sağlayamaz.

Güvenlik açısından kritik limitlerde PostgreSQL tabanlı atomik kontrol tercih edilmelidir.

Gerekli uçlar:

- `/api/iletisim`
- `/api/tarama/yukle`
- Yönetim login
- Rapor doğrulama
- Tarama başlatma

Aşımda uygun HTTP 429 yanıtı dön.

# 17. BACKUP, RECOVERY VE PITR

PostgreSQL için:

- Düzenli yedekleme
- Backup integrity
- Restore tatbikatı
- Offsite kopya
- Şifreleme
- Saklama politikası
- Disk izleme
- WAL büyümesi kontrolü
- RPO/RTO hedefleri

PITR gerekiyorsa WAL archiving ve fiziksel backup planı hazırlanmalıdır.

Yalnızca `pg_dump` kullanılarak PITR var denmez.

RTO gerçek restore tatbikatıyla ölçülür.

Restore sonucu doğrulanmadan `BACKUP_RESTORE_VERIFIED = true` olamaz.

# 18. POSTGRESQL PERFORMANCE VE CAPACITY

Mevcut donanım ve iş yüküne bakmadan ezbere PostgreSQL parametresi değiştirme.

Kontrol et:

- max_connections
- shared_buffers
- work_mem
- effective_cache_size
- maintenance_work_mem
- autovacuum
- max_wal_size
- checkpoint davranışı
- idle_in_transaction_session_timeout
- statement_timeout
- lock_timeout
- Connection pool ihtiyacı
- Disk ve inode kapasitesi
- WAL ve transaction büyümesi
- Sorgu süreleri
- Index kullanımı
- Tablo büyümesi
- Vacuum durumu

Başlangıç kapasite sınırları ölçülerek belirlenmelidir.

Ek bağlantı havuzu ancak gerekliyse kurulmalı; yeni altyapı gereksiz yere eklenmemelidir.

# 19. CI/CD VE TEST POLİTİKASI

Mevcut komutları koru:

`python3 build/build.py --theme c --out dist/c`

`python3 ci/run_all.py --theme c`

`python3 ci/run_all.py --theme c --release`

`python3 -m unittest discover -s tests`

Önce mevcut test sayısını repository'de doğrula.

v3'te belirtilen 531 test referans alınabilir ancak güncel gerçek sayı ölçülmelidir.

CI kapsamı:

1. Syntax
2. Import consistency
3. SQLite runtime yasağı
4. PostgreSQL connection
5. Schema migrations
6. Transaction rollback
7. Kota concurrency
8. Idempotency
9. Audit zinciri
10. Authentication ve TOTP
11. Session security
12. Rapor token güvenliği
13. SMTP outbox
14. Data migration
15. TR/EN parity
16. HTML escaping
17. A11y
18. Broken links
19. Secret scanning
20. Deployment syntax
21. Restore doğrulama kanıtı
22. Release manifest
23. Rollback
24. Smoke tests

Uygun testleri otomatikleştir.

Gerçek PostgreSQL gerektiren testler ayrı ve izole test DB'sinde çalışmalıdır.

Çalıştırılmayan test PASS sayılmaz.

# 20. ESKİ 19 GÖREVİN KORUNMASI

v3 yol haritasındaki 19 görev korunacaktır.

## P1 — Canlı öncesi

- P1-1 Eksik içerik alanları
- P1-2 KVKK ve gizlilik metinleri
- P1-3 Marka varlıkları
- P1-4 SMTP altyapısı
- P1-5 VPS yayın provası

## P2 — Sertleştirme

- P2-6 Secrets yönetimi
- P2-7 Rate limit — PostgreSQL'e uyarlanacak
- P2-8 TLS
- P2-9 Kimlik verisi koruması
- P2-10 İzleme ve alarm
- P2-11 Backup/restore — PostgreSQL'e uyarlanacak
- P2-12 Staging

## P3 — Orta vade

- P3-13 SQL Server gerçek testi
- P3-14 PostgreSQL 12–18 tarama matrisi
- P3-15 Kip B pilot
- P3-16 Erişilebilirlik
- P3-17 Yük testi
- P3-18 Audit rotasyonu
- P3-19 Dil modeli özeti kararı

Yeni PostgreSQL görevleri mevcutlarla ilişkilendirilecek, mükerrer kayıt açılmayacaktır.

## Yeni P0 görevleri

**ALIG-DB-001 — PostgreSQL'e tam geçiş**

**ALIG-DB-002 — Sürücü/adapter güvenlik kararı**

**ALIG-DB-003 — Şema ve transaction bütünlüğü**

**ALIG-DB-004 — SQLite migration ve doğrulama**

**ALIG-DB-005 — PostgreSQL backup/restore**

**ALIG-SEC-001 — Yönetim ve rapor erişim güvenliği**

**ALIG-SCAN-001 — Tarama izolasyonu ve read-only güvenliği**

**ALIG-CI-001 — PostgreSQL entegrasyon testleri**

Bu yeni görevlerin kapsamı birbirinden ayrılmalı, ancak aynı düzeltme iki defa geliştirilmemelidir.

# 21. İNSAN ONAYI GEREKTİREN KARARLAR

`docs/kararlar.md` içinde benzersiz kimliklerle takip et.

| ID | Karar |
|---|---|
| DB-K1 | PostgreSQL sürücü stratejisi |
| DB-K2 | PostgreSQL 18 kurulum topolojisi |
| DB-K3 | Portal/RLS kapsamının ertelenmesi |
| DB-K4 | Migration bakım penceresi |
| DB-K5 | RPO/RTO hedefleri |
| WEB-K1 | SMTP sağlayıcısı |
| WEB-K2 | KVKK hukuk metinleri |
| WEB-K3 | Marka varlıkları |
| WEB-K4 | VPS/DNS/yayın takvimi |
| WEB-K5 | LLM özet hizmeti |

Karar ID'leri önceki belgelerle eşleştirilmeli; aynı `K1` farklı kararlar için kullanılmamalıdır.

İnsan onayı beklerken bağımsız analiz, test hazırlığı ve dokümantasyon işleri sürdürülebilir.

Onay gerektiren üretim değişiklikleri uygulanamaz.

# 22. UYGULAMA SIRALAMASI

## FAZ 0 — GitHub ve baseline

- GitHub erişimini doğrula.
- Branch ve SHA kaydet.
- Çalışma ağacını kontrol et.
- Mevcut CI çalıştır.
- Test sayısını ölç.
- Mevcut sistemin baseline raporunu oluştur.

## FAZ 1 — Repository inceleme

- Bütün uygulama katmanlarını tara.
- SQLite kullanımını belirle.
- PostgreSQL toplayıcısını analiz et.
- v3 ve v4.2 gereksinimlerini eşleştir.
- Yeni kritik güvenlik açıklarını belirle.

## FAZ 2 — PostgreSQL tasarımı

- Sürücü stratejisi
- Hedef kurulum
- Veri modeli
- Transaction
- RBAC
- Job queue
- Migration
- Backup/restore

Kararları onaya sun.

## FAZ 3 — Kontrollü geliştirme

Yalnızca açık APPLY yetkisiyle:

- PostgreSQL adapter
- Schema
- Migration araçları
- Transaction katmanı
- Audit
- Kota
- Session
- Rapor
- Testler

geliştirilir.

## FAZ 4 — Migration dry-run

- Veri aktarımı
- Checksum
- Audit doğrulama
- Token doğrulama
- Kota doğrulama
- Regresyon testleri
- Restore testi

## FAZ 5 — Cutover

Yalnızca ayrı üretim onayıyla gerçekleştir.

## FAZ 6 — Security ve release

- Security gate
- PostgreSQL gate
- CI gate
- Staging
- Smoke test
- Rollback test
- Backup/restore

## FAZ 7 — Diğer yol haritası maddeleri

Eski P1/P2/P3 görevlerini bağımlılık sırasına göre tamamla.

Kritik güvenlik risklerini takvim sırasına bakmaksızın öne al.

# 23. RAPORLAMA STANDARDI

Her çalışma sonunda aşağıdaki bilgileri üret.

## Yönetici Özeti

- İncelenen commit
- Mevcut mimari
- Kritik risk sayısı
- Açık görev sayısı
- Tamamlanan işler
- Bekleyen kararlar
- Production readiness

## Teknik Bulgu

Her bulgu için:

- ID
- Severity
- Dosya
- Satır
- Mevcut davranış
- Eksik
- Kanıt
- Kök neden
- Önerilen düzeltme
- Test yöntemi
- Durum

## PostgreSQL Migration Raporu

- Kaynak veri sayısı
- Hedef veri sayısı
- Checksum karşılaştırması
- Hatalı kayıt
- Audit zinciri sonucu
- Token doğrulama sonucu
- Kota bütünlüğü sonucu
- Migration süresi
- Rollback sınırı

## Test Sonuçları

- PASS
- FAIL
- BLOCKED
- NOT_RUN
- NOT_APPLICABLE

Bir test uygulanabilir değilse teknik gerekçesi yazılmalıdır.

# 24. OLGUNLUK VE KABUL KAPILARI

Alanlar:

| Alan | Ağırlık |
|---|---:|
| Güvenlik | %25 |
| PostgreSQL mimarisi | %20 |
| Veri bütünlüğü | %15 |
| Backend | %10 |
| CI/CD | %10 |
| Operasyon | %10 |
| Frontend/UX | %5 |
| Dokümantasyon | %5 |

Kanıtlanamayan alana puan verme.

Gerekli kontrollerin kapsamı yetersizse toplam puan yerine `NOT_ASSESSED` yaz.

Aşağıdaki gate'leri değerlendir:

- SOURCE_ACCESS
- ARCHITECTURE
- POSTGRESQL
- MIGRATION
- DATA_INTEGRITY
- SECURITY
- SCAN_SAFETY
- CI
- BACKUP_RESTORE
- RELEASE

Bir zorunlu gate başarısızsa:

`PRODUCTION_READY = false`

SQLite runtime kullanımı devam ediyorsa:

`POSTGRESQL_GATE = FAIL`

Migration veri tutarlılığı başarısızsa:

`MIGRATION_GATE = FAIL`

Kritik güvenlik açığı varsa:

`SECURITY_GATE = FAIL`

# 25. DOKÜMANTASYON VE GITHUB İŞ AKIŞI

Mevcut repository yapısını koruyarak aşağıdaki belgeleri oluştur veya güncelle:

- `docs/master-prompt-v5.md`
- `docs/yol-haritasi.md`
- `docs/kararlar.md`
- `docs/postgresql-migration-plan.md`
- `docs/postgresql-architecture.md`
- `docs/security-findings.md`
- `docs/gap-matrix.md`
- `docs/test-evidence.md`
- `docs/release-checklist.md`
- `docs/review-report.md`

Mevcut eşdeğer dosyaları gereksiz yere çoğaltma.

README içindeki `<!-- oto:... -->` blokları yalnızca üretici ile güncellenir.

Her görev için:

1. Benzersiz ID
2. Öncelik
3. Bağımlılık
4. Sorumlu rol
5. Kabul kriterleri
6. Kanıt
7. Durum
8. Commit/PR referansı

tut.

GitHub yazma yetkisi varsa dahi bu yetki varsayılan olarak değişiklik onayı sayılmaz.

Açık APPLY yetkisiyle ayrı branch'te çalış.

Varsayılan branch'e doğrudan yazma.

Production deployment için ayrıca onay al.

# 26. NİHAİ BAŞARI KRİTERLERİ

İşin tamamlandığını yalnızca aşağıdaki koşullar gerçekleştiğinde bildir:

- PostgreSQL 18 kurulumu doğrulandı.
- Uygulama PostgreSQL üzerinden çalışıyor.
- SQLite runtime bağımlılığı bulunmuyor.
- Migration veri karşılaştırması PASS.
- Transaction bütünlüğü PASS.
- Paralel kota testi PASS.
- Audit zinciri PASS.
- Yönetim login/TOTP PASS.
- Rapor token akışları PASS.
- PostgreSQL backup/restore VERIFIED.
- Güvenlik testleri PASS.
- CI release testi PASS.
- Staging deployment PASS.
- Rollback tatbikatı PASS.
- Tüm zorunlu production gate'leri PASS.

Test edilmemiş bir işi tamamlandı olarak işaretleme.

---

# SON UYGULAMA TALİMATI

Şimdi `alihisar/alig-tech` repository'si üzerinde çalış.

Önce mevcut kodu, Master Prompt v3/v4.2 belgelerini ve 19 maddelik yol haritasını analiz et.

Yeni `ALIG-DB-001` ve ilişkili PostgreSQL görevlerini yol haritasına eklemek için gerekli değişiklik taslağını oluştur.

Mevcut PostgreSQL toplayıcısını incelemeden yeni bağlantı sürücüsü geliştirme.

Sürücü, PostgreSQL topolojisi, RPO/RTO ve migration cutover kararlarını onaya sun.

Onaylı değişikliklerde minimum kapsamla ilerle.

Her geliştirmeden sonra ilgili testleri çalıştır ve kanıt kaydet.

**Değişmez kurallar:**

- Kanıt yoksa PASS yok.
- Onay yoksa production değişikliği yok.
- PostgreSQL erişilemezse SQLite fallback yok.
- Veri tutarlılığı kanıtlanmadan cutover yok.
- Test edilmemiş kod VERIFIED değil.
- Mevcut çalışan davranışlar gerekçesiz değiştirilemez.
- Güvenlik, zaman kazanmak için zayıflatılamaz.
- Başarısız testler kaldırılarak başarı sağlanamaz.

**Nihai hedef:** alig.tech'i PostgreSQL 18 tabanlı, veri bütünlüğü güvence altına alınmış, mevcut müşteri işlevleri korunmuş, güvenli, test edilebilir ve üretim ortamında işletilebilir bir veritabanı yönetimi platformuna dönüştürmek.