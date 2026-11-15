# Implementation plan

Status: `[x]` done and verified, `[ ]` pending.

1. [x] Repo skeleton, `.gitignore`, `config.example`, `CHANGELOG.md`
2. [x] Build script (TR/EN, reproducible, manifest, font pruning)
3. [x] CI checks and `run_all.py`, GitHub Actions definition (pinned to SHA)
4. [x] Home page draft, two directions (A Console, B Report), a working failover console in the hero
5. [x] Direction choice: C (Agent). Logo and background are temporary, see `site/assets/bg/README.md`
6. [ ] The counter theme (light/dark) of the chosen direction, to be designed separately
7. [ ] Other pages: Services, How it works, Security, About us, Articles (2 drafts)
8. [x] Portal demo (`/demo`): fleet, findings, approval queue, incident timeline, hardening score, audit log (SHA-256 verification in the browser), reports
9. [x] Form endpoint (`form/`): stdlib, SQLite WAL, validation, rate limit, honeypot, `/healthz`, tests
10. [x] Packaging: `alig-site-<version>.tar.gz` and manifest
11. [x] Ansible (`deploy/`): reverse proxy + TLS, firewall, SSH hardening, automatic security updates, form service (sandboxed systemd)
12. [x] Deployment and rollback: `releases/<version>`, the `current` link, smoke test, automatic rollback
13. [x] Monitoring, log retention (default 30 days), SQLite backup and restore script
14. [x] Runbook and `docs/dns.md`

Each step does not move on to the next until its verification passes.

## Health scan (docs/saglik-taramasi-tasarim.md)

1. [x] Design and threat model
2. [x] Catalog, rules, collector, store, upload validation, report, server, page (Mode A, PostgreSQL)
3. [x] Per-company limit (2 per 30 days per domain or free mail address). Email verification when the sending method is decided
4. [ ] SQL Server catalog
5. [ ] Mode B (direct connection): threat model written (`docs/kip-b-tasarim.md`), waiting for decisions before code
6. [ ] Optional language model summary

## Admin panel

1. [x] Login (password + verification code), session, CSRF, login limit, user CLI
2. [x] Overview, requests, scans and report, audit log, system
3. [x] Local run, package, systemd, nginx (IP list or SSH tunnel), runbook
4. [x] Companies: registration, active/inactive, scan allowance reset, note, deletion
5. [ ] If wanted: request export (CSV), notification, multiple roles
