# PostgreSQL'e geçiş (ALIG-DB-001)

Kaynak: `docs/master-prompt-v5.md` (v4.1'i içerir). Bu belge mimari ve göç planıdır. Şema ve roller (ALIG-DB-003a) `db/` altında yazıldı ve PostgreSQL 16'da sınandı; uygulama kodu hâlâ SQLite kullanır.
Durum sütunlarındaki PASS yalnız gerçek PostgreSQL üzerinde çalıştırılmış testler için yazılır.

Hedef: uygulamanın tüm kalıcı verisi tek bir PostgreSQL 18 veritabanında (`aligtech`). SQLite'a geri düşme (fallback) yok:
PostgreSQL erişilemezse yazma işlemleri kontrollü hatayla durur. Müşterilerin taranan PostgreSQL sunucuları bu
veritabanından ayrı güvenlik alanıdır; tarama toplayıcısı (`alig-toplayici.py`, `psql` ile) bu geçişten etkilenmez.

## 1. Mevcut durum (envanter, 2026-11-15, commit 1569edd)

| Kaynak | Dosya | Tablolar | Kod |
| --- | --- | --- | --- |
| Tarama veritabanı | `tarama.sqlite` | rapor, denetim (SHA-256/HMAC zinciri), kullanim (kota), firma, firma_silinen, baglanti_istegi, posta (giden kutusu), esitleme, portal_kullanici, portal_kod, portal_oturum, portal_deneme, portal_talep | `tarama/depo.py` (688 satır), `tarama/portal_depo.py` |
| Yönetim veritabanı | `yonetim.sqlite` | kullanici (scrypt parola, TOTP sırrı, TOTP sayacı), oturum (kodun SHA-256 özeti), giris_denemesi, giris_ip, talep_durum, denetim (zincir) | `yonetim/depo.py`, `yonetim/server.py` |
| İletişim formu | `form.sqlite` | contact | `form/server.py` |
| Yedek ve bakım | — | SQLite backup API, bütünlük denetimi, geri yükleme | `deploy/bakim.py` |
| Hız sınırı | bellek içi | — | `form/server.py` `RateLimiter` |

`firma_yeni` ve `rapor_yeni` yalnız eski göçlerin ara tablolarıdır. Kayıt sayıları canlı veriden ölçülecek
(ALIG-DB-004 Faz A); canlı sunucuya erişim olmadığı için şu an **NOT_RUN**.

## 2. Sürücü kararı (DB-K1)

| Ölçüt | A: `psql` alt süreci | B: `ctypes` + `libpq.so.5` | C: `psycopg` |
| --- | --- | --- | --- |
| Dış Python paketi | yok | yok | var (kuralı bozar) |
| İşletim sistemi bağımlılığı | `postgresql-client` | `libpq5` (Ubuntu paketi) | `libpq5` ya da ikili tekerlek |
| TLS, SCRAM | var | var (libpq) | var |
| Parametreli sorgu | yok (`psql -v` kaçışı, sunucu tarafı bağlama değil) | `PQexecParams`: sunucu tarafı bağlama | var |
| İşlem (BEGIN/COMMIT) birden çok sorguda | yok, her çağrı ayrı süreç | var | var |
| Zaman aşımı, iptal | süreç öldürme | `connect_timeout`, `statement_timeout`, `PQcancel` | var |
| Bellek sızıntısı riski | düşük | `PQclear`/`PQfinish` disiplini; testle denetlenir | düşük |
| Bakım maliyeti | düşük ama yetersiz | orta (dar bir sarmalayıcı, ~300 satır) | düşük |
| Windows geliştirme | var | `libpq.dll` gerekir | var |

Öneri **B**: tek ortak bağlantı katmanı `ortak/pg.py` (bağlantı, parametre bağlama, işlem, geri alma, zaman aşımı,
hata sınıflandırma, sır maskeleme). Yeniden deneme yalnız bağlantı kurulurken yapılır; işlem kör tekrarlanmaz.
Sıfırdan protokol sürücüsü yazılmaz. `libpq5` ve sürümü `deploy/` içinde açıkça kurulur ve belgelenir.

## 3. Veri modeli

Mevcut tablo adları korunur (v5 bölüm 7'deki İngilizce adlar mantıksal karşılıktır, yeni tablo talimatı değildir):

| v5 mantıksal tablo | Mevcut karşılık | Not |
| --- | --- | --- |
| companies | firma | `durum` CHECK, benzersiz anahtar |
| admin_users, admin_sessions | kullanici, oturum | oturum kodu yalnız özetiyle; TOTP sırrı ayrı ele alınır (ALIG-SEC-001) |
| scan_results | rapor | belirteç benzersiz, `firma_id` yabancı anahtar |
| scan_quotas, quota_transactions | kullanim | kota bir sayaç değil, kayan pencere: son 30 günde en çok 2 kullanım kaydı (`SINIR_GUN`, `SINIR_ADET`) |
| scan_jobs | baglanti_istegi (Kip B) | iş kuyruğu: madde 21, `FOR UPDATE SKIP LOCKED` |
| audit_events | denetim (iki zincir) | uygulama rolünde UPDATE/DELETE yok; zincir ucu kilitle sıralanır; kanonik biçim değişmez |
| contact_requests | contact | |
| verification_requests | portal_kod ve firma doğrulama kodu | tek kullanımlık |
| outbox_events | posta | gönderim niyeti iş verisiyle aynı işlemde |
| idempotency_keys | yeni | yükleme ve tarama başlatmada; aynı anahtar farklı içerikle reddedilir |
| schema_migrations | `PRAGMA user_version` yerine | |

Şema SQL dosyaları ve kararlar: `db/sema/*.sql`, `db/README.md` (ALIG-DB-003a, PG16'da PASS). Yönetim zinciri tek şemada
çakışmasın diye `yonetim_denetim` adını aldı; `rapor.belge_json` metin kaldı (gerekçe `db/README.md`).

Tüm zamanlar `timestamptz` (UTC). Şema: `alig`. Roller: `alig_owner` (NOLOGIN, nesne sahibi), `alig_app` (DML,
BYPASSRLS/CREATEDB/CREATEROLE/REPLICATION yok), `alig_migrator` (DDL, yalnız göç sırasında), `alig_readonly`,
`alig_backup`. `public` şemasında CREATE kaldırılır, `search_path` sabitlenir.

## 4. İşlem kuralları

Firma oluşturma/güncelleme/pasifleştirme/silme, oturum iptali, kota düşme ve sıfırlama, tarama başlatma/bitirme/iptal,
e-posta doğrulama, rapor silme ve denetim kaydı yazma tek işlemde yapılır. Bugün SQLite'ta da büyük kısmı tek işlemdedir
(`depo.islem`, madde 28); geçişte aynı sınırlar korunur ve PostgreSQL üzerinde testle kanıtlanır.

Kota: bugünkü model kayan pencere olduğu için v5'teki `UPDATE ... SET remaining = remaining - 1 WHERE remaining > 0`
kalıbı doğrudan uymaz. PostgreSQL'de eşdeğeri: aynı işlemde kota anahtarına `pg_advisory_xact_lock` (ya da firma satırına
`SELECT ... FOR UPDATE`), penceredeki kayıtları say, sınırın altındaysa kullanım kaydını ekle. Idempotency kaydı, rapor
kaydı ve denetim kaydı aynı işlemdedir; paralel iki yükleme sınırı aşamaz (test: iki eşzamanlı istemci). Bağlantı işlem ortasında koparsa başarı ilan edilmez, idempotency kaydıyla
uzlaştırılır.

## 5. Göç aşamaları (ALIG-DB-004)

A envanter (satır sayısı, zincir doğrulama) → B şema ve göç rolü → C kopya üzerinde prova (satır sayısı, kanonik
özet karşılaştırması, NULL/boş dizgi, boolean, timestamptz, Türkçe karakter, belirteç benzersizliği, yabancı anahtar,
denetim zinciri, kota tutarlılığı) → D cutover (yalnız DB-K4 onayıyla). SQLite dosyaları başarı doğrulanmadan silinmez.
`sqlite3` yalnız yalıtılmış göç aracında okunur; bu araç çalışma zamanına paketlenmez ve cutover sonrası kaldırılır.
Cutover sonrası SQLite'a dönüş, cutover'dan sonra yazılan veriyi kaybettirir; bu sınır cutover raporunda yazılır.

## 6. Yedek ve geri yükleme (ALIG-DB-005)

`pg_basebackup` + WAL arşivi (PITR için); yalnız `pg_dump` ile PITR iddia edilmez. Şifreli yedek, saklama, restore
tatbikatı; RTO yalnız tatbikatla ölçülür. `BACKUP_RESTORE_VERIFIED` tatbikat yapılmadan `false`.

## 7. Test matrisi ve durum

| Test | Beklenen | Durum |
| --- | --- | --- |
| SQLite çalışma zamanı bağımlılığı | NONE | FAIL (bugün SQLite kullanılıyor; ALIG-CI-001 cutover sonrası denetim ekler) |
| PostgreSQL bağlantısı | PASS | NOT_RUN |
| Parametreli SQL | PASS | NOT_RUN |
| Yabancı anahtar, benzersizlik, CHECK | PASS | PG16'da PASS (`tests/test_pg_sema.py`; firma silme kaskadı dahil) |
| İşlem geri alma | PASS | NOT_RUN |
| Paralel kota tüketimi | ATOMIC | NOT_RUN |
| Idempotency | PASS | NOT_RUN (yalnız tablo kısıtı PG16'da PASS: aynı anahtar ikinci kez eklenemez; farklı içerik reddi uygulama kodudur, ALIG-DB-003c) |
| Firma izolasyonu | PASS | NOT_RUN (SQLite'ta testli: `tests/test_portal.py`) |
| RLS aşma denemesi | DENY | NOT_APPLICABLE (DB-K3: portal kapalı, RLS sonra) |
| Salt okuma rolüyle DML, uygulama rolüyle DDL | DENY | PG16'da PASS (42501; denetim tablolarında UPDATE/DELETE/TRUNCATE de DENY) |
| Şema göçü: tüm dosyalar, tekrar çalıştırma, değişmiş eski dosya | PASS | PG16'da PASS (`db/uygula.py`) |
| PostgreSQL bağlantı kesintisi | SAFE FAILURE | NOT_RUN |
| Göç satır sayısı ve özet | MATCH | NOT_RUN |
| Geri yükleme | VERIFIED | NOT_RUN |
| Sır maskeleme | PASS | NOT_RUN |

Ortam notu: bu geliştirme ortamında yalnız sistem PostgreSQL 16 var. PostgreSQL 18 ikilisi indirilmesine izin
verilmedi; PG18 üzerinde testler **BLOCKED**. PG16'da geçen test "PG16'da PASS" olarak yazılır, PG18 için PASS sayılmaz.

## 8. Kapılar

`POSTGRESQL_GATE = FAIL` (SQLite çalışma zamanında), `MIGRATION_GATE = NOT_RUN`, `BACKUP_RESTORE = NOT_RUN`,
dolayısıyla `PRODUCTION_READY = false`.
