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
| 8 | P0 | Canlıya alma doğrulama raporu: sözdizimi, kuru çalıştırma ve gerçek dağıtımı ayrı gösteren denetim listesi; servis kullanıcıları, izinler, disk doluluk denetimi | `docs/runbook.md` güncel, her satır DONE ya da NOT_TESTED | **tamam** (`deploy/hazirlik.py yerel/sunucu`, bakımda disk koruması, `docs/canli-kontrol-listesi.md`; gerçek sunucu satırları NOT_TESTED) |
| 9 | P1 | Ortak kanıt modeli ve durumlar: kural kimliği, kategori, PASS, FAIL, WARNING, UNKNOWN, NOT_APPLICABLE, UNAVAILABLE, güven düzeyi, kaynak | Her denetim bir durum üretir, veri yokken PASS çıkmaz | **tamam** (`tarama/kanit.py`; PostgreSQL 17, SQL Server 20 kural, kalıcı kimlik; raporda durum tablosu TR/EN; kural listesi `docs/kural-katalogu.md` üretilir; eski motorla 20 000 rastgele belgede bulgular aynı; gerçek PostgreSQL 16 çıktısında denendi) |
| 10 | P1 | Sürüm yetenek matrisi PostgreSQL 12–18: denetim başına desteklenen sürüm ve gereken yetki; desteklenmeyen sürümde sorgu çalışmaz | Matris, toplayıcı sürüme göre atlar, test | **kod tamam, yalnız 16 sınandı** (`docs/surum-matrisi.md`; toplayıcı ve Kip B sürüme göre sorgu seçer, desteklenmeyende çalıştırmaz; `pg_hesap` ile rol eksikse kural geçemez; `tarama/surum_dogrula.py` gerçek PostgreSQL 16'da üç hesapla çalıştı. 12, 13, 14, 15, 17, 18 ikilileri indirildi ama bu ortamda çalıştırma izni çıkmadı: Ali'nin onayı ya da kendi ortamında çalıştırması bekleniyor) |
| 11 | P1 | Sağlık puanı ve kanıt kapsamı: 0–100, kategori bazında, katsayılar yapılandırılabilir | Bilinmeyen durum puanı yükseltmez, test | **tamam** (`tarama/puan.py`; her kural bir risk düzeyi taşır, puan risk ağırlıklı kredi oranı; UNKNOWN ve UNAVAILABLE FAIL kadar puan kaybettirir, NOT_APPLICABLE hesaba girmez; kanıt kapsamı ayrı ve her yerde puanla birlikte; raporda kategori tablosu ve puanı düşüren denetimler (bulgu ve kanıt eksikliği ayrı); panelde Puan sütunu ve Sistem sayfasında etkin katsayılar; `ALIG_PUAN_AYARI` ile JSON katsayı dosyası, geçersizse iki servis de başlamaz; 800 rastgele belgede kanıt silmek puanı hiç artırmadı, 26 mutasyonun 24'ü yakalandı, kalan 2'si eşdeğerdi ve gereksiz kod kaldırıldı) |
| 12 | P1 | Katalog genişletme: replikasyon gecikmesi, wraparound ve freeze yaşı, autovacuum, `pg_stat_statements` erişilebilirliği, geçici dosyalar | Kural, test, gerçek PostgreSQL 16 denemesi | **tamam** (6 yeni kural: PG-MAINT-006 autovacuum ve track_counts, PG-MAINT-007 tablo düzeyinde kapatılmış autovacuum, PG-MAINT-008 multixact yaşı, PG-HA-002 replikasyon gecikmesi (süre ve bayt), PG-PERF-002 pg_stat_statements, PG-PERF-003 geçici dosyalar. Gerçek PostgreSQL 16'da birincil ve akışlı yedekle denendi; yedekte slot sorgusu hata veriyordu, düzeltildi, artık bütün sorgular yedekte çalışıyor. Yedekte ölü satır kuralı veri yokken temiz çıkıyordu: tablo istatistiğine ve arşivlemeye dayanan 3 kural yedekte Uygulanmaz. 22 mutasyonun hepsi yakalandı) |
| 13 | P1 | Geçmiş karşılaştırması: NEW, PERSISTING, RESOLVED, REGRESSED, UNKNOWN; kaybolan kanıt çözülmüş sayılmaz | Veritabanı kimliği, karşılaştırma, test | **tamam** (`tarama/gecmis.py`; veritabanı kimliği: küme tanımlayıcısının SHA-256 özeti (`pg_kume_kimligi`, ham değer sunucudan çıkmaz) ve sunucu rolü; aynı firmanın aynı kimlikli, daha önceki, doğrulanmış ve süresi dolmamış raporuyla kural kural karşılaştırma; önceki sorun bu taramada kanıtsızsa UNKNOWN, önceki taramada kanıt yoksa yeni sayılmaz; raporda ve panelde önceki ve yeni puan, kapsam değişimi, değişim tablosu; görüntüleme denetim kaydına karşılaştırılan raporla yazılır; gerçek PostgreSQL 16'da birincil ve yedek aynı küme özetini, farklı rolü verdi. Saklama süresi dolan raporla karşılaştırma yapılmaz: uzun dönem geçmiş Ali'nin saklama kararını bekliyor) |
| 14 | P1 | Rapor: yönetici özeti ve teknik rapor görünümleri, yazdırma düzeni | TR ve EN, kanıt ile yorum ayrı | **tamam** (`?gorunum=yonetici` ya da `?gorunum=teknik`, varsayılan teknik; yönetici özeti yalnız kural çıktısından, dil modeli yok; bulgu kartında Kanıt ve Yorum ayrı blok; kanıtı eksik tarama “temiz” denmez; yazdırma düzeni tema C'de, `tests/test_rapor_gorunum.py`) |
| 15 | P1 | E-posta doğrulamasının gönderimden bağımsız kısmı: tek kullanımlık süreli kod, takılabilir gönderici | Gönderici yokken canlıda açılmaz | **kod tamam, kapalı** (rapor bağlantısı yalnız e-postayla, giden kutusu + `alig-posta` servisi, SMTP yalnız TLS; açmak için SMTP sağlayıcısı ve gönderen adres Ali'den) |
| 16 | P1 | Müşteri portalı 1: giriş, firma izolasyonu veri erişim katmanında, izolasyon testleri | Başka firmanın kaydına tahmin edilen kimlikle erişilemez | **kod tamam, kapalı** (`/portal/`, `ALIG_PORTAL=1` ve e-posta doğrulaması gerekir; kayıt, tek kullanımlık süreli e-posta kodu, giriş, oturum, firma kapsamlı `Kapsam`, rapor listesi ve görüntüleme, `tests/test_portal.py`; parola sıfırlama yok: canlıya açmadan önce eklenmeli; gerçek SMTP ile denenmedi) |
| 17 | P1 | Müşteri portalı 2: tarama geçmişi, rapor silme, hizmet talebi, kullanım hakkı, veri silme talebi | TR ve EN, test | **kod tamam, kapalı** (geçmiş tablosunda önceki taramaya göre puan değişimi; rapor silme onay sayfası ve form koduyla, firma kapsamlı; ücretsiz tarama hakkı ve yenilenme tarihi; hizmet talebi; silme talebi yalnız kayıt; panelde Portal talepleri; `tests/test_portal.py`, `tests/test_yonetim.py`; talep e-postası otomatik gitmez) |
| 18 | P1 | Ana sayfa: hizmet kartları, "nasıl çalışır", güvenlik yaklaşımı, SSS | Kanıtsız iddia yok, boyut bütçesi içinde | **tamam** (7 hizmet kartı, sağlık taraması adımları, SSS; müşteri, SLA, sertifika, başarı oranı iddiası yok) |
| 19 | P1 | Örnek rapor sayfası: test verisinden üretilmiş ve öyle etiketlenmiş | Sayfa, i18n, test | bekliyor |
| 20 | P1 | Yönetim paneli: gösterge sayıları ve ticari süreç durumları (basit durum makinesi ve not) | Test | bekliyor |
| 21 | P1 | İş kuyruğu: yalnızca doğrudan bağlantı için, SQLite tabanlı, ayrı işçi | Durum geçişleri idempotent, yeniden başlatmada toparlanır | bekliyor |
| 22 | P2 | SQL Server: yetenek tablosu ve gerçek sunucu çıktısına göre düzeltme | Ali'nin gönderdiği `ok` / `ATLANDI` listesi | Ali'yi bekliyor |
| 23 | P2 | LLM rapor özeti: varsayılan kapalı, kanıt üretemez, puanı değiştiremez | Sağlayıcı yokken rapor aynen çalışır | bekliyor |
| 24 | P3 | Kip B kalanları: istek listesi panelde, sunucu sertifikası doğrulaması, yanıt süresini sabitleme, kılavuz bölümü (`channel_binding=require` yapıldı) | Ayrı kabul kapısı | bekliyor |

Kod incelemesinden (`docs/kod-inceleme.md`) gelen açık maddeler:

| # | Öncelik | Madde | Bitti sayılır | Durum |
| --- | --- | --- | --- | --- |
| 25 | P1 | Toplayıcı bağlanabildiği tüm veritabanlarını dolaşsın; tablo, indeks ve sequence bulguları veritabanı adıyla (Y4) | Gerçek kümede iki veritabanı, ikisindeki bulgu da raporda | **tamam** (en çok 50 veritabanı, atlananlar nedenleriyle; gerçek PostgreSQL 16'da boşluklu adlı ve yetkisiz veritabanıyla denendi) |
| 26 | P1 | Firma silmede iletişim taleplerini de silme seçeneği; KVKK silme talebi tek işlemde (O7) | Test, denetim kaydı | **tamam** (firma silme formunda seçenek; önce talepler, sonra firma) |
| 27 | P1 | Maskeli taramada eşleme dosyası yalnız müşteri tarafında yazılsın, yüklenmesin (O8) | Toplayıcı testi | **tamam** (`<çıktı>-maske.json`, 0600, yüklenirse reddedilir) |
| 28 | P2 | İş eylemi ve denetim kaydı aynı işlemde; firma eşitleme tek işlemde ve yalnız yeni talepler için (O10, O11) | Test | **tamam** (`depo.islem`; çapraz dosya işlemleri sıralı: form.sqlite ile yonetim.sqlite tek işlemde olamaz) |
| 29 | P2 | Toplayıcı: bağlantı dizgisinde kaçış, şifresiz bağlantıda uyarı (D5, D6) | Test | **tamam** |
| 30 | P2 | Küçükler: talep listesi sayfalama, firma kimliği yeniden kullanılmasın, tünel kipinde CSP, sınır metni sabitten, TOTP girişinde kilit (D7–D11) | Test | **tamam** |

## Varsayılanla ilerleyenler (onay bekliyor, engellemiyor)

| Konu | Varsayılan | Nerede değişir |
| --- | --- | --- |
| Ücretsiz tarama sınırı | Şirket başına 30 günde 2 | `tarama/depo.py` `SINIR_ADET`, `SINIR_GUN` |
| Rapor saklama | 30 gün | `ALIG_SAKLAMA_RAPOR_GUN` (`tarama/saklama.py`) |
| Firma kaydı saklama | Son etkinlikten 365 gün sonra, etkin raporu yoksa silinir | `ALIG_SAKLAMA_FIRMA_GUN` (`tarama/saklama.py`) |
| İletişim talebi saklama | Oluşturulmadan 365 gün sonra silinir | `ALIG_SAKLAMA_TALEP_GUN` (`tarama/saklama.py`) |
| Kip B parola | Saklanmaz, her taramada sorulur | tasarım kararı |
| Kip B sınırları | İstek 30 dk, 3 deneme, saatte 5 istek, aynı anda 2 tarama | `tarama/depo.py` `ISTEK_*`, `tarama/calistirici.py` |
| Kip B kimlik | E-posta doğrulaması yerine yönetici izni | panel, firma ayrıntısı |
| Doğrudan bağlantı ve SQL Server | Kapalı | `ALIG_DOGRUDAN`, `ALIG_MSSQL` |
| Müşteri portalı | Kapalı; e-posta doğrulaması açık değilse açılmaz | `ALIG_PORTAL`, `musteri_portali` |
| Portal girişi | E-posta + parola (en az 12 karakter), ikinci faktör yok; aynı kurumsal alan adı aynı firma | `tarama/portal_depo.py` |
| Portal hizmet talebi | Firma başına günde en çok 5; konu 120, mesaj 2000 karakter; türler: denetim, destek, diğer | `tarama/portal_depo.py` |
| Portal silme talebi | Yalnız kayıt; kimlik doğrulaması ve silme yönetici işlemi; firma başına tek açık talep | panel, Portal talepleri |
| Portal giriş sınırları | E-posta başına 5, IP başına 10 hatalı deneme / 15 dk; oturum 30 dk boşta, en çok 8 saat; doğrulama kodu 24 saat | `tarama/portal_depo.py` |
| Kanıt modeli: önemden duruma eşleme | Kritik ve yüksek FAIL; orta, düşük ve bilgi WARNING | `tarama/kanit.py` `BULGU_DURUMU` |
| Kanıt modeli: kural kategorisi ve güven düzeyi | Kural başına seçildi, liste `docs/kural-katalogu.md` | kural tanımı (`tarama/kurallar.py`, `tarama/kurallar_mssql.py`) |
| Kısmi veritabanı kapsamı | Bir veritabanı bile taranmadıysa veritabanı başına kurallar UNKNOWN (bulgu varsa FAIL/WARNING). Yönetilen hizmetlerin iç veritabanları (ör. bağlanılamayan sistem veritabanı) da sayılır | `tarama/kanit.py` `_tam_kapsam` |
| Arşivleme açık ama başarılı arşiv kaydı yok | UNKNOWN (arşivlemenin çalıştığına dair kanıt yok) | `tarama/kurallar.py` PG-BACKUP-001 |
| Sürüm aralığı | 12–18; 12 altında yalnız sürüm ve hesap denetimi çalışır, 18 üstünde ana sorgular çalışır | `tarama/katalog.py` `SURUM_ALT`, `SURUM_UST`, denetim başına `en_az` |
| Sınanmamış sürümde güven | Gerçek sunucuda sınanmayan sürümde kanıt güveni en çok MEDIUM | `tarama/kanit.py` `SINANMAMIS_SURUM_TAVANI`, `katalog.SINANAN` |
| Sağlık puanı katsayıları | Ağırlık: kritik 10, yüksek 6, orta 3, düşük 1, bilgi 0. Uyarı kredisi: orta 0,5, düşük 0,75, bilgi 1. Kategori çarpanı 1 | `ALIG_PUAN_AYARI` (JSON dosyası, `docs/runbook.md`); `tarama/puan.py` `VARSAYILAN` |
| Kural risk düzeyi | Kuralın üretebileceği en yüksek bulgu önemi (test denetler) | kural tanımı (`tarama/kurallar.py`, `tarama/kurallar_mssql.py`) |
| Replikasyon gecikmesi | 60 sn ya da 1 GB orta, 600 sn ya da 16 GB yüksek; akışta olmayan replika orta; pg_basebackup bağlantısı replika sayılmaz; süre gecikmesi boşsa (yetişmiş replika) bayt gecikmesine bakılır | `tarama/kurallar.py` PG-HA-002, `MUHENDISLIK` |
| Geçici dosyalar | Günde 10 GB düşük, 100 GB orta; ölçüm penceresi en az 1 gün sayılır; istatistik başlangıcı bilinmiyorsa bilgi (puan düşürmez) | `tarama/kurallar.py` PG-PERF-003 |
| pg_stat_statements | Yüklü değilse ya da `pg_stat_statements.track` none ise düşük önemli bulgu | `tarama/kurallar.py` PG-PERF-002 |
| Yedek sunucuda değerlendirilmeyen kurallar | PG-MAINT-003, PG-MAINT-005, PG-BACKUP-001 yedekte Uygulanmaz; sunucunun rolü okunamazsa bu kurallar Geçti olamaz | kural tanımında `birincil=True` |
| Geçmiş karşılaştırmasının kapsamı | Aynı firma, aynı küme özeti ve aynı rol (birincil birincille); yalnız saklama süresi dolmamış, doğrulanmış raporlar; aynı tarama zamanı (aynı dosya) karşılaştırılmaz; aynı kümenin birden çok yedeği birbirinden ayrılmaz; SQL Server için kimlik yok | `tarama/gecmis.py`, `tarama/depo.py` `onceki_rapor` |
| Puanın gösterimi | Aşağı yuvarlanır: 100 yalnız kayıp yoksa, %100 kapsam yalnız her kuralın kanıtı varsa. Puana giren kuralların hiçbirinde kanıt yoksa "hesaplanamadı". Puan saklanmaz, rapor her açıldığında etkin katsayılarla hesaplanır | `tarama/puan.py` |

## Engelleyen kararlar (Ali)

| Karar | Neyi engelliyor |
| --- | --- |
| E-posta gönderim yöntemi (sağlayıcı ya da kendi sunucu) | Kayıt e-postası, firma doğrulamasının gönderimi, Kip B'nin genel açılışı |
| Barındırma sağlayıcısı, sunucu IP adresi, sabit çıkış IP | Canlıya alma, Kip B için müşteri güvenlik duvarı izni |
| Hukuki metinler: KVKK aydınlatma, kullanım koşulları, Kip B bağlantı onayı | Canlıya alma |
| Gerçek iletişim e-postası ve şirket bilgileri | Sürüm etiketi (`--release` denetimi) |
| SQL Server'ın gerçek sunucuda denenmesi | SQL Server taramasının yayımlanması |
| Rapor silindikten sonra karşılaştırma için özet (puan ve denetim durumları, nesne adı yok) saklanması ve süresi; KVKK metnine girmesi | Saklama süresinden (30 gün) eski taramayla karşılaştırma |
| Logo ve arka plan görselleri | Tasarımın son hâli |
