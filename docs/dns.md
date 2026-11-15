# DNS and certificate

The DNS records must have propagated before the certificate is obtained; the certbot step in `site.yml` uses Let's Encrypt's HTTP validation.

| Name | Type | Value | Note |
| --- | --- | --- | --- |
| `alig.tech` | A | the server's IPv4 address | If the server gets IPv6, add an AAAA too. If you add it, the server must also work over IPv6. |
| `www.alig.tech` | CNAME | `alig.tech.` | nginx redirects www to the root domain with a 308. |
| `alig.tech` | CAA | `0 issue "letsencrypt.org"` | So that only Let's Encrypt can issue certificates. |

TTL: set it to 300 s before the installation, and to 3600 s once everything has settled.

## For e-mail (once the contact e-mail is known)

SPF, DKIM and DMARC records vary with the e-mail provider. `[doldurulacak: e-posta sağlayıcısı]` (to be filled in: e-mail provider). Recommended at minimum: start with `_dmarc.alig.tech TXT "v=DMARC1; p=none; rua=mailto:..."` and, watching the reports, move up to `quarantine` and `reject`.

## In order

1. Set up the server and write its address in `inventory.ini`.
2. Add the A and CNAME records and wait until `dig +short alig.tech` returns the correct address.
3. Run `site.yml` (it obtains the certificate and turns on HTTPS).
4. Publish the first release (`docs/runbook.md`).
5. HSTS is published for 1 year. If there is a certificate or HTTPS problem, browsers do not fall back to HTTP: in the first weeks you can start by setting `hsts_saniye` to 300 and increase it later (`group_vars/all.yml`).
