# PostgreSQL'e geçiş (ALIG-DB-001)

Kaynak: `docs/master-prompt-v5.md` (v4.1'i içerir). Bu belge mimari ve göç planıdır; uygulamaya bağlı kod henüz yazılmadı (yalnız sürücü değerlendirme prototipi `ortak/pg.py` var, bölüm 2).
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
| Bellek sızıntısı riski | düşük | `PQclear`/`PQfinish` disiplini; PG16'da ölçüldü: 20 000 sorguda RSS artışı 0 KB | düşük |
| Bakım maliyeti | düşük ama yetersiz | orta (dar sarmalayıcı: prototip `ortak/pg.py` 468 satır, yorum ve belge dizgisi dahil) | düşük |
| Windows geliştirme | var | `libpq.dll` gerekir (aşağıdaki not) | var |

Ölçüm (ALIG-DB-002, PG16 geçici küme, Unix soketi, scram-sha-256, süper kullanıcı olmayan rol, libpq 16.15; yerel soket
olduğu için ağ ve TLS maliyeti içermez; tek makine, tek çalıştırma, kaba değerlerdir):

| Ölçüm | Sonuç (PG16) |
| --- | --- |
| Bağlantı kurma (SCRAM + 4 oturum ayarı) | ~10 ms (medyan, 30 deneme) |
| Parametreli `SELECT $1::int, $2::text`, kalıcı bağlantı | ~19 µs medyan, ~61 µs p99 (2000 sorgu) |
| `psql -c` alt süreci, tek `SELECT 1` | ~13 ms medyan (20 deneme); bağlantı kurma dahil, karşılaştırma yalnız büyüklük sırası içindir |
| 5000 `INSERT` tek işlemde | 0,2 sn |
| 5000 satır okuma ve Python'a çevirme | ~29 ms |
| RSS artışı, 20 000 sorgu (2000 karakterlik parametre) | 0 KB |
| Test kümesi kurulum + 25 test | ~7 sn |

Prototipin PG16'da PASS veren davranışları (`tests/test_pg_prototip.py`, 25 test): bağlantı ve süper kullanıcı olmayan rol;
`PQexecParams` ile parametre bağlama (enjeksiyon denemesi değer olarak kalır); NULL ve Türkçe karakter gidiş-dönüşü
(boş dizgi NULL'a dönmez); `timestamptz` gidiş-dönüşü (saat dilimsiz `datetime` reddedilir); işlem, istisnada ve SQL
hatasında geri alma; SQLSTATE ile hata sınıfı (`23505` -> `BenzersizlikHatasi`); `statement_timeout` ve başka
iş parçacığından `PQcancel` ile iptal (`57014`); yanlış parolada hata metninde parola yok; sunucu durunca ve işlem
ortasında kesintide `BaglantiHatasi` (tekrar denenmez, işlem başarılı sayılmaz); 1000 sorgu döngüsünde sınırlı RSS; iki iş
parçacığının ayrı bağlantılarla paralel çalışması; aynı bağlantının iş parçacıkları arasında paylaşımının reddi.

Ölçümde görülen ve prototipe işlenen ayrıntılar (C ile karşılaştırmada B'nin gerçek maliyeti):
- Sunucu kapanınca ilk hata sonucu SQLSTATE'siz geldi ve `PQstatus` hemen bozuk görünmedi; yalnız `PQstatus`'a bakmak kesintiyi
  sunucu hatası sanıyordu. Kural: SQLSTATE'siz hata, `08xxx` ve `57P01-03` bağlantı kaybı sayılır.
- Hata metnine `PQresultErrorMessage` (DETAIL satır değerleri içerebilir) yerine yalnız birincil ileti ve SQLSTATE yazılır.
- `PQcancel` nesnesi bağlantı kurulurken alınır; iptal başka iş parçacığından güvenli çağrılır.
- Parametre tipi çıkarılamazsa sunucu hata verir (`SELECT $1`); sorguda `$1::text` gibi tür dönüşümü gerekir.
- Sonuçlar metin biçimindedir; yalnız bool, tamsayı, float, numeric ve `timestamptz` Python tipine çevrilir (diğerleri `str`).

Sınanmayanlar: PostgreSQL 18 (BLOCKED, ortamda yok), TCP ve TLS bağlantısı, gerçek ağ kesintisi, 1000'den uzun süreli
sızıntı koşusu, bağlantı havuzu, çok sütunlu büyük sonuçlarda bellek, Windows `libpq.dll`.

Öneri **B** (DB-K1 için kanıtla desteklenir): tek ortak bağlantı katmanı `ortak/pg.py` (bağlantı, parametre bağlama, işlem,
geri alma, zaman aşımı, hata sınıflandırma, sır maskeleme). Gerekçe: dış paket kuralını bozmaz (C elenir); A'da birden çok
sorgulu işlem ve sunucu tarafı parametre bağlama yoktur, bu yüzden kota ve denetim zinciri işlemleri (bölüm 4) A ile
yazılamaz; B bunları ~19 µs sorgu maliyetiyle ve sınırlı bellekle sağlar. Risk: ctypes imza hatası süreci çökertebilir; bu
yüzden sarmalayıcı dar tutulur, imzalar tek yerde tanımlıdır ve testler her sürümde çalışır. Yeniden deneme yalnız bağlantı
kurulurken yapılır; işlem kör tekrarlanmaz. Sıfırdan protokol sürücüsü yazılmaz. `libpq5` ve sürümü `deploy/` içinde açıkça
kurulur ve belgelenir. Karar DB-K1 sahibine aittir; bu bölüm öneridir.

Windows notu: `libpq.dll` (PostgreSQL istemci dağıtımından) ve bağımlılıkları (`libssl`, `libcrypto`, `libintl` vb.) `PATH`
üzerinde olmalı ya da `ALIG_LIBPQ` ortam değişkeniyle tam yol verilmeli. Prototip Windows'ta çalıştırılmadı; yalnız yükleme
adayları (`libpq.dll`) kodda var. Üretim Ubuntu'dadır, Windows yalnız geliştirme içindir.

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
| PostgreSQL bağlantısı | PASS | PG16'da PASS (prototip) |
| Parametreli SQL | PASS | PG16'da PASS (prototip) |
| İşlem geri alma | PASS | PG16'da PASS (prototip) |
| Yabancı anahtar, benzersizlik, CHECK | PASS | PG16'da PASS (`tests/test_pg_sema.py`; firma silme kaskadı dahil) |
| Paralel kota tüketimi | ATOMIC | NOT_RUN |
| Idempotency | PASS | NOT_RUN (yalnız tablo kısıtı PG16'da PASS: aynı anahtar ikinci kez eklenemez; farklı içerik reddi uygulama kodudur, ALIG-DB-003c) |
| Firma izolasyonu | PASS | NOT_RUN (SQLite'ta testli: `tests/test_portal.py`) |
| RLS aşma denemesi | DENY | NOT_APPLICABLE (DB-K3: portal kapalı, RLS sonra) |
| PostgreSQL bağlantı kesintisi | SAFE FAILURE | PG16'da PASS (prototip) |
| Salt okuma rolüyle DML, uygulama rolüyle DDL | DENY | PG16'da PASS (42501; denetim tablolarında UPDATE/DELETE/TRUNCATE de DENY) |
| Şema göçü: tüm dosyalar, tekrar çalıştırma, değişmiş eski dosya | PASS | PG16'da PASS (`db/uygula.py`) |
| Göç satır sayısı ve özet | MATCH | NOT_RUN |
| Geri yükleme | VERIFIED | NOT_RUN |
| Sır maskeleme | PASS | PG16'da PASS (prototip; parola hata metninde ve repr'de yok) |

Ortam notu: bu geliştirme ortamında yalnız sistem PostgreSQL 16 var. PostgreSQL 18 ikilisi indirilmesine izin
verilmedi; PG18 üzerinde testler **BLOCKED**. PG16'da geçen test "PG16'da PASS" olarak yazılır, PG18 için PASS sayılmaz.

## 8. Kapılar

`POSTGRESQL_GATE = FAIL` (SQLite çalışma zamanında), `MIGRATION_GATE = NOT_RUN`, `BACKUP_RESTORE = NOT_RUN`,
dolayısıyla `PRODUCTION_READY = false`.
