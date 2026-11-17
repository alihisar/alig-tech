# Migration to PostgreSQL (ALIG-DB-001)

Source: `docs/master-prompt-v5.md` (includes v4.1). This document is the architecture and migration plan; no code tied to the application has been written yet (only the driver evaluation prototype `ortak/pg.py` exists, section 2).
Source: `docs/master-prompt-v5.md` (includes v4.1). This document is the architecture and migration plan. The schema and roles (ALIG-DB-003a) were written under `db/` and tested on PostgreSQL 16; the application code still uses SQLite.
PASS in the status columns is written only for tests that were run on a real PostgreSQL.

Goal: all persistent data of the application in a single PostgreSQL 18 database (`aligtech`). There is no fallback to SQLite:
if PostgreSQL is unreachable, write operations stop with a controlled error. The customers' scanned PostgreSQL servers are a
security domain separate from this database; the scan collector (`alig-toplayici.py`, via `psql`) is not affected by this migration.

## 1. Current state (inventory, 2026-11-15, commit 1569edd)

| Source | File | Tables | Code |
| --- | --- | --- | --- |
| Scan database | `tarama.sqlite` | rapor, denetim (SHA-256/HMAC chain), kullanim (quota), firma, firma_silinen, baglanti_istegi, posta (outbox), esitleme, portal_kullanici, portal_kod, portal_oturum, portal_deneme, portal_talep | `tarama/depo.py` (688 lines), `tarama/portal_depo.py` |
| Admin database | `yonetim.sqlite` | kullanici (scrypt password, TOTP secret, TOTP counter), oturum (SHA-256 digest of the code), giris_denemesi, giris_ip, talep_durum, denetim (chain) | `yonetim/depo.py`, `yonetim/server.py` |
| Contact form | `form.sqlite` | contact | `form/server.py` |
| Backup and maintenance | - | SQLite backup API, integrity check, restore | `deploy/bakim.py` |
| Rate limit | in memory | - | `form/server.py` `RateLimiter` |

`firma_yeni` and `rapor_yeni` are only intermediate tables of old migrations. Record counts will be measured from live data
(ALIG-DB-004 Phase A); since there is no access to the live server this is **NOT_RUN** for now.

## 2. Driver decision (DB-K1)

| Criterion | A: `psql` subprocess | B: `ctypes` + `libpq.so.5` | C: `psycopg` |
| --- | --- | --- | --- |
| External Python package | none | none | yes (breaks the rule) |
| Operating system dependency | `postgresql-client` | `libpq5` (Ubuntu package) | `libpq5` or a binary wheel |
| TLS, SCRAM | yes | yes (libpq) | yes |
| Parameterized query | no (`psql -v` escaping, not server-side binding) | `PQexecParams`: server-side binding | yes |
| Transaction (BEGIN/COMMIT) across multiple queries | no, every call is a separate process | yes | yes |
| Timeout, cancel | killing the process | `connect_timeout`, `statement_timeout`, `PQcancel` | yes |
| Memory leak risk | low | `PQclear`/`PQfinish` discipline; measured on PG16: 0 KB RSS growth over 20,000 queries | low |
| Maintenance cost | low but insufficient | medium (a narrow wrapper: the prototype `ortak/pg.py` is 468 lines, comments and docstrings included) | low |
| Windows development | yes | needs `libpq.dll` (note below) | yes |

Measurement (ALIG-DB-002, PG16 temporary cluster, Unix socket, scram-sha-256, a non-superuser role, libpq 16.15; since it is a local socket
it contains no network or TLS cost; single machine, single run, rough values):

| Measurement | Result (PG16) |
| --- | --- |
| Connection setup (SCRAM + 4 session settings) | ~10 ms (median, 30 tries) |
| Parameterized `SELECT $1::int, $2::text`, persistent connection | ~19 µs median, ~61 µs p99 (2000 queries) |
| `psql -c` subprocess, a single `SELECT 1` | ~13 ms median (20 tries); includes connection setup, the comparison is only for order of magnitude |
| 5000 `INSERT`s in a single transaction | 0.2 s |
| Reading 5000 rows and converting to Python | ~29 ms |
| RSS growth, 20,000 queries (2000-character parameter) | 0 KB |
| Test cluster setup + 25 tests | ~7 s |

Behaviors of the prototype that gave PASS on PG16 (`tests/test_pg_prototip.py`, 25 tests): connection and a non-superuser role;
parameter binding with `PQexecParams` (an injection attempt stays a value); NULL and Turkish character round trip
(an empty string does not turn into NULL); `timestamptz` round trip (a `datetime` without a time zone is rejected); transaction, rollback on an exception and on an SQL
error; error class by SQLSTATE (`23505` -> `BenzersizlikHatasi`); cancel with `statement_timeout` and `PQcancel` from another
thread (`57014`); no password in the error text on a wrong password; `BaglantiHatasi` when the server stops and on an interruption in the
middle of a transaction (not retried, the transaction is not counted as successful); bounded RSS in a 1000-query loop; two
threads running in parallel with separate connections; sharing the same connection between threads is rejected.

Details seen in the measurement and built into the prototype (the real cost of B compared with C):
- When the server shut down the first error result came without an SQLSTATE and `PQstatus` did not immediately look broken; looking only at `PQstatus` mistook the interruption for
  a server error. Rule: an error without an SQLSTATE, `08xxx` and `57P01-03` count as connection loss.
- The error text is written only from the primary message and the SQLSTATE, instead of `PQresultErrorMessage` (DETAIL can contain row values).
- The `PQcancel` object is obtained when the connection is made; cancel is called safely from another thread.
- If the parameter type cannot be inferred the server gives an error (`SELECT $1`); a type cast like `$1::text` is needed in the query.
- Results are in text form; only bool, integer, float, numeric and `timestamptz` are converted to a Python type (the rest are `str`).

Not tested: PostgreSQL 18 (BLOCKED, not in the environment), TCP and TLS connections, a real network interruption, a leak run longer than 1000,
a connection pool, memory with large multi-column results, Windows `libpq.dll`.

Recommendation **B** (supported with evidence for DB-K1): a single shared connection layer `ortak/pg.py` (connection, parameter binding, transaction,
rollback, timeout, error classification, secret masking). Rationale: it does not break the external package rule (C is eliminated); A has no
multi-query transactions or server-side parameter binding, so the quota and audit chain transactions (section 4) cannot be
written with A; B provides these at ~19 µs query cost and bounded memory. Risk: a ctypes signature error can crash the process; for this
reason the wrapper is kept narrow, signatures are defined in one place and the tests run on every version. Retry is done only when a connection
is being made; a transaction is not blindly repeated (v5.1: retry only in read-only transactions or in writes with an idempotency key). A protocol driver is not written from scratch. `libpq5` and its version are
explicitly installed and documented in `deploy/`. The decision DB-K1 belongs to its owner; this section is a recommendation.

Windows note: `libpq.dll` (from the PostgreSQL client distribution) and its dependencies (`libssl`, `libcrypto`, `libintl`, etc.) must be on `PATH`
or the full path must be given with the `ALIG_LIBPQ` environment variable. The prototype was not run on Windows; only the loading
candidates (`libpq.dll`) are in the code. Production is on Ubuntu, Windows is only for development.

## 3. Data model

The existing table names are kept (the English names in v5 section 7 are a logical counterpart, not an instruction for new tables):

| v5 logical table | Existing counterpart | Note |
| --- | --- | --- |
| companies | firma | `durum` CHECK, unique key |
| admin_users, admin_sessions | kullanici, oturum | the session code only as its digest; the TOTP secret is handled separately (ALIG-SEC-001) |
| scan_results | rapor | token unique, `firma_id` foreign key |
| scan_quotas, quota_transactions | kullanim | the quota is not a counter but a sliding window: at most 2 usage records in the last 30 days (`SINIR_GUN`, `SINIR_ADET`) |
| scan_jobs | baglanti_istegi (Mode B) | job queue: item 21, `FOR UPDATE SKIP LOCKED` |
| audit_events | denetim (two chains) | no UPDATE/DELETE in the application role; the chain tail is ordered with a lock; the canonical format does not change |
| contact_requests | contact | |
| verification_requests | portal_kod and the company verification code | single use |
| outbox_events | posta | the intent to send in the same transaction as the business data |
| idempotency_keys | new | in upload and scan start; the same key with different content is rejected |
| schema_migrations | instead of `PRAGMA user_version` | |

Schema SQL files and decisions: `db/sema/*.sql`, `db/README.md` (ALIG-DB-003a, PASS on PG16). So that the admin chain does not clash in a single schema
it took the name `yonetim_denetim`; `rapor.belge_json` stayed text (rationale in `db/README.md`).

All times are `timestamptz` (UTC). Schema: `alig`. Roles: `alig_owner` (NOLOGIN, object owner), `alig_app` (DML,
no BYPASSRLS/CREATEDB/CREATEROLE/REPLICATION), `alig_migrator` (DDL, only during migration), `alig_readonly`,
`alig_backup`. CREATE on the `public` schema is removed, `search_path` is pinned.

## 4. Transaction rules

Company create/update/deactivate/delete, session revocation, quota decrement and reset, scan start/finish/cancel,
email verification, report deletion and audit record writing are done in a single transaction. Today in SQLite most of it is also in a single transaction
(`depo.islem`, item 28); in the migration the same boundaries are kept and proven by a test on PostgreSQL.

Quota: since today's model is a sliding window, the v5 pattern `UPDATE ... SET remaining = remaining - 1 WHERE remaining > 0`
does not fit directly. The equivalent on PostgreSQL: in the same transaction `pg_advisory_xact_lock` on the quota key (or
`SELECT ... FOR UPDATE` on the company row), count the records in the window, and if below the limit insert the usage record. The idempotency record, the report
record and the audit record are in the same transaction; two parallel uploads cannot exceed the limit (test: two concurrent clients). If the connection drops in the middle of a transaction, success is not declared, it is
reconciled with the idempotency record.

### 4.1 Store implementation and settings (ALIG-DB-003c)

`tarama/depo_pg.py` and `tarama/portal_depo_pg.py` have the same public functions as the SQLite stores. A process uses them only when an
`ALIG_DB_*` variable is present (`ortak/pg_ayar.py`, the one place that parses them); otherwise the SQLite store stays. If PostgreSQL is
configured but the settings are wrong or the server is unreachable at start, the process stops with a clear error; it never falls back to SQLite.

| Variable | Meaning |
| --- | --- |
| `ALIG_DB_HOST` | required; a directory starting with `/` is a Unix socket directory, otherwise a TCP host |
| `ALIG_DB_PORT`, `ALIG_DB_NAME`, `ALIG_DB_USER` | default `5432`, `aligtech`, `alig_app` (`postgres` is rejected) |
| `ALIG_DB_PAROLA_DOSYASI` | file with the password (mode 0600); required over TCP; the password is never in the environment |
| `ALIG_DB_SSLMODE`, `ALIG_DB_SSLROOTCERT` | TCP only: `verify-full` (the only accepted value) and the CA file (required) |

Locks (advisory, transaction scoped, released by commit, rollback or a dropped connection). Order everywhere: company row, quota,
e-mail registration, audit chain. Quota: `pg_advisory_xact_lock(7431, hashtext(company key digest))` is taken before the window is counted and
held until the transaction ends. Audit chain: `pg_advisory_xact_lock(7432, 1)` (scan chain; `2` is reserved for the admin chain). The
quota stays a sliding window; `kota_al` does lock + count + insert in one transaction, and the existing upload code
(`kullanim_tekrar`, `kullanim_say`, `kullanim_ekle`) takes the same lock whenever it runs inside a transaction.

## 5. Migration phases (ALIG-DB-004)

A inventory (row count, chain verification) -> B schema and migration role -> C rehearsal on a copy (row count, canonical
digest comparison, NULL/empty string, boolean, timestamptz, Turkish characters, token uniqueness, foreign key,
audit chain, quota consistency) -> D cutover (only with DB-K4 approval). SQLite files are not deleted until success is verified.
`sqlite3` is read only in the isolated migration tool; this tool is not packaged into the runtime and is removed after cutover.
Going back to SQLite after cutover loses data written after cutover; this limit is written in the cutover report.

Added to Phase C with v5.1: after import every sequence is pulled to the largest ID with `setval`; record and event
IDs are kept (the audit chain is tied by ID, if regenerated the chain breaks and `MIGRATION_GATE = FAIL`); chain
verification is run separately on the source and the target; uniqueness clashes (email) arising from the SQLite `NOCASE` and Turkish I/i difference
are reported; orphan records that arose while `foreign_keys` was off are moved to a quarantine table, not silently deleted, a human
decides; that time values without a time zone are UTC is verified from code; the three SQLite stores (form, admin, scan) are merged into a single
database and company deletion + contact requests + KVKK deletion request become a single transaction (atomicity test). The migration tool
runs as a single copy with an advisory lock, only goes forward, and stores the digest of the applied file (`db/uygula.py` already does this).
Schema changes follow the expand/contract pattern: the old code can work with the new schema, a destructive change is in a separate
release. In Phase D the write freeze is done with maintenance mode (OPS-K1, ALIG-OPS-002) and verified by the source digest not changing.

## 6. Backup and restore (ALIG-DB-005)

`pg_basebackup` + WAL archive (for PITR); PITR is not claimed with `pg_dump` alone. Retention, restore drill; RTO is measured only by a
drill. `BACKUP_RESTORE_VERIFIED` is `false` until a drill is done.

Tool: `db/yedek.py` (stdlib; calls the PostgreSQL CLI tools as subprocesses; not tied to the application or `deploy/bakim.py`).
- `al`: with `pg_basebackup -X stream` as the `alig_backup` role (REPLICATION only; the password is not on the command line, `PGPASSFILE`
  or a socket), plain or tar format, SHA-256 manifest; then `pg_verifybackup`. The backup does not get its final name until verification passes
  (`pg-<UTC>.devam` is a partial backup and is deleted on error). The tar format cannot be verified directly with `pg_verifybackup` before PG18;
  the tool unpacks it to a temporary directory and verifies.
- `dogrula`: `pg_verifybackup`. `geri-yukle`: unpacks only to an empty (or nonexistent) target directory; it does not write to a full directory,
  the data directory of a running cluster, or into/over the backup; without `--evet` it only writes a plan and writes nothing. If a WAL archive is given,
  `recovery.signal` + `restore_command` (+ optional `recovery_target_time`, time zone required, `promote`) are added;
  `archive_mode = off` is written in the restored cluster so it does not corrupt the source's archive. The cluster is not started. `eskileri-sil`: keeps the newest
  N backups (without `--evet` it lists). `arsiv-onerisi`: writes the `archive_command` text, does not touch the server.
- WAL archive command: `test ! -f ARCHIVE/%f && cp %p ARCHIVE/%f.gecici && mv ARCHIVE/%f.gecici ARCHIVE/%f` (does not overwrite an existing one,
  atomic). It was used only in the documents and the test cluster; not applied to a live server. Deleting old WAL archive files
  (`pg_archivecleanup`, based on the starting WAL of the oldest retained backup) is done by hand; the tool does not delete WAL.
- Encryption: no code written (DB-K6). Default: the backup directory on an encrypted volume, 0700.
- No RPO/RTO target is written (DB-K5). The time measured in the drill is for local PG16 and small data; it is neither a target nor a live RTO.
- The option to move to pgBackRest is in the DB-K5 note; it was not installed.

## 7. Test matrix and status

| Test | Expected | Status |
| --- | --- | --- |
| SQLite runtime dependency | NONE | FAIL (SQLite is used today; ALIG-CI-001 adds a check after cutover) |
| PostgreSQL connection | PASS | PASS on PG16 (prototype) |
| Parameterized SQL | PASS | PASS on PG16 (prototype) |
| Transaction rollback | PASS | PASS on PG16 (prototype) |
| Foreign key, uniqueness, CHECK | PASS | PASS on PG16 (`tests/test_pg_sema.py`; including company deletion cascade) |
| Parallel quota consumption | ATOMIC | ATOMIC on PG16 (`tests/test_pg_depo_yerel.py` `PgKotaTests`: 16 concurrent connections x 4 rounds, forked processes, several companies at once, the real upload transaction `_yukleme_isle`; allowance never exceeded; a lock-free control run does exceed it) |
| Idempotency | PASS | PASS on PG16 for the store function `idempotency_kaydet` (new / same request returns the stored result / same key with different content rejected; concurrent same key gives one new; rolled back with the business transaction; `PgIdempotencyTests`). NOT_RUN: reading an `Idempotency-Key` from HTTP requests (not wired yet) and the same-document repeat of the quota, which is PASS (`kota_al` returns `tekrar`) |
| Company isolation | PASS | PASS on PG16 (the existing isolation tests of `tests/test_portal.py` re-run on `tarama/portal_depo_pg.py`: `tests/test_pg_depo.py` `PgIzolasyonTests`, plus a static guard on the PostgreSQL portal source) |
| RLS bypass attempt | DENY | NOT_APPLICABLE (DB-K3: portal off, RLS later) |
| PostgreSQL connection interruption | SAFE FAILURE | PASS on PG16 (prototype) |
| DML with the read-only role, DDL with the application role | DENY | PASS on PG16 (42501; UPDATE/DELETE/TRUNCATE on the audit tables are also DENY) |
| Schema migration: all files, re-run, a changed old file | PASS | PASS on PG16 (`db/uygula.py`; 0006 added by ALIG-DB-003c) |
| Existing scan and portal store tests on PostgreSQL | PASS | PASS on PG16 (`tests/test_pg_depo.py`: DepoTests, portal Kayit/Giris/Izolasyon/PortalIslem, OncekiRapor, outbox, and the HTTP server classes of the scan, portal, history and Mode B tests; 17 SQLite-specific tests skipped with a reason each and re-tested natively where it matters). Run as the superuser; least privilege run: `PgUygulamaRoluTests` (alig_app) |
| Audit chain: concurrent writers, tail lock | PASS | PASS on PG16 (`PgZincirTests`: 6 threads + 3 processes, no lost record or branch; tamper detection; the application role cannot UPDATE/DELETE the chain, SQLSTATE 42501) for the scan chain; the admin chain is ALIG-DB-003d |
| Migration row count and digest | MATCH | NOT_RUN |
| Restore | VERIFIED | The drill passed on PG16 (`tests/test_pg_yedek.py`: full backup, `pg_verifybackup`, PITR restore to a timestamp, audit chain intact, corrupt backup rejected, full target rejected, dry run); not VERIFIED on a live server |
| Secret masking | PASS | PASS on PG16 (prototype; the password is not in the error text or repr) |

Test layout (ALIG-CI-001): PostgreSQL tests use the shared temporary cluster `tests/pg_yardimci.py` (initdb, free port,
Unix socket, `trust` or `scram-sha-256`, role and database, stop and delete; even if the process dies with SIGKILL a watchdog process
stops the server and deletes the directory). If there is no system PostgreSQL 16 the tests SKIP. The 6 tests that require `ALIG_TEST_PG_HOST`
(`GercekPgTests`, `GercekPgOturumTests`) now run with a temporary cluster if the variable is not given (PASS on PG16); if the variable
is given, the external server is used. `ci/run_all.py` reports these separately in the "postgresql tests" step with PASS/FAIL/SKIP and the version;
if PostgreSQL is missing the step says "skipped" (not counted as success) and gives an error with `--release`.

Environment note: in this development environment only the system PostgreSQL 16 exists. Downloading a PostgreSQL 18 binary was not
permitted; tests on PG18 are **BLOCKED**. A test that passes on PG16 is written as "PASS on PG16", it does not count as PASS for PG18.

Evidence record (v5.1 §23): for every PASS the evidence ID, UTC time, commit, full command, working directory, environment (operating
system, Python, PostgreSQL and libpq versions), exit code and output path are written. The PostgreSQL step in CI (`ci/pg_adimi.py`)
summarizes the version and the PASS/FAIL/SKIP counts; at the release gate (`--release`) a skipped PostgreSQL test is an error.

## 8. Gates

`POSTGRESQL_GATE = FAIL` (SQLite in the runtime), `MIGRATION_GATE = NOT_RUN`, `BACKUP_RESTORE = the PG16 drill passed, NOT_RUN on a live server` (`BACKUP_RESTORE_VERIFIED = false`: the live server drill, the encryption decision DB-K6 and the RPO/RTO decision DB-K5 are pending),
therefore `PRODUCTION_READY = false`.

## 9. While PostgreSQL is unreachable (the OPS-K1 default)

| Component | Behavior |
| --- | --- |
| Static site | nginx keeps serving |
| `/healthz` | liveness: passes if the process is alive |
| Readiness, `/api/tarama/saglik` | 503 |
| Form, upload, portal, admin, report | 503 + Retry-After, a safe error page, no data loss |

There is no fallback to SQLite at any endpoint. Maintenance mode (`ALIG_BAKIM`, ALIG-OPS-002) uses the same page.
