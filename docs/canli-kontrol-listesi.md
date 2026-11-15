# Go-live checklist

The status of each row is only one of two values: **DONE** (there is evidence and the evidence command is written) or **NOT_TESTED** (not tried). Syntax checking, dry run and real deployment are separate layers: one layer passing does not mean the other passed.

Nothing in this repository was run on a real server. The rows in the real deployment layer are filled in after the first installation with `python3 deploy/hazirlik.py sunucu` and manual checks.

## 1. Syntax and configuration (on this machine)

| Item | Status | Evidence or gap |
| --- | --- | --- |
| Syntax of `yayin.yml` and `geri-al.yml` | DONE | `python3 deploy/hazirlik.py yerel` |
| Syntax of `site.yml` | NOT_TESTED | The `community.general` collection is not in this environment (to be tried with `hazirlik.py yerel` after `ansible-galaxy collection install -r deploy/ansible/requirements.yml`) |
| `systemd-analyze verify` of the 6 systemd units (including the Mode B unit) | DONE | `python3 deploy/hazirlik.py yerel`: the templates are rendered by Ansible itself; warnings about paths and users not on the target are left out; verified that a unit with a broken setting gives FAIL |
| Hardening settings in the units, loopback-only listening | DONE | `tests/test_deploy.py` `YapilandirmaTests` |
| Secrets are not in the repository | DONE | `tests/test_deploy.py` `test_sirlar_depoda_degil` |
| nginx configuration (`nginx -t`, TLS, redirect, headers, proxy, upload limit) | DONE | Tried by hand in an earlier session with real nginx 1.24; there is no automated test in the repository |
| Logic of the server check script (permissions, keys, disk thresholds) | DONE | `tests/test_deploy.py` `HazirlikTests` (in a temporary directory; not evidence from a real server) |
| Disk fullness protection of the backup script | DONE | `tests/test_deploy.py` `BakimDiskTests` |
| Restore-from-backup logic | DONE | `tests/test_deploy.py` `GeriYuklemeTests` (in a temporary directory) |
| The collector walking all databases | DONE | On a local PostgreSQL 16 cluster: a database with a space in its name was scanned, one without CONNECT privilege was skipped with "yetki" (privilege) (`GercekPgTests` and a manual run; not a server, a customer-side script) |
| E-mail sending (SMTP) | NOT_TESTED | Only with a fake SMTP object; no real provider was chosen |
| Services not starting with an invalid health score setting | DONE | `tests/test_puan.py` `BaslangicTests` (a call to `main()`, not a service process; not tried with systemd on a server) |

## 2. Dry run (needs the target server)

| Item | Status | Evidence or gap |
| --- | --- | --- |
| `ansible-playbook site.yml --check --diff` | NOT_TESTED | No server |
| `ansible-playbook yayin.yml --check --diff` | NOT_TESTED | No server |

## 3. Real deployment (on the server, after deployment)

| Item | Status | Evidence or gap |
| --- | --- | --- |
| Ansible applied to the server, no changes on a second run | NOT_TESTED | |
| The service user exists and cannot log in | NOT_TESTED | `hazirlik.py sunucu` |
| `/etc/alig` 0750, `env` 0640 root:alig-web, data 0750, backups 0700 | NOT_TESTED | `hazirlik.py sunucu` |
| The salt and audit key are in `env`, at least 32 characters | NOT_TESTED | `hazirlik.py sunucu` |
| Database and backup files are open only to the owner | NOT_TESTED | `hazirlik.py sunucu` |
| Disk fullness (more than 20% free on the data and backup disks) | NOT_TESTED | `hazirlik.py sunucu` |
| Services and timers are running, form/scan/admin only on 127.0.0.1 | NOT_TESTED | `hazirlik.py sunucu` |
| Units start with the hardening settings (`SystemCallFilter`, `MemoryDenyWriteExecute`) | NOT_TESTED | `systemd-analyze security alig-form` |
| Smoke test on the live address | NOT_TESTED | `deploy/duman_testi.py` |
| Certificate and renewal with certbot | NOT_TESTED | Needs DNS and a server |
| ufw and sshd rules | NOT_TESTED | Console access must be ready so as not to cut off access |
| Daily maintenance and backup ran on a real server | NOT_TESTED | The log after `systemctl start alig-bakim` |
| Restore from backup was tried on a real server | NOT_TESTED | `docs/runbook.md` |
| Mode B (only if it will be turned on) | NOT_TESTED | `docs/kip-b-tasarim.md` "before going live" |
| E-mail verification (only if it will be turned on): `alig-posta` is running, the message arrives, the link verifies | NOT_TESTED | `docs/runbook.md` "E-mail verification" |
| Legal texts, real contact details | NOT_TESTED | Waiting on Ali |
| Health score setting (only if the default will be changed): `/etc/alig/puan.json` is read by the service user, the panel System page shows "Bu kurulum için ayarlandı" (configured for this installation) | NOT_TESTED | `docs/runbook.md` "Health score coefficients" |
