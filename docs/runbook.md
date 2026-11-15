# Operations runbook

Target: a single Ubuntu 24.04 server, nginx (TLS), two Python services (`alig-form` 8090, `alig-tarama` 8091, bound to 127.0.0.1 only), systemd timers.

## What is where

| Item | Path |
| --- | --- |
| Releases | `/srv/alig/releases/<version>`, with `current` and `onceki` (previous) links |
| Data (SQLite) | `/var/lib/alig/form.sqlite`, `/var/lib/alig/tarama.sqlite` |
| Backups | `/var/backups/alig/` (daily 02:17 UTC, last 14, 0600) |
| Secret salt and audit key | `/etc/alig/env` (`ALIG_FORM_SALT`, `ALIG_DENETIM_ANAHTARI`; readable only by root and the service group) |
| nginx logs | `/var/log/nginx/alig-*.log` (30 days; the report link token is not logged) |

## First installation

```sh
cd deploy/ansible
ansible-galaxy collection install -r requirements.yml
cp inventory.example.ini inventory.ini           # write the address
# group_vars/all.yml: certbot_eposta, yonetim_kullanici
# The admin user's ~/.ssh/authorized_keys must be populated, otherwise SSH hardening stops.
ansible-playbook site.yml --check --diff         # dry run first
ansible-playbook site.yml
```

## Release

```sh
python3 deploy/paketle.py --surum 1.0.0 --release     # stops if any placeholder field remains
cd deploy/ansible
ansible-playbook yayin.yml -e surum=1.0.0 -e paket=../../dist/alig-site-1.0.0.tar.gz
```

Flow: the package digest is verified, the package is unpacked, the manifest is verified, `current` is switched atomically, the services restart, then a local smoke test (5 attempts) and a `/surum.txt` check through the domain name are run. If any step fails, `current` returns to the previous release, the services restart, and the release ends with an error. On the first release there is no release to return to; the message says so.

## Rollback (manual)

```sh
ansible-playbook geri-al.yml        # returns to the "onceki" (previous) release, runs the smoke test
```

The database schema changes only through forward migrations; data is not rolled back when a release is rolled back. Before a release that changes the schema, take a backup by hand: `sudo -u alig-web python3 /srv/alig/current/deploy/bakim.py --veri /var/lib/alig --yedek /var/backups/alig`.

## Restoring from a backup

The command first validates the backup: SQLite integrity check, tables and schema version (a backup cannot be newer than the code), and the integrity of the audit chain. Validation does not touch the real file; it runs on a temporary copy. Without `--evet` (yes) nothing changes.

```sh
sudo systemctl stop alig-form alig-tarama alig-yonetim
# 1) check (dry run); provide the key and the chain head if you have them
sudo -u alig-web bash -c 'set -a; . /etc/alig/env; \
  python3 /srv/alig/current/deploy/bakim.py geri-yukle --veri /var/lib/alig \
  --dosya /var/backups/alig/tarama-<time>.sqlite --bas /safe/place/bas.json'
# 2) the same command with --evet really restores
sudo systemctl start alig-form alig-tarama alig-yonetim
python3 /srv/alig/current/tarama/depo.py dogrula /var/lib/alig/tarama.sqlite   # chain, with the key
```

Behaviour:
- If another process holds the target file (or `-wal`, `-shm`) open, the command stops; stop the services first. The check is done through `/proc`, so run the command as the same user as the services (`alig-web`) or as root; processes of other users cannot be seen.
- The existing file is not deleted; it stays next to the new one as `<name>.onceki-<time>`, so you can put it back if something goes wrong. Delete it by hand when it is no longer needed.
- Run the command as the `alig-web` user; if run as root, the file owner is kept as that of the previous file.
- The old `-wal` and `-shm` files are removed, the new file is written with 0600 permissions, and after loading, the integrity and a content digest are compared with the backup; on a mismatch the previous file is put back.
- Exit code: 0 success or dry run, 1 validation or restore error (nothing changed), 2 usage error.
- Keyed records cannot be verified without the key and a warning is given; with a wrong key the backup is rejected. If the chain head is not given, a backup that was produced from scratch or whose last records were truncated cannot be caught; the command writes this as a warning.
- A restore does not bring back records (reports, requests, audit) made after the moment the backup was taken.

The backup sits on the same disk as the server: it gives no protection against losing the server. Copy the backup directory regularly to another place `[doldurulacak: uzak yedek hedefi]` (to be filled in: remote backup target). It can also be restored into an empty data directory after a server loss (if the target file does not exist it is written directly).

**Status:** unit tests try the restore in a temporary directory (corruption, truncated chain, wrong key, target in use). It has not yet been tried on a real server, by stopping and starting the systemd services.

### Audit chain: key and chain head

The `alanlar` (fields) column of the records (company, target, result, reason, IP digest) is part of the digest; if it is changed, the chain breaks. When an administrator logs in from a new IP, "login from a new IP" is written to the audit (a user's first login does not count as a warning). IPs are not written in plain text: they are kept as a 16-character digest, with HMAC if there is an audit key.

New audit records are written as HMAC-SHA-256 with `ALIG_DENETIM_ANAHTARI`; if there is no key, the old SHA-256 format is used. Old records are not broken. If a keyless record follows keyed records, the chain is counted as broken. The key must be at least 32 characters; with a short key the services do not start.

Verification reads the key from the environment: `sudo bash -c 'set -a; . /etc/alig/env; python3 /srv/alig/current/tarama/depo.py dogrula /var/lib/alig/tarama.sqlite'`. If run without the key, the linkage is checked, the HMAC cannot be checked, and the command returns 1.

As long as the key and the database are on the same server, someone with full access to the server can regenerate the chain. To catch this, write the chain head off the server regularly: `python3 /srv/alig/current/tarama/depo.py bas /var/lib/alig/tarama.sqlite > bas.json`. Later it is checked with `dogrula <db> --bas bas.json`; if the chain head has changed or the last records have been truncated, the chain comes out broken. Where the chain head will go remains open as `[doldurulacak: zincir başı hedefi]` (to be filled in: chain head target). Keep the key apart from the backups; if the key is lost, old keyed records cannot be verified.

The backup sits on the same disk as the server: it gives no protection against losing the server. Copy the backup directory regularly to another place `[doldurulacak: uzak yedek hedefi]`.

## PostgreSQL backup and restore (after the migration)

This section is for after the move to PostgreSQL; today the runtime is SQLite and the `bakim.py` backup above applies. The tool is `db/yedek.py` and is independent of the application. **Status:** the drill passed on a temporary PG16 cluster (`tests/test_pg_yedek.py`); it has not been tried on a live server, `BACKUP_RESTORE_VERIFIED = false`. There is no RPO/RTO target (decision DB-K5); the duration is measured only by drills. `pg_dump` provides no PITR; point-in-time recovery is done only with a base backup plus a WAL archive.

Defaults (until the encryption decision DB-K6 arrives):
- The backup and WAL archive directories are on an **encrypted volume**, owned by the server user, with permissions **0700**. If there is no encrypted volume, the backup is not counted as encrypted; the tool does not encrypt.
- The backup does not sit on the same disk as the database and is copied elsewhere `[doldurulacak: uzak yedek hedefi]`.
- The `alig_backup` role's password goes through `PGPASSFILE` (0600); no password is put on the command line. A `replication` line is needed in `pg_hba.conf` (DB-K2).

WAL archive (the server administrator puts it in `postgresql.conf`; the tool does not touch the server). To generate the text:

```sh
python3 db/yedek.py arsiv-onerisi --wal-arsivi /var/backups/alig-pg/wal
# archive_mode = on ; archive_command = 'test ! -f .../%f && cp %p .../%f.gecici && mv .../%f.gecici .../%f'
```

Daily backup, verification and retention (operator or timer, as the server user):

```sh
export PGHOST=/var/run/postgresql PGPASSFILE=/etc/alig/pgpass
python3 db/yedek.py al --kok /var/backups/alig-pg/temel            # pg_basebackup + pg_verifybackup, the backup is deleted if corrupt
python3 db/yedek.py dogrula --yedek /var/backups/alig-pg/temel/pg-<UTC time>
python3 db/yedek.py eskileri-sil --kok /var/backups/alig-pg/temel --sakla 7          # lists first
python3 db/yedek.py eskileri-sil --kok /var/backups/alig-pg/temel --sakla 7 --evet
```

`eskileri-sil` (delete old) does not delete the WAL archive; clean the archive by hand with `pg_archivecleanup` according to the start WAL of the oldest retained backup, otherwise the disk fills up.

Restore (always into a **new, empty directory**; an existing cluster is never overwritten, the tool stops on a non-empty directory):

```sh
# 1) dry run: the plan is written, nothing changes
python3 db/yedek.py geri-yukle --yedek .../pg-<time> --hedef /var/lib/postgresql/geri --wal-arsivi .../wal --hedef-zaman "2026-11-15 10:00:00+03"
# 2) the same command with --evet
```

Afterwards: the directory must be owned by the server user; the copy carries the configuration of the source cluster, so **before starting it, make the port and socket path different** from the source (if on the same machine). `archive_mode = off` is written; the restored cluster does not write to the source's archive. Start the cluster and wait until `pg_is_in_recovery()` is `f`; changes after the target time do not arrive. Write the time with the time zone. If the WAL covering the time after the target is not in the archive, recovery gives an error (a missed archive segment is completed with `pg_switch_wal()`). Verify the audit chains (`alig.denetim`, `alig.yonetim_denetim`). Connecting the application to the restored cluster is a separate, manual decision.

Drill: the same steps run automatically on a temporary PG16 cluster (`python3 -m unittest tests.test_pg_yedek -v`; the duration is at the end of the test output). On the live server a regular drill and a record of the measured duration are needed (the frequency is Ali's decision); an unmeasured RTO is not written as "met".

## Monitoring

`alig-izleme.timer` runs the smoke test every 5 minutes (`http://127.0.0.1:8081`). On failure `alig-uyari.service` writes a critical entry to the system log. The notification path (e-mail or message) is `[doldurulacak: bildirim yöntemi]` (to be filled in: notification method); it is connected by changing `ExecStart` in `/etc/systemd/system/alig-uyari.service`.

```sh
systemctl list-timers 'alig-*'
journalctl -u alig-izleme -n 50
journalctl -u alig-form -u alig-tarama -n 100
```

## Admin panel

The `alig-yonetim` service listens only on `127.0.0.1:8092`. There are two access paths (`group_vars/all.yml`, `yonetim_izinli_ipler`, allowed IPs):

- **Empty (default):** The panel is not exposed to the internet; nginx returns 404 for `/yonetim`. Access is through an SSH tunnel: `ssh -L 8092:127.0.0.1:8092 deploy@server`, then `http://localhost:8092/yonetim/` in the browser. The panel service serves the style and logo files itself.
- **IP list filled in:** nginx opens the path `https://alig.tech/yonetim/` only to those addresses and returns 403 to others. Write your office or VPN exit address.

User management is done on the server, as the service user:

```sh
sudo -u alig-web python3 /srv/alig/current/yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite ekle ali
#   asks for a password (at least 12 characters), shows the key for the authenticator app once
sudo -u alig-web python3 /srv/alig/current/yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite liste
... parola ali | totp-yenile ali | sil ali      # when the password or key changes, open sessions are closed
```

Login: username, password and a 6-digit verification code. After 5 failed attempts in 15 minutes the user is blocked, and after 10 attempts the IP address is blocked, for 15 minutes. A session closes after 30 minutes idle or after 8 hours. If the verification device is lost, follow the "Verification device loss" section below.

The Firmalar (companies) page shows, in one list, the companies that upload a health scan and that fill in the contact form. The buttons (Turkish UI labels): Pasif et / Aktif et (make inactive / active; an inactive company cannot upload a new scan, its existing reports stay), Tarama hakkını sıfırla (reset the scan allowance; clears the 30-day count), Not (note), Kalıcı olarak sil (delete permanently: the company record and its reports; contact requests stay).

Every action in the panel (login, viewing requests and reports, status changes, deletion) is written to the admin audit chain; access to a customer report additionally lands in the scan chain as `yonetici:<name>`. `yonetim.sqlite` contains verification keys: for this reason its backups are 0600; encrypt them when copying elsewhere.

### Verification device loss

The user lost or replaced the phone that holds the authenticator app. There is nothing to do from the panel: `yonetim/kullanici.py` is run on the server, as the service user. For this reason another administrator who can SSH into the server is needed; if nobody can get into the server, server access is recovered first (this section does not cover that).

1. **Verify identity.** Make sure the requester is who they say they are (a call back by phone, or in person). For an administrator account the key is not renewed on a request that arrives only by e-mail or message.
2. **Lost or stolen?** If it was only replaced, step 3 is enough. If it may have been stolen or may have fallen into someone else's hands, do step 4 as well after step 3: the app on the phone alone does not let one person in, but it provides the second factor, and the password may also be known.
3. **Renew the key.** In an SSH session that does not take a terminal recording (`script`, session recording or screen sharing off):
   ```sh
   sudo -u alig-web python3 /srv/alig/current/yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite totp-yenile ali
   ```
   The command writes the new key and the `otpauth://` address once; the user adds this to the new device. Do not paste the key into chat, e-mail or a ticket system; give it to the user in person or on a screen only they will see. The old key becomes invalid immediately, the counter is reset, and the user's open sessions are closed.
4. **If it may have been stolen, renew the password too:** `... kullanici.py --db /var/lib/alig/yonetim.sqlite parola ali` (asks for the password from the terminal; it closes open sessions again). In the admin audit log (`/yonetim/denetim?kaynak=yonetim`) look at the user's latest logins and the "login from a new IP" lines; if there is a login you do not recognise, treat it as an incident.
5. **Verify.** `... kullanici.py --db /var/lib/alig/yonetim.sqlite liste` shows the user. The user logs in with the new device. In the admin audit chain there must be the line `dogrulama kodu anahtari yenilendi: <name>` (actor `cli`) and, depending on the case, `parola degisti, oturumlar kapatildi: <name>`.

Known limits:

- If the user tried many wrong codes with the old device, they are blocked for 15 minutes. `totp-yenile` does not reset this counter; wait 15 minutes. The block lifts by itself when the time expires.
- The same 6-digit code is not accepted twice. When trying the first code after adding the new device, do not enter the previous window's code; wait for the next code.
- `yonetim.sqlite` keeps TOTP secrets in plain text (`docs/kod-inceleme.md` ALIG-SEC-001 S1, decision SEC-K1). For this reason the `/var/lib/alig` directory and the backups must be open only to the service user (0700 is targeted; files 0600). The disk and the backup medium must be encrypted; when copying a backup elsewhere, additionally encrypt it. The command line tool creates files with 0600 even under a loose umask.
- `kullanici.py kod <name>` reads the secret from the database and prints a current code; it is only for local testing, do not use it on a live server.
- If all administrator accounts are lost or the database does not exist: a new account is opened with `ekle` (if there is one, the `--db` file is restored from a backup, see the "Restoring from a backup" section).

## Health score coefficients

The health score in the report is computed with default coefficients; the method and values are in `docs/kural-katalogu.md`, under the "Sağlık puanı" (health score) heading. To change them, write a JSON file on the server and give only the values you want to change; those not given stay at the default:

```sh
sudoedit /etc/alig/puan.json
#   {"agirlik": {"kritik": 12}, "kredi_uyari": {"orta": 0.4}, "kategori_carpani": {"guvenlik": 1.5}}
sudo chown root:alig-web /etc/alig/puan.json && sudo chmod 0640 /etc/alig/puan.json
echo 'ALIG_PUAN_AYARI=/etc/alig/puan.json' | sudo tee -a /etc/alig/env
sudo systemctl restart alig-tarama alig-yonetim
```

Fields: `agirlik` (weight: kritik, yuksek, orta, dusuk, bilgi; 0-1000), `kredi_uyari` (warning credit: orta, dusuk, bilgi; 0-1), `kategori_carpani` (category multiplier: guvenlik, performans, konfigurasyon, bakim, kapasite, ha_dr, yedek; 0-100). Status credits are fixed: Bilinmiyor (unknown) and Alınamadı (could not be obtained) always get 0. If the file is invalid (unknown field, out-of-range value, malformed JSON, duplicate key, all weights zero) `alig-tarama` and `alig-yonetim` do not start; the reason is shown by `journalctl -u alig-tarama -n 20`. The two services read the same file; the report and the panel show the same score. The score is not stored, it is computed each time a report is opened: when a coefficient changes, the score of old reports changes too. The effective values are on the System page in the panel.

## E-mail verification (off by default)

When off, the report link is shown right after the upload and the e-mail address entered is not verified; in the panel the companies appear as "unverified". When on:

- After the upload the page only says "check your e-mail"; the report link goes only by e-mail and is valid for 24 hours.
- Opening the link (GET) changes nothing; e-mail security scanners open links by themselves. The free allowance is spent when verified by the button on the page (POST), and the company's e-mail becomes verified.
- At most 3 pending links per address and 5 per company are sent in 24 hours.
- The web process does not reach the network: the message is written to the outbox in `tarama.sqlite`, and the `alig-posta` service sends it. The text of a sent message (the link) is deleted immediately; the record is deleted after 7 days.

To turn it on (Ansible `group_vars/all.yml`):

```yaml
eposta_dogrulama: true
smtp_sunucu: smtp.provider.com   # 587: STARTTLS required, 465: direct TLS; plain SMTP is not supported
smtp_port: 587
smtp_kullanici: username
eposta_gonderen: tarama@alig.tech
```

The SMTP password does not go into the repository: add the line `ALIG_SMTP_PAROLA=...` by hand to `/etc/alig/env` on the server, then run `ansible-playbook site.yml` and `yayin.yml`. Check: `python3 /srv/alig/current/deploy/hazirlik.py sunucu` (is `alig-posta` running, is the password defined). Messages that cannot be sent: `sqlite3 /var/lib/alig/tarama.sqlite "SELECT id, durum, deneme, son_hata FROM posta ORDER BY id DESC LIMIT 20"`; after 5 failed attempts the message becomes "basarisiz" (failed) and its text is deleted.

To try locally: `ALIG_EPOSTA_DOGRULAMA=1 python3 yerel.py`; to read the messages, `ALIG_POSTA_DIZINI=yerel-posta python3 tarama/posta.py --db yerel-tarama.sqlite` (messages are written as `.eml`).

**Status:** sending was tested with a fake SMTP object (STARTTLS before login, no password sent if there is no STARTTLS, direct TLS on 465). It has not been tried with a real SMTP server.

## Customer portal (off by default)

The portal is under `/portal/`. To turn it on, `group_vars/all.yml` must have `musteri_portali: true` **and** `eposta_dogrulama: true`; without the second, Ansible stops and the service does not start either (`ALIG_PORTAL=1` is accepted only when e-mail verification is on). Do not turn it on before real SMTP sending is set up and tried: the account is opened when the owner of the address confirms the link in the e-mail.

- Login: e-mail and password (at least 12 characters, scrypt). A wrong login is blocked for 15 minutes after 5 attempts per e-mail and 10 per IP. A session lasts 30 minutes when idle, at most 8 hours; the cookie is `HttpOnly`, `SameSite=Strict`, with path `/portal`.
- Users in the same corporate domain see the reports of the same company (`ornek.com.tr`); free mail addresses (gmail etc.) stand alone.
- Company isolation is in the data layer (`tarama/portal_depo.py` `Kapsam`): every query is limited to the company of the user in the session; another company's report gives the same response as a nonexistent ID.
- The platform administrator's account and session are separate (`yonetim.sqlite`); a portal account does not enter the panel.
- Making a company inactive from the panel immediately invalidates that company's portal login and open sessions; when a company is deleted its accounts are deleted too.
- For the portal user: the report list (in the last 20 rows, the score change compared with the previous scan), permanently deleting a report (confirmation page + form code; a deleted report does not give back the free scan allowance), the free scan allowance and its renewal date, a service request (at most 5 per day per company), an account and data deletion request (a single open request per company).
- Administrator side: **Portal talepleri** (portal requests) in the panel (status: Yeni = new, İnceleniyor = under review, Tamamlandı = completed, Reddedildi = rejected). A deletion request is only a record, it does not delete the data by itself: verify the identity, apply it with **Firmayı sil** (delete company) on the company page (portal accounts and requests are deleted too), then mark the request as Tamamlandı. No automatic e-mail goes to the requester; the reply is given from your own e-mail.
- Password reset does not exist in this slice: for a user who forgot the password, a new account request cannot be made (if there is an active account at the address, the request does not open a new account). Password reset comes in the next slice; do not turn it on for production until then.

## Direct connection (Mode B, off by default)

In Mode B the customer gives the connection details and the scan runs on the alig.tech side, in the separate `alig-calistirici` (runner) process (`docs/kip-b-tasarim.md`). It does not open without `ALIG_DOGRUDAN=1` and the runner socket; the decision to open is separate, and this section does not open it. A customer can open a request only for companies for which the administrator has pressed "Doğrudan bağlantı izni ver" (grant direct connection permission) on the company page.

**Monitoring requests.** In the panel **Kip B istekleri** (Mode B requests, `/yonetim/kip-b`): read-only, paginated by 25, with `firma` (company) and `durum` (status: bekliyor = pending, tamam = done, iptal = cancelled, deneme = attempt) filters. The target (name:port), database, account, number of attempts and validity end are visible. The password, connection string, ownership proof, token and IP are not shown; the password is not stored anywhere. Request records are deleted when they expire. Every view of the panel is written to the audit chain.

**Preparation you give to the customer** (site: `/tarama-hazirlik/`, "Doğrudan bağlantı (Kip B) için hazırlık", i.e. preparation for direct connection):

1. A read-only role: `alig-rol.sql` (member of pg_monitor, read-only session, 15 s query, 2 s lock). The password is set with `SET password_encryption TO 'scram-sha-256'`; a superuser is rejected.
2. `pg_hba.conf`: only TLS and only from our fixed egress address, `scram-sha-256`:

   ```
   hostssl  postgres  alig_hc  [doldurulacak: alig.tech çıkış IP adresi]/32  scram-sha-256
   ```

   (the bracketed placeholder means: alig.tech egress IP address.) The fixed egress IP address depends on the hosting choice and is **not yet known** (`docs/kip-b-tasarim.md`, pending decisions); do not have the customer allow it in the firewall until the address is written. Until the field in the site text is filled in, `--release` packaging stops (`docs/doldurulacak.md`).
3. `channel_binding=require`: mandatory on every connection. The account must authenticate with SCRAM-SHA-256 and bound to the TLS channel; Mode B does not work with an account using the `md5` or `password` method (deliberately). `ssl = on` on the customer server.
4. Server certificate verification (optional): if the customer pastes their own CA as PEM in the password step, the connection is made with `sslmode=verify-full` and a temporary `sslrootcert`.

**How certificate verification works.**

- **Default (when no CA is given, unchanged):** `sslmode=require` + `channel_binding=require`. The connection is encrypted and channel-bound but the server certificate is not checked; this is the behaviour before this section and is not downgraded.
- **If a CA is given:** `sslmode=verify-full`. The certificate chain must match the given CA and the name in the certificate (SAN) must match the server name entered; if not, the scan does not start and the customer sees the "could not connect" page. It does not silently fall to the weak mode.
- **CA input:** at most 16 KiB, at most 5 `BEGIN CERTIFICATE` blocks, ASCII and base64 only; a private key, extra text, a header line, NUL and a body that does not start with a DER `SEQUENCE` are rejected (the "CA certificate not accepted" page; the attempt allowance is not spent, no connection is opened). The same check is repeated in the runner.
- **Temporary file:** in the runner user's private `/tmp` space (`PrivateTmp`), a 0700 directory and a 0600 file; deleted when the job ends, whether the scan succeeded, failed or errored. The CA text is not written to the database, the audit record or the log.
- The `sslrootcert` path goes through a strict pattern before it enters the connection string (absolute path; letters, digits, `. _ / -`); a path containing a space, quote, `=`, backslash or line break is rejected.

**Response time pinning.** A target rejection (internal address, bad name or port, DNS not resolving) and a connection error (unreachable port, wrong password) give the same page and the same minimum duration; this makes it harder to scan the internal network through response timing. Targets rejected at the form step are answered after at least 6 s (`SABIT_RED_SN`), and connection errors at the password step after at least 12 s (`SABIT_BAGLANTI_SN`, covers the psql `connect_timeout=10` s). These are **lower bounds**: if name resolution or the connection already exceeds this time there is no extra wait, so a very slow DNS can still be distinguished. A successful flow and errors unrelated to the target (no permission, invalid e-mail) are not delayed. A waiting request holds a thread; the limits of 5 requests per hour and concurrent scans bound this load.

**Test status.** Certificate verification was tested on PostgreSQL 16 with a real TLS connection (`tests/test_baglanti_tls.py`, a temporary self-signed CA): the correct CA and name succeed; a foreign CA and a mismatched server name fail; the default without a CA connects as before. It was not tested on PG18 or on a real customer server; the behaviour of the runner under systemd (private `/tmp`) was not tested on a real server.

## Troubleshooting

| Symptom | Look at |
| --- | --- |
| The site cannot be reached | `systemctl status nginx`, `nginx -t`, `ufw status` |
| Form or upload 502 | `systemctl status alig-form alig-tarama`, is the port listening: `ss -ltnp \| grep -E '8090\|8091'` |
| Upload 413 | File above 5 MB or the nginx `client_max_body_size 6m` limit |
| Upload 429 | Company limit (2 in 30 days) or rate limit. The limit data is in the `kullanim` table, no plain address is kept |
| Certificate did not renew | `certbot renew --dry-run`, `systemctl list-timers certbot*` |

## Changing the secret salt

Deleting the `/etc/alig/env` file and running `site.yml` generates a new salt. The salt affects only the IP digests in form records; old digests do not match new records, which is acceptable.

## What is tested in this repository

Status layer by layer: `docs/canli-kontrol-listesi.md` (DONE or NOT_TESTED). After deployment: `python3 /srv/alig/current/deploy/hazirlik.py sunucu` (users, permissions, keys, disk, services, ports; it does not print secret values, and returns 1 if there is a FAIL).

Tested: package reproducibility, the maintenance and backup script, the smoke test, the nginx configuration (`nginx -t` and end to end with real nginx 1.24: TLS, redirect, headers, proxy, upload limit, hiding the token in the log), the `current` link switching logic, Ansible syntax and lint.

Not tested (watch on the first run on a real server): applying Ansible to a real server, ufw and sshd rules, obtaining a certificate with certbot, systemd units starting with their hardening settings (`SystemCallFilter`, `MemoryDenyWriteExecute`). If a unit does not start, look first at `journalctl -u alig-form` and `systemd-analyze security alig-form`; find the cause instead of loosening the setting.
