# Health scan: design and threat model

Status: Mode A is live for PostgreSQL. Mode A for SQL Server is coded as a preview, has not been tested on a real server and is off by default (`docs/mssql-onsurum.md`). Mode B, e-mail verification and the language model summary come in later slices.

## Default decisions (until a reply arrives from you)

| Topic | Default | To change it |
| --- | --- | --- |
| Product name | None; the page says "alig.tech Sağlık taraması" (health scan) | i18n keys `tarama_*` |
| Language model | Off (`LLM_PROVIDER=none`), no code | Later slice |
| Free scan limit | 5 uploads per hour per IP. A per-company limit will come with e-mail verification | `tarama/server.py` `RateLimiter` |
| Report retention | 30 days, with a "delete now" button | `SAKLAMA_GUN` |
| Egress IP address | No Mode B, not needed | Mode B slice |
| E-mail sending | None. The report link is shown in the upload response | When a sending method is chosen |
| MySQL | None, shown as "on the roadmap" in the UI | The catalog is per engine, easy to add |

## Data flow (Mode A)

1. The company downloads `alig-toplayici.py` (the collector) from the site (the fixed SHA-256 is written on the page) and runs it on its own network.
2. The script runs the fixed query catalog with `psql` and writes a single JSON file. It sends nothing to the network.
3. The company reads the file (if it wishes, it has replaced object names with aliases using `--maskele`) and uploads it to the site.
4. The server validates the file with a strict schema, produces findings with the rules and one evidence record for every rule (below), stores the report, and gives a random link.
5. Every step is written to the SHA-256 chained audit record.

The web process connects to no customer database. In Mode A the only thing that connects is the script on the company's own machine.

## Evidence model and statuses

Every rule (with a permanent ID such as `PG-SEC-001`) produces a single evidence record in each scan: status, severity, category, confidence
level, the source read, collection time, observed values and findings (`tarama/kanit.py`). Both engines use the same format.
The rule list, categories, confidence levels and pass conditions: `docs/kural-katalogu.md` (generated from the code, checked by a test).

- **PASS** appears only when all sources arrived completely and there are no findings. If the collection check did not run, it is
  **UNAVAILABLE**; if data arrived but the format is broken, a required value is empty, an expected row is missing, a database was not scanned or an additional
  source did not arrive, it is **UNKNOWN**. For this reason evidence that disappears in a comparison with history is not counted as resolved.
- If there is a finding, even when coverage is partial, **FAIL** (critical, high) or **WARNING** (medium, low, info) is returned.
- **NOT_APPLICABLE** rests only on data: no replication slot, no Always On, an Azure managed service, no TCP connection.
- A confidence level is given in cases that have evidence. Because SQL Server is a preview, the report shows at most MEDIUM.
- Records are not stored; like findings, they are regenerated from `belge_json` when read.

## Version and privilege matrix

The collector and Mode B read the server's major version; according to each check's `en_az` (minimum), `en_cok` (maximum) and `eski_surum` (old version) fields they pick the
query for that version, and on an unsupported version they do not run the query at all (`desteklenmiyor`, unsupported). The `yetki` (privilege) field of each check writes the role needed for a correct
result; the `pg_hesap` check reads the roles of the scan account and if a role is missing, a rule using that source cannot be
Passed. On real PostgreSQL 16 an unprivileged account could not see other users' sessions; for this reason the idle transaction and
connection saturation rules need `pg_read_all_stats`. Matrix and verification: `docs/surum-matrisi.md`.

## Data model (SQLite, WAL, UTC)

- `rapor(id, token_sha256, olusturma_utc, bitis_utc, motor, surum_num, dil, belge_json)`: `belge_json` is the validated collection file. Findings are regenerated when read; this way rule fixes also apply to old reports.
- `firma(id, anahtar, ad, eposta, durum, kaynak, aciklama, kayit_utc, son_utc)`: the key is the domain name for a corporate address and the full address for free mail. `durum` (status) is aktif (active) or pasif (inactive); an inactive company cannot upload (403). It matches `rapor.firma_id`.
- `kullanim(anahtar_sha256, zaman_utc)`: counting for the limit of 2 scans in 30 days.
- `denetim(seq, zaman_utc, aktor, olay, onceki, ozet)`: ozet = SHA-256(`seq|aktor|olay|onceki`). Verification: `python3 tarama/depo.py dogrula <db>`.
- The schema version is kept with `PRAGMA user_version`, forward-only migration.

## Threat model

| Threat | Measure | Test |
| --- | --- | --- |
| Writes on the customer database | Static checking of the catalog (only `SELECT`, a forbidden word list), `default_transaction_read_only=on`, 15 s query timeout | `test_katalog_*` |
| Running as a superuser | The script warns and writes `superuser:true` to the collection file, and it becomes a finding in the report | `test_superuser_bulgusu` |
| Leak of row data | There is no user table query in the catalog; columns are fixed in the schema; the upload rejects an unknown column | `test_yukleme_bilinmeyen_kolon` |
| HTML or instructions in object names | The report writes all values with `html.escape`. There is no model. Column values are limited to 200 characters | `test_rapor_kacis` |
| Malicious or huge upload | 5 MB limit, content type check, strict schema, row count limit, type check | `test_yukleme_*` |
| Guessing the report link | 32 bytes of `secrets.token_urlsafe`, only the SHA-256 in the database | `test_token_saklanmaz` |
| Denial of service | Per-IP rate limit, body limit, low CPU of the single-threaded work | `test_hiz_siniri` |
| Tampering with the audit record | SHA-256 chain, verification command | `test_zincir_*` |
| Password leak | The script does not take a password (`PGPASSFILE`/environment), there is no connection information in the collection file | `test_toplayici_dosyasinda_baglanti_yok` |
| Old collector version | If the catalog digest does not match the upload is rejected | `test_yukleme_katalog_ozeti` |

The threat model and pending decisions for Mode B (direct connection): `docs/kip-b-tasarim.md`. No code was written.

## Known limits

- `pg_authid` (MD5 roles) and `pg_hba_file_rules` can be read only by a superuser. With a `pg_monitor` privileged role, PG-SEC-003 returns "Could not be obtained: no privilege" (UNAVAILABLE). This is deliberate: it is not clean, it could not be measured.
- A database the scan account cannot connect to (including the internal databases of managed services) makes the per-database rules UNKNOWN. The report's scope section lists the skipped databases with their reasons.
- Backup recoverability, the operating system, the network and application queries are outside the scan; the report says so.
- Some thresholds are not in an official document; they are marked `MUHENDISLIK` (engineering judgement) in `tarama/kurallar.py` and are in the list in `docs/doldurulacak.md`.
- SQL Server has no session-level read-only mode. What prevents writing is the privileges of the login (only `VIEW SERVER STATE` and `VIEW ANY DEFINITION`) and the static check of the catalog (`tests/test_mssql.py`).
