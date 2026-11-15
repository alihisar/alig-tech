# Code review (2026-11-13)

Scope: the whole repository (form, scan, admin, storage and migrations, rule engine, report, Mode B, collector, maintenance and deployment scripts, CI, client JS, Ansible templates). Method: adversarial reading, `kod-disiplini/kontrol.py`, `ruff`, `mypy`, probes against running servers, running the collector against a real PostgreSQL 16 cluster, and mutation testing of the security tests (does a test go red when the protection is removed).

Severity levels reflect impact: **CRITICAL** outage, data loss or unauthorised access; **HIGH** wrong result or weakened protection; **MEDIUM** breakage under specific conditions or maintenance cost; **LOW** consistency and readability.

## Summary

| Severity | Found | Fixed | Open |
| --- | --- | --- | --- |
| CRITICAL | 1 | 1 | 0 |
| HIGH | 5 | 5 | 0 (the code for Y5 is ready; enabling it waits for the SMTP provider choice) |
| MEDIUM | 12 | 12 | 0 (O12 was sped up; cross-file operations stayed sequential, see below) |
| LOW | 12 | 11 | 0 (D12 is a false positive, not counted as open) |

First round (same day): the CRITICAL finding, the first three HIGH findings and six MEDIUM findings were fixed. Second round ("Fix the findings"): all remaining findings were fixed; details in the "Second round" section.

No code finding blocks going live. The blocking decisions are outside the code: for e-mail verification, an SMTP provider and a sender address; the server and the legal texts (`docs/yol-haritasi.md`).

Mutation testing: of the 14 existing security protections, tests went red when 13 were removed; when the static file path check was removed no test failed (D1, fixed). The same trial was run for every fix added in this review (result at the bottom).

## CRITICAL

### K1 `tarama/kurallar.py` — a single upload report with a wrong type could take down the admin panel for 30 days — FIXED

- **FINDING:** The upload check validated the column names and that the value was a scalar, but not its type or whether the column was present. The rule engine trusted the type in operations such as `r[0]["surum_num"] // 10000` and `kullanilan / ust`.
- **EVIDENCE:** Probe: an unauthenticated upload returned `303`; afterwards the customer report, `/yonetim/`, `/yonetim/taramalar`, `/yonetim/taramalar/1` and `/yonetim/firmalar/1` dropped the connection (`TypeError`, `KeyError`). Of the 16 PostgreSQL checks at review time, 8 crashed on a malformed value.
- **RISK:** With no e-mail verification, anyone could make the admin panel's main pages unusable for the report lifetime (30 days) with a single file; it was also impossible to find and delete the malformed report from the panel.
- **FIX:** (1) `tarama/yukleme.py` `TURLER`: a type for every PostgreSQL column; a value of the wrong type, a missing column and an infinite number (`1e999`) are rejected at upload. (2) Every check is isolated in the rule engine: a data error marks that check as unmeasurable with "invalid value format" and the report does not crash. (3) A per-report shield in the panel: even an unexpected error does not take the page down, and a malformed report can be deleted. Tests: `BozukDegerTests`, `test_zehirli_rapor_paneli_dusurmez`, `test_beklenmeyen_kural_hatasi_paneli_dusurmez`. Real PostgreSQL 16 output passed the new type check.

## HIGH

### Y1 `tarama/depo.py` `denetim_ekle` — concurrent writers lost audit records — FIXED

- **FINDING:** The last record was read without a lock and `seq+1` was written. The scan server, the admin panel and maintenance all write to the same `tarama.sqlite` chain.
- **EVIDENCE:** Probe: 3 processes x 300 records -> 896/900 written, 4 `IntegrityError: UNIQUE constraint failed: denetim.seq`.
- **RISK:** A business action (upload, delete) is performed but its audit record is lost and the request ends with a 500: the audit guarantee is breached.
- **FIX:** Read and insert under `BEGIN IMMEDIATE`. Test: `test_eszamanli_surecler_zinciri_bozmaz_kayit_kaybetmez` (3 processes, 360/360, chain intact).

### Y2 `yonetim/server.py` `_firma_esitle` — a deleted company came back from an old contact request — FIXED

- **FINDING:** Every time the panel opens it creates company records from the contact requests. Because the deleted company's request was still there, the record was re-created on the next page view.
- **EVIDENCE:** Probe: `pasif` (inactive) -> delete -> `[]` -> summary page -> `[(1, 'kurban.com', 'aktif')]`.
- **RISK:** Deletion by the administrator and deletion by the retention period are silently undone; a company made inactive comes back active; a KVKK (Turkish data protection law) deletion request cannot be fulfilled.
- **FIX:** A `firma_silinen` table (a digest, not a plain key). Requests from before the deletion do not bring the record back; a new request arriving after the deletion opens a new record. The traces are deleted when the request retention period expires. Tests: `test_silinen_firma_talepten_geri_gelmez`, `test_saklamayla_silinen_firma_eski_talepten_geri_gelmez`.

### Y3 `tarama/katalog.py` `pg_sequence` — a full sequence was invisible to the recommended scan account — FIXED

- **FINDING:** `pg_sequences.last_value` is empty for a sequence on which the role has neither USAGE nor SELECT. `alig_hc` in the guide (only `pg_monitor`) cannot read any sequence value; the check returned an empty list and counted as "no problem".
- **EVIDENCE:** Real PostgreSQL 16: a sequence with `MAXVALUE 100` and value 99. Superuser: `oran 0.99` (ratio); `alig_hc`: `satirlar: []` (rows).
- **RISK:** A sequence that will stop inserts looks clean in the report (false negative).
- **FIX:** A new `pg_sequence_gorunurluk` check gives the number of unreadable sequences; if the number is greater than zero, `pg_sequence` appears among the unmeasurable checks as "partially measured". Verified on a real cluster (`okunamayan: 2`, 2 unreadable).

### Y4 Table, index and sequence checks cover only the connected database — FIXED (second round)

- **FINDING:** These checks read the catalog of the database they are connected to. The guide recommended `--dbname postgres`; application tables live in another database. The report did not state this limit.
- **RISK:** Dead rows, invalid indexes and sequence problems in the application database look like "no finding".
- **FIX (done):** The `pg_kapsam` check gives the connected database and the number of databases on the server; the report states the scope in the summary and, if there are several databases, says so in the "what this scan does not look at" section; the guide uses `--dbname uygulama_db` and explains the scope (TR, EN).
- **SECOND ROUND:** The collector walks every database it can connect to (at most 50; 20 in Mode B). It does not try to connect to a database without CONNECT privilege and skips it with "yetki" (privilege); those exceeding the limit are skipped with "sınır" (limit). The report states in how many databases it ran and which were skipped. In Mode B, a database whose name does not match the safe pattern never enters the connection string. On real PostgreSQL 16, a dead-row finding was reported in a database with a name containing a space, and the database without privilege was skipped.

### Y5 No e-mail verification — CODE READY, DISABLED BY DEFAULT (second round)

- **FINDING:** The e-mail in the upload form is not verified. The company key is the domain name.
- **RISK:** Someone could write `x@kurban.com` ("victim"), use up the victim's 30-day free allowance, change the e-mail in the company record and show the report of their own database in the panel under the victim's name. This weakens the per-company limit protection.
- **SECOND ROUND:** Interim measures are on in every case: an unverified upload does not change the registered company e-mail, the uploader's address is kept separately on every report, and the panel shows an "unverified" label. When verification is on (`ALIG_EPOSTA_DOGRULAMA=1`): the report link is sent only by e-mail; opening the link (GET) changes nothing, the allowance is spent by the button on the page (POST); a limit of 3 pending links per address and 5 per company in 24 hours; an unverified report is deleted after 24 hours. The web process does not reach the network: an outbox plus a separate `alig-posta` service, SMTP over TLS only. Enabling it needs an SMTP provider and a sender address. Not tried with a real SMTP server.

## MEDIUM

| # | Location | Finding and evidence | Status |
| --- | --- | --- | --- |
| O1 | `tarama/depo.py`, `yonetim/depo.py` `baglan` | Migrations without a lock: processes opened at the same time crashed. Probe: of 120 opens, 90 hit `table ... already exists` or `database is locked`. When a new version is deployed the services restart together. | FIXED: migration under a single write lock, the version is re-read inside the lock; the WAL switch waits until the lock is free. Test: `test_eszamanli_ilk_acilis_ve_goc_cokmez` |
| O2 | `form/server.py` `RateLimiter` | Keys were never deleted (probe: 100,001 keys after the window expired). With IPv6 every request can come from a new address; memory grows without bound. It was lock-free (a race could not be produced in the probe). | FIXED: cleanup per window, and a lock. Tests `test_limiter_*` |
| O3 | `tarama/server.py` `_sil` | An unauthenticated `POST /rapor/<anything>/sil` wrote a row to the audit chain, which is never deleted, every time. | FIXED: only a log line for a nonexistent report |
| O4 | `deploy/bakim.py` `disk_yeterli` (written in this session) | If the disk was less than 10% free, the backup was stopped even if there was room: on a large disk, backups would stop as space tightened. | FIXED: the criterion is twice the DB size plus a 64 MB margin; below 10% is only a warning |
| O5 | `deploy/bakim.py` `geri_yukle` (written in this session) | In WAL mode `BEGIN EXCLUSIVE` does not block readers: a running service holding a connection between requests was not detected. | FIXED: a check via `/proc` for processes holding the file open. Test: `test_bosta_baglanti_tutan_surec_varken_durur` |
| O6 | `deploy/hazirlik.py` (written in this session) | It imported `jinja2`; against the standard-library-only rule. | FIXED: units are rendered by Ansible itself; verified that a broken unit gives FAIL |
| O7 | `yonetim/server.py` company deletion | Contact requests are not deleted (the UI says so); on a KVKK deletion request the personal data stays in `form.sqlite`. | FIXED (second round): a "Also delete contact requests" option in the delete form; requests first, then the company; no address is written to the audit |
| O8 | collector `--maskele` (mask) | The alias -> real name mapping is not given to the customer; in a masked report it cannot be known which table `nesne-3` is. | FIXED (second round): `<output>-maske.json` stays only at the customer, 0600; rejected if uploaded |
| O9 | `tarama/baglanti.py` | Mode B `sslmode=require` does not verify the server certificate; `channel_binding=require` prevents the password being sent in clear or with MD5 and prevents a SCRAM relay attack. Mode B is off. | FIXED (second round): `channel_binding=require`; the cost is that an account with md5/password authentication does not work in Mode B |
| O10 | business action and audit record | Not in the same transaction: if the process dies between the two, the action stays unaudited. | FIXED (second round): with `depo.islem`, upload, verification, deletion, company operations, user operations, login and retention deletion in a single transaction. Remaining: `form.sqlite` and `yonetim.sqlite` are separate files and cannot be in a single transaction; delete first, then the audit record |
| O11 | `yonetim/server.py` `_firma_esitle` | A separate commit for up to 500 requests on every summary and company page (a GET with side effects, every commit an fsync). | FIXED (second round): only requests after the last sync, in a single transaction |
| O12 | `tarama/server.py` upload | `_derinlik_denetle` scans 5 MB with a pure Python loop; the nginx limit (6 per minute) and the IP limit exist. | FIXED (second round): structure, quote and escape counts are limited at C speed, the loop runs only over those bytes; a 4.5 MB malicious file is rejected in 0.01 s |

## LOW

| # | Location | Finding | Status |
| --- | --- | --- | --- |
| D1 | `tests/test_yonetim.py` | The static file path check had no test (the mutation escaped): a path with an allowed extension but outside `assets` was not tried. | FIXED |
| D2 | `yonetim/server.py` | Trying to delete a nonexistent report wrote "deleted" to the admin chain. | FIXED |
| D3 | `ci/run_all.py` | The test and collector calls had no timeout; a hung test would make CI wait forever. | FIXED |
| D4 | various | Unused imports and variables (`ruff`). | FIXED |
| D5 | collector | `dbname=%s sslmode=%s` concatenation: a database name with a space or quote breaks it (the customer's own input). | FIXED (second round): values are quoted with libpq rules; tried on a real cluster with a name containing a space |
| D6 | collector | Default `sslmode=prefer`; no warning if the connection was made unencrypted. | FIXED (second round): checked with `pg_stat_ssl`, a warning if unencrypted; the output file is also 0600 |
| D7 | `yonetim/server.py` | The request list and CSV were silently limited to 500 rows. | FIXED (second round): the request page is paginated by 100, the CSV has all rows |
| D8 | `tarama/depo.py` | A company ID can be reused after deletion (no `AUTOINCREMENT`); in the audit the same number could point to two companies. | FIXED (second round): the company and report tables were rebuilt with `AUTOINCREMENT`, preserving the IDs |
| D9 | `yonetim/server.py` | No CSP header on a panel opened through an SSH tunnel (without nginx). | FIXED (second round): the panel sends its own CSP header (no script, no inline style) |
| D10 | `tarama/hata.py` | The text "2 scans in 30 days" is fixed; it would go wrong if `SINIR_ADET` changes. | FIXED (second round): the error page writes from the constant; a test comparing static texts with the constants |
| D11 | `yonetim/depo.py` `giris` | The same TOTP code could be accepted twice in two concurrent logins (race window; the password is also required). | FIXED (second round): code and counter under the write lock; of two concurrent logins with the same code one passes (test) |
| D12 | `kontrol.py` | The "embedded secret" (test passwords) and "SQL concatenation" (fixed catalog, fixed column lists) warnings are false positives. | Noted |

## Verification

- All tests and the 13 CI checks passed.
- Real PostgreSQL 16: the collector output passed the new type check; `pg_kapsam` and `pg_sequence_gorunurluk` gave the expected values; `GercekPgTests` passed.
- The probes (upload, panel, concurrent chain, concurrent migration, company reappearing) were re-run after the fix: all clean.
- Nothing was tried on a real server, under systemd or with live traffic.

## Second round: fixing the remaining findings

| Finding | Done | Evidence |
| --- | --- | --- |
| Y5 | E-mail verification (off by default) and interim measures that are always on | `EpostaDogrulamaTests`, `tests/test_posta.py`, panel label test |
| Y4 | Walking all databases; report scope | `VeritabaniKapsamTests`, `ToplayiciVeritabaniTests` (fake `psql`), real PostgreSQL 16 (below) |
| O7 | Option to also delete requests when deleting a company | `test_firma_silinirken_talepleri_de_silinebilir` |
| O8 | Mask mapping only at the customer | `test_maske_eslemesi_yalniz_yerelde`, real PostgreSQL 16 |
| O9 | `channel_binding=require` | `test_baglanti_dogrulanan_ipye_sabitlenir_ve_tls_ister`, real PostgreSQL 16 (TLS + SCRAM) |
| O10 | `depo.islem`: action and audit record together | `IslemTests`, `test_denetim_yazilamazsa_yukleme_ve_silme_geri_alinir`, `test_saklama_silmesi_denetimsiz_kalmaz` |
| O11 | Company sync only new requests, in a single transaction | `test_firma_esitleme_yalniz_yeni_talepleri_isler` |
| O12 | Fast structure check | `test_cok_sayida_yapi_hizla_reddedilir` |
| D5, D6 | Connection string escaping, unencrypted connection warning, output 0600 | `ToplayiciVeritabaniTests` |
| D7 | Request pagination, full CSV | `test_talepler_sayfali_csv_eksiksiz` |
| D8 | `AUTOINCREMENT` migration | `test_silinen_firma_ve_rapor_kimligi_yeniden_kullanilmaz`, `test_eski_firma_ve_rapor_tablosu_kimlikleri_korunarak_tasinir` |
| D9 | CSP in the panel | `test_panel_kendi_csp_basligini_gonderir` |
| D10 | Limit text from the constant | `MetinTests` |
| D11 | TOTP lock | `test_ayni_dogrulama_kodu_es_zamanli_iki_giriste_bir_kez_gecer` |

Real PostgreSQL 16 trials (local cluster, not a server):

- The collector, with `alig_hc` (only `pg_monitor`) on a cluster with 4 databases: `"satis db"` (a name with a space) was scanned and the dead-row finding there was reported as `satis db.public.siparis`; the `gizli` database, whose CONNECT privilege was revoked, was not connected to and was skipped as "no privilege"; the output and mask mapping files are 0600.
- Mode B: TLS on, `pg_hba` only `hostssl ... scram-sha-256`, `channel_binding=require` in the connection string: the scan completed, a wrong password gave a "baglanti" (connection) error. The database with a space in its name did not enter the connection string in Mode B and was skipped because of "ad" (name).

Remaining limits (not findings, design): because `form.sqlite` and `yonetim.sqlite` are separate files, deleting a request and writing the admin audit record cannot be done in a single transaction (delete first, then the record). E-mail sending was not tried with a real SMTP server. Nothing was run on a real server, under systemd.

## Mutation testing

On each row the protection was removed in a temporary copy and the relevant test module was run.

| Protection | Result |
| --- | --- |
| CSRF, Origin, session lifetime, TOTP replay protection, HMAC comparison, duplicate JSON key, unknown column, per-company limit, report lifetime, report escaping, CSV formula protection, SSRF internal address check, chain check on restore | 13/13 caught |
| Static file path check | Escaped at first (D1); caught after the test was added |
| This review's fixes: rule isolation, type check at upload, missing column, chain write lock, migration lock, deleted company trace, rate limiter cleanup, open file check, sequence partial privilege, panel shield, unauthenticated deletion not writing to the audit | 11/11 caught |
| Infinite number check (`_skaler`) | Escaped at first: in PostgreSQL the type check also caught it, so it was not tested on its own. A test was added for the SQL Server path, which has no type table; verified that it goes red when the protection is removed |
| Second round fixes: spending the allowance on verification, mail limit, privacy of an unverified report, protection of the company e-mail, deletion of the sent text, STARTTLS, database walking, Mode B name check, requests on company deletion, `AUTOINCREMENT`, panel CSP, structure count limit, upload / company operation / user creation inside a transaction, limit text | 17/17 caught |
| `channel_binding` and the company sync marker | Escaped at first: in the first, the mutation pattern matched the text in a comment, not in the code; in the second, the test data contained a single request so the difference was invisible. The pattern was fixed, the test was raised to five requests; both were caught |
| Lock in TOTP login | At first caught in only one of three attempts (depends on the race). The test was changed to widen the race window by slowing the code check; caught in three of three attempts |


## ALIG-SEC-001: admin and report access security review (2026-11-16)

Scope: `tarama/server.py` report endpoints, `tarama/portal.py` and `portal_depo.py`, `yonetim/server.py`, `yonetim/depo.py`, `yonetim/guvenlik.py`, `yonetim/kullanici.py`, `tarama/rapor.py` escaping. Method: adversarial reading and negative tests (`tests/test_erisim_guvenligi.py`, 47 tests): every path through which access must not exist was tested, then the protection was removed in a temporary copy and it was checked whether the test went red (below). The runtime is SQLite; PostgreSQL was not touched.

Summary: 1 open finding (MEDIUM, awaiting a decision), 1 fixed (LOW), 3 accepted limits (INFO/LOW), 1 documentation gap (closed). No gap was found in company isolation, token lifetime, CSV, unauthenticated access or escaping: these are proven by tests in the "verified" table.

### S1 `yonetim/depo.py` `kullanici.totp` — TOTP secret in plain text in the database — OPEN (decision SEC-K1, MEDIUM)

- **FINDING:** The `kullanici.totp` column holds the base32 secret as is. The password is hashed with scrypt; TOTP (HMAC-SHA1, RFC 6238) however needs the secret itself on the server and cannot be hashed. The standard library has no symmetric cipher (`hashlib`, `hmac`, `secrets` exist; no AES), so this was not solved by writing code. The `yonetim/kullanici.py kod <name>` command also reads the secret from the database and prints a current code (written for local testing only).
- **EVIDENCE:** `tests/test_erisim_guvenligi.py::TotpSirriSizmazTests::test_sir_veritabaninda_duz_metin_oldugu_belgelenmis_bulgudur`: the column equals the secret returned by `kullanici_ekle`. The non-leak direction was also tested (`test_sir_panelde_csvde_denetimde_ve_cli_listesinde_yok`): the secret is not in panel pages, in CSVs, in the two audit chains or in the `liste` output; it is written once, only in the output of `ekle` and `totp-yenile`. Backups are taken with `deploy/bakim.py` at 0600 but the content is the plain secret (runbook: encrypt when copying elsewhere). `veri_dizini` (the data directory) is 0750 in Ansible, services run with `UMask=0077`.
- **RISK:** Someone who reaches the `yonetim.sqlite` file (disk, backup copy, a removed or disposed disk, root access) can generate TOTP codes. This alone does not give login: the password is protected with scrypt (`n=2^15`), only TOTP, the second factor, falls. The password hash is in the same file; if both are broken together, the panel (customer reports, CSVs) opens.
- **RECOMMENDATION:** Options, with pros and cons:
  1. **Data directory 0700 and file 0600** (needs no code; `veri_dizini` from 0750 to 0700, files 0600 with `UMask=0077` and the S2 fix). Gives no protection against backup or the root user.
  2. **Disk encryption** (LUKS or the provider's volume encryption) and copying backups encrypted: protects against a stolen or disposed disk and against the backup medium; does not protect against root access on the running server. Needs no code.
  3. **A secret file with systemd-creds** (`systemd-creds encrypt`, `LoadCredentialEncrypted=` in the unit): the secrets leave the database and go to a credential file encrypted with the server's key (with TPM2 if present); only the service process sees the decrypted form under `$CREDENTIALS_DIRECTORY`. It requires a code change (`kullanici.py` writes the secrets to that file, `giris` reads from there; the service restarts on secret renewal), and cannot be chosen without knowing the systemd version and the server operating system (WEB-K4).
  Default (SEC-K1, waiting for Ali): options 1 and 2; the disk encryption recommendation is in `docs/runbook.md`, no code. Option 3 becomes a separate item after Ali's decision.

### S2 `yonetim/kullanici.py` — the CLI created `yonetim.sqlite` world-readable under a loose umask — FIXED (LOW)

- **FINDING:** The application does not set file permissions; the umask determines them. Services run with `UMask=0077`, but the `sudo -u alig-web python3 .../kullanici.py ...` call in the runbook inherits the caller's umask (mostly 022). When the CLI creates the database first, the file becomes 0644.
- **EVIDENCE:** Probe: `umask 022; python3 yonetim/kullanici.py --db y.sqlite liste` -> `-rw-r--r--`. The file carries password hashes and TOTP secrets (S1). Mitigating: `veri_dizini` is 0750 and owned by the service user, so only that group could reach the file.
- **RISK:** If the directory permission is loosened or the file is moved elsewhere, the secrets would be world-readable; the defence fell to a single layer.
- **RECOMMENDATION / FIX:** `kullanici.py` calls `os.umask(0o077)` at start (only when run from the command line; imported as a library, it does not change the process umask). Test: `CliDosyaIzniTests` (subprocess, umask 022 -> no group or other bits on any file). Red in mutation when the protection is removed.

### S3 `yonetim/server.py` — no role separation: "authorised" means a valid session — ACCEPTED (INFO)

- **FINDING:** Every panel user can use every page, both CSVs, report deletion and company deletion; there is no read-only or CSV-only role.
- **EVIDENCE:** `YonetimOturumsuzTests::test_yetki_modeli_tek_rol_belgelenmis_varsayim` (a second user also gets the CSV). Every CSV download is written to the admin audit chain with the row count (`firmalar csv indirildi, N satir`); an unauthorised attempt is not written to the audit (`test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir`).
- **RISK:** No effect today since there is a single administrator. If the number of users grows, so does the number of people who can get the CSV containing personal data (contact requests, e-mails).
- **RECOMMENDATION:** Before a second user is added, a role design (at minimum: view-only, with CSV and deletion as separate rights). For now users are reviewed with `kullanici.py liste`.

### S4 `yonetim/depo.py` `giris_engelli` — the per-user lock can keep an administrator whose name is known out for 15 minutes — ACCEPTED (LOW)

- **FINDING:** After 5 failed attempts in 15 minutes the user is blocked from login even with correct credentials. Someone who knows the username could lock the administrator out.
- **EVIDENCE:** `GirisTests::test_kilitleme`; `TotpKurtarmaTests::test_kilitli_kullanici_yenilemeden_sonra_sure_dolana_kadar_kilitli_kalir`: `totp-yenile` does not reset the attempt counter, the block lifts when the time expires.
- **RISK:** Availability only; the door is behind the nginx IP allowlist or the SSH tunnel (`yonetim_izinli_ipler`). A per-IP limit (10) also exists. Password guessing is not accelerated this way.
- **RECOMMENDATION:** Accepted; a deliberate trade-off against brute force. Waiting out the lock takes 15 minutes (written in the runbook); a CLI command that resets the counter was not added, because an attacker cannot force the lock to be lifted, but if the command is misused it would weaken the protection.

### S5 `tarama/server.py` `_sil` — the delete endpoint with an expired token deletes the row until cleanup runs — ACCEPTED (INFO)

- **FINDING:** The read endpoint and the `/dogrula` (verify) endpoint look for `bitis_utc > now`; `rapor_sil` (report delete) does not. For a report that has expired but has not yet been cleaned up by `suresi_dolanlari_sil`, the `/sil` endpoint returns `303` and deletes the row.
- **EVIDENCE:** `RaporBelirteciTests::test_bitis_sonrasi_hicbir_uc_veri_vermez`: after the end time GET (two views) and `/dogrula` give `404`; the `/sil` response has no report content and afterwards it is `404` again.
- **RISK:** No data leaks; deletion is the desired outcome (the retention period has already expired). The token holder can see the "did it exist" difference, and the token is already in the holder's hands.
- **RECOMMENDATION:** No change needed. The test only says "no content comes"; it does not pin the status code, so if it is changed to `404` later the test does not break.

### S6 `docs/runbook.md` — the TOTP device loss procedure was a single sentence — FIXED (MEDIUM, documentation)

- **FINDING:** The runbook only said "if the phone is lost, generate a new key with `totp-yenile`". It had no information on which user to use, in which order, what to do if the lost device may have been stolen, the lock duration, and verification.
- **EVIDENCE:** `yonetim/kullanici.py` `totp-yenile` generates the new secret, resets the counter, closes the user's open sessions and writes to the audit with the `cli` actor (`TotpKurtarmaTests`: the old device cannot log in, the new key can, the password stays the same, a nonexistent or invalid name leaves no record). The code was sufficient; only the procedure was missing.
- **RISK:** In an emergency, the wrong order (for example renewing only TOTP while a device is stolen and leaving the password), or the key landing in the terminal log.
- **RECOMMENDATION / FIX:** A "Verification device loss" section was added to `docs/runbook.md` (identity verification, command order, password renewal for a stolen device, lock, verification, audit record).

### ALIG-SEC-001: paths through which access must not exist — verified (no gap found)

| Requirement | Result | Evidence (`tests/test_erisim_guvenligi.py`, plus the existing `test_portal.py`) |
| --- | --- | --- |
| A company A token cannot open a company B report | Verified | `RaporBelirteciTests` (single character change at 43 positions, truncation, extension, upper/lower case, path and query tricks, B cannot be deleted/verified with an A token); portal: `IzolasyonTests`, `test_rapor_izolasyonu_http` |
| Report token lifetime: no access after `bitis_utc`; a deleted report does not reopen | Verified | `test_bitis_sonrasi_hicbir_uc_veri_vermez`, `test_bitis_siniri_saniye_hassasiyetinde`, `test_silinen_rapor_belirteci_yeniden_yuklemeyle_dirilmez`, `BekleyenRaporSureTests` (pending report: when the time expires the confirmation page is also `404`, verification does not spend the allowance) |
| Admin CSV only with a session | Verified | `test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir`, `test_oturum_baska_yollarla_gecersiz_olunca_acilmaz` (user deleted, password changed, key renewed) |
| All admin endpoints closed without a session | Verified | Table-driven: menu and source paths must be in the table (`test_tablo_menu_ve_kaynak_yollarini_kapsar`); 25 GET and 10 POST paths x 10 invalid-credential cases (no cookie, forged, empty, malformed, without the `__Host-` prefix, a digest cookie, idle and total timeout expired, logged out) |
| Escaping in report HTML | Verified | `RaporKacisTests`, `RaporKacisSunucuTests`, `PortalKacisTests`, `YonetimKacisTests`: an object name containing tags, quotes and entities in every text column of all checks; two languages, two views, customer/portal/admin, stored and reflected values |
| TOTP replay prevention | Verified | `TotpTekrarVeOturumOzetiTests` (the same code from two IPs, an older window code, a wrong password does not burn the code, the counter resets when the key is renewed); the existing race test `test_ayni_dogrulama_kodu_es_zamanli_iki_giriste_bir_kez_gecer` |
| Session code stored only as a SHA-256 digest | Verified | `test_oturum_kodu_yalniz_sha256_ozetiyle_saklanir` (no raw code bytes in the database files; the digest is not accepted as a cookie), `test_portal_oturum_kodu_da_yalniz_ozetle_saklanir` |

Limits: the tests are against the SQLite runtime; the same behaviour will be tested again in the `ALIG-DB-003` items on PostgreSQL. No real browser, nginx or real server was used: the HTTP tests are against a local `ThreadingHTTPServer` (the nginx IP allowlist and `X-Real-IP` writing were not tested).

### ALIG-SEC-001 mutation testing

On each row the protection was removed in a temporary copy and `tests.test_erisim_guvenligi` was run.

| Protection | First test to fail |
| --- | --- |
| `bitis_utc` check on report read (`rapor_getir`) | `test_bitis_siniri_saniye_hassasiyetinde` |
| `bitis_utc` check on a pending report (`rapor_bekleyen_getir`) | `test_suresi_dolan_bekleyen_rapor_dogrulanamaz_ve_hak_harcamaz` |
| Session check on admin GET endpoints | `test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir` |
| CSRF code on admin POST | `test_oturumlu_ama_csrf_ya_da_kaynak_yanlis_post_reddedilir` |
| Rejecting the session digest as a cookie | `test_oturum_kodu_yalniz_sha256_ozetiyle_saklanir` |
| TOTP replay protection (`s > son_sayac`) | `test_ayni_kod_ikinci_kez_hicbir_yolla_gecmez` |
| Escaping in the report evidence list | `test_portal_sayfalari` |
| `totp-yenile` closing sessions | `test_totp_yenile_yeni_anahtar_verir_oturumlari_kapatir_parolayi_degistirmez` |
| CLI `umask` (S2) | `test_cli_gevsek_umask_altinda_bile_dosyayi_0600_olusturur` |
| Writing the CSV download to the audit | `test_csv_yalniz_oturumlu_ve_indirme_denetime_yazilir` |

10/10 caught (the test run was stopped at the first failure; only the first failing test is listed on each row). No mutation escaped. The mutation script did not enter the repository (it ran on a temporary copy).

## ALIG-SCAN-001: scan security review (2026-11-15)

Scope: the Mode A collector (`tarama/toplayici/sablon.py`, the generated `site/assets/alig-toplayici.py`, `tarama/onsurum/`) and Mode B (`tarama/hedef.py`, `tarama/baglanti.py`, `tarama/calistirici.py`, the related endpoints). Method: reading the code, probes, mutation testing, a temporary PG16 cluster. Tests: `tests/test_tarama_guvenlik.py`. The collector source was not changed; `uret_toplayici.py --kontrol` returns 0.

### S1 `tarama/hedef.py` and `tarama/baglanti.py` — an IPv6 scope ID was injected into the connection string and bypassed the SSRF rejection — FIXED

- **FINDING:** The IPv6 notation inside `[...]` was parsed with `ipaddress.IPv6Address`. Python 3.9+ accepts any text as the scope ID after `%` (including spaces and `=`) and `str(ip)` writes the ID back. `Hedef.ad` and `Hedef.ip` carried this text, and `baglanti_dizgisi` concatenated it directly with `host=%s hostaddr=%s`. Because the address part was a public IP, `adres_uygun` passed.
- **EVIDENCE:** `hedef.dogrula("[2606:2800:220:1::1%x hostaddr=127.0.0.1 sslmode=disable]", 5432)` was accepted; the string became `host=2606:...%x hostaddr=127.0.0.1 sslmode=disable hostaddr=2606:...%x hostaddr=127.0.0.1 sslmode=disable port=54329 ...`. With this string `psql` connected to 127.0.0.1:54329 on the PG16 temporary cluster; only `channel_binding=require` cut the connection ("channel binding required"; the cluster used `trust` authentication). The same path was also open in `calistirici.py` through `ipaddress.ip_address(i["ip"])`.
- **RISK:** With the "server" field in the customer form, a connection could be attempted to loopback, RFC1918 or cloud metadata addresses; with extra keys (`options=-c default_transaction_read_only=off`, `sslmode=disable`) the read-only and TLS protections could also be overridden. Mode B is off by default and the runner unit is closed to the internal network with `IPAddressDeny` (second layer); the first layer was still a hole.
- **FIX:** (1) `adres_uygun`: an address with a scope ID is never suitable; `dogrula`: an internal address with an ID is rejected as `ic_adres` (internal address), a public address with an ID as `ad` (name). (2) `baglanti_dizgisi`: unless `host` and `hostaddr` are only `[0-9A-Za-z.:-]` and the port is an integer 1-65535, `BaglantiHatasi("bicim")` (format) is raised (also valid for a target coming from the runner socket). (3) `\Z` instead of `$` in the `AD` pattern (trailing newline). Tests: `HedefTablosuTests`, `BaglantiDizgisiSavunmasi`, `CalistiriciHedefTests`; they went red when the related protections were removed.
- **RECOMMENDATION:** Keep `ALIG_YASAK_AGLAR` and the `IPAddressDeny` in the runner unit; a single layer must not be trusted.

### S2 `tarama/baglanti.py` `_calistir` — psql output was collected in memory without a limit — FIXED

- **FINDING:** `subprocess.run(capture_output=True)` accumulates stdout in memory until the time limit expires (30 s). In Mode B the customer chooses the server; a hostile server can send a response of any size apart from `LIMIT` and `statement_timeout`.
- **EVIDENCE:** While a fake `psql` wrote 200 MB, the test was red because there was no `CIKTI_SINIRI` (output limit). The new `_surec_calistir`: if stdout exceeds 2 MB the process is killed and the result is `hata` (error).
- **RISK:** The runner can be brought down by memory consumption; the limit of two concurrent scans does not mitigate it.
- **FIX:** Bounded reading with `selectors`: stdout 2 MB, stderr 64 KB, a total time limit, `kill` in every case. Test: `CiktiSiniriTests`. No change was needed in Mode A: the collector runs on the customer's own machine against their own server.

### S3 Collector and Mode B: read-only, allowlist, session settings — VERIFIED (missing tests added)

- **FINDING:** The existing `KatalogTests` only checked the `katalog.PG` queries; the `YASAKLI` (forbidden) list did not have `into`, `set_config`, `nextval`/`setval`, `for update`, `pg_advisory_*`, `pg_stat_reset*`; the database list query, the initial connection queries (Mode A and Mode B), the embedded catalog of the generated collector, `sorgu-katalogu*.txt` and the SQL Server collector did not pass through this allowlist.
- **EVIDENCE:** The new `TumSqlAllowlistTests`: only `SELECT`/`SHOW`/`WITH ... SELECT`, a single statement, no comments, a broad forbidden pattern list (INSERT/UPDATE/DELETE/ALTER/CREATE/DROP/TRUNCATE/GRANT/COPY/`pg_terminate_backend`/`pg_cancel_backend`/`pg_reload_conf`/`set_config`/`SELECT INTO`/`FOR UPDATE` etc.); the checker first tests itself with 38 bad examples. Scope: the catalog (including old-version forms, 26 checks), `VT_LISTE_SQL`, `ILK_SORGU`, all SQL constants in the AST of the generated collector and the embedded `KATALOG`, `sorgu-katalogu.txt`, the SQL Server collector and `sorgu-katalogu-mssql.txt`; that the SQL of `calistir()` calls comes only from constants or from the catalog is checked with the AST. All passed, no query changed. Session: both paths give `default_transaction_read_only=on`, `statement_timeout=15000`, `lock_timeout=2000` with `PGOPTIONS` on every `psql` call and a hostile `PGOPTIONS` in the environment is overridden (mock tests; verified by mutation). On PG16: the collector session returned `on / 15s / 2s`, a text that breaks the wrapper and adds `CREATE TABLE` was rejected in the read-only session and the table was not created, all 26 checks ran in the read-only session. Mode B: when the total time budget runs out the catalog checks do not run.
- **RISK:** `default_transaction_read_only` is not a security boundary, it is a safety net against accidents: SQL in the session can get around it with `SET`. The real boundary is that the SQL text comes from the fixed catalog, and the allowlist test. The account being unprivileged (recommendation: `pg_monitor`) is the third layer.
- **RECOMMENDATION:** No change was needed in the collector source. Adding `BEGIN READ ONLY` gives no meaningful extra protection, since it can be bypassed with `SET TRANSACTION READ WRITE` before the first query.

### S4 SQL Server collector (preview): no session-level read-only mode — OPEN, ACCEPTED

- **FINDING:** `ON_EK` (the prefix) is only `SET NOCOUNT ON`, `SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED`, `SET LOCK_TIMEOUT 2000`, `SET DEADLOCK_PRIORITY LOW`, `DECLARE @j`; the query timeout is `sqlcmd -t 15`, the connection `-l 15`.
- **EVIDENCE:** `test_mssql_sabit_on_ek_yalniz_oturum_ayari` pins the prefix. SQL Server has no equivalent of `default_transaction_read_only` (`ApplicationIntent=ReadOnly` is only availability group routing and does not prevent writes).
- **RISK:** The protection is only the fixed SELECTs and the account's privileges (`alig-giris-mssql.sql`: `VIEW SERVER STATE`, `VIEW ANY DEFINITION`).
- **RECOMMENDATION:** No privileges should be granted outside the privilege script; `ALIG_MSSQL` is already off by default. Not tested on a real SQL Server.

### S5 Mode B target validation, resource limits, off by default — VERIFIED (table-driven tests added)

- **FINDING:** The existing tests were good; the gaps: IPv6 scope ID, IPv4-mapped hexadecimal notations (`::ffff:7f00:1`), `::ffff:0:a.b.c.d`, full-width digits and control characters, the resolver returning a malformed record, port tables (`"05432"`, `"+5432"`, Arabic digits, `True`), the target coming from the runner socket, testing the resource limits at the limit and above it (5 MB, depth 8, 200 and 5000 rows, 1000 skipped, structure/quote/escape counts), `TARAMA_YUVASI` (scan slot) and runner concurrency (2), frame size, the 404 of the endpoints when Mode B is off.
- **EVIDENCE:** `HedefTablosuTests` (90 direct inputs, 22 resolution scenarios, port tables), `CalistiriciHedefTests`, `SinirTests`, `KapaliTests`, `KapaliUclarTests` (when off, `GET`/`POST` `/api/tarama/baglan` and `/api/tarama/baglan/<token>` give 404; `baglanti.tara` and the runner are not called). `ALIG_DOGRUDAN` is enabled only by exactly `1` together with the runner socket; there is no unconditional `ALIG_DOGRUDAN=1` in `deploy/` and `config.example`.
- **RISK (design, not a finding):** The allowed port range is 1024-65535 plus 5432/1433; a high port on any internet-facing address can be tried. Since the response is uniform it is not useful for port scanning; limits on requests and attempts per company are an extra brake.
- **RECOMMENDATION:** If the business need is broad, a per-customer allowed port list can be considered; no change for now.

Mutation: the scope ID check, the `baglanti_dizgisi` validation, the psql output limit, the Mode A `lock_timeout` and the Mode A `default_transaction_read_only=on` lines were temporarily broken; each turned the relevant test red, then was reverted.

