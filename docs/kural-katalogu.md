# Kural kataloğu

<!-- Bu dosya `python3 tarama/uret_kurallar.py` ile üretilir; elle düzenlemeyin. -->

Her kural her taramada tek bir kanıt kaydı üretir (`tarama/kanit.py`): durum, önem, güven düzeyi, kaynak, toplama zamanı, gözlenen değerler ve bulgular. Kimlikler kalıcıdır: kural kaldırılırsa kimliği yeniden kullanılmaz, kategori değişse de kimlik aynı kalır.

## Durumlar

| Durum | Rapordaki adı | Anlamı |
|---|---|---|
| FAIL | Başarısız | Kural en az bir kritik ya da yüksek önemli bulgu üretti. |
| WARNING | Uyarı | Kural yalnız orta, düşük ya da bilgi önemli bulgu üretti. |
| UNKNOWN | Bilinmiyor | Veri geldi ama sonuca yetmiyor: biçim ya da tür geçersiz, zorunlu değer boş, beklenen satır yok, sunucudaki bazı veritabanları taranmadı ya da ek kaynak gelmedi. |
| UNAVAILABLE | Alınamadı | Veri alınamadı: çalıştırılmadı, yetki yok, zaman aşımı, sürümde yok, yedek sunucu, hata, sınır. |
| NOT_APPLICABLE | Uygulanmaz | Veri, kuralın konusunun sunucuda olmadığını gösteriyor (örneğin replikasyon slotu yok). |
| PASS | Geçti | Bütün kaynaklar eksiksiz geldi, kural çalıştı ve bulgu yok. Veri yokken PASS çıkmaz. |

Bulgu varsa kapsam kısmi olsa bile durum FAIL ya da WARNING olur: bulunan sorun gerçektir. Önem ile durum eşlemesi: kritik ve yüksek FAIL; orta, düşük ve bilgi WARNING.

## Güven düzeyleri

| Düzey | Anlamı |
|---|---|
| HIGH | Ayar ya da katalog durumu doğrudan okundu. |
| MEDIUM | İstatistik tahmini ya da tarama anının görüntüsü: istatistik sıfırlama ve tarama zamanı sonucu etkiler. |
| LOW | Dolaylı işaret: karar için ek bağlam gerekir (örneğin replikalardaki kullanım). |

Güven yalnız kanıtı olan durumlarda verilir (FAIL, WARNING, NOT_APPLICABLE, PASS). SQL Server kuralları ön sürümdür: sorgular gerçek sunucuda sınanmadı, raporda güven en çok MEDIUM gösterilir.

Veri koşulu: *tek satır* kaynakta tam bir satır beklenir; *en az bir satır* kaynakta boş sonuç veri yok demektir; *boş sonuç geçerli* kaynakta boş sonuç sorun yok demektir. Zorunlu değeri boş ya da türü yanlış satır değerlendirmeye girmez ve sonucu kısmi yapar. *Ek* kaynak gelmezse kural yine çalışır, bulguyu raporlar, ama PASS veremez. *Her veritabanında* çalışan kaynakta PASS için sunucudaki bağlanılabilir bütün veritabanlarının taranmış olması gerekir (`pg_kapsam`); atlanan ya da seçilmeyen veritabanı varsa sonuç kısmidir.

## PostgreSQL (17 kural)

| Kimlik | Denetim | Kategori | Güven | Toplama denetimi | Okunan kaynak | Geçme koşulu |
|---|---|---|---|---|---|---|
| PG-BACKUP-001 | WAL arşivleme | Yedekleme | HIGH | `pg_arsiv` (tek satır) | `archive_mode`, `pg_stat_archiver` | archive_mode açık, başarılı arşivleme kaydı var ve son hata son başarıdan eski. |
| PG-CAP-001 | Bağlantı doluluğu | Kapasite | MEDIUM | `pg_baglanti` (tek satır) | `max_connections`, `pg_stat_activity` | Tarama anında istemci bağlantıları max_connections değerinin %75'inden az. |
| PG-CAP-002 | Sequence doluluğu | Kapasite | HIGH | `pg_sequence` (her veritabanında, boş sonuç geçerli)<br>`pg_sequence_gorunurluk` (ek, her veritabanında, en az bir satır) | `has_sequence_privilege`, `pg_sequences` | Bütün sequence'lar okunabiliyor ve her biri en büyük değerinin %80'inin altında. |
| PG-HA-001 | Replikasyon slotları | HA/DR | HIGH | `pg_slot` (boş sonuç geçerli) | `pg_replication_slots` | Bütün replikasyon slotları etkin ve hiçbiri WAL kaybetmemiş (lost, unreserved değil). |
| PG-MAINT-001 | Ana sürüm desteği | Bakım | HIGH | `pg_surum` (tek satır) | `server_version_num` | Ana sürümün topluluk desteği en az 90 gün daha sürüyor. |
| PG-MAINT-002 | İşlem kimliği yaşı (wraparound) | Bakım | HIGH | `pg_xid_yasi` (en az bir satır) | `autovacuum_freeze_max_age`, `pg_database` | Her veritabanında işlem kimliği yaşı autovacuum_freeze_max_age değerinin iki katından ve 1,6 milyardan küçük. |
| PG-MAINT-003 | Ölü satır oranı | Bakım | MEDIUM | `pg_olu_satir` (her veritabanında, boş sonuç geçerli) | `pg_stat_user_tables` | 10 000'den çok ölü satırı olan tablolarda ölü satır oranı %20'yi geçmiyor. |
| PG-MAINT-004 | Geçersiz indeksler | Bakım | HIGH | `pg_gecersiz_indeks` (her veritabanında, boş sonuç geçerli) | `pg_index` | Geçersiz (indisvalid = false) indeks yok. |
| PG-MAINT-005 | Kullanılmayan büyük indeksler | Bakım | LOW | `pg_kullanilmayan_indeks` (her veritabanında, boş sonuç geçerli) | `pg_stat_user_indexes` | İstatistiklere göre hiç taranmamış, 10 MB'tan büyük, tekil olmayan indeks yok. |
| PG-PERF-001 | Boşta bekleyen açık işlemler | Performans | MEDIUM | `pg_bosta_islem` (boş sonuç geçerli) | `pg_stat_activity` | Tarama anında 10 dakikadan uzun süredir boşta bekleyen açık işlem yok. |
| PG-SEC-001 | TLS | Güvenlik | HIGH | `pg_tls_parola` (tek satır) | `ssl`, `ssl_min_protocol_version` | ssl açık ve en düşük protokol sürümü TLSv1.2 ya da üstü. |
| PG-SEC-002 | Parola özeti ayarı | Güvenlik | HIGH | `pg_tls_parola` (tek satır) | `password_encryption` | password_encryption değeri scram-sha-256. |
| PG-SEC-003 | MD5 özetli rol parolaları | Güvenlik | HIGH | `pg_md5_roller` (tek satır) | `pg_authid` | MD5 özetiyle saklanan rol parolası yok (pg_authid okuma yetkisi gerekir). |
| PG-SEC-004 | Oturum açabilen süper kullanıcılar | Güvenlik | HIGH | `pg_super_roller` (boş sonuç geçerli) | `pg_roles` | Oturum açabilen süper kullanıcı rolü yok. |
| PG-SEC-005 | Taramanın hesabı | Güvenlik | HIGH | belge: `superuser` (tek satır) | `is_superuser` | Tarama süper kullanıcı olmayan bir rolle çalıştırıldı. |
| PG-SEC-006 | public şemasında CREATE yetkisi | Güvenlik | HIGH | `pg_public_create` (her veritabanında, en az bir satır) | `has_schema_privilege` | Hiçbir veritabanında PUBLIC rolü public şemasında nesne oluşturamıyor. |
| PG-SEC-007 | Bağlantı günlüğü | Güvenlik | HIGH | `pg_log_ayarlari` (en az bir satır) | `pg_settings` | log_connections ve log_disconnections açık. |

Kural kaynağı olmayan bilgi denetimleri: `pg_kapsam`, `pg_eklentiler`.

## SQL Server, ön sürüm (20 kural)

| Kimlik | Denetim | Kategori | Güven | Toplama denetimi | Okunan kaynak | Geçme koşulu |
|---|---|---|---|---|---|---|
| MS-BACKUP-001 | Yedek geçmişi | Yedekleme | MEDIUM | `ms_yedek` (en az bir satır) | `msdb.dbo.backupset`, `sys.databases` | Bu sunucunun msdb kaydına göre her veritabanının son 7 günde tam yedeği, tam ya da toplu kayıtlı kurtarma modelindekilerin son 24 saatte log yedeği var. |
| MS-CONFIG-001 | Sayfa doğrulama | Konfigürasyon | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | Bütün veritabanlarında PAGE_VERIFY CHECKSUM. |
| MS-CONFIG-002 | AUTO_SHRINK ve AUTO_CLOSE | Konfigürasyon | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | Hiçbir veritabanında AUTO_SHRINK ya da AUTO_CLOSE açık değil. |
| MS-CONFIG-003 | En yüksek sunucu belleği | Konfigürasyon | HIGH (gösterilen: MEDIUM) | `ms_sunucu_ayar` (en az bir satır) | `sys.configurations` | max server memory varsayılan (sınırsız) değerde değil. |
| MS-CONFIG-004 | Dosya büyüme ayarı | Konfigürasyon | HIGH (gösterilen: MEDIUM) | `ms_dosya_buyume` (boş sonuç geçerli) | `sys.master_files` | Yüzde ile büyüyen veri ya da log dosyası yok. |
| MS-HA-001 | Veritabanı durumu | HA/DR | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | Bütün veritabanları ONLINE. |
| MS-HA-002 | Always On replikaları | HA/DR | HIGH (gösterilen: MEDIUM) | `ms_ag` (boş sonuç geçerli) | `sys.availability_groups`, `sys.dm_hadr_availability_replica_states` | Bütün replikalar HEALTHY ve CONNECTED. |
| MS-MAINT-001 | Sürüm desteği | Bakım | HIGH (gösterilen: MEDIUM) | `ms_surum` (tek satır) | `SERVERPROPERTY` | Genişletilmiş destek en az 90 gün daha sürüyor. |
| MS-MAINT-002 | Bütünlük denetimi (CHECKDB) | Bakım | HIGH (gösterilen: MEDIUM) | `ms_checkdb` (en az bir satır) | `DATABASEPROPERTYEX`, `sys.databases` | Her veritabanında son başarılı CHECKDB 14 günden yeni. |
| MS-PERF-001 | Paralellik maliyet eşiği | Performans | HIGH (gösterilen: MEDIUM) | `ms_sunucu_ayar` (en az bir satır) | `sys.configurations` | cost threshold for parallelism varsayılan 5 değerinde değil. |
| MS-PERF-002 | tempdb veri dosyaları | Performans | HIGH (gösterilen: MEDIUM) | `ms_tempdb` (tek satır) | `sys.dm_os_sys_info`, `tempdb.sys.database_files` | Çok çekirdekli sunucuda tempdb birden çok veri dosyasıyla çalışıyor. |
| MS-PERF-003 | Uzun açık işlemler | Performans | MEDIUM | `ms_acik_islem` (boş sonuç geçerli) | `sys.dm_exec_sessions`, `sys.dm_tran_active_transactions` | Tarama anında 10 dakikadan uzun süredir açık kullanıcı işlemi yok. |
| MS-SEC-001 | TRUSTWORTHY | Güvenlik | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | msdb dışında TRUSTWORTHY açık veritabanı yok. |
| MS-SEC-002 | Saldırı yüzeyini büyüten ayarlar | Güvenlik | HIGH (gösterilen: MEDIUM) | `ms_sunucu_ayar` (en az bir satır) | `sys.configurations` | xp_cmdshell, Ad Hoc Distributed Queries ve cross db ownership chaining kapalı. |
| MS-SEC-003 | sa girişi | Güvenlik | HIGH (gösterilen: MEDIUM) | `ms_sa` (tek satır) | `sys.sql_logins` | sa girişi devre dışı. |
| MS-SEC-004 | sysadmin üyeleri | Güvenlik | HIGH (gösterilen: MEDIUM) | `ms_sysadmin` (en az bir satır) | `sys.server_principals`, `sys.server_role_members` | sysadmin rolünün etkin üyesi yok; varsa liste gözden geçirilir. |
| MS-SEC-005 | Parola politikası | Güvenlik | HIGH (gösterilen: MEDIUM) | `ms_parola_politikasi` (tek satır) | `sys.sql_logins` | Etkin SQL girişlerinin hepsinde CHECK_POLICY açık. |
| MS-SEC-006 | Bağlantı şifrelemesi | Güvenlik | MEDIUM | `ms_sifreleme` (tek satır) | `sys.dm_exec_connections` | Tarama anındaki TCP bağlantılarının hepsi şifreli. |
| MS-SEC-007 | Kimlik doğrulama kipi | Güvenlik | HIGH (gösterilen: MEDIUM) | `ms_kimlik` (tek satır) | `SERVERPROPERTY` | Yalnızca Windows kimlik doğrulaması açık. |
| MS-SEC-008 | Taramanın hesabı | Güvenlik | HIGH (gösterilen: MEDIUM) | belge: `superuser` (tek satır) | `IS_SRVROLEMEMBER('sysadmin')` | Tarama sysadmin üyesi olmayan bir girişle çalıştırıldı. |
