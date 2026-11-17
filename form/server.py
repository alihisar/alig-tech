#!/usr/bin/env python3
"""alig.tech contact form endpoint. Standard library only.

POST /api/iletisim  (application/x-www-form-urlencoded)
GET  /healthz
When ALIG_BAKIM=1 (maintenance mode) the POST is answered with 503 + Retry-After; /healthz stays live.
Records go into SQLite (WAL), timestamps in UTC. If the honeypot field (website) is filled,
the record is discarded but 303 is returned (so the bot does not notice). Rate limit per IP, in memory.
"""
import argparse
import hashlib
import importlib.util
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

_spec = importlib.util.spec_from_file_location("alig_bakim", Path(__file__).resolve().parent.parent / "tarama" / "bakim.py")
_bakim = importlib.util.module_from_spec(_spec)   # maintenance mode (ALIG-OPS-002) is shared with the other services
_spec.loader.exec_module(_bakim)

try:   # PostgreSQL mode (ALIG-DB-003e): ortak/ is one level above this directory; with no PostgreSQL layer the tuple stays empty
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ortak.pg import PgHata as _PgHata
    _PG_HATA = (_PgHata,)
except ImportError:
    _PG_HATA = ()

MAX_BODY = 8192
SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Content-Security-Policy", "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
)
DB_CHOICES = {"pg", "ms", "my", "multi", "unsure"}
LIMITS = {"name": 120, "company": 160, "email": 200, "message": 2000}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCHEMA = """CREATE TABLE IF NOT EXISTS contact(
  id INTEGER PRIMARY KEY, created_utc TEXT NOT NULL, name TEXT NOT NULL, company TEXT NOT NULL,
  email TEXT NOT NULL, db TEXT NOT NULL, message TEXT NOT NULL, ip_hash TEXT NOT NULL)"""


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(SCHEMA)
    return con


def validate(form):
    """(clean_data, errors). Every field has a single value; control characters are dropped."""
    def one(k):
        v = (form.get(k) or [""])[0]
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v).strip()
    data = {k: one(k) for k in ("name", "company", "email", "db", "message")}
    errors = []
    for k in ("name", "company", "email"):
        if not data[k]:
            errors.append(k)
    for k, n in LIMITS.items():
        if len(data[k]) > n and k not in errors:
            errors.append(k)
    if data["email"] and not EMAIL_RE.match(data["email"]) and "email" not in errors:
        errors.append("email")
    if data["db"] not in DB_CHOICES:
        errors.append("db")
    return data, errors


class RateLimiter:
    """Sliding window per IP. Thread safe; expired keys are dropped once per window
    (otherwise every new address, IPv6 in particular, would stay in memory forever)."""

    def __init__(self, per_window=5, window=3600, clock=time.monotonic):
        self.n, self.w, self.clock, self.hits = per_window, window, clock, {}
        self._kilit = threading.Lock()
        self._temizlik = clock()

    def allow(self, key):
        with self._kilit:
            now = self.clock()
            if now - self._temizlik >= self.w:
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.w}
                self._temizlik = now
            recent = [t for t in self.hits.get(key, []) if now - t < self.w]
            if len(recent) >= self.n:
                self.hits[key] = recent
                return False
            recent.append(now)
            self.hits[key] = recent
            return True


def make_handler(db_path, limiter, salt, thanks="/tesekkurler/", bakim=False, bakim_bekle=_bakim.BEKLE_VARSAYILAN, pg=None):
    """pg: an form.iletisim_pg.IletisimPg when PostgreSQL is configured (then db_path and SQLite are not used and there is no fallback);
    limiter is then a form.iletisim_pg.FormSinir. A PostgreSQL failure is 503 + Retry-After."""
    class H(BaseHTTPRequestHandler):
        server_version = "aligform"
        sys_version = ""

        def log_message(self, fmt, *args):  # do not log personal data: only path and status
            print(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}", flush=True)

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # Security headers (ALIG-SEC-002); this process is standalone, so the values are repeated from tarama/basliklar.py.
            # Responses are plain text or redirects, never HTML: nothing may load or embed.
            for k, v in SECURITY_HEADERS:
                self.send_header(k, v)
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _thanks(self):  # if the Referer is /en/, the English thank-you page
            ref = self.headers.get("Referer") or ""
            return "/en" + thanks if re.match(r"^https?://[^/]+/en(/|$)", ref) else thanks

        def do_GET(self):
            if self.path == "/healthz":
                if pg is not None:
                    return self._send(200, b"ok\n") if pg.saglik() else self._send(503, b"db\n", extra=(("Retry-After", "30"),))
                try:
                    connect(db_path).close()
                    return self._send(200, b"ok\n")
                except sqlite3.Error:
                    return self._send(503, b"db\n")
            self._send(404, b"yok\n")

        def do_POST(self):
            if _bakim.engelle(self):   # maintenance mode (ALIG_BAKIM): the write is refused before anything is read
                return
            if self.path != "/api/iletisim":
                return self._send(404, b"yok\n")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/x-www-form-urlencoded":
                return self._send(415, b"icerik turu\n")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._send(411, b"uzunluk\n")
            if length < 0 or length > MAX_BODY:
                return self._send(413, b"cok buyuk\n")
            ip = self.headers.get("X-Real-IP") or self.client_address[0]
            try:
                izin = limiter.allow(ip)
            except _PG_HATA:
                return self._send(503, b"db\n", extra=(("Retry-After", "30"),))
            if not izin:
                tekrar = limiter.tekrar_sn() if pg is not None else 3600
                return self._send(429, b"cok fazla istek\n", extra=(("Retry-After", str(tekrar)),))
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
            if (form.get("website") or [""])[0].strip():
                return self._send(303, extra=(("Location", self._thanks()),))
            data, errors = validate(form)
            if errors:
                return self._send(422, ("gecersiz alan: " + ",".join(errors) + "\n").encode())
            ip_hash = hashlib.sha256((salt + ip).encode()).hexdigest()[:16]
            if pg is not None:
                try:
                    pg.kaydet(data, ip_hash)
                except _PG_HATA:
                    return self._send(503, b"db\n", extra=(("Retry-After", "30"),))
                return self._send(303, extra=(("Location", self._thanks()),))
            con = connect(db_path)
            try:
                con.execute("INSERT INTO contact(created_utc,name,company,email,db,message,ip_hash) VALUES(?,?,?,?,?,?,?)",
                            (utcnow(), data["name"], data["company"], data["email"], data["db"], data["message"], ip_hash))
                con.commit()
            finally:
                con.close()
            self._send(303, extra=(("Location", self._thanks()),))
    H.bakim, H.bakim_bekle = bakim, bakim_bekle
    return H


def _pg_ayar(ortam):
    """Connection kwargs for ortak.pg.Baglanti.baglan from ortak/pg_ayar.py (ALIG-DB-003c), or None when PostgreSQL is not configured
    (or that module does not exist yet: then the SQLite runtime is the only store)."""
    try:
        from ortak import pg_ayar
    except ImportError:
        return None
    return pg_ayar.yukle(ortam)


def _pg_modul():
    spec = importlib.util.spec_from_file_location("alig_iletisim_pg", Path(__file__).resolve().parent / "iletisim_pg.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("ALIG_FORM_DB", "form.sqlite"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--salt", default=os.environ.get("ALIG_FORM_SALT", ""))
    args = ap.parse_args(argv)
    try:
        bakim_acik, bakim_sn = _bakim.etkin(os.environ), _bakim.bekle_sn(os.environ)
    except ValueError as ex:
        raise SystemExit("error: %s" % ex)
    if not args.salt:
        raise SystemExit("ALIG_FORM_SALT (or --salt) is required: the salt for the IP digest")
    pg_ayar = _pg_ayar(os.environ)
    if pg_ayar is None:
        connect(args.db).close()
        isleyici = make_handler(args.db, RateLimiter(), args.salt, bakim=bakim_acik, bakim_bekle=bakim_sn)
    else:   # PostgreSQL is configured: NEVER fall back to SQLite; an unusable database stops the start (docs/postgresql-gecis.md section 9)
        from ortak import pg as _pgmod, sinir_pg
        iletisim_pg = _pg_modul()
        baglan = lambda: _pgmod.Baglanti.baglan(**pg_ayar)   # noqa: E731
        depo_pg = iletisim_pg.IletisimPg(baglan)
        if not depo_pg.saglik():
            raise SystemExit("error: PostgreSQL is configured but not reachable; refusing to fall back to SQLite")
        isleyici = make_handler(None, iletisim_pg.FormSinir(sinir_pg.SinirPg(baglan, tuz=args.salt)), args.salt,
                                bakim=bakim_acik, bakim_bekle=bakim_sn, pg=depo_pg)
    srv = ThreadingHTTPServer((args.host, args.port), isleyici)
    print(f"listening on {args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
