# Rule catalog

<!-- This file is generated with `python3 tarama/uret_kurallar.py`; do not edit it by hand. -->

Every rule produces a single evidence record in every scan (`tarama/kanit.py`): status, severity, confidence level, source, collection time, observed values and findings. Ids are permanent: if a rule is removed its id is not reused, and the id stays the same even if the category changes.

## Statuses

| Status | Name in the report | Meaning |
|---|---|---|
| FAIL | Fail | The rule produced at least one critical or high severity finding. |
| WARNING | Warning | The rule produced only medium, low or informational findings. |
| UNKNOWN | Unknown | Data arrived but is not enough for a conclusion: invalid format or type, a required value is empty, an expected row is missing, some databases on the server were not scanned, or an additional source did not arrive. |
| UNAVAILABLE | Unavailable | Data could not be obtained: not run, no privilege, timeout, not available in this version, standby server, error, limit. |
| NOT_APPLICABLE | Not applicable | The data shows that the rule's subject does not exist on the server (for example, there is no replication slot). |
| PASS | Pass | All sources arrived completely, the rule ran and there are no findings. PASS never appears when data is missing. |

If there is a finding, the status is FAIL or WARNING even if coverage is partial: a problem that is found is real. Mapping of severity to status: critical and high are FAIL; medium, low and info are WARNING.

## Confidence levels

| Level | Meaning |
|---|---|
| HIGH | A setting or catalog state was read directly. |
| MEDIUM | A statistical estimate or a snapshot of the scan moment: the statistics reset time and the scan time affect the result. |
| LOW | An indirect sign: extra context is needed for a decision (for example, usage on replicas). |

Confidence is given only for statuses that have evidence (FAIL, WARNING, NOT_APPLICABLE, PASS). SQL Server rules are a preview: the queries were not tested on a real server, and the confidence shown in the report is at most MEDIUM.

## Health score

The score (0-100) is the weighted credit ratio of the applicable rules (`tarama/puan.py`):

```text
score = 100 × Σ(category multiplier × weight × credit) / Σ(category multiplier × weight)
```

The weight comes from the rule's risk level. The risk level is the highest finding severity the rule can produce (`tests/test_puan.py` checks this with random documents). The credit comes from the rule's status:

| Risk level | Default weight |
|---|---|
| Critical | 10 |
| High | 6 |
| Medium | 3 |
| Low | 1 |
| Info | 0 |

| Status | Credit |
|---|---|
| FAIL | 0 (fixed) |
| WARNING | by the finding's severity, default: medium 0.5; low 0.75; info 1 |
| UNKNOWN | 0 (fixed) |
| UNAVAILABLE | 0 (fixed) |
| NOT_APPLICABLE | not counted |
| PASS | 1 (fixed) |

The default of the category multipliers is 1.

An unknown status does not raise the score: a rule with no evidence loses as many points as a failed rule; a rule whose evidence disappears does not improve the score. For this reason the score is always shown together with the evidence coverage (the ratio of applicable rules that have evidence, unweighted) and the report separates whether each loss comes from a finding or from missing evidence. If none of the rules that enter the score has evidence, the score is not computed. The integers shown are rounded down: 100 appears only if there is no loss, and 100% coverage only if every rule has evidence. The category score is computed with the same formula, only with the rules of that category and without multipliers.

The weights, the warning credits and the category multipliers can be set from the JSON file given with `ALIG_PUAN_AYARI` (`docs/runbook.md`); the status credits are fixed. The default values are an engineering choice, not taken from a standard.

## Data conditions

Data condition: for *single row* exactly one row is expected in the source; for *at least one row* an empty result in the source means no data; for *empty result is valid* an empty result in the source means no problem. A row with a required value empty or of the wrong type does not enter the evaluation and makes the result partial. If an *additional* source does not arrive the rule still runs and reports the finding, but cannot give PASS. For a source that runs *in every database*, PASS requires that all connectable databases on the server were scanned (`pg_kapsam`); if a database was skipped or not selected, the result is partial.

## PostgreSQL (23 rules)

| ID | Check | Category | Risk | Confidence | Collection check | Source read | Pass condition |
|---|---|---|---|---|---|---|---|
| PG-BACKUP-001 | WAL archiving | Backup | High | HIGH | `pg_arsiv` (single row) | `archive_mode`, `pg_stat_archiver` | archive_mode is on, a successful archive is recorded and the last failure is older than the last success. |
| PG-CAP-001 | Connection usage | Capacity | High | MEDIUM | `pg_baglanti` (single row) | `max_connections`, `pg_stat_activity` | At scan time client connections are below 75% of max_connections. |
| PG-CAP-002 | Sequence exhaustion | Capacity | Critical | HIGH | `pg_sequence` (in every database, empty result is valid)<br>`pg_sequence_gorunurluk` (additional, in every database, at least one row) | `has_sequence_privilege`, `pg_sequences` | Every sequence is readable and below 80% of its maximum value. |
| PG-HA-001 | Replication slots | HA/DR | Critical | HIGH | `pg_slot` (empty result is valid) | `pg_replication_slots` | All replication slots are active and none has lost WAL (not lost or unreserved). |
| PG-HA-002 | Replication lag | HA/DR | High | MEDIUM | `pg_replikasyon` (empty result is valid) | `pg_stat_replication` | Every replica fed by this server is streaming, with replay lag below 60 seconds and 1 GB. |
| PG-MAINT-001 | Major version support | Maintenance | High | HIGH | `pg_surum` (single row) | `server_version_num` | Community support for the major version lasts at least 90 more days. |
| PG-MAINT-002 | Transaction ID age (wraparound) | Maintenance | Critical | HIGH | `pg_xid_yasi` (at least one row) | `autovacuum_freeze_max_age`, `autovacuum_multixact_freeze_max_age`, `pg_database` | In every database the transaction ID age is below twice autovacuum_freeze_max_age and below 1.6 billion. |
| PG-MAINT-003 | Dead row ratio | Maintenance | Medium | MEDIUM | `pg_olu_satir` (in every database, empty result is valid) | `pg_stat_user_tables` | In tables with more than 10,000 dead rows the dead-row ratio stays below 20%. |
| PG-MAINT-004 | Invalid indexes | Maintenance | High | HIGH | `pg_gecersiz_indeks` (in every database, empty result is valid) | `pg_index` | There are no invalid indexes (indisvalid = false). |
| PG-MAINT-005 | Large unused indexes | Maintenance | Low | LOW | `pg_kullanilmayan_indeks` (in every database, empty result is valid) | `pg_stat_user_indexes` | There is no non-unique index over 10 MB that statistics show as never scanned. |
| PG-MAINT-006 | Autovacuum | Maintenance | High | HIGH | `pg_autovacuum` (at least one row) | `autovacuum`, `track_counts` | autovacuum and track_counts are on. |
| PG-MAINT-007 | Autovacuum turned off per table | Maintenance | Medium | HIGH | `pg_tablo_autovacuum` (in every database, empty result is valid) | `pg_class` | No table has autovacuum_enabled turned off. |
| PG-MAINT-008 | Multixact ID age (wraparound) | Maintenance | Critical | HIGH | `pg_xid_yasi` (at least one row) | `autovacuum_freeze_max_age`, `autovacuum_multixact_freeze_max_age`, `pg_database` | In every database the multixact ID age is below twice autovacuum_multixact_freeze_max_age and below 1.6 billion. |
| PG-PERF-001 | Idle-in-transaction sessions | Performance | High | MEDIUM | `pg_bosta_islem` (empty result is valid) | `pg_stat_activity` | At scan time no transaction has been idle for more than 10 minutes. |
| PG-PERF-002 | Query statistics (pg_stat_statements) | Performance | Low | HIGH | `pg_sorgu_istatistigi` (single row) | `pg_stat_statements.track`, `shared_preload_libraries` | pg_stat_statements is loaded through shared_preload_libraries and collecting (pg_stat_statements.track: top or all). |
| PG-PERF-003 | Temporary files | Performance | Medium | MEDIUM | `pg_gecici_dosya` (at least one row) | `pg_stat_database` | No temporary files were written, or less than 10 GB per day on average in every database with a known statistics start; usage with an unknown start is shown as information. |
| PG-SEC-001 | TLS | Security | High | HIGH | `pg_tls_parola` (single row) | `ssl`, `ssl_min_protocol_version` | ssl is on and the minimum protocol version is TLSv1.2 or later. |
| PG-SEC-002 | Password hashing setting | Security | Medium | HIGH | `pg_tls_parola` (single row) | `password_encryption` | password_encryption is scram-sha-256. |
| PG-SEC-003 | Role passwords stored as MD5 | Security | Medium | HIGH | `pg_md5_roller` (single row) | `pg_authid` | No role password is stored as an MD5 hash (requires read access to pg_authid). |
| PG-SEC-004 | Superusers that can log in | Security | Medium | HIGH | `pg_super_roller` (empty result is valid) | `pg_roles` | No superuser role can log in. |
| PG-SEC-005 | Scan account | Security | Medium | HIGH | document: `superuser` (single row) | `is_superuser` | The scan ran with a role that is not a superuser. |
| PG-SEC-006 | CREATE on the public schema | Security | Medium | HIGH | `pg_public_create` (in every database, at least one row) | `has_schema_privilege` | In no database can PUBLIC create objects in the public schema. |
| PG-SEC-007 | Connection logging | Security | Low | HIGH | `pg_log_ayarlari` (at least one row) | `pg_settings` | log_connections and log_disconnections are on. |

Information checks that are not a rule source: `pg_sunucu_rolu`, `pg_kume_kimligi`, `pg_hesap`, `pg_kapsam`, `pg_eklentiler`.

Rules evaluated only on the primary server: PG-BACKUP-001, PG-MAINT-003, PG-MAINT-005. Table statistics (dead rows, index usage) are not kept on a standby and archiving is made primary-only; these rules become Not applicable on a standby. The server role is read from the `pg_sunucu_rolu` check; if it cannot be read, these rules cannot be Pass.

## SQL Server, preview (20 rules)

| ID | Check | Category | Risk | Confidence | Collection check | Source read | Pass condition |
|---|---|---|---|---|---|---|---|
| MS-BACKUP-001 | Backup history | Backup | High | MEDIUM | `ms_yedek` (at least one row) | `msdb.dbo.backupset`, `sys.databases` | According to msdb on this server, every database has a full backup in the last 7 days, and those in full or bulk-logged recovery a log backup in the last 24 hours. |
| MS-CONFIG-001 | Page verification | Configuration | High | HIGH (shown: MEDIUM) | `ms_db_ayar` (at least one row) | `sys.databases` | PAGE_VERIFY is CHECKSUM in all databases. |
| MS-CONFIG-002 | AUTO_SHRINK and AUTO_CLOSE | Configuration | Medium | HIGH (shown: MEDIUM) | `ms_db_ayar` (at least one row) | `sys.databases` | No database has AUTO_SHRINK or AUTO_CLOSE on. |
| MS-CONFIG-003 | Max server memory | Configuration | Medium | HIGH (shown: MEDIUM) | `ms_sunucu_ayar` (at least one row) | `sys.configurations` | max server memory is not at the default (unlimited) value. |
| MS-CONFIG-004 | File growth setting | Configuration | Low | HIGH (shown: MEDIUM) | `ms_dosya_buyume` (empty result is valid) | `sys.master_files` | No data or log file grows by percentage. |
| MS-HA-001 | Database state | HA/DR | High | HIGH (shown: MEDIUM) | `ms_db_ayar` (at least one row) | `sys.databases` | All databases are ONLINE. |
| MS-HA-002 | Always On replicas | HA/DR | High | HIGH (shown: MEDIUM) | `ms_ag` (empty result is valid) | `sys.availability_groups`, `sys.dm_hadr_availability_replica_states` | All replicas are HEALTHY and CONNECTED. |
| MS-MAINT-001 | Version support | Maintenance | High | HIGH (shown: MEDIUM) | `ms_surum` (single row) | `SERVERPROPERTY` | Extended support lasts at least 90 more days. |
| MS-MAINT-002 | Integrity check (CHECKDB) | Maintenance | Medium | HIGH (shown: MEDIUM) | `ms_checkdb` (at least one row) | `DATABASEPROPERTYEX`, `sys.databases` | In every database the last successful CHECKDB is less than 14 days old. |
| MS-PERF-001 | Cost threshold for parallelism | Performance | Low | HIGH (shown: MEDIUM) | `ms_sunucu_ayar` (at least one row) | `sys.configurations` | cost threshold for parallelism is not at the default of 5. |
| MS-PERF-002 | tempdb data files | Performance | Medium | HIGH (shown: MEDIUM) | `ms_tempdb` (single row) | `sys.dm_os_sys_info`, `tempdb.sys.database_files` | On a multi-core server tempdb has more than one data file. |
| MS-PERF-003 | Long open transactions | Performance | High | MEDIUM | `ms_acik_islem` (empty result is valid) | `sys.dm_exec_sessions`, `sys.dm_tran_active_transactions` | At scan time no user transaction has been open for more than 10 minutes. |
| MS-SEC-001 | TRUSTWORTHY | Security | Medium | HIGH (shown: MEDIUM) | `ms_db_ayar` (at least one row) | `sys.databases` | No database other than msdb has TRUSTWORTHY on. |
| MS-SEC-002 | Settings that widen the attack surface | Security | High | HIGH (shown: MEDIUM) | `ms_sunucu_ayar` (at least one row) | `sys.configurations` | xp_cmdshell, Ad Hoc Distributed Queries and cross db ownership chaining are off. |
| MS-SEC-003 | The sa login | Security | Medium | HIGH (shown: MEDIUM) | `ms_sa` (single row) | `sys.sql_logins` | The sa login is disabled. |
| MS-SEC-004 | sysadmin members | Security | Info | HIGH (shown: MEDIUM) | `ms_sysadmin` (at least one row) | `sys.server_principals`, `sys.server_role_members` | The sysadmin role has no enabled members; if it has, the list is reviewed. |
| MS-SEC-005 | Password policy | Security | Medium | HIGH (shown: MEDIUM) | `ms_parola_politikasi` (single row) | `sys.sql_logins` | CHECK_POLICY is on for every enabled SQL login. |
| MS-SEC-006 | Connection encryption | Security | Medium | MEDIUM | `ms_sifreleme` (single row) | `sys.dm_exec_connections` | All TCP connections at scan time are encrypted. |
| MS-SEC-007 | Authentication mode | Security | Low | HIGH (shown: MEDIUM) | `ms_kimlik` (single row) | `SERVERPROPERTY` | Only Windows authentication is enabled. |
| MS-SEC-008 | Scan account | Security | Medium | HIGH (shown: MEDIUM) | document: `superuser` (single row) | `IS_SRVROLEMEMBER('sysadmin')` | The scan ran with a login that is not a sysadmin member. |
