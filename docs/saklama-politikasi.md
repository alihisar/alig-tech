# Data classes and retention policy

Source: `tarama/saklama.py` (the single place). The periods are set from the environment: `ALIG_SAKLAMA_<CLASS>_GUN` (`/etc/alig/env`). `0` or `suresiz` (indefinite) is valid only for classes that can be set to indefinite; with an invalid value the services and the maintenance job stop with an explicit error and do not silently fall back to the default.

**The default periods are not legally approved values.** Until legal approval arrives they are a draft `[doldurulacak: saklama sürelerinin hukuki onayı]` (to be filled in: legal approval of the retention periods).

| Class | Default | Where | When it is deleted |
| --- | --- | --- | --- |
| `rapor` (report) | 30 days | tarama.sqlite | The end date is written at creation; the daily maintenance and the customer/administrator delete button delete it |
| `baglanti_istegi` (connection request) | 1 day | tarama.sqlite | A Mode B request whose time has expired (the password is never stored) |
| `firma` (company) | 365 days | tarama.sqlite | After the last activity and if it has no active report; the deletion is written to the audit as `sistem` (system), the company name and e-mail are not written to the audit. The business process status and note (admin panel) stay in the company row and are deleted together with the company record (manual deletion and retention period); the note may contain personal data and is not written to the audit chain |
| `talep` (request) | 365 days | form.sqlite, yonetim.sqlite | After its creation; status notes are deleted too, the action is written to the admin chain |
| `denetim` (audit) | indefinite | all chains | It is not deleted: deletion breaks the chain. It is protected by exporting the chain head (`docs/runbook.md`) |

History comparison (`tarama/gecmis.py`) does not store new data: it only reads reports whose retention period has not expired. When a report is deleted or expires, that scan also drops out of the comparison. For a longer history, keeping a summary is a separate data class and needs legal approval `[doldurulacak: karşılaştırma özeti saklama kararı]` (to be filled in: decision to keep the comparison summary).

The customer portal (`ALIG_PORTAL`, off by default) adds a new data class: the portal account (e-mail, scrypt password digest, language). The account is deleted together with the company when the company is deleted (the `firma` period above); an unverified account request and verification code are deleted after 24 hours, a session after 30 minutes when idle (at most 8 hours), a login attempt after 1 day (`tarama/portal_depo.py`, `temizle` in the daily maintenance). A service request (subject, message) and an account/data deletion request are also deleted together with the portal account, when the company is deleted. The user records the deletion request from the portal; identity verification and deletion are an administrator action (Portal talepleri in the panel, then Firmayı sil on the company page) and are written to the audit chain; the content of the request is not written to the chain. A separate retention period for accounts needs legal approval `[doldurulacak: portal hesabı saklama süresi]` (to be filled in: portal account retention period).

What stays fixed: the limit window is 30 days (a business rule, `depo.SINIR_GUN`); an admin session expires by usage time and is deleted when the password changes.

Deletion runs in the daily maintenance job (`deploy/bakim.py`); it is done before the backup.

## Deletion from backups

Deleted data stays in backups taken before the moment of deletion. 14 backups are kept (about 14 days with daily backups), and old backups are deleted automatically. So a record also disappears from the backups after the retention period plus at most about 14 days. How this is to be told to the customer, and a separate period for the remote copy of the backups, await a decision `[doldurulacak: uzak yedek hedefi ve süresi]` (to be filled in: remote backup target and period). When a deletion request arrives, no separate action is taken for the copy in the backups; the backups are allowed to expire. This must be stated in the privacy notice.

## Verification

Tests: `tests/test_deploy.py` (`SaklamaTests`). The scheduled maintenance was not run on a real server; only unit tests and the maintenance script in a temporary directory were tried.
