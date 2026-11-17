# alig.tech

Corporate site, demo portal, health scan, admin panel and release pipeline for alig.tech, a database management company.
Python standard library only, no external resources.

The sections of this file marked with `<!-- oto:... -->` are generated from code by `ci/uret_readme.py`.
The hand-written parts are explanations and must be updated by hand.

Language note: the repository documentation is in English so outside readers can follow it. Customer-facing site text is
bilingual by design (Turkish and English). Identifiers (file, module, function, table and column names, environment
variables) are Turkish and are deliberately not renamed. KVKK (the Turkish personal data protection law) and BDDK
(the Turkish banking regulator) are kept under their Turkish names.

## Status

- Home page: direction C (puts the agent service first) is the default theme. Logo and background are temporary.
- The portal demo (`/demo/`), contact form, health scan (Mode A, PostgreSQL) and admin panel (`/yonetim/`) work.
- The admin panel has company management: name and email are stored in plain text, active/inactive, note, scan allowance reset, deletion.
- Release files (Ansible, nginx, systemd) are written. The syntax of `yayin.yml` and `geri-al.yml` and 6 systemd units were verified; the syntax of `site.yml` needs an Ansible collection and could not be tried in this environment. Nothing was run on a real server. Layer-by-layer status: `docs/canli-kontrol-listesi.md`.
- The SQL Server scan is coded as a preview, has not been tested on a real server and is off by default.
- Email verification is coded and off by default: turning it on needs an SMTP provider and a sender address (`docs/runbook.md`). The collector scans every database it can connect to.
- In the health scan every rule produces a single status with a permanent ID (PASS, FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE); PASS is never produced when data is missing. Rule list: `docs/kural-katalogu.md`.
- The report shows the health score (0-100), category scores and evidence coverage together; an unknown status does not raise the score. Method and default coefficients: `docs/kural-katalogu.md`, setting: `ALIG_PUAN_AYARI` (`docs/runbook.md`).
- The report is compared with the same company's earlier scan of the same server (if the retention period has not expired); evidence that disappeared is not counted as resolved.
- The PostgreSQL scan also runs on a standby server; checks that rely on table statistics and archiving are Not applicable there. The replication lag, autovacuum, multixact age, pg_stat_statements and temporary file checks were tested on a real PostgreSQL 16 primary and standby.
- PostgreSQL 12-18 version and privilege matrix: `docs/surum-matrisi.md`. The queries were tested on a real server only on PostgreSQL 16; on other versions the report shows evidence confidence at most medium.
- Open work: choosing the email sending method, testing the SQL Server scan on a real server, turning on Mode B (coded, off), the optional language model summary. Order and status: `docs/yol-haritasi.md`. Source document: `docs/master-prompt-v2.md`. Current-state analysis: `docs/faz0-analiz.md`. Latest code review: `docs/kod-inceleme.md`.

## Running locally

Easiest: `python3 yerel.py` (`python yerel.py` on Windows). It builds the site and opens it at `http://localhost:8080/`; the form, scan and admin panel also work at that address.

Building by hand:

```sh
python3 build/build.py --theme c --out dist/c
python3 -m http.server 8080 --directory dist/c
```

<!-- oto:basla temalar -->
Design themes: `a`, `b`, `c`. The default theme is `c` (`--theme c`).
<!-- oto:bitis temalar -->

In the browser: `http://localhost:8080/` (Turkish) and `/en/` (English). Hash digests need
`localhost` or HTTPS (`crypto.subtle`).

## Checks

The same command locally and in CI:

```sh
python3 ci/run_all.py --theme c             # merge request
python3 ci/run_all.py --theme c --release   # release tag: no field to be filled in may remain
python3 -m unittest discover -s tests       # unit tests only
python3 ci/uret_readme.py                   # updates the README automatic sections (run_all does this too)
```

<!-- oto:basla denetimler -->
`run_all.py` runs these 16 checks in order:

1. build
2. collector up to date
3. sample report up to date
4. unit tests
5. postgresql tests
6. html structure
7. internal links
8. external resources
9. size budget
10. accessibility
11. secret scan
12. workflow pinning
13. banned patterns
14. language parity
15. placeholders
16. readme up to date
<!-- oto:bitis denetimler -->

<!-- oto:basla testler -->
Unit tests: 936 tests (PostgreSQL tests are counted separately in the `postgresql tests` step: an external server if `ALIG_TEST_PG_HOST` is set, otherwise a temporary cluster with the system PostgreSQL 16; if neither exists, SKIP, and an error in `--release` mode).
<!-- oto:bitis testler -->

## Directories

<!-- oto:basla dizinler -->
| Directory | Contents |
| --- | --- |
| `site/` | Source: `i18n/` (TR and EN texts), `partials/`, `pages/`, `themes/`, `assets/` |
| `build/` | `build.py`, reproducible build and SHA-256 manifest |
| `ci/` | Check scripts, `run_all.py`, the generator script for this README |
| `tests/` | Unit tests |
| `docs/` | Design notes, plan, runbook, DNS, fields to be filled in |
| `form/` | Contact form endpoint (stdlib, SQLite) |
| `tarama/` | Health scan: collector templates, catalog, rules, server, store; `onsurum/` is the SQL Server preview |
| `yonetim/` | Admin panel (TOTP login, audit chain) |
| `deploy/` | Packaging, maintenance, smoke test, Ansible |
<!-- oto:bitis dizinler -->

## Routes

<!-- oto:basla rotalar -->
| Path | Source | Description |
| --- | --- | --- |
| `/` | `site` | Static site (TR), `/en/` English |
| `/demo/` | `site` | Portal demo (client side only, no server) |
| `/saglik-taramasi/` | `site` | Scan upload page |
| `/tarama-hazirlik/` | `site` | Customer preparation guide (scan account, steps) |
| `/api/iletisim` | `form/server.py` | Contact form (POST) |
| `/healthz` | `form/server.py` | Form health check |
| `/api/tarama/yukle` | `tarama/server.py` | Scan file upload (POST) |
| `/rapor/<token>/` | `tarama/server.py` | Report page (random link) |
| `/rapor/<token>/sil` | `tarama/server.py` | Delete the report immediately (POST) |
| `/rapor/<token>/dogrula` | `tarama/server.py` | Email verification: opens the report, spends the allowance (POST, off by default) |
| `/api/tarama/saglik` | `tarama/server.py` | Scan server health check |
| `/api/tarama/baglan` | `tarama/server.py` | Direct connection form and request (off by default) |
| `/api/tarama/baglan/<token>` | `tarama/server.py` | Take the password and run the scan (POST, off by default) |
| `/yonetim/giris` | `yonetim/server.py` | Admin login (password + TOTP) |
| `/yonetim/` | `yonetim/server.py` | Overview |
| `/yonetim/firmalar` | `yonetim/server.py` | Companies: list, active/inactive |
| `/yonetim/firmalar/<id>` | `yonetim/server.py` | Company details, note, scan allowance, deletion |
| `/yonetim/talepler` | `yonetim/server.py` | Contact requests |
| `/yonetim/firmalar.csv` | `yonetim/server.py` | Company list CSV export |
| `/yonetim/talepler.csv` | `yonetim/server.py` | Request list CSV export |
| `/yonetim/taramalar` | `yonetim/server.py` | Scan reports |
| `/yonetim/denetim` | `yonetim/server.py` | Audit log and chain verification |
| `/yonetim/sistem` | `yonetim/server.py` | System status |
<!-- oto:bitis rotalar -->

## Adding new text

Texts live in `site/i18n/tr.json` and `en.json`, under the same keys. In a template `{{key}}` is written
escaped and `{{key_html}}` raw; a missing key stops the build. In place of every claim that cannot be proven,
`[doldurulacak: ...]` ("to be filled in") is written; the current list is in `docs/doldurulacak.md`.

## Fonts

Schibsted Grotesk, Source Serif 4 and Red Hat Mono, SIL OFL 1.1. The files are local under `site/assets/fonts/`,
with the license texts next to them. The build leaves fonts the theme does not use out of the output.

## Form endpoint

`form/server.py`: `ALIG_FORM_SALT=... python3 form/server.py --db /var/lib/alig/form.sqlite`.
The reverse proxy must forward the `/api/iletisim` and `/healthz` paths to 127.0.0.1:8090 and set the `X-Real-IP`
header. Records are SQLite WAL, times are UTC, the IP is a salted digest.

## Health scan

`tarama/` (server, rules, store). The collector `site/assets/alig-toplayici.py` is generated from the catalog:
`python3 tarama/uret_toplayici.py` (CI checks that it is up to date with `--kontrol`).
Company name and email are stored in plain text; for the privacy notice and the retention period see
`docs/doldurulacak.md`. Testing against a real PostgreSQL: if the system has PostgreSQL 16, the tests set up their own temporary cluster
(`tests/pg_yardimci.py`); for an external server use
`ALIG_TEST_PG_HOST=<socket directory> ALIG_TEST_PG_PORT=<port> ALIG_TEST_PG_USER=<role> python3 -m unittest tests.test_tarama`.

### SQL Server (preview)

The catalog, collector (`tarama/onsurum/alig-toplayici-mssql.py`), rules and tests are ready; it has not been tested on a real SQL Server.
It is not published on the public page; the server accepts these files only with `ALIG_MSSQL=1` (turned on in `yerel.py`).
Test steps: `docs/mssql-onsurum.md`.

### Direct connection (Mode B, off)

The customer provides the connection details and the scan runs in a separate runner process (`tarama/calistirici.py`): `/api/tarama/baglan`. In production it is turned on only with `dogrudan_baglanti: true` (Ansible) and only companies
granted "Direct connection permission" in the admin panel can use it. The password is not stored. What must be done
before going live: `docs/kip-b-tasarim.md`.

## Admin panel

`yonetim/` (stdlib). Locally: `python3 yerel.py`, then
`python3 yonetim/kullanici.py --db yerel-yonetim.sqlite ekle ali` and `http://localhost:8080/yonetim/`.
To try it locally without an authenticator app, an instant code:
`python3 yonetim/kullanici.py --db yerel-yonetim.sqlite kod ali`.
Login is with password and TOTP; every action is written to a SHA-256 chained audit log.
Production use: `docs/runbook.md`.

## Going live

`deploy/paketle.py` (reproducible package), `deploy/ansible/` (setup, release, rollback),
`deploy/bakim.py` (backup), `deploy/duman_testi.py` (smoke test). Steps: `docs/runbook.md`, DNS: `docs/dns.md`.

<!-- oto:basla ansible -->
Ansible roles: `servisler`, `temel`, `web`, `yayin`.
<!-- oto:bitis ansible -->
