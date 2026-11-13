# PostgreSQL sürüm ve yetki matrisi

<!-- Bu dosya `python3 tarama/uret_kurallar.py` ile üretilir; elle düzenlemeyin. Kaynak: tarama/katalog.py, docs/surum-dogrulama.json -->

Toplayıcı ve doğrudan bağlantı (Kip B) sunucunun ana sürümünü okur, her denetim için o sürümün sorgusunu seçer. Denetimin desteklemediği sürümde sorgu hiç çalışmaz; denetim raporda "Alınamadı: bu sürümde desteklenmiyor" olur. Matris PostgreSQL 12–18'i kapsar; daha yeni sürümde ana sorgu çalışır.

Bütün sorguların gerçek sunucuda sınandığı sürümler: **16**. Sınanmayan sürümde rapordaki kanıt güveni en çok orta (MEDIUM) gösterilir ve raporun özetinde yazar.

Önerilen tarama hesabı yalnız `pg_monitor` üyesidir (`alig-rol.sql`). Bir denetim `pg_monitor` içindeki bir rolü gerektiriyorsa ve hesapta yoksa kanıt motoru sonucu kısmi sayar (`pg_hesap` denetimi hesabın rollerini okur): o kural Geçti olamaz.

## Denetimler

| Denetim | Sürümler | Gereken yetki | Yetki yoksa | Gerçek sunucuda çalıştığı sürüm |
|---|---|---|---|---|
| `pg_surum` | her sürüm | herkes | - | 16 |
| `pg_sunucu_rolu` | her sürüm | herkes | - | 16 |
| `pg_kume_kimligi` | 12 ve üstü | herkes | - | 16 |
| `pg_hesap` | her sürüm | herkes | - | 16 |
| `pg_kapsam` | 12 ve üstü | herkes | - | 16 |
| `pg_xid_yasi` | 12 ve üstü | herkes | - | 16 |
| `pg_bosta_islem` | 12 ve üstü | pg_read_all_stats (pg_monitor) | Sorgu çalışır ama başka kullanıcıların oturumları görünmez; kural Bilinmiyor olur. | 16 |
| `pg_baglanti` | 12 ve üstü | pg_read_all_stats (pg_monitor) | Sorgu çalışır ama başka kullanıcıların oturumları görünmez; kural Bilinmiyor olur. | 16 |
| `pg_olu_satir` | 12 ve üstü | herkes | - | 16 |
| `pg_gecersiz_indeks` | 12 ve üstü | herkes | - | 16 |
| `pg_kullanilmayan_indeks` | 12 ve üstü | herkes | - | 16 |
| `pg_sequence` | 12 ve üstü | herkes | - | 16 |
| `pg_sequence_gorunurluk` | 12 ve üstü | herkes | - | 16 |
| `pg_slot` | 12 ve üstü; 12 ve öncesinde ayrı sorgu (wal_status kolonu PostgreSQL 13'te geldi, 12'de boş döner) | herkes | - | 16 |
| `pg_replikasyon` | 12 ve üstü | pg_read_all_stats (pg_monitor) | Sorgu çalışır ama başka kullanıcıların oturumları görünmez; kural Bilinmiyor olur. | 16 |
| `pg_arsiv` | 12 ve üstü | herkes | - | 16 |
| `pg_tls_parola` | 12 ve üstü | pg_read_all_settings (pg_monitor) | Sorgu yetki hatası verir; kural Alınamadı olur. | 16 |
| `pg_md5_roller` | 12 ve üstü | süper kullanıcı | Sorgu yetki hatası verir; kural Alınamadı olur. | 16 |
| `pg_super_roller` | 12 ve üstü | herkes | - | 16 |
| `pg_public_create` | 12 ve üstü | herkes | - | 16 |
| `pg_log_ayarlari` | 12 ve üstü | herkes | - | 16 |
| `pg_autovacuum` | 12 ve üstü | herkes | - | 16 |
| `pg_tablo_autovacuum` | 12 ve üstü | herkes | - | 16 |
| `pg_sorgu_istatistigi` | 12 ve üstü | pg_read_all_settings (pg_monitor) | Sorgu yetki hatası verir; kural Alınamadı olur. | 16 |
| `pg_gecici_dosya` | 12 ve üstü | herkes | - | 16 |
| `pg_eklentiler` | 12 ve üstü | herkes | - | 16 |

## PostgreSQL 16 doğrulaması

PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), 2026-11-13. Katalog özeti `bd29039b6f2f446f`.

Geçici bir kümede senaryo nesneleri kuruldu (geçersiz indeks, birincilde ve yedekte etkin olmayan replikasyon slotu, ölü satır ve autovacuum'u kapatılmış tablo, sınıra yakın ve tarama hesabının okuyamadığı sequence, 10 MB üstü kullanılmamış indeks, boşta açık işlem, MD5 parolalı rol, bağlanma yetkisi olmayan veritabanı, PUBLIC'e CREATE verilmiş public şeması, geçici dosyaya yazan sıralama, pakette varsa pg_stat_statements). pg_basebackup ile akışlı bir yedek sunucu başlatıldı, yeniden oynatması duraklatılarak geride bırakıldı. Toplayıcı birincilde üç hesapla, yedekte pg_monitor hesabıyla çalıştırıldı.

| Denetim | pg_monitor hesabı | Yetkisiz hesap | Süper kullanıcı | Yedek sunucu (pg_monitor) |
|---|---|---|---|---|
| `pg_surum` | 1 satır; surum_num: `160015` | 1 satır; surum_num: `160015` | 1 satır; surum_num: `160015` | 1 satır; surum_num: `160015` |
| `pg_sunucu_rolu` | 1 satır; yedek: `hayır` | 1 satır; yedek: `hayır` | 1 satır; yedek: `hayır` | 1 satır; yedek: `evet` |
| `pg_kume_kimligi` | 1 satır; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` | 1 satır; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` | 1 satır; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` | 1 satır; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` |
| `pg_hesap` | 1 satır; pg_read_all_settings: `evet`, pg_read_all_stats: `evet`, super_kullanici: `hayır` | 1 satır; pg_read_all_settings: `hayır`, pg_read_all_stats: `hayır`, super_kullanici: `hayır` | 1 satır; pg_read_all_settings: `evet`, pg_read_all_stats: `evet`, super_kullanici: `evet` | 1 satır; pg_read_all_settings: `evet`, pg_read_all_stats: `evet`, super_kullanici: `hayır` |
| `pg_kapsam` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 3 satır | 2 satır, 1 veritabanı atlandı |
| `pg_xid_yasi` | 4 satır | 4 satır | 4 satır | 4 satır |
| `pg_bosta_islem` | 1 satır | 0 satır | 1 satır | 0 satır |
| `pg_baglanti` | 1 satır; kullanilan: `2`, ust: `100` | 1 satır; kullanilan: `1`, ust: `100` | 1 satır; kullanilan: `2`, ust: `100` | 1 satır; kullanilan: `1`, ust: `100` |
| `pg_olu_satir` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 2 satır | 0 satır, 1 veritabanı atlandı |
| `pg_gecersiz_indeks` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 2 satır | 2 satır, 1 veritabanı atlandı |
| `pg_kullanilmayan_indeks` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 2 satır | 2 satır, 1 veritabanı atlandı |
| `pg_sequence` | 0 satır, 1 veritabanı atlandı | 0 satır, 1 veritabanı atlandı | 2 satır | 0 satır, 1 veritabanı atlandı |
| `pg_sequence_gorunurluk` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 3 satır | 2 satır, 1 veritabanı atlandı |
| `pg_slot` | 1 satır | 1 satır | 1 satır | 1 satır |
| `pg_replikasyon` | 1 satır | 1 satır | 1 satır | 0 satır |
| `pg_arsiv` | 1 satır; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` | 1 satır; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` | 1 satır; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` | 1 satır; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` |
| `pg_tls_parola` | 1 satır; password_encryption: `scram-sha-256`, ssl: `off`, ssl_min_protocol_version: `TLSv1.2` | Alınamadı: yetki yok | 1 satır; password_encryption: `scram-sha-256`, ssl: `off`, ssl_min_protocol_version: `TLSv1.2` | 1 satır; password_encryption: `scram-sha-256`, ssl: `off`, ssl_min_protocol_version: `TLSv1.2` |
| `pg_md5_roller` | Alınamadı: yetki yok | Alınamadı: yetki yok | 1 satır; sayi: `1` | Alınamadı: yetki yok |
| `pg_super_roller` | 1 satır | 1 satır | 1 satır | 1 satır |
| `pg_public_create` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 3 satır | 2 satır, 1 veritabanı atlandı |
| `pg_log_ayarlari` | 3 satır | 3 satır | 3 satır | 3 satır |
| `pg_autovacuum` | 2 satır | 2 satır | 2 satır | 2 satır |
| `pg_tablo_autovacuum` | 2 satır, 1 veritabanı atlandı | 2 satır, 1 veritabanı atlandı | 2 satır | 2 satır, 1 veritabanı atlandı |
| `pg_sorgu_istatistigi` | 1 satır; izleme: `top`, shared_preload_libraries: `pg_stat_statements` | Alınamadı: yetki yok | 1 satır; izleme: `top`, shared_preload_libraries: `pg_stat_statements` | 1 satır; izleme: `top`, shared_preload_libraries: `pg_stat_statements` |
| `pg_gecici_dosya` | 5 satır | 5 satır | 5 satır | 5 satır |
| `pg_eklentiler` | 3 satır, 1 veritabanı atlandı | 3 satır, 1 veritabanı atlandı | 4 satır | 3 satır, 1 veritabanı atlandı |

Kuralların durumu: aynı belgeler bugünkü kural motoruyla değerlendirildi (`tests/veri/surum/16/`).

| Kural | pg_monitor hesabı | Yetkisiz hesap | Süper kullanıcı | Yedek sunucu (pg_monitor) |
|---|---|---|---|---|
| PG-BACKUP-001 | Uyarı | Uyarı | Uyarı | Uygulanmaz: yedek sunucuda değerlendirilmez: birincil sunucuyu tarayın |
| PG-CAP-001 | Geçti | Bilinmiyor: kısmen ölçüldü: tarama hesabında gereken rol yok (pg_monitor) | Geçti | Geçti |
| PG-CAP-002 | Bilinmiyor: kısmen ölçüldü: sunucudaki bazı veritabanları taranmadı | Bilinmiyor: kısmen ölçüldü: sunucudaki bazı veritabanları taranmadı | Başarısız | Bilinmiyor: kısmen ölçüldü: sunucudaki bazı veritabanları taranmadı |
| PG-HA-001 | Başarısız | Başarısız | Başarısız | Başarısız |
| PG-HA-002 | Geçti | Bilinmiyor: kısmen ölçüldü: tarama hesabında gereken rol yok (pg_monitor) | Geçti | Uygulanmaz: bu sunucudan beslenen replika yok |
| PG-MAINT-001 | Geçti | Geçti | Geçti | Geçti |
| PG-MAINT-002 | Geçti | Geçti | Geçti | Geçti |
| PG-MAINT-003 | Uyarı | Uyarı | Uyarı | Uygulanmaz: yedek sunucuda değerlendirilmez: birincil sunucuyu tarayın |
| PG-MAINT-004 | Başarısız | Başarısız | Başarısız | Başarısız |
| PG-MAINT-005 | Uyarı | Uyarı | Uyarı | Uygulanmaz: yedek sunucuda değerlendirilmez: birincil sunucuyu tarayın |
| PG-MAINT-006 | Geçti | Geçti | Geçti | Geçti |
| PG-MAINT-007 | Uyarı | Uyarı | Uyarı | Uyarı |
| PG-MAINT-008 | Geçti | Geçti | Geçti | Geçti |
| PG-PERF-001 | Geçti | Bilinmiyor: kısmen ölçüldü: tarama hesabında gereken rol yok (pg_monitor) | Geçti | Geçti |
| PG-PERF-002 | Geçti | Alınamadı: yetki yok | Geçti | Geçti |
| PG-PERF-003 | Uyarı | Uyarı | Uyarı | Geçti |
| PG-SEC-001 | Başarısız | Alınamadı: yetki yok | Başarısız | Başarısız |
| PG-SEC-002 | Geçti | Alınamadı: yetki yok | Geçti | Geçti |
| PG-SEC-003 | Alınamadı: yetki yok | Alınamadı: yetki yok | Uyarı | Alınamadı: yetki yok |
| PG-SEC-004 | Uyarı | Uyarı | Uyarı | Uyarı |
| PG-SEC-005 | Geçti | Geçti | Uyarı | Geçti |
| PG-SEC-006 | Uyarı | Uyarı | Uyarı | Uyarı |
| PG-SEC-007 | Uyarı | Uyarı | Uyarı | Uyarı |

## Doğrulamayı yinelemek

Her PostgreSQL sürümünün `initdb`, `pg_ctl` ve `postgres` dosyalarının bulunduğu dizinle, root olmayan bir kullanıcıyla:

```sh
python3 tarama/surum_dogrula.py --pg-bin /usr/lib/postgresql/18/bin --cikti docs/surum-dogrulama.json --belge-dizini tests/veri/surum
python3 tarama/uret_kurallar.py
```

Araç yalnız kendi kurduğu geçici kümeye bağlanır ve sonunda siler. Sonuç `docs/surum-dogrulama.json` dosyasına eklenir; bütün sorgular o sürümde çalıştıysa sürüm `tarama/katalog.py` içindeki `SINANAN` listesine eklenir (`tests/test_surum.py` kanıtı denetler).
