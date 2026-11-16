# Fields to be filled in

This list is generated with `python3 ci/check_placeholders.py --write docs/doldurulacak.md`.
If any of these fields remains in a production tag (`--release`), CI fails.

| Language | Key | Field |
| --- | --- | --- |
| tr | `sec_v_kvkk` | [doldurulacak: hukuk onayı] |
| tr | `about_todo` | [doldurulacak: kurucunun adı, deneyim yılı, profil bağlantısı] |
| tr | `foot_mail` | [doldurulacak: e-posta adresi] |
| tr | `page_pending` | [doldurulacak] |
| tr | `hz_b_hba` | [doldurulacak: alig.tech çıkış IP adresi] |
| en | `sec_v_kvkk` | [doldurulacak: legal review] |
| en | `about_todo` | [doldurulacak: founder's name, years of experience, profile link] |
| en | `foot_mail` | [doldurulacak: email address] |
| en | `page_pending` | [doldurulacak] |
| en | `hz_b_hba` | [doldurulacak: alig.tech egress IP address] |

Other open decisions (not in the text, in the configuration):

- Contact e-mail address, CI provider, hosting provider, target customer segment
- KVKK (Turkish data protection law) privacy notice and cookie texts (legal review)

## Health scan: thresholds awaiting approval (not in an official document, an engineering choice)

- `pg_bosta_islem`: idle in transaction duration: >=600 s medium, >=3600 s high
- `pg_baglanti`: connection saturation: >=75% medium, >=90% high
- `pg_xid_yasi`: medium threshold: age >= 2 x autovacuum_freeze_max_age
- `pg_sequence`: sequence fullness: >0.8 high, >0.95 critical
- `pg_slot`: inactive slot: high
- `pg_kullanilmayan_indeks`: over 10 MB and idx_scan=0: low (statistics may have been reset)
- `pg_mxid`: multixact age: >= 2 x autovacuum_multixact_freeze_max_age medium, >= 1.6 billion critical
- `pg_tablo_autovacuum`: autovacuum disabled at the table level: medium
- `pg_replikasyon`: replica lag: >=60 s or >=1 GB medium, >=600 s or >=16 GB high; a replica not streaming is medium
- `pg_gecici_dosya`: temporary files: daily >=10 GB low, >=100 GB medium; the measurement window is counted as at least 1 day, info if unknown
- PostgreSQL end-of-support dates (`tarama/eol.py` `VARSAYILAN`, retrieved 2026-11-16, used by PG-MAINT-009 and PG-MAINT-001): verify every year against https://www.postgresql.org/support/versioning/ (or override with `ALIG_EOL_AYARI`, `docs/runbook.md`). The 180-day warning window is our own choice (awaiting approval, not blocking).
- History comparison: because reports are deleted after 30 days, only scans within this period are compared. For a longer history, a decision to keep a summary (score, audit statuses; no object names) after a report is deleted is needed, and it must enter the KVKK text.
- New rule choices (awaiting approval, not blocking): a low-severity finding if pg_stat_statements is not loaded; info for temporary file use whose statistics start is unknown; PG-MAINT-003, PG-MAINT-005 and PG-BACKUP-001 do not apply on a standby server.
- Version verification: `tarama/surum_dogrula.py` must be run on PostgreSQL 12, 13, 14, 15, 17 and 18 (in this environment permission to run the downloaded binaries was not granted). The result goes under `docs/surum-dogrulama.json` and `tests/veri/surum/`, and the version is added to the `katalog.SINANAN` list.
- Health score coefficients (awaiting approval, not blocking): weights critical 10, high 6, medium 3, low 1, info 0; warning credit medium 0.5, low 0.75, info 1; category multipliers 1; the risk levels of the rules (`docs/kural-katalogu.md`). To change them use `ALIG_PUAN_AYARI` (`docs/runbook.md`).
- Evidence model choices (awaiting approval, not blocking): rule categories and confidence levels (`docs/kural-katalogu.md`), the mapping from severity to status (critical and high FAIL, others WARNING), counting the per-database rules as UNKNOWN while a database cannot be connected to.
- Legal texts: terms of use of the health scan, the KVKK annex, data location and storage provider, e-mail verification and sending method.
- To turn on e-mail verification: an SMTP provider (587 STARTTLS or 465 TLS), user name and password, sender address (`deploy/ansible/group_vars/all.yml` and `/etc/alig/env`). The code is ready, off by default.

## Company record (must enter the KVKK text)

- When a health scan is uploaded, the company name and e-mail address are stored as **plain text** (`tarama.sqlite`, the `firma` table) and matched with the report. In the previous design only an irreversible digest was kept; the note on the page was changed accordingly.
- The company record is deleted after 365 days (adjustable); the period and the customer deletion request path await approval. `[doldurulacak: firma kaydı saklama süresi ve silme talebi yolu]` (to be filled in: company record retention period and deletion request path)
- The privacy notice must state: the data collected (company name, e-mail), the purpose (record matching, limits, contact), the retention period, the right to deletion.

## SQL Server scan (preview)

- Testing on a real SQL Server: the steps in `docs/mssql-onsurum.md`. It is not published on the public page without being tested.
- The `MSSQL_EOL` dates in `tarama/kurallar_mssql.py` were taken from the Microsoft lifecycle pages (November 2026). They must be verified every year.
- MUHENDISLIK (engineering) thresholds (`kurallar_mssql.MUHENDISLIK`): full backup 168 hours, log backup 24 hours, CHECKDB 14 days, open transaction 600 and 3600 seconds, parallelism cost threshold 5.

## Direct connection (Mode B)

- Before going live: a separate runner process, server certificate verification, a fixed egress IP address, the customer consent text. Details: `docs/kip-b-tasarim.md`.
- Limits (awaiting approval): a request is valid for 30 minutes, 3 attempts per request, 5 requests per hour per company, 2 scans at the same time.
