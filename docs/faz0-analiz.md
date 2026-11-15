# PHASE 0: analysis of the current system

Source: `docs/master-prompt-v2.md` (Ali's development document dated 12 November 2026). This file compares every request in the document
with the actual state in the code. Statuses: DONE (code + a passing test), PARTIAL, MISSING, NOT_TESTED, BLOCKED.

Numbers (12 November 2026): 198 unit tests (2 skipped: those that need a real PostgreSQL), 13 CI checks, all passing.
The "178 tests" in the document is an old number; the rule stays the same: the test count does not go down.

## Module 1: application security (P0)

| Request | Status | Evidence or gap |
| --- | --- | --- |
| Request and file size limit | DONE | 5 MB, `tarama/yukleme.py` `MAX_BAYT`; `test_yukleme_*` |
| Content format, schema and type validation | DONE | Strict schema, unknown fields and columns rejected |
| Nesting depth limit | DONE (in this step) | Deep JSON produced an uncaught `RecursionError`; `MAX_DERINLIK`, `test_derinlik_siniri` |
| Non-standard JSON (NaN, duplicate keys) | DONE (in this step) | `test_standart_disi_json_reddedilir` |
| List, row and text length limit | DONE | `MAX_SATIR`, `MAX_METIN` |
| Temporary file, file path manipulation | DONE | The upload is not written to disk, the file name is not used |
| Duplicate upload check | MISSING | If the same file is uploaded twice it spends two allowances |
| Company quota, IP rate limit | DONE | 2 per 30 days, 5 per hour per IP |
| Per-user rate limit | MISSING | There is no customer login (comes with the portal) |
| Scan data is not executed | DONE | Values are only shown escaped |
| Company isolation, in the data layer | PARTIAL | Today there is no customer login: a report can only be reached with an unguessable link, company lists are only in the admin panel. When the portal arrives, a company check in the data access layer is mandatory |
| Password derivation, attempt limit, session lifetime | DONE | scrypt, 5/10 attempts, 30 min idle, 8 hours upper limit |
| Cookie, CSRF, TOTP reuse | DONE | `__Host-` cookie, per-session CSRF, `totp_sayac` |
| Session revocation on password or TOTP change | DONE | `yonetim/depo.py` |
| Audit record of suspicious logins | PARTIAL | A failed login is written; there is no new-IP warning |
| Report link: random, time-limited, deletable | DONE | 32 bytes, only the SHA-256 in the database, 30 days |
| `Cache-Control: no-store`, `Referrer-Policy` | DONE | `tarama/server.py` |
| No link in the log | DONE | The path is masked |
| Single-use report access | MISSING | Optional, low priority |
| Audit chain | PARTIAL | A SHA-256 chain exists. There is no keyed verification and no storing of the chain head in an independent place: someone who can write to the database can regenerate the chain from the start |
| Audit record fields (company, target, result) | PARTIAL | Actor, event, time exist; the fields are inside the event text, not separate columns |

## Module 2: data privacy and retention (P0)

| Request | Status | Evidence or gap |
| --- | --- | --- |
| Deleting expired reports | DONE | `suresi_dolanlari_sil` |
| Report deletion at the customer's request | DONE | The button on the report page |
| A deleted report cannot be reached with the old link | DONE | A test exists; extra negative tests will be added for the full acceptance criterion |
| Company deletion workflow | PARTIAL | The admin deletes; there is no customer request flow |
| Company record retention period | DONE | 365 days by default, adjustable; the period awaits approval |
| Data classes and a configurable retention policy | DONE | `tarama/saklama.py`, `docs/saklama-politikasi.md` |
| Policy for deleting from backups | DONE (document) | `docs/saklama-politikasi.md`; the remote backup period awaits Ali |
| KVKK (Turkish personal data protection law) text draft | BLOCKED | Needs legal approval; only a draft can be written |

## Module 3: Health Intelligence v2 (P1)

| Request | Status | Evidence or gap |
| --- | --- | --- |
| Existing catalog, collector, rule system | DONE | 16 PostgreSQL checks, the rule engine |
| Version capability matrix (12-18) | MISSING | The catalog was written for 13-18, tested only on 16. PostgreSQL 12 is out of support; it should be recognized and reported |
| Statuses: PASS, FAIL, WARNING, UNKNOWN, NOT_APPLICABLE, UNAVAILABLE | PARTIAL | Finding and "could not be measured" exist; passing checks and the not-applicable state are not shown separately |
| Shared evidence model | PARTIAL | Every finding has an evidence dictionary; the rule ID, category, confidence level and source fields are missing |
| Health score and evidence coverage | MISSING | |
| History comparison | MISSING | Reports are tied to the company but there is no database identity |
| Categories: replication lag, wraparound, autovacuum, `pg_stat_statements`, HBA | PARTIAL | Some exist; the list expands in item 12 |

## Modules 4-8

| Module | Status | Note |
| --- | --- | --- |
| Customer portal (`/portal/`) | MISSING | `/demo/` is only a client-side demonstration. It does not open in production before email sending is chosen |
| Corporate site | PARTIAL | Theme C, TR/EN, canonical, hreflang, sitemap, robots exist. The service cards, "how it works", sample report and FAQ sections are missing or partial |
| Admin panel | PARTIAL | Company, scan, request, audit, system status exist. Indicator numbers and commercial process statuses are missing |
| Job queue | MISSING | In a file upload the analysis takes milliseconds, no queue is needed. A queue is needed only for direct connection |
| Reporting | PARTIAL | A single view, TR/EN, with evidence. There is no split between an executive summary and a technical report |

## Modules 9-12

| Module | Status | Note |
| --- | --- | --- |
| SQL Server | NOT_TESTED | Preview, off. The real server trial is with Ali |
| LLM summary | MISSING | P2, to be designed off by default |
| Mode B | PARTIAL, off | P3 in the document. The threat model, target validation, scan and a separate runner are written. New Mode B work was stopped until P0 and P1 are finished |
| Going live | NOT_TESTED | Ansible, nginx, systemd files exist. The nginx configuration was verified with a real nginx; nothing was run on a real server. Backup exists, the restore command and test do not |

## Points where I differ from the document

- **PostgreSQL 12:** Community support ended in November 2024. It enters the capability matrix as "out of support, recognized"; the queries cannot be tested separately on 12 (I only have 16).
- **Job queue:** The document suggests queuing every scan. For the file upload path this would be unnecessary complexity; it is suggested only for direct connection.
- **Mode B:** P3 in the document, brought forward in the code. It was not reversed, it is kept off.
- **Audit chain:** Keyed verification is not a full solution as long as the key stays on the same server. The chain head also needs to be written regularly to the outside (for example to a backup destination); choosing the destination is with Ali.

## Open P0 risks

1. The audit chain can be regenerated by someone who can write to the database.
2. Company records are kept indefinitely; the retention policy and data classes are not defined.
3. Restoring from backup has never been tried.
4. Nothing has been run on a real server.
5. There are no legal texts (a blocking decision).
