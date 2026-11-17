# db: PostgreSQL schema and roles (ALIG-DB-003a)

This directory holds the application's PostgreSQL schema and the migration tool. **It is not connected to the application**: the runtime still
uses SQLite (`tarama/depo.py`, `yonetim/depo.py`, `form/server.py` are unchanged). Because the driver decision (DB-K1) has not been made,
there is no Python connection code; the schema is installed with SQL files and verified with `psql`. Architecture and migration plan:
`docs/postgresql-gecis.md`.

## Files

| File | Content | Applied by |
| --- | --- | --- |
| `sema/0001_roller.sql` | Five roles, database privileges, removal of CREATE on the `public` schema, the `alig` schema, `schema_migrations` | An administrator with CREATEROLE (first installation) |
| `sema/0002_tarama.sql` | `firma`, `firma_silinen`, `rapor`, `kullanim`, `denetim`, `baglanti_istegi`, `posta`, `esitleme`, `portal_*` | `alig_migrator` |
| `sema/0003_yonetim_form.sql` | `kullanici`, `oturum`, `giris_denemesi`, `giris_ip`, `talep_durum`, `yonetim_denetim`, `contact` | `alig_migrator` |
| `sema/0004_idempotency.sql` | `idempotency_anahtari` | `alig_migrator` |
| `sema/0005_yetkiler.sql` | Table and column privileges | `alig_migrator` |
| `sema/0007_sinir_sayac.sql` | `sinir_sayac`: atomic rate-limit window counters (ALIG-DB-003e), with its own privileges | `alig_migrator` |
| `sema/0006_firma_surec.sql` | `firma.surec`, `surec_notu`, `surec_utc` (commercial process; missing from 0002, found by ALIG-DB-003c) | `alig_migrator` |
| `uygula.py` | A tool that applies the migration files in order (standard library only, a `psql` subprocess) | operator |
| `yedek.py` | Physical backup (`pg_basebackup`), verification, restore into an empty directory/PITR, retention (ALIG-DB-005; `docs/postgresql-gecis.md` section 6, `docs/runbook.md`) | operator (with the `alig_backup` role) |

## Roles

| Role | Login | Privileges |
| --- | --- | --- |
| `alig_owner` | none (NOLOGIN) | Owner of all objects in the `alig` schema |
| `alig_app` | yes | Only the DML the code performs (separately per table). Only INSERT and SELECT on the audit tables. No DDL |
| `alig_migrator` | yes | Performs DDL by switching to the `alig_owner` role (SET ROLE, no inheritance); adds rows to `schema_migrations` |
| `alig_readonly` | yes | SELECT on selected tables and columns (password, TOTP, token digest, report document, e-mail, message text are not given) |
| `alig_backup` | yes | Only REPLICATION (`pg_basebackup`); no privilege to connect to the database and no table privileges |

No role has SUPERUSER, CREATEDB, CREATEROLE or BYPASSRLS; REPLICATION is only on `alig_backup`. Roles
belong to the cluster, so `0001` can be re-applied in other databases in the same cluster (e.g. staging).
For `alig_app`, `alig_migrator` and `alig_readonly`, `search_path` is fixed to `alig, pg_catalog` and `TimeZone` to `UTC` at the role
level. CREATE on the `public` schema was removed; PUBLIC's CONNECT and TEMP privileges on the database were removed, and
only the three roles can connect. Identity sequences do not need a separate sequence privilege.

## Password

**No password is written** to the files; the roles are created without a password; until a password is given they cannot log in with the password method (`scram-sha-256`). The password is given after the installation in a separate
step, in a `psql` session connected as an administrator:

1. `psql` is opened as an administrator (socket, `-X`).
2. For each LOGIN role the command `\password alig_app`, `\password alig_migrator`, `\password alig_readonly`, `\password alig_backup`
   is run. The password is read from the prompt and hashed with SCRAM on the client side; no plain text falls into the command history or the server
   log. (Do not write an `ALTER ROLE ... PASSWORD` statement with a plain-text password in a script or on the command line.)
3. The passwords are given in the service environment with `~/.pgpass` or `PGPASSFILE` (file permission 0600); `uygula.py` does not take a
   password on the command line.
4. On the server the password hashing method is `scram-sha-256` and in `pg_hba.conf` these roles are allowed with `scram-sha-256` (`trust`
   is not used); a `replication` line is also needed for `alig_backup`. This setting is server administration (DB-K2) and is not
   changed here.

## Migration tool

```
PGHOST=/var/run/postgresql PGDATABASE=aligtech PGUSER=<administrator> python3 db/uygula.py     # first installation, including 0001
PGHOST=/var/run/postgresql PGDATABASE=aligtech PGUSER=alig_migrator python3 db/uygula.py  # later migrations
```

- `PGHOST`, `PGDATABASE`, `PGUSER` are required, `PGPORT` is optional. The password is not put on the command line.
- Files are named `NNNN_name.sql` and numbered without gaps; if a name or number is wrong the tool stops.
- Each file runs in a single transaction (`psql -X -1 -v ON_ERROR_STOP=1`); the `schema_migrations` row (version, application time,
  file SHA-256) is written in the same transaction. A file that is interrupted leaves no trace. Two appliers at the same time queue up with the advisory
  lock taken at the start of the transaction.
- A second run applies nothing new (`yeni göç yok`, no new migration).
- If the digest of an already applied file has changed or the file has been deleted, it stops **without applying anything**. An old file
  is not modified; a fix is made with a new migration file.
- The first statement of the migration files (except 0001) is `SET ROLE alig_owner;`: whichever role applies the migration, the objects
  belong to `alig_owner`. A migration that adds a new table also writes its own privileges.

## Decisions

- **Table names** are the existing SQLite names. The only exception: the admin chain was also called `denetim` (a separate SQLite file);
  so that they do not collide in a single schema it became `yonetim_denetim`. The temporary migration tables (`firma_yeni`, `rapor_yeni`) were not carried over.
- **Types:** `bigint GENERATED BY DEFAULT AS IDENTITY` primary key (like AUTOINCREMENT in SQLite, a deleted ID is not reused;
  `DEFAULT` is so that old IDs can be carried over as they are in the ALIG-DB-004 migration, after the migration the counter is advanced with `setval`),
  `timestamptz` (UTC), `boolean`, status fields `text` + CHECK (values from the lists in the code:
  `FIRMA_DURUMLARI`, `TALEP_DURUMLARI`, the admin `DURUMLAR`, mail and connection request statuses). A 64-digit hexadecimal CHECK was put on the SHA-256 fields.
- **`rapor.belge_json` stayed `text`, not `jsonb`.** In the code the document JSON is not queried inside SQL; `rapor_listele` and
  `onceki_rapor` read it in Python with `json.loads`. The stored text is the output of `json.dumps(belge, sort_keys=True)` and
  the "canonical digest comparison" of ALIG-DB-004 will be done on this text; `jsonb` changes the key order, whitespace, number
  format (`1.0`) and duplicate keys, which would break the byte-for-byte equality of a document carried over from SQLite.
  Validity is ensured by `CHECK (belge_json IS JSON OBJECT)`. `belge_ozeti` (for the quota) is computed not from the stored text but from the Python
  object. If a need to query inside SQL arises, a generated column or a separate `jsonb` column will be added then.
- **Foreign keys and ON DELETE:** in line with the `firma_sil` (company delete) cascade: when a company is deleted `rapor`, `baglanti_istegi`,
  `portal_kullanici`, `portal_talep` and (through the user) `portal_kod`, `portal_oturum` are deleted by CASCADE. `kullanim`
  is not tied to the company by a foreign key (it matches the digest of the company key); `firma_sil` writes these rows, the `firma_silinen`
  trace and the audit record separately in the application code. There is nowhere `RESTRICT` is used.
- **`talep_durum.talep_id`** is the ID of the contact form record but no foreign key to `contact(id)` was added: in the old SQLite
  there were two separate files, so an orphan row can exist. The decision was left to the ALIG-DB-004 Phase C rehearsal.
- **Audit chains** (`denetim`, `yonetim_denetim`): the columns and the canonical digest format did not change. `seq` is the primary key
  and in the application it is computed under the lock on the last record; `UNIQUE(onceki)` prevents the chain from forking. `alig_app` gets only
  INSERT and SELECT; there is no UPDATE, DELETE, TRUNCATE. Note: the table owner and the administrator are outside this restriction; the integrity
  of the chain is additionally checked with the verification command (ALIG-DB-003d).
- **`idempotency_anahtari`:** `anahtar` (primary), `istek_ozeti`, `sonuc`, `zaman_utc`. The logic that rejects the same key
  arriving with different content is in the application code (ALIG-DB-003c); the table only enforces uniqueness and the digest format.
- **The read-only role** cannot read the `belge_json`, `token_sha256`, `eposta` columns in the `rapor` table; the `eposta` and
  `aciklama` columns in the `firma` table; the `posta`, `portal_*`, `kullanici`, `oturum` tables.

## Verification

`python3 -m unittest tests.test_pg_sema`: opens a temporary PostgreSQL 16 cluster (`initdb`, only a Unix socket, trust authentication for this cluster), applies the migrations with `uygula.py` and tests them. If PostgreSQL 16 is not available the cluster tests are skipped (SKIP). The result
is valid only for PostgreSQL 16; there is no PostgreSQL 18 binary in this environment, it was not tested on PG18.
