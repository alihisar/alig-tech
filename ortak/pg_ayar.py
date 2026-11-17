"""PostgreSQL connection settings, parsed in ONE place (ALIG-DB-003c). Standard library only.

    yukle(ortam) -> dict | None

* None: PostgreSQL is NOT configured (no ALIG_DB_* variable at all). The caller keeps the SQLite runtime.
* dict: keyword arguments for ortak.pg.Baglanti.baglan (host, port, dbname, user, password, sslmode, sslrootcert).
* PgAyarHatasi: some ALIG_DB_* variable is set but the configuration is incomplete or unsafe. When PostgreSQL IS configured the
  application never falls back to SQLite silently (docs/postgresql-gecis.md section 9): the caller must stop at startup with this error.

Variables:
  ALIG_DB_HOST            required. A directory starting with "/" is a Unix socket directory, otherwise a TCP host name.
  ALIG_DB_PORT            default 5432
  ALIG_DB_NAME            default aligtech
  ALIG_DB_USER            default alig_app (the application role: DML only, never a superuser)
  ALIG_DB_PAROLA_DOSYASI  path of a file that holds the password (never the password itself in the environment). Optional for a
                          Unix socket with peer/trust authentication; REQUIRED for TCP.
  ALIG_DB_SSLMODE         TCP: only verify-full is accepted (default verify-full). Unix socket: not used.
  ALIG_DB_SSLROOTCERT     TCP: path of the CA certificate file; required. Unix socket: not used.

The password is read from the file here and appears in no error text. Superuser roles are not detected here (the server decides);
the user name "postgres" is rejected as a cheap guard.
"""
import os
import stat

__all__ = ["PgAyarHatasi", "yukle", "ONEK"]

ONEK = "ALIG_DB_"
BILINEN = ("HOST", "PORT", "NAME", "USER", "PAROLA_DOSYASI", "SSLMODE", "SSLROOTCERT")
VARSAYILAN_PORT = "5432"
VARSAYILAN_DB = "aligtech"
VARSAYILAN_KULLANICI = "alig_app"
PAROLA_EN_COK_BAYT = 1024


class PgAyarHatasi(ValueError):
    """Invalid or incomplete PostgreSQL configuration. The message never contains the password."""


def _al(ortam, ad):
    v = ortam.get(ONEK + ad)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _dosya_oku(yol, ad):
    try:
        d = os.stat(yol)
    except OSError:
        raise PgAyarHatasi("%s%s: file not found or not readable: %s" % (ONEK, ad, yol)) from None
    if not stat.S_ISREG(d.st_mode):
        raise PgAyarHatasi("%s%s: not a regular file: %s" % (ONEK, ad, yol))
    return d


def yukle(ortam=None):
    """See the module docstring. ortam: a mapping (default os.environ)."""
    ortam = os.environ if ortam is None else ortam
    # ANY ALIG_DB_* variable means "PostgreSQL is configured": a misspelled ALIG_DB_HOTS then fails loudly (HOST missing)
    # instead of silently turning into "not configured" and a SQLite fallback.
    verilen = [k for k in ortam if k.startswith(ONEK) and str(ortam[k]).strip()]
    if not verilen:
        return None
    host = _al(ortam, "HOST")
    if host is None:
        raise PgAyarHatasi("%sHOST is required when any %s* setting is present (no fallback to SQLite); found: %s"
                           % (ONEK, ONEK, ", ".join(sorted(verilen))))
    if any(c in host for c in "\x00\n\r'\\ ") or "," in host:
        raise PgAyarHatasi("%sHOST: invalid characters" % ONEK)
    port = _al(ortam, "PORT") or VARSAYILAN_PORT
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise PgAyarHatasi("%sPORT: not a valid port number" % ONEK)
    dbname = _al(ortam, "NAME") or VARSAYILAN_DB
    kullanici = _al(ortam, "USER") or VARSAYILAN_KULLANICI
    if kullanici.lower() == "postgres":
        raise PgAyarHatasi("%sUSER: the application must not connect as the postgres superuser; use the alig_app role" % ONEK)
    for ad, deger in (("NAME", dbname), ("USER", kullanici)):
        if "\x00" in deger:
            raise PgAyarHatasi("%s%s: invalid characters" % (ONEK, ad))

    soket = host.startswith("/")
    parola = None
    pdosya = _al(ortam, "PAROLA_DOSYASI")
    if pdosya is not None:
        d = _dosya_oku(pdosya, "PAROLA_DOSYASI")
        if os.name == "posix" and d.st_mode & 0o077:
            raise PgAyarHatasi("%sPAROLA_DOSYASI: the password file must not be readable by group or others (chmod 600): %s" % (ONEK, pdosya))
        if d.st_size > PAROLA_EN_COK_BAYT:
            raise PgAyarHatasi("%sPAROLA_DOSYASI: file too large" % ONEK)
        with open(pdosya, "rb") as f:
            ham = f.read(PAROLA_EN_COK_BAYT + 1)
        try:
            parola = ham.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            raise PgAyarHatasi("%sPAROLA_DOSYASI: not UTF-8 text" % ONEK) from None
        if not parola:
            raise PgAyarHatasi("%sPAROLA_DOSYASI: the file is empty" % ONEK)

    ayar = {"host": host, "port": int(port), "dbname": dbname, "user": kullanici, "password": parola}
    if soket:
        # a local socket carries no network traffic; TLS settings do not apply
        if _al(ortam, "SSLMODE") or _al(ortam, "SSLROOTCERT"):
            raise PgAyarHatasi("%sSSLMODE/%sSSLROOTCERT are for TCP connections; the host is a Unix socket directory" % (ONEK, ONEK))
        return ayar
    if parola is None:
        raise PgAyarHatasi("%sPAROLA_DOSYASI is required for a TCP connection" % ONEK)
    sslmode = _al(ortam, "SSLMODE") or "verify-full"
    if sslmode != "verify-full":
        raise PgAyarHatasi("%sSSLMODE: only verify-full is accepted over TCP (got %r)" % (ONEK, sslmode))
    kok = _al(ortam, "SSLROOTCERT")
    if kok is None:
        raise PgAyarHatasi("%sSSLROOTCERT is required over TCP (CA certificate file)" % ONEK)
    _dosya_oku(kok, "SSLROOTCERT")
    ayar["sslmode"] = sslmode
    ayar["sslrootcert"] = kok
    return ayar
