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

## Sağlık puanı

Puan (0–100) uygulanabilir kuralların ağırlıklı kredi oranıdır (`tarama/puan.py`):

```text
puan = 100 × Σ(kategori çarpanı × ağırlık × kredi) / Σ(kategori çarpanı × ağırlık)
```

Ağırlık kuralın risk düzeyinden gelir. Risk düzeyi, kuralın üretebileceği en yüksek bulgu önemidir (`tests/test_puan.py` rastgele belgelerle denetler). Kredi kuralın durumundan gelir:

| Risk düzeyi | Varsayılan ağırlık |
|---|---|
| Kritik | 10 |
| Yüksek | 6 |
| Orta | 3 |
| Düşük | 1 |
| Bilgi | 0 |

| Durum | Kredi |
|---|---|
| FAIL | 0 (sabit) |
| WARNING | bulgunun önemine göre, varsayılan: orta 0,5; düşük 0,75; bilgi 1 |
| UNKNOWN | 0 (sabit) |
| UNAVAILABLE | 0 (sabit) |
| NOT_APPLICABLE | hesaba girmez |
| PASS | 1 (sabit) |

Kategori çarpanlarının varsayılanı 1.

Bilinmeyen durum puanı yükseltmez: kanıtı olmayan kural, başarısız kural kadar puan kaybettirir; kanıtı kaybolan kural puanı iyileştirmez. Bu yüzden puan her zaman kanıt kapsamıyla (kanıtı olan uygulanabilir kuralların oranı, ağırlıksız) birlikte gösterilir ve rapor her kaybın bulgudan mı kanıt eksikliğinden mi geldiğini ayırır. Puana giren kuralların hiçbirinde kanıt yoksa puan hesaplanmaz. Gösterilen tamsayılar aşağı yuvarlanır: 100 yalnız kayıp yoksa, %100 kapsam yalnız her kuralın kanıtı varsa görünür. Kategori puanı aynı formülle, yalnız o kategorinin kurallarıyla ve çarpansız hesaplanır.

Ağırlık, uyarı kredisi ve kategori çarpanları `ALIG_PUAN_AYARI` ile verilen JSON dosyasından ayarlanabilir (`docs/runbook.md`); durum kredileri sabittir. Varsayılan değerler mühendislik seçimidir, bir standarttan gelmez.

## Veri koşulları

Veri koşulu: *tek satır* kaynakta tam bir satır beklenir; *en az bir satır* kaynakta boş sonuç veri yok demektir; *boş sonuç geçerli* kaynakta boş sonuç sorun yok demektir. Zorunlu değeri boş ya da türü yanlış satır değerlendirmeye girmez ve sonucu kısmi yapar. *Ek* kaynak gelmezse kural yine çalışır, bulguyu raporlar, ama PASS veremez. *Her veritabanında* çalışan kaynakta PASS için sunucudaki bağlanılabilir bütün veritabanlarının taranmış olması gerekir (`pg_kapsam`); atlanan ya da seçilmeyen veritabanı varsa sonuç kısmidir.

## PostgreSQL (23 kural)

| Kimlik | Denetim | Kategori | Risk | Güven | Toplama denetimi | Okunan kaynak | Geçme koşulu |
|---|---|---|---|---|---|---|---|
| PG-BACKUP-001 | WAL arşivleme | Yedekleme | Yüksek | HIGH | `pg_arsiv` (tek satır) | `archive_mode`, `pg_stat_archiver` | archive_mode açık, başarılı arşivleme kaydı var ve son hata son başarıdan eski. |
| PG-CAP-001 | Bağlantı doluluğu | Kapasite | Yüksek | MEDIUM | `pg_baglanti` (tek satır) | `max_connections`, `pg_stat_activity` | Tarama anında istemci bağlantıları max_connections değerinin %75'inden az. |
| PG-CAP-002 | Sequence doluluğu | Kapasite | Kritik | HIGH | `pg_sequence` (her veritabanında, boş sonuç geçerli)<br>`pg_sequence_gorunurluk` (ek, her veritabanında, en az bir satır) | `has_sequence_privilege`, `pg_sequences` | Bütün sequence'lar okunabiliyor ve her biri en büyük değerinin %80'inin altında. |
| PG-HA-001 | Replikasyon slotları | HA/DR | Kritik | HIGH | `pg_slot` (boş sonuç geçerli) | `pg_replication_slots` | Bütün replikasyon slotları etkin ve hiçbiri WAL kaybetmemiş (lost, unreserved değil). |
| PG-HA-002 | Replikasyon gecikmesi | HA/DR | Yüksek | MEDIUM | `pg_replikasyon` (boş sonuç geçerli) | `pg_stat_replication` | Bu sunucudan beslenen her replika akışta (streaming) ve yeniden oynatma gecikmesi 60 saniyenin ve 1 GB'ın altında. |
| PG-MAINT-001 | Ana sürüm desteği | Bakım | Yüksek | HIGH | `pg_surum` (tek satır) | `server_version_num` | Ana sürümün topluluk desteği en az 90 gün daha sürüyor. |
| PG-MAINT-002 | İşlem kimliği yaşı (wraparound) | Bakım | Kritik | HIGH | `pg_xid_yasi` (en az bir satır) | `autovacuum_freeze_max_age`, `autovacuum_multixact_freeze_max_age`, `pg_database` | Her veritabanında işlem kimliği yaşı autovacuum_freeze_max_age değerinin iki katından ve 1,6 milyardan küçük. |
| PG-MAINT-003 | Ölü satır oranı | Bakım | Orta | MEDIUM | `pg_olu_satir` (her veritabanında, boş sonuç geçerli) | `pg_stat_user_tables` | 10 000'den çok ölü satırı olan tablolarda ölü satır oranı %20'yi geçmiyor. |
| PG-MAINT-004 | Geçersiz indeksler | Bakım | Yüksek | HIGH | `pg_gecersiz_indeks` (her veritabanında, boş sonuç geçerli) | `pg_index` | Geçersiz (indisvalid = false) indeks yok. |
| PG-MAINT-005 | Kullanılmayan büyük indeksler | Bakım | Düşük | LOW | `pg_kullanilmayan_indeks` (her veritabanında, boş sonuç geçerli) | `pg_stat_user_indexes` | İstatistiklere göre hiç taranmamış, 10 MB'tan büyük, tekil olmayan indeks yok. |
| PG-MAINT-006 | Autovacuum | Bakım | Yüksek | HIGH | `pg_autovacuum` (en az bir satır) | `autovacuum`, `track_counts` | autovacuum ve track_counts açık. |
| PG-MAINT-007 | Tablo düzeyinde kapatılmış autovacuum | Bakım | Orta | HIGH | `pg_tablo_autovacuum` (her veritabanında, boş sonuç geçerli) | `pg_class` | Hiçbir tabloda autovacuum_enabled kapalı değil. |
| PG-MAINT-008 | Multixact yaşı (wraparound) | Bakım | Kritik | HIGH | `pg_xid_yasi` (en az bir satır) | `autovacuum_freeze_max_age`, `autovacuum_multixact_freeze_max_age`, `pg_database` | Her veritabanında multixact yaşı autovacuum_multixact_freeze_max_age değerinin iki katından ve 1,6 milyardan küçük. |
| PG-PERF-001 | Boşta bekleyen açık işlemler | Performans | Yüksek | MEDIUM | `pg_bosta_islem` (boş sonuç geçerli) | `pg_stat_activity` | Tarama anında 10 dakikadan uzun süredir boşta bekleyen açık işlem yok. |
| PG-PERF-002 | Sorgu istatistikleri (pg_stat_statements) | Performans | Düşük | HIGH | `pg_sorgu_istatistigi` (tek satır) | `pg_stat_statements.track`, `shared_preload_libraries` | pg_stat_statements shared_preload_libraries ile yüklü ve sorgu topluyor (pg_stat_statements.track: top ya da all). |
| PG-PERF-003 | Geçici dosyalar | Performans | Orta | MEDIUM | `pg_gecici_dosya` (en az bir satır) | `pg_stat_database` | Geçici dosya yazılmamış ya da istatistik başlangıcı bilinen her veritabanında günde ortalama 10 GB'ın altında; başlangıcı bilinmeyen kullanım bilgi olarak gösterilir. |
| PG-SEC-001 | TLS | Güvenlik | Yüksek | HIGH | `pg_tls_parola` (tek satır) | `ssl`, `ssl_min_protocol_version` | ssl açık ve en düşük protokol sürümü TLSv1.2 ya da üstü. |
| PG-SEC-002 | Parola özeti ayarı | Güvenlik | Orta | HIGH | `pg_tls_parola` (tek satır) | `password_encryption` | password_encryption değeri scram-sha-256. |
| PG-SEC-003 | MD5 özetli rol parolaları | Güvenlik | Orta | HIGH | `pg_md5_roller` (tek satır) | `pg_authid` | MD5 özetiyle saklanan rol parolası yok (pg_authid okuma yetkisi gerekir). |
| PG-SEC-004 | Oturum açabilen süper kullanıcılar | Güvenlik | Orta | HIGH | `pg_super_roller` (boş sonuç geçerli) | `pg_roles` | Oturum açabilen süper kullanıcı rolü yok. |
| PG-SEC-005 | Taramanın hesabı | Güvenlik | Orta | HIGH | belge: `superuser` (tek satır) | `is_superuser` | Tarama süper kullanıcı olmayan bir rolle çalıştırıldı. |
| PG-SEC-006 | public şemasında CREATE yetkisi | Güvenlik | Orta | HIGH | `pg_public_create` (her veritabanında, en az bir satır) | `has_schema_privilege` | Hiçbir veritabanında PUBLIC rolü public şemasında nesne oluşturamıyor. |
| PG-SEC-007 | Bağlantı günlüğü | Güvenlik | Düşük | HIGH | `pg_log_ayarlari` (en az bir satır) | `pg_settings` | log_connections ve log_disconnections açık. |

Kural kaynağı olmayan bilgi denetimleri: `pg_sunucu_rolu`, `pg_kume_kimligi`, `pg_hesap`, `pg_kapsam`, `pg_eklentiler`.

Yalnız birincil sunucuda değerlendirilen kurallar: PG-BACKUP-001, PG-MAINT-003, PG-MAINT-005. Yedek sunucuda tablo istatistikleri (ölü satır, indeks kullanımı) tutulmaz ve arşivlemeyi birincil yapar; bu kurallar yedekte Uygulanmaz olur. Sunucunun rolü `pg_sunucu_rolu` denetiminden okunur; okunamazsa bu kurallar Geçti olamaz.

## SQL Server, ön sürüm (20 kural)

| Kimlik | Denetim | Kategori | Risk | Güven | Toplama denetimi | Okunan kaynak | Geçme koşulu |
|---|---|---|---|---|---|---|---|
| MS-BACKUP-001 | Yedek geçmişi | Yedekleme | Yüksek | MEDIUM | `ms_yedek` (en az bir satır) | `msdb.dbo.backupset`, `sys.databases` | Bu sunucunun msdb kaydına göre her veritabanının son 7 günde tam yedeği, tam ya da toplu kayıtlı kurtarma modelindekilerin son 24 saatte log yedeği var. |
| MS-CONFIG-001 | Sayfa doğrulama | Konfigürasyon | Yüksek | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | Bütün veritabanlarında PAGE_VERIFY CHECKSUM. |
| MS-CONFIG-002 | AUTO_SHRINK ve AUTO_CLOSE | Konfigürasyon | Orta | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | Hiçbir veritabanında AUTO_SHRINK ya da AUTO_CLOSE açık değil. |
| MS-CONFIG-003 | En yüksek sunucu belleği | Konfigürasyon | Orta | HIGH (gösterilen: MEDIUM) | `ms_sunucu_ayar` (en az bir satır) | `sys.configurations` | max server memory varsayılan (sınırsız) değerde değil. |
| MS-CONFIG-004 | Dosya büyüme ayarı | Konfigürasyon | Düşük | HIGH (gösterilen: MEDIUM) | `ms_dosya_buyume` (boş sonuç geçerli) | `sys.master_files` | Yüzde ile büyüyen veri ya da log dosyası yok. |
| MS-HA-001 | Veritabanı durumu | HA/DR | Yüksek | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | Bütün veritabanları ONLINE. |
| MS-HA-002 | Always On replikaları | HA/DR | Yüksek | HIGH (gösterilen: MEDIUM) | `ms_ag` (boş sonuç geçerli) | `sys.availability_groups`, `sys.dm_hadr_availability_replica_states` | Bütün replikalar HEALTHY ve CONNECTED. |
| MS-MAINT-001 | Sürüm desteği | Bakım | Yüksek | HIGH (gösterilen: MEDIUM) | `ms_surum` (tek satır) | `SERVERPROPERTY` | Genişletilmiş destek en az 90 gün daha sürüyor. |
| MS-MAINT-002 | Bütünlük denetimi (CHECKDB) | Bakım | Orta | HIGH (gösterilen: MEDIUM) | `ms_checkdb` (en az bir satır) | `DATABASEPROPERTYEX`, `sys.databases` | Her veritabanında son başarılı CHECKDB 14 günden yeni. |
| MS-PERF-001 | Paralellik maliyet eşiği | Performans | Düşük | HIGH (gösterilen: MEDIUM) | `ms_sunucu_ayar` (en az bir satır) | `sys.configurations` | cost threshold for parallelism varsayılan 5 değerinde değil. |
| MS-PERF-002 | tempdb veri dosyaları | Performans | Orta | HIGH (gösterilen: MEDIUM) | `ms_tempdb` (tek satır) | `sys.dm_os_sys_info`, `tempdb.sys.database_files` | Çok çekirdekli sunucuda tempdb birden çok veri dosyasıyla çalışıyor. |
| MS-PERF-003 | Uzun açık işlemler | Performans | Yüksek | MEDIUM | `ms_acik_islem` (boş sonuç geçerli) | `sys.dm_exec_sessions`, `sys.dm_tran_active_transactions` | Tarama anında 10 dakikadan uzun süredir açık kullanıcı işlemi yok. |
| MS-SEC-001 | TRUSTWORTHY | Güvenlik | Orta | HIGH (gösterilen: MEDIUM) | `ms_db_ayar` (en az bir satır) | `sys.databases` | msdb dışında TRUSTWORTHY açık veritabanı yok. |
| MS-SEC-002 | Saldırı yüzeyini büyüten ayarlar | Güvenlik | Yüksek | HIGH (gösterilen: MEDIUM) | `ms_sunucu_ayar` (en az bir satır) | `sys.configurations` | xp_cmdshell, Ad Hoc Distributed Queries ve cross db ownership chaining kapalı. |
| MS-SEC-003 | sa girişi | Güvenlik | Orta | HIGH (gösterilen: MEDIUM) | `ms_sa` (tek satır) | `sys.sql_logins` | sa girişi devre dışı. |
| MS-SEC-004 | sysadmin üyeleri | Güvenlik | Bilgi | HIGH (gösterilen: MEDIUM) | `ms_sysadmin` (en az bir satır) | `sys.server_principals`, `sys.server_role_members` | sysadmin rolünün etkin üyesi yok; varsa liste gözden geçirilir. |
| MS-SEC-005 | Parola politikası | Güvenlik | Orta | HIGH (gösterilen: MEDIUM) | `ms_parola_politikasi` (tek satır) | `sys.sql_logins` | Etkin SQL girişlerinin hepsinde CHECK_POLICY açık. |
| MS-SEC-006 | Bağlantı şifrelemesi | Güvenlik | Orta | MEDIUM | `ms_sifreleme` (tek satır) | `sys.dm_exec_connections` | Tarama anındaki TCP bağlantılarının hepsi şifreli. |
| MS-SEC-007 | Kimlik doğrulama kipi | Güvenlik | Düşük | HIGH (gösterilen: MEDIUM) | `ms_kimlik` (tek satır) | `SERVERPROPERTY` | Yalnızca Windows kimlik doğrulaması açık. |
| MS-SEC-008 | Taramanın hesabı | Güvenlik | Orta | HIGH (gösterilen: MEDIUM) | belge: `superuser` (tek satır) | `IS_SRVROLEMEMBER('sysadmin')` | Tarama sysadmin üyesi olmayan bir girişle çalıştırıldı. |
