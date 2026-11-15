# Mode B (direct connection, "Kip B"): design and threat model

Status: the first slice is coded for PostgreSQL and is **off by default** (enabled with `ALIG_DOGRUDAN=1`). It has not gone live.

| Part | Location | Status |
| --- | --- | --- |
| Target validation (redirection to the internal network, DNS rebinding) | `tarama/hedef.py`, `tests/test_hedef.py` | Coded |
| Scan (ownership proof, superuser rejection, TLS, fixed catalog) | `tarama/baglanti.py`, `tests/test_baglanti.py` | Coded; tried by hand with real PostgreSQL 16 + TLS |
| Request flow and pages | `tarama/server.py` (`/api/tarama/baglan`), `tarama/hata.py` | Coded |
| Company permission | Admin panel, company detail: "Doğrudan bağlantı izni ver" (grant direct connection permission) | Coded |
| Request list (panel, read-only) | `yonetim/server.py` `/yonetim/kip-b`, `tarama/depo.py` `istek_listele`, `tests/test_yonetim.py` `KipBPanelTests` | Coded |
| Server certificate verification (`verify-full`, customer CA) | `tarama/baglanti.py` `ca_dogrula`, `tests/test_baglanti.py`, `tests/test_baglanti_tls.py` | Coded; tested with PostgreSQL 16 + TLS |
| Response time pinning | `tarama/server.py` `SABIT_RED_SN`, `SABIT_BAGLANTI_SN` | Coded; tested with a fake clock |
| Customer guide | `site/pages/tarama-hazirlik.html`, `docs/runbook.md` | Written; the fixed egress IP address is `[doldurulacak]` (to be filled in) |
| Separate runner process and systemd unit | `tarama/calistirici.py`, `tests/test_calistirici.py`, `alig-calistirici.service.j2` | Coded; not tested on a real server under systemd |
| SQL Server | none | **Not written** (the proof method is unclear) |

## Deviations from the design and what remains open

- **The runner was not tried on a real server.** The scan now runs in a separate process (`alig-calistirici`): a separate user, no access to the data directory and the service secrets, and the internal network is also forbidden at the systemd level. The web process passes the password in memory over a local socket and cannot connect outward. The live launcher (`tarama/server.py`) does not enable the feature without the runner socket. The unit file, the socket permissions and the `SupplementaryGroups` setting have not been tested on a real systemd; `ansible-lint` and the unit tests passed. There is no job queue: the request stays open until the scan finishes.
- **Administrator permission instead of e-mail verification.** Because a sending method has not been chosen, the company identity is not verified by e-mail. Instead, direct connection is open only to companies the administrator has permitted from the panel. Someone who knows the e-mail address of a permitted company can open a request in its name; they still cannot scan a database they do not manage (an ownership proof is required), but they can spend the company's scan allowance.
- **Server certificate verification is optional.** The default (if the customer does not give a CA) is unchanged: encrypted with `sslmode=require`, the certificate is not checked. `channel_binding=require` is mandatory in every case: the server must bind its identity to the TLS channel with SCRAM-SHA-256, so the password is not sent in plain or with MD5 and a man in the middle cannot relay the authentication. The cost: Mode B does not work with an account authenticated by the `md5` or `password` method (the error page mentions SCRAM). If the customer pastes their own CA as PEM in the password step, `sslmode=verify-full` and a temporary `sslrootcert` are used: the PEM size (16 KiB), block count (5), character set and DER start are validated, a private key and extra text are rejected; the file sits in a 0600 temporary directory and is deleted when the job ends; the CA is not stored; an invalid CA does not silently fall to the weak mode, it gives an error and does not spend the attempt allowance. The `sslrootcert` path also goes through a strict pattern similar to `GUVENLI_AD`. Missing: storing the CA permanently and using it in a scheduled scan (the password is not stored either), certificate revocation list (CRL) checking, and PG18 was not tested.
- **The target address is stored.** The server name and IP stay in the request record for at most one day (needed to run the scan). Only its digest is written to the audit record. The password is stored nowhere.
- **Port scan timing (partly closed).** The error message is uniform, and a target rejection (internal address, bad name or port, DNS error) is answered after at least 6 s and a connection error (unreachable port, wrong password) after at least 12 s with the same page. These are lower bounds: if DNS resolution or the connection exceeds this time there is no extra wait and a very slow response can still be distinguished (a separate timeout was not placed on the resolver). The ownership proof error and the superuser rejection occur after the connection is established, so they give a separate page and duration; only someone who knows a valid password sees them. Since only permitted companies can open requests and there is a limit of 5 requests per hour, the effect is limited. A waiting request holds a thread.
- **The scan is synchronous.** The request stays open until the scan finishes (about 2 minutes at most). At most two scans run at the same time.

## Difference from Mode A

In Mode A the customer runs the script on their own network and alig.tech does not connect to any database. In Mode B the customer gives the connection details and the scan runs from the alig.tech server. This brings two new risks: our server turns into a tool that opens connections outward, and the customer's credential sits with us for a while.

## Proposed flow

1. The customer logs in with a company record (e-mail verification mandatory; none today).
2. They enter the server address, port, database and the name of the scan account. The password is requested at the last step, once.
3. The server address is validated (the SSRF measures below) and the customer is given an ownership proof task.
4. When the proof is verified, the scan runs in a runner separate from the web process, with the same fixed query catalog as Mode A.
5. The password is erased from memory right after the scan and is not written to disk. The report is produced by the same path as Mode A.

## Threat model

| Threat | Measure | Test |
| --- | --- | --- |
| SSRF: the customer enters an address in our internal network or on the cloud metadata service | The name is resolved and **every** resulting address is checked: private (RFC 1918), loopback, link-local, CGNAT, multicast, IPv6 equivalents and our own address range are rejected. Only allowed ports (default 5432, 1433 and a port above 1024 entered by the customer) | `test_ic_ve_ozel_adresler_reddedilir`, `test_ipv4_tasiyan_ipv6_bicimleri_reddedilir`, `test_alisilmadik_sayisal_yazimlar_reddedilir`, `test_portlar` |
| DNS rebinding: the name resolves to a public address at check time and to an internal address at connection time | The name is resolved once and the connection is opened **to the resolved IP**; the TLS server name is given separately. No re-resolution | `test_rebinding_ikinci_cozumleme_olmaz`, `test_bir_kayit_bile_icse_tumu_reddedilir` |
| Bypass through redirects and proxies | Only the database protocol over raw TCP; no HTTP client is used, environment proxy variables are ignored | Check of the runner environment |
| Scanning someone else's database | Ownership proof: the customer adds a comment carrying a random value we give to the scan account (`COMMENT ON ROLE alig_hc IS 'alig-kanit-<random>'`); the scan reads this first and if it does not match no query runs | Tests for connections without proof and with wrong proof |
| Abuse as a port scanning and service discovery tool | The error message is uniform ("could not connect") and the duration is pinned to a lower bound (6 s target rejection, 12 s connection error); a per-company and per-target attempt limit; only permitted companies | Tests of duration and message with a fake clock (`test_hedef_red_nedenleri_ayni_sure_ve_govde`, `test_baglanti_hatalari_ayni_sure_ve_govde`) |
| Password leak | The password lives only in memory, for a single scan; it does not enter logs, the audit record, error messages or process arguments. The request body is not logged | A test that searches the log and the audit record for the password |
| Password read on the network | The connection requires TLS (at least `sslmode=require`, `channel_binding=require`). If the customer gives a CA, certificate verification is `verify-full` | `test_baglanti_tls.py` (PG16: the correct CA succeeds, a foreign CA and a mismatched name fail), CA PEM and `sslrootcert` escaping tests |
| Writes or long locks on the customer database | Same as Mode A: fixed catalog, read-only session, 15 s query and 2 s lock limit, a single connection. A scan with a superuser is rejected (only a warning in Mode A) | Existing catalog tests and the superuser rejection test |
| A malicious server harming us | Every value coming from the server goes through the same upload validation as Mode A (strict schema, size and type limits). The runner has a separate user, a separate systemd unit, no filesystem writes, and limited total time and response size | Tests for huge responses and malformed types |
| Compromise of the runner | The runner is separate from the web process and our databases; it only reads jobs from the job queue and writes the result back as validated JSON | Hardening check of the unit file |
| Denial of service | A limited number of concurrent scans, a daily per-company limit, a queue length limit | Limit tests |
| Repudiation and traceability | Who started a scan, when, and for which target digest (SHA-256 of the address) is written to the audit chain; the address itself and the password are not written | Chain test |

## Known limits

- The customer has to expose their database to the internet or allow our egress address. For most organisations Mode A is more suitable; Mode B is for small teams.
- The ownership proof shows the approval of someone who can write a comment on the scan account; it does not show the approval of the organisation. A contract and an authority declaration are still needed.
- An equivalent proof method for SQL Server has not been determined (there is no comment on a login).

## Pending decisions

1. ~~Will Mode B be built?~~ Answer: yes, the first slice is coded (off).
2. **Fixed egress IP address:** Needed so the customer can allow it in their firewall; depends on the hosting choice.
3. **E-mail sending method:** Mode B is not opened without company verification.
4. ~~Will the password be stored?~~ Implemented: it is not stored, it is asked again on each scan. If a scheduled scan is wanted, encrypted storage and key management need a separate design.
5. **Legal text:** The consent text showing that the customer gave us authority to connect.
