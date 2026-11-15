# SQL Server health scan (preview)

Status: the code and tests are ready, **not tested on a real SQL Server**. For this reason it is not published on the public page, and the server accepts these files only if explicitly enabled.

## What exists

| Part | Location |
| --- | --- |
| Query catalog (14 checks, `SELECT` only) | `MSSQL` in `tarama/katalog.py` |
| Collector script (uses `sqlcmd`) | `tarama/onsurum/alig-toplayici-mssql.py` (template: `tarama/toplayici/sablon_mssql.py`) |
| List of the queries that run | `tarama/onsurum/sorgu-katalogu-mssql.txt` |
| Creating and removing the scan login | `tarama/onsurum/alig-giris-mssql.sql`, `alig-giris-mssql-kaldir.sql` |
| Rules and finding texts (TR, EN) | `tarama/kurallar_mssql.py` |
| Tests (with a fake `sqlcmd`) | `tests/test_mssql.py` |

## Requirements

- SQL Server 2016 or later (`FOR JSON` is required).
- The `sqlcmd` client and Python 3.9 or later.
- An `alig_hc` login with only `VIEW SERVER STATE` and `VIEW ANY DEFINITION` privileges. No user is created in any database.

## Steps for testing on a real server

1. Create the login (the password is read from an environment variable, not written on the command line):
   `export ALIG_PAROLA='...' ; sqlcmd -S <server> -E -i tarama/onsurum/alig-giris-mssql.sql`
2. Run the script:
   `SQLCMDPASSWORD='...' python3 tarama/onsurum/alig-toplayici-mssql.py --sunucu <server>,1433 --kullanici alig_hc --sifrele --maskele`
3. In the list on the screen, check that each check is `ok` or `ATLANDI (reason)` (skipped). Every check showing `ATLANDI (desteklenmiyor)` (unsupported) or `ATLANDI (hata)` (error) is a candidate for a fix.
4. Open the `alig-toplama-mssql.json` file and check that the values match the real state on the server.
5. Run `python3 yerel.py` locally and upload the file from the scan page (SQL Server is enabled locally) and read the report.
6. Remove the login: `sqlcmd -S <server> -E -i tarama/onsurum/alig-giris-mssql-kaldir.sql`

## Uncertainties that must be tested

- `sqlcmd` output: the script uses `-y 0` and counts what is between the first `[` and the last `]` in the output as JSON. The ODBC-based `sqlcmd` and the new `go-sqlcmd` may not behave the same.
- Reading `msdb.dbo.backupset`: the login reads in `msdb` only through `guest`. On hardened servers it may give a `yetki` (privilege) error.
- If backups are taken on another replica, `ms_yedek` produces a false alarm.
- In builds without the `LastGoodCheckDbTime` property, `ms_checkdb` returns empty and produces no finding.
- `ms_sifreleme` looks only at the TCP connections at the moment of the scan.
- For Azure SQL Database and Managed Instance the version rule is skipped; the other checks were not tried in these environments.

## Turning it on in production

When testing is complete: the `ALIG_MSSQL=1` environment variable on the scan service, then moving the script and the login files under `site/assets`, and adding the SQL Server steps to the scan and preparation pages. These were deliberately not done.
