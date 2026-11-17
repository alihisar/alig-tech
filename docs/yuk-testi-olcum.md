# Load measurement note (ALIG-TEST-001)

This note records one local measurement of the scan/report server. It reports what was measured. **It sets no capacity target and
no SLA**, and nothing here should be read as one: the numbers come from one run, on one small machine, with the client and the
server on the same host, with no reverse proxy and no network between them.

## How to repeat it

```
python3 deploy/yuk_testi.py [--yukleme 200] [--goruntuleme 1000] [--esanlilik 16] [--cikti olcum.txt]
```

- It starts `tarama/server.py` (the real handler) as a child process on a free loopback port, against a temporary SQLite database
  that is deleted afterwards. Every optional `ALIG_*` switch is removed from the child's environment, so the optional gates stay at
  their defaults (off).
- It refuses any target that is not loopback (`127.0.0.0/8`, `::1`, `localhost`): at start (exit code 2) and again before every
  connection. A name that only contains `localhost` or `127.0.0.1` is not accepted.
- Scenarios: (1) concurrent upload, one company per upload so the per-company allowance is not hit and the per-address limit is
  raised above the upload count; (2) concurrent viewing of the reports created in (1), each view also writes one audit row;
  (3) the 429 behaviour of the two rate limits with the server's real defaults, with sequential requests.
- Latency is measured by the client from sending the request to reading the whole response. Percentiles use the nearest-rank
  method over the requests that got a response; requests that failed (timeout, reset) are counted separately as errors.
- Logic tests: `tests/test_yuk_testi.py` (loopback refusal, percentile and summary maths, upload body, report text, and a small real
  end-to-end run). They assert counts and statuses only, never a timing value.

## Environment of the recorded run

- Date: 2026-11-17
- CPU count: 2 (`os.cpu_count()`)
- Python: 3.13.18
- System: Linux 6.18.44-fc-v553
- Server: `tarama/server.py` (`ThreadingHTTPServer` + SQLite, no reverse proxy, loopback), same host as the client
- Parameters: 200 uploads, 1000 report views, concurrency 16 (defaults of the script)

## Measurements

Latency in milliseconds.

| Scenario | Requests | Status counts | Errors | min | p50 | p90 | p95 | p99 | max | Requests/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| upload (POST /api/tarama/yukle) | 200 | 303: 200 | none | 4.0 | 11.6 | 116.6 | 363.5 | 1095.9 | 1144.9 | 172.5 |
| report view (GET /rapor/<token>/) | 1000 | 200: 1000 | none | 3.4 | 7.9 | 62.3 | 135.2 | 739.1 | 1342.2 | 396.2 |

429 behaviour (real defaults; sequential requests from one address):

| Limit | Configured in code | Requests | Status counts | First 429 at request | Retry-After seen |
| --- | --- | --- | --- | --- | --- |
| per address (`RateLimiter`, uploads) | 5 per 3600 s | 8 (a different company each) | 303: 5, 429: 3 | 6 | 3600 |
| per company (`depo.SINIR_ADET`) | 2 free scans per 30 days | 4 (same company, a different file each) | 303: 2, 429: 2 | 3 | 2592000 (30 days) |

## Reading the numbers

- Both limits behave as configured: the first request over the limit gets 429 with a `Retry-After` header, and the requests before
  it are accepted. Under the raised address limit no 429 appeared in the concurrent runs and no request failed.
- The upper percentiles (p95 and above) are much larger than the median in both scenarios. Under this load the tail is where the
  runs differ most; a single run does not show how stable it is. Repeat the run before comparing it with anything.
- The client load generator (16 Python threads) and the server share two CPUs, so part of the tail may come from the client side.
  The measurement cannot separate the two.

## Not measured

- A real nginx in front, TLS, a real network, or a production-sized host.
- PostgreSQL (the runtime is still SQLite; the migration items are separate).
- The portal, the admin panel, Mode B, e-mail verification (all off by default), and larger or hostile upload bodies.
- Repeatability across runs and over a long duration (soak), memory use, and disk growth.
- Any capacity target, SLA or required request rate: none has been defined, and none is derived from these numbers.
