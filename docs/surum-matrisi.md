# PostgreSQL version and privilege matrix

<!-- This file is generated with `python3 tarama/uret_kurallar.py`; do not edit it by hand. Source: tarama/katalog.py, docs/surum-dogrulama.json -->

The collector and the direct connection (Mode B) read the server's major version and pick that version's query for each check. On a version the check does not support the query does not run at all; the check becomes "Unavailable: not supported on this version" in the report. The matrix covers PostgreSQL 12-18; on a newer version the main query runs.

Versions on which all the queries were tested on a real server: **16**. On a version that was not tested the evidence confidence in the report is shown at most as medium (MEDIUM) and the report summary says so.

The recommended scan account is only a member of `pg_monitor` (`alig-rol.sql`). If a check requires a role inside `pg_monitor` and the account lacks it, the evidence engine counts the result as partial (the `pg_hesap` check reads the account's roles): that rule cannot be Pass.

## Checks

| Check | Versions | Required privilege | If the privilege is missing | Versions on which it ran on a real server |
|---|---|---|---|---|
| `pg_surum` | every version | everyone | - | 16 |
| `pg_sunucu_rolu` | every version | everyone | - | 16 |
| `pg_kume_kimligi` | 12 and later | everyone | - | 16 |
| `pg_hesap` | every version | everyone | - | 16 |
| `pg_kapsam` | 12 and later | everyone | - | 16 |
| `pg_xid_yasi` | 12 and later | everyone | - | 16 |
| `pg_bosta_islem` | 12 and later | pg_read_all_stats (pg_monitor) | The query runs but other users' sessions are not visible; the rule becomes Unknown. | 16 |
| `pg_baglanti` | 12 and later | pg_read_all_stats (pg_monitor) | The query runs but other users' sessions are not visible; the rule becomes Unknown. | 16 |
| `pg_olu_satir` | 12 and later | everyone | - | 16 |
| `pg_gecersiz_indeks` | 12 and later | everyone | - | 16 |
| `pg_kullanilmayan_indeks` | 12 and later | everyone | - | 16 |
| `pg_sequence` | 12 and later | everyone | - | 16 |
| `pg_sequence_gorunurluk` | 12 and later | everyone | - | 16 |
| `pg_slot` | 12 and later; separate query for 12 and earlier (the wal_status column arrived in PostgreSQL 13 and returns empty in 12) | everyone | - | 16 |
| `pg_replikasyon` | 12 and later | pg_read_all_stats (pg_monitor) | The query runs but other users' sessions are not visible; the rule becomes Unknown. | 16 |
| `pg_arsiv` | 12 and later | everyone | - | 16 |
| `pg_tls_parola` | 12 and later | pg_read_all_settings (pg_monitor) | The query fails with a privilege error; the rule becomes Unavailable. | 16 |
| `pg_md5_roller` | 12 and later | superuser | The query fails with a privilege error; the rule becomes Unavailable. | 16 |
| `pg_super_roller` | 12 and later | everyone | - | 16 |
| `pg_public_create` | 12 and later | everyone | - | 16 |
| `pg_log_ayarlari` | 12 and later | everyone | - | 16 |
| `pg_autovacuum` | 12 and later | everyone | - | 16 |
| `pg_tablo_autovacuum` | 12 and later | everyone | - | 16 |
| `pg_sorgu_istatistigi` | 12 and later | pg_read_all_settings (pg_monitor) | The query fails with a privilege error; the rule becomes Unavailable. | 16 |
| `pg_gecici_dosya` | 12 and later | everyone | - | 16 |
| `pg_eklentiler` | 12 and later | everyone | - | 16 |

## PostgreSQL 16 verification

PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), 2026-11-13. Catalog digest `bd29039b6f2f446f`.

Scenario objects were set up in a temporary cluster (an invalid index, an inactive replication slot on the primary and on the standby, dead rows and a table with autovacuum disabled, a sequence near its limit that the scan account could not read, an unused index over 10 MB, an idle open transaction, a role with an MD5 password, a database without connect privilege, a public schema with CREATE granted to PUBLIC, a sort that writes to a temporary file, pg_stat_statements if the package has it). A streaming standby was started with pg_basebackup and left behind by pausing its replay. The collector was run with three accounts on the primary and with the pg_monitor account on the standby.

| Check | pg_monitor account | Unprivileged account | Superuser | Standby server (pg_monitor) |
|---|---|---|---|---|
| `pg_surum` | 1 rows; surum_num: `160015` | 1 rows; surum_num: `160015` | 1 rows; surum_num: `160015` | 1 rows; surum_num: `160015` |
| `pg_sunucu_rolu` | 1 rows; yedek: `no` | 1 rows; yedek: `no` | 1 rows; yedek: `no` | 1 rows; yedek: `yes` |
| `pg_kume_kimligi` | 1 rows; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` | 1 rows; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` | 1 rows; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` | 1 rows; kume: `abb332a2a3a40d968bffaab14a05d892124b302414e41711386a95841cf886fc` |
| `pg_hesap` | 1 rows; pg_read_all_settings: `yes`, pg_read_all_stats: `yes`, super_kullanici: `no` | 1 rows; pg_read_all_settings: `no`, pg_read_all_stats: `no`, super_kullanici: `no` | 1 rows; pg_read_all_settings: `yes`, pg_read_all_stats: `yes`, super_kullanici: `yes` | 1 rows; pg_read_all_settings: `yes`, pg_read_all_stats: `yes`, super_kullanici: `no` |
| `pg_kapsam` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 3 rows | 2 rows, 1 databases skipped |
| `pg_xid_yasi` | 4 rows | 4 rows | 4 rows | 4 rows |
| `pg_bosta_islem` | 1 rows | 0 rows | 1 rows | 0 rows |
| `pg_baglanti` | 1 rows; kullanilan: `2`, ust: `100` | 1 rows; kullanilan: `1`, ust: `100` | 1 rows; kullanilan: `2`, ust: `100` | 1 rows; kullanilan: `1`, ust: `100` |
| `pg_olu_satir` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 2 rows | 0 rows, 1 databases skipped |
| `pg_gecersiz_indeks` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 2 rows | 2 rows, 1 databases skipped |
| `pg_kullanilmayan_indeks` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 2 rows | 2 rows, 1 databases skipped |
| `pg_sequence` | 0 rows, 1 databases skipped | 0 rows, 1 databases skipped | 2 rows | 0 rows, 1 databases skipped |
| `pg_sequence_gorunurluk` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 3 rows | 2 rows, 1 databases skipped |
| `pg_slot` | 1 rows | 1 rows | 1 rows | 1 rows |
| `pg_replikasyon` | 1 rows | 1 rows | 1 rows | 0 rows |
| `pg_arsiv` | 1 rows; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` | 1 rows; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` | 1 rows; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` | 1 rows; archive_mode: `off`, basarili: `0`, hatali: `0`, son_basari_utc: `-`, son_hata_utc: `-` |
| `pg_tls_parola` | 1 rows; password_encryption: `scram-sha-256`, ssl: `off`, ssl_min_protocol_version: `TLSv1.2` | Unavailable: no permission | 1 rows; password_encryption: `scram-sha-256`, ssl: `off`, ssl_min_protocol_version: `TLSv1.2` | 1 rows; password_encryption: `scram-sha-256`, ssl: `off`, ssl_min_protocol_version: `TLSv1.2` |
| `pg_md5_roller` | Unavailable: no permission | Unavailable: no permission | 1 rows; sayi: `1` | Unavailable: no permission |
| `pg_super_roller` | 1 rows | 1 rows | 1 rows | 1 rows |
| `pg_public_create` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 3 rows | 2 rows, 1 databases skipped |
| `pg_log_ayarlari` | 3 rows | 3 rows | 3 rows | 3 rows |
| `pg_autovacuum` | 2 rows | 2 rows | 2 rows | 2 rows |
| `pg_tablo_autovacuum` | 2 rows, 1 databases skipped | 2 rows, 1 databases skipped | 2 rows | 2 rows, 1 databases skipped |
| `pg_sorgu_istatistigi` | 1 rows; izleme: `top`, shared_preload_libraries: `pg_stat_statements` | Unavailable: no permission | 1 rows; izleme: `top`, shared_preload_libraries: `pg_stat_statements` | 1 rows; izleme: `top`, shared_preload_libraries: `pg_stat_statements` |
| `pg_gecici_dosya` | 5 rows | 5 rows | 5 rows | 5 rows |
| `pg_eklentiler` | 3 rows, 1 databases skipped | 3 rows, 1 databases skipped | 4 rows | 3 rows, 1 databases skipped |

Rule statuses: the same documents were evaluated with today's rule engine (`tests/veri/surum/16/`).

| Rule | pg_monitor account | Unprivileged account | Superuser | Standby server (pg_monitor) |
|---|---|---|---|---|
| PG-BACKUP-001 | Warning | Warning | Warning | Not applicable: not evaluated on a standby: scan the primary |
| PG-CAP-001 | Pass | Unknown: partially measured: the scan account lacks the required role (pg_monitor) | Pass | Pass |
| PG-CAP-002 | Unknown: partially measured: some databases on the server were not scanned | Unknown: partially measured: some databases on the server were not scanned | Fail | Unknown: partially measured: some databases on the server were not scanned |
| PG-HA-001 | Fail | Fail | Fail | Fail |
| PG-HA-002 | Pass | Unknown: partially measured: the scan account lacks the required role (pg_monitor) | Pass | Not applicable: no replicas are fed by this server |
| PG-MAINT-001 | Pass | Pass | Pass | Pass |
| PG-MAINT-002 | Pass | Pass | Pass | Pass |
| PG-MAINT-003 | Warning | Warning | Warning | Not applicable: not evaluated on a standby: scan the primary |
| PG-MAINT-004 | Fail | Fail | Fail | Fail |
| PG-MAINT-005 | Warning | Warning | Warning | Not applicable: not evaluated on a standby: scan the primary |
| PG-MAINT-006 | Pass | Pass | Pass | Pass |
| PG-MAINT-007 | Warning | Warning | Warning | Warning |
| PG-MAINT-008 | Pass | Pass | Pass | Pass |
| PG-PERF-001 | Pass | Unknown: partially measured: the scan account lacks the required role (pg_monitor) | Pass | Pass |
| PG-PERF-002 | Pass | Unavailable: no permission | Pass | Pass |
| PG-PERF-003 | Warning | Warning | Warning | Pass |
| PG-SEC-001 | Fail | Unavailable: no permission | Fail | Fail |
| PG-SEC-002 | Pass | Unavailable: no permission | Pass | Pass |
| PG-SEC-003 | Unavailable: no permission | Unavailable: no permission | Warning | Unavailable: no permission |
| PG-SEC-004 | Warning | Warning | Warning | Warning |
| PG-SEC-005 | Pass | Pass | Warning | Pass |
| PG-SEC-006 | Warning | Warning | Warning | Warning |
| PG-SEC-007 | Warning | Warning | Warning | Warning |

## Repeating the verification

With the directory that holds the `initdb`, `pg_ctl` and `postgres` files of each PostgreSQL version, as a user who is not root:

```sh
python3 tarama/surum_dogrula.py --pg-bin /usr/lib/postgresql/18/bin --cikti docs/surum-dogrulama.json --belge-dizini tests/veri/surum
python3 tarama/uret_kurallar.py
```

The tool connects only to the temporary cluster it set up itself and deletes it at the end. The result is appended to `docs/surum-dogrulama.json`; if all the queries ran on that version, the version is added to the `SINANAN` list in `tarama/katalog.py` (`tests/test_surum.py` checks the evidence).
