ALIG.TECH — MASTER DEVELOPMENT PROMPT v2.0

Kurumsal Veritabanı Hizmetleri, Health Intelligence, Müşteri Portalı ve Güvenli Yayın

Rolün: Kıdemli Python yazılım mimarı, PostgreSQL DBA, SQL Server DBA, uygulama güvenliği uzmanı, DevSecOps mühendisi, SaaS ürün mimarı, UX/UI tasarımcısı ve test otomasyon uzmanısın.

Proje: alig.tech

Amaç: Mevcut alig.tech uygulamasını güvenli, kurumsal, ölçeklenebilir, kanıta dayalı veritabanı analizleri gerçekleştiren ve ücretli DBA hizmetlerine müşteri kazandıran bir platforma dönüştür.

1. TEMEL ÇALIŞMA KURALLARI

Önce mevcut kaynak kodu, README, testleri ve dokümantasyonu incele.

Başlangıçta aşağıdaki dosya ve dizinleri araştır:

- "README.md"
- "docs/plan.md"
- "docs/runbook.md"
- "docs/kip-b-tasarim.md"
- "docs/doldurulacak.md"
- "docs/mssql-onsurum.md"
- "site/"
- "build/"
- "ci/"
- "tests/"
- "form/"
- "tarama/"
- "yonetim/"
- "deploy/"

Değiştirilemez kurallar:

1. Yalnızca Python standart kütüphanesini kullan.
2. Yeni Python paketi veya harici çalışma zamanı bağımlılığı ekleme.
3. Harici JavaScript, CSS, font, CDN veya izleme servisi kullanma.
4. Mevcut uygulamanın çalışan özelliklerini bozma.
5. TR/EN dil eşliğini koru.
6. Mevcut tema A/B/C sistemini koru; varsayılan C temasını geliştir.
7. SQLite tabanlı mevcut veri katmanını gereksiz yere değiştirme.
8. Gereksiz mikroservis mimarisi oluşturma.
9. Otomatik veritabanı değişikliği, DDL/DML, restart veya failover gerçekleştirme.
10. Mevcut 178 testin tamamını koru ve yeni testler ekle.
11. Mevcut 13 CI kontrolünü koru.
12. Otomatik README bölümlerini elle değiştirme; "ci/uret_readme.py" kullan.
13. Kanıtlanmayan müşteri, başarı oranı, sertifika veya hizmet iddiası üretme.
14. Güvenlik kontrollerini kapatarak test geçirme.
15. Mevcut özellik bayraklarını ve varsayılan kapalı mekanizmaları koru.

Her geliştirmeden önce mevcut uygulamanın davranışını belirle, sonra en küçük güvenli değişikliği uygula.

---

2. HEDEF ÜRÜN MİMARİSİ

Platform aşağıdaki modüllerden oluşmalıdır:

A. Kurumsal web sitesi

- Türkçe ve İngilizce
- Mobil uyumlu
- PostgreSQL odaklı
- DBA danışmanlık hizmetleri
- Performans optimizasyonu
- Güvenlik analizi
- HA/DR danışmanlığı
- Yönetilen veritabanı hizmetleri
- Sağlık taraması
- Demo portalı
- Teklif ve iletişim

B. Müşteri portalı

- Firma doğrulaması
- Yetkili kullanıcı girişi
- Sağlık taraması
- Rapor geçmişi
- Risk karşılaştırması
- Hizmet talepleri
- Firma bazlı kullanım hakları
- Veri silme talepleri

C. Database Health Intelligence

- PostgreSQL 12–18 sürüm farkındalığı
- Kanıta dayalı kontroller
- Kural motoru
- Risk sınıflandırması
- Sağlık puanı
- Teknik bulgular
- İnsan dilinde açıklamalar
- Çözüm önerileri
- Önceki taramayla karşılaştırma
- DBA doğrulama durumu

D. Yönetim paneli

- Firma yönetimi
- Tarama yönetimi
- Rapor inceleme
- Müşteri talepleri
- Denetim kayıtları
- Sistem sağlığı
- Hizmet dönüşümü
- Yetki ve oturum yönetimi

E. Güvenli operasyon ve yayın

- CI/CD
- Ansible
- nginx
- systemd
- TLS
- Yedekleme ve geri yükleme
- Sürüm yükseltme
- Geri alma
- Loglama
- Sağlık denetimleri
- Güvenlik testleri

Bu modüller birbirini tekrar eden ayrı altyapılar oluşturmamalıdır. Ortak kimlik doğrulama, veri erişim, kanıt ve audit bileşenleri mümkün olduğunca yeniden kullanılmalıdır.

---

3. MODÜL 1 — UYGULAMA GÜVENLİĞİ

Öncelik: P0

İlk geliştirme güvenlik sertleştirmesidir.

3.1 Dosya yükleme güvenliği

"/api/tarama/yukle" uç noktasını incele.

Şu kontrolleri gerçekleştir:

- Maksimum istek boyutu
- Maksimum dosya boyutu
- İzin verilen içerik biçimleri
- JSON şema ve tip doğrulaması
- Maksimum iç içe nesne derinliği
- Maksimum liste ve nesne elemanı sayısı
- Maksimum metin alanı uzunluğu
- Bellek kullanım sınırı
- İşlem zaman aşımı
- Güvenli geçici dosya kullanımı
- Dosya yolu manipülasyonu önleme
- Yinelenen yükleme kontrolü
- Firma bazlı yükleme kotası
- Kullanıcı ve IP bazlı hız sınırı

Tarama verisini güvenilmeyen girdi kabul et.

SQL metinleri, komutlar veya rapor alanları hiçbir zaman yürütülmemelidir.

3.2 Firma izolasyonu

Her kaydı "firm_id" ile ilişkilendir.

Firma bazlı bütün veri erişimlerinde yetki denetimi uygula.

Aşağıdaki erişimler engellenmelidir:

- Başka firmanın taramasını görüntüleme
- Başka firmanın raporunu indirme
- Başka firmanın hakkını değiştirme
- Başka firmanın talebini görüntüleme
- Tahmin edilen ID ile veri erişimi

Yalnızca arayüz filtresiyle yetinme. Yetki kontrolü sunucu veri erişim katmanında zorunlu olsun.

3.3 Kimlik doğrulama

Mevcut parola + TOTP sistemini koru.

Şunları incele ve eksik olanları geliştir:

- Parolaların güçlü ve tuzlu türetme yöntemiyle saklanması
- Giriş denemesi sınırlaması
- Oturum süresi
- Oturum yenileme
- Çıkışta oturum iptali
- Secure, HttpOnly ve uygun SameSite çerezleri
- CSRF koruması
- TOTP tekrar kullanımının engellenmesi
- Yetki değişikliğinde oturum geçersizleştirme
- Şüpheli girişlerin audit kaydı

3.4 Rapor güvenliği

"/rapor/<token>/" mekanizmasını incele.

- Kriptografik güvenli token
- Süre sonu
- Token iptali
- Yetkili erişim
- İsteğe bağlı tek kullanımlık erişim
- Hassas veri maskeleme
- "Cache-Control: no-store"
- "Referrer-Policy: no-referrer"
- Token içermeyen erişim logları
- Süresi dolmuş raporların silinmesi

Token hiçbir zaman uygulama loguna açık yazılmamalı.

3.5 Denetim kayıtları

Mevcut SHA-256 zincirini koru.

Şunları ekle:

- Kullanıcı
- Firma
- İşlem
- İşlem zamanı
- Hedef kayıt
- Sonuç
- Güvenli istemci kimliği
- Zincir doğrulama durumu

SHA-256 zincirinin tek başına yetkili bir saldırganın tüm geçmişi yeniden yazmasını önlemediğini dikkate al.

Zincir başlıklarının bağımsız bir sistemde korunması veya anahtarlı doğrulanması için güvenli, yapılandırılabilir bir tasarım geliştir.

Kabul kriteri: Yetkisiz firma erişimi, CSRF, oturum atlatma ve bozuk dosya yükleme testleri başarısız erişimle sonuçlanmalıdır.

---

4. MODÜL 2 — VERİ GİZLİLİĞİ VE SAKLAMA

Öncelik: P0

Mevcut firma adı, e-posta ve tarama verilerinin nasıl saklandığını incele.

Aşağıdaki veri sınıflarını tanımla:

- Kişisel iletişim bilgileri
- Firma bilgileri
- Teknik tarama verileri
- Potansiyel hassas metadata
- Raporlar
- Audit kayıtları
- Oturum ve doğrulama verileri

Her veri sınıfı için yapılandırılabilir saklama politikası oluştur.

Varsayılan saklama sürelerini hukuki olarak onaylanmış değerler gibi sunma.

Önerilen işlevler:

- Süresi dolan raporları silme
- Müşteri talebiyle rapor silme
- Firma kapatma ve silme iş akışı
- Silme işlemini audit'e kaydetme
- Yedeklerden silme politikasını açıklama
- Gizlilik bildirimi
- Veri minimizasyonu
- Gizli alanları loglardan maskeleme

KVKK aydınlatma metni ve politikalar hukuki onay gerektiren taslaklar olarak hazırlanmalı.

Kabul kriteri: Silinen rapora API, doğrudan bağlantı veya eski token üzerinden erişilememeli.

---

5. MODÜL 3 — POSTGRESQL HEALTH INTELLIGENCE v2

Öncelik: P1

Mevcut "tarama/" modülünü geliştir.

Sıfırdan yeni tarama motoru yazma.

Mevcut katalog, toplayıcı ve kural sistemini yeniden kullan.

5.1 Sürüm farkındalığı

PostgreSQL 12, 13, 14, 15, 16, 17 ve 18 sürümlerini kapsayan bir capability matrisi oluştur.

Her kontrol şu bilgileri içersin:

- Kural ID
- Kategori
- Desteklenen sürümler
- Gerekli yetki
- Gerekli veri alanları
- Kontrolün açıklaması
- Risk seviyesi
- Kanıt koşulu
- Öneri
- Doğrulama durumu

Sürümde bulunmayan özellik için sorgu çalıştırma.

Veri yoksa yanlış şekilde PASS üretme.

Durumlar:

- PASS
- FAIL
- WARNING
- UNKNOWN
- NOT_APPLICABLE
- UNAVAILABLE

5.2 Analiz kategorileri

Güvenlik

- Superuser hesapları
- Rol yetkileri
- PUBLIC erişimleri
- Schema ACL
- Varsayılan yetkiler
- HBA yapılandırması
- TLS durumu
- Güvensiz ayarlar

Performans

- Cache kullanım göstergeleri
- I/O istatistikleri
- Geçici dosyalar
- Bağlantı tüketimi
- Uzun işlemler
- Lock göstergeleri
- pg_stat_statements erişilebilirliği
- Sorgu maliyetine dair mevcut kanıtlar

Bakım

- Autovacuum
- Dead tuple
- Transaction ID wraparound riski
- Freeze yaşı
- Analyze durumu
- Invalid index
- Kullanılmayan indeks göstergeleri

Kapasite

- Database boyutu
- Tablo ve indeks boyutları
- Büyüme geçmişi
- Bağlantı baskısı
- Disk kapasitesi — ancak host kanıtı varsa
- RAM ve CPU kapasitesi — ancak host kanıtı varsa

HA/DR

- Streaming replication
- Replication lag
- Replication slot
- WAL birikimi
- Synchronous replication
- Patroni durumu — yalnızca kanıt varsa
- Failover geçmişi — yalnızca kanıt varsa

Backup

- Backup yapılandırma kanıtı
- WAL arşivleme
- PITR ön koşulları
- Son başarılı yedek kanıtı
- Restore testi doğrulaması

Bir restore testi yapılmamışsa başarılı diye raporlama.

5.3 Kanıt modeli

Her bulgu aşağıdaki ortak veri modeline göre temsil edilmeli:

{
  "rule_id": "PG-CONFIG-001",
  "category": "configuration",
  "status": "WARNING",
  "severity": "HIGH",
  "confidence": "HIGH",
  "observed_value": "1000",
  "expected_value": "workload_dependent",
  "source": "pg_settings",
  "collected_at": "UTC_TIMESTAMP",
  "explanation": "Bağlantı limiti kapasiteyle birlikte değerlendirilmelidir.",
  "impact": "Bellek ve bağlantı baskısı riski",
  "recommendation": "Gerçek eşzamanlı kullanım ve bağlantı havuzu ölçülmeli.",
  "requires_dba_approval": true
}

Bu nesne örnek şemadır; mevcut veri modeliyle uyumlu hale getir.

Kanıt yoksa değer uydurma.

5.4 Sağlık puanı

0–100 arası açıklanabilir sağlık puanı oluştur.

Kategori bazında puan hesapla.

- Güvenlik
- Performans
- Konfigürasyon
- Bakım
- HA/DR
- Backup
- Kapasite

Ancak UNKNOWN veya UNAVAILABLE durumlarını başarılı kabul etme.

Sağlık puanını kanıt kapsamı ile birlikte göster.

Örnek:

- Sağlık puanı: 72/100
- Kanıt kapsamı: %64
- Kritik bulgu: 2
- Yüksek bulgu: 4

Puanlama katsayılarını yapılandırılabilir ve test edilebilir yap.

5.5 Geçmiş karşılaştırması

Aynı firmaya ve aynı veritabanı kimliğine ait taramaları karşılaştır.

Şu durumları oluştur:

- NEW
- PERSISTING
- RESOLVED
- REGRESSED
- UNKNOWN

Kaybolan kanıtı çözülmüş problem olarak işaretleme.

Yeni raporda şunlar gösterilsin:

- Önceki sağlık puanı
- Yeni sağlık puanı
- Yeni riskler
- Çözülen riskler
- Devam eden riskler
- Kanıt kapsamı değişimi

---

6. MODÜL 4 — MÜŞTERİ PORTALI

Öncelik: P1

Mevcut "/demo/" arayüzünü incele.

Demo mantığını gerçek müşteri portalına dönüştürürken mevcut demoyu koru.

Önerilen rota:

"/portal/"

Özellikler:

1. Firma hesabı doğrulama
2. Güvenli kullanıcı girişi
3. Firma profili
4. Sağlık taraması yükleme
5. Tarama geçmişi
6. Sağlık puanı
7. Kategori bazlı riskler
8. Rapor görüntüleme
9. Rapor silme
10. Hizmet talebi oluşturma
11. Kullanım hakkını görüntüleme
12. Hesap ve verilerin silinmesini talep etme

Firma kullanıcısı ile platform yöneticisinin yetkilerini birbirinden ayır.

Başka firmaya erişim kesinlikle engellensin.

Firma e-posta doğrulamasını güvenli, tek kullanımlık ve süreli token ile tasarla.

Henüz e-posta gönderim sağlayıcısı seçilmediğinden gönderim katmanı soyutlanmalı. Canlıda doğrulama, gerçek ve güvenilir gönderim altyapısı kurulmadan etkinleştirilmemeli.

---

7. MODÜL 5 — KURUMSAL WEB SİTESİ VE UX/UI

Öncelik: P1

Varsayılan C temasını koru ve geliştir.

Marka kimliği:

- Marka: alig.tech
- Konumlandırma: Database Health & DBA Services
- Ana hedef: Kurumsal veritabanı müşterileri
- Dil: Türkçe öncelikli, İngilizce destekli
- Ton: Profesyonel, güven veren, teknik olarak doğru
- Görsel yaklaşım: Modern, sade, yüksek kaliteli

Ana başlık önerisi:

Veritabanınızın risklerini sorun oluşmadan keşfedin.

Alt açıklama:

PostgreSQL performans, güvenlik ve operasyonel sağlık analizi. Kanıta dayalı bulgular, anlaşılır raporlar ve uzman DBA desteği.

Ana sayfaya aşağıdaki bölümleri ekle:

1. Hero ve ana çağrı
2. Temel hizmetler
3. Sağlık taraması nasıl çalışır?
4. Güvenlik ve veri gizliliği yaklaşımı
5. Örnek sağlık raporu
6. DBA danışmanlığı
7. Yönetilen hizmetler
8. Sık sorulan sorular
9. İletişim ve teklif talebi

Hizmet kartları:

- PostgreSQL Health Check
- Performance Optimization
- PostgreSQL Security Assessment
- High Availability & Disaster Recovery
- Database Migration
- Database Consulting
- Managed Database Services

Doğrulanmayan SLA, referans, sertifika, başarı oranı veya müşteri sayısı yayımlama.

Tasarım koşulları:

- Responsive
- Mobile-first
- Semantik HTML
- Klavye erişilebilirliği
- Görünür odak durumu
- Yeterli kontrast
- Yerel fontlar
- Harici kaynak olmadan çalışma
- İyi sayfa performansı
- SEO başlıkları
- Canonical URL
- TR/EN hreflang
- Sitemap
- Robots.txt
- Yapılandırılmış veri — yalnızca doğrulanmış gerçek bilgilerle

Logo geçiciyse mevcut logo altyapısını koru, onaylanmamış yeni markayı kesinleştirme.

---

8. MODÜL 6 — YÖNETİM PANELİ

Öncelik: P1

Mevcut "/yonetim/" panelini geliştir.

Mevcut firma, tarama, talep ve audit özelliklerini koru.

Önerilen gösterge paneli:

Firma istatistikleri

- Toplam firma
- Aktif firma
- Doğrulanmış firma
- Son 30 gündeki yeni firmalar

Tarama istatistikleri

- Toplam tarama
- Son 7 gün
- Son 30 gün
- Başarısız taramalar
- Kritik bulgu içeren taramalar

Operasyon

- Bekleyen müşteri talepleri
- Hata veren işler
- Depolama kullanımı
- Servis sağlık durumu
- Audit bütünlüğü

Ticari süreç

- Yeni potansiyel müşteri
- Ön değerlendirme tamamlandı
- DBA incelemesi talep edildi
- Teklif hazırlandı
- Teklif gönderildi
- Kazanıldı
- Kaybedildi

Müşteri CRM modülünü gereksiz karmaşık hale getirme.

Başlangıçta basit durum makinesi ve notlar yeterli.

---

9. MODÜL 7 — TARAMA İŞ KUYRUĞU

Öncelik: P1

HTTP isteği içinde uzun analiz çalıştırma.

Mevcut tarama servisini incele.

Gerekliyse SQLite tabanlı kalıcı bir iş kuyruğu oluştur.

İş durumları:

- QUEUED
- RUNNING
- COMPLETED
- FAILED
- EXPIRED
- CANCELLED

Her iş için:

- Job ID
- Firm ID
- Scan ID
- Oluşturulma zamanı
- Başlama zamanı
- Bitiş zamanı
- Durum
- Hata sınıfı
- Yeniden deneme sayısı
- İlerleme durumu

İşler ayrı, kısıtlı worker sürecinde yürütülmeli.

Gereksinimler:

- Eşzamanlı işlem sınırı
- Kaynak kullanımı sınırı
- Güvenli yeniden deneme
- Çift çalıştırmayı önleme
- Servis yeniden başlatıldıktan sonra toparlanma
- İdempotent durum geçişleri
- Hata sınıflandırması
- Denetim kaydı

Bir tarama başarısız olduğunda müşteri, gizli teknik bilgileri görmeden anlaşılır hata almalı.

---

10. MODÜL 8 — RAPORLAMA

Öncelik: P1

Raporlar iki görünüm sunmalı.

Yönetici özeti

Teknik olmayan müşteri yöneticisinin anlayacağı şekilde:

- Genel sağlık durumu
- En önemli riskler
- Olası iş etkisi
- Yapılması gerekenler
- Öncelik sırası
- Önceki taramaya göre değişim

Teknik DBA raporu

- Kaynak
- Ölçüm
- Bulgular
- Kanıt güven düzeyi
- Etkilenen veritabanı
- Risk seviyesi
- Detaylı açıklama
- Önerilen iyileştirme
- Değişiklik ön koşulları
- Doğrulama yöntemi

Rapor dili doğal Türkçe olmalı.

Örnek kötü anlatım:

"max_connections HIGH WARNING."

Doğru anlatım:

"PostgreSQL üzerinde tanımlı bağlantı limiti, mevcut iş yükü ve bellek kapasitesiyle birlikte değerlendirilmelidir. Yalnızca bu ayar üzerinden bellek yetersizliği olduğu sonucuna varılamaz."

Raporda kesin kanıt ile hipotezi açıkça ayır.

---

11. MODÜL 9 — SQL SERVER DESTEĞİ

Öncelik: P2

Mevcut ön sürüm kodlarını koru.

"ALIG_MSSQL=1" özelliğini gerçek entegrasyon testleri başarılı olmadan canlıda açma.

Sınanacak alanlar:

- SQL Server sürümü
- Yetki kontrolleri
- Veritabanı durumu
- Backup bilgisi
- Database dosyaları
- Wait statistics
- Memory pressure göstergeleri
- Blocking
- Index göstergeleri
- TempDB
- Always On — varsa ve gerekli kanıt mevcutsa

Desteklenen platform ve sürümlere göre capability tablosu oluştur.

PostgreSQL ile SQL Server'a ait veritabanı özelliklerini aynıymış gibi değerlendirme.

İki motorun rapor çıktısında ortak üst seviye kanıt modelini kullan.

---

12. MODÜL 10 — LLM RAPOR ÖZETİ

Öncelik: P2

İsteğe bağlı modül olarak tasarla.

Varsayılan kapalı olsun.

LLM aşağıdaki işlemleri yapabilir:

- Teknik bulguyu anlaşılır Türkçeye dönüştürme
- Yönetici özeti hazırlama
- Riskleri öncelik sırasına göre anlatma
- DBA önerilerini sadeleştirme
- Teknik rapordan kısa yönetim notu üretme

LLM aşağıdaki işlemleri yapamaz:

- Kanıt üretme
- Olmayan metrik yazma
- Otomatik SQL çalıştırma
- Veritabanı değiştirme
- Risk puanını bağımsız değiştirme
- Kanıt olmadan kök neden kesinleştirme
- Gizli müşteri verisini izinsiz dış servise gönderme

Olası sağlayıcı entegrasyonu ayrı arayüz üzerinden kurulmalı.

Yalnızca Python standart kütüphanesiyle iletişim kurabilecek şekilde tasarla.

LLM servisi yoksa deterministik, şablon tabanlı rapor üretimi eksiksiz çalışmaya devam etmeli.

---

13. MODÜL 11 — KİP B DOĞRUDAN BAĞLANTI

Öncelik: P3

Mevcut varsayılan kapalı durumu koru.

"ALIG_DOGRUDAN=1" tek başına üretim güvenliği için yeterli kabul edilmemeli.

Önce tehdit modeli oluştur.

Özellikle şu riskleri incele:

- SSRF
- İç ağ keşfi
- Keyfi hedef bağlantısı
- DNS rebinding
- Kimlik bilgisi sızıntısı
- TLS doğrulama hataları
- Yetki yükseltme
- Komut enjeksiyonu
- Kaynak tüketimi
- Bağlantı zaman aşımı
- Ağ izolasyonu
- Yetkisiz veri toplama

Kip B yalnızca açık firma onayı, doğrulanmış hedef, asgari yetkili veritabanı hesabı ve kontrollü ağ erişimiyle kullanılabilmelidir.

Üretim için tehdit modeli, entegrasyon testleri ve güvenlik onayı tamamlanmadan etkinleştirme.

---

14. MODÜL 12 — CANLIYA ALMA VE OPERASYON

Öncelik: P0

Mevcut Ansible, nginx ve systemd dosyalarını incele.

Şunları doğrula:

- Ayrı servis kullanıcıları
- Minimum dosya yetkileri
- TLS ve güvenli HTTP başlıkları
- Gizli anahtar yönetimi
- Güvenli oturum çerezleri
- Servis izolasyonu
- Reverse proxy sınırları
- İstek boyutu sınırı
- Dosya depolama izinleri
- SQLite WAL uyumluluğu
- Yedekleme
- Geri yükleme testi
- Deploy
- Rollback
- Sağlık denetimleri
- Log rotasyonu
- Disk doluluk kontrolleri
- Servis yeniden başlatma
- İzleme ve alarm koşulları

Canlı sunucu erişimi yoksa gerçek üretim testini tamamlanmış gibi raporlama.

Dry-run, syntax check ve gerçek deployment doğrulamasını ayrı göster.

---

15. TEST VE KALİTE STANDARDI

Her modül için aşağıdaki test türlerini uygula:

1. Birim testleri
2. API entegrasyon testleri
3. Negatif güvenlik testleri
4. Firma izolasyon testleri
5. Yetki kontrolü testleri
6. Hatalı yükleme testleri
7. TR/EN eşlik testleri
8. Eski işlevlerle uyumluluk testleri
9. Veri silme testleri
10. Tarama sonuçlarının doğruluk testleri
11. Yedekleme/geri yükleme testleri
12. Dağıtım ve geri alma testleri

Mevcut test sayısını düşürme.

Testleri şu komutla çalıştır:

python3 ci/run_all.py --theme c
python3 -m unittest discover -s tests

Sürüm yayını için:

python3 ci/run_all.py --theme c --release

"--release" başarısızsa yayın başarılı deme.

Test başarısını, testlerin gerçekten çalıştığını gösteren çıktılarla kanıtla.

Gerçek PostgreSQL veya SQL Server erişimi yoksa entegrasyon testini SKIPPED olarak bildir.

---

16. UYGULAMA SIRASI

Geliştirmeyi aşağıdaki sırada gerçekleştir.

FAZ 0 — Mevcut sistem analizi

Kaynak kodu, mimariyi, testleri, güvenlik sınırlarını, mevcut rotaları, veri modellerini ve açık işleri incele.

Çıktı:

- Mevcut özellik matrisi
- Eksik özellikler
- Tekrar kullanılan bileşenler
- Risk listesi
- Değiştirilecek dosyalar

FAZ 1 — Güvenlik ve üretim hazırlığı

Dosya yükleme güvenliği, firma izolasyonu, kimlik doğrulama, veri saklama ve üretim sertleştirmesini tamamla.

FAZ 2 — Health Intelligence v2

Kural motorunu, kanıt modelini, sağlık puanını ve geçmiş karşılaştırmasını geliştir.

FAZ 3 — Müşteri portalı

Firma doğrulama, giriş, rapor geçmişi ve hizmet taleplerini geliştir.

FAZ 4 — Kurumsal web sitesi ve yönetim paneli

C temasını, hizmet sayfalarını, rapor görsellerini ve yönetim ekranlarını geliştir.

FAZ 5 — İş kuyruğu ve raporlama

Asenkron tarama işçisi, güvenli iş takibi, teknik ve yönetici raporlarını tamamla.

FAZ 6 — Doğrulama ve sınırlı yayın

CI, gerçek veritabanı testleri, güvenlik kontrolleri, dağıtım, geri alma ve üretim kabul testlerini tamamla.

FAZ 7 — İleri özellikler

SQL Server, isteğe bağlı LLM ve Kip B özelliklerini ayrı kabul kapılarından geçirerek geliştir.

---

17. GELİŞTİRME RAPORLAMA BİÇİMİ

Her faz sonunda aşağıdaki bilgileri ver:

A. Yapılan işler

Gerçekten uygulanan değişiklikler.

B. Değişen dosyalar

Dosya yolu ve değişiklik amacı.

C. Test sonuçları

Çalışan, başarısız ve atlanan testler.

D. Güvenlik değerlendirmesi

Kapatılan ve açık kalan riskler.

E. Uyumluluk

Mevcut sistemin hangi davranışlarının korunduğu.

F. Kalan işler

Eksik özellikler ve engeller.

G. Sonraki adım

En yüksek öncelikli geliştirme.

Durumları açık göster:

- DONE
- PARTIAL
- BLOCKED
- NOT_TESTED
- FAILED

Kod yazıldığı için özelliği DONE kabul etme.

DONE için çalışan kod, ilgili testlerin PASS olması ve kabul kriterlerinin karşılanması gerekir.

---

18. BAŞARI KRİTERLERİ

Proje aşağıdaki koşullara ulaştığında sınırlı üretim yayınına aday olabilir:

- Mevcut ana özellikler çalışıyor.
- Kritik güvenlik testleri PASS.
- Firma izolasyon testleri PASS.
- Hassas veriler yetkisiz erişime kapalı.
- Rapor saklama ve silme politikası uygulanıyor.
- En az bir gerçek PostgreSQL ortamında uçtan uca tarama doğrulanmış.
- Sağlık puanı açıklanabilir.
- Eksik kanıtlar başarılı sonuç gibi gösterilmiyor.
- Yönetim paneli güçlü şekilde korunuyor.
- Kurumsal site mobil ve erişilebilir.
- Tüm zorunlu CI kontrolleri PASS.
- Geri yükleme ve geri alma testleri doğrulanmış.
- Canlı servisler yetki sınırları içinde çalışıyor.
- KVKK ve diğer hukuki yayın gereklilikleri değerlendirilip onaylanmış.
- Açık P0 risk kalmamış.

Son talimat:

Mevcut alig.tech projesini koruyarak geliştir. Gereksiz yeniden yazım yapma. Önce sistemde zaten bulunan özellikleri tespit et; eksik veya hatalı olanları düzelt. Her yeni fonksiyonun testini ekle.

Güvenlik, veri gizliliği ve doğruluk; görsel tasarımdan ve yeni özellik sayısından önce gelir.

Önce FAZ 0 analizini gerçekleştir. Ardından P0 güvenlik ve üretim hazırlığı çalışmalarını uygula. Gerçekten doğrulanmamış hiçbir işlemi tamamlanmış olarak gösterme.