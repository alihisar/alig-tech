#!/usr/bin/env python3
"""Builds and runs the site locally (Python 3.9+, no extra packages needed).

  python3 yerel.py            # http://localhost:8080/
  python3 yerel.py --port 9000

The contact form works too: records are written to the yerel-form.sqlite file.
"""
import argparse
import functools
import os
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "form"))
import build as site_build  # noqa: E402
import server as form  # noqa: E402
from tarama import server as tarama  # noqa: E402
from tarama import depo, puan  # noqa: E402
from yonetim import depo as ydepo  # noqa: E402
from yonetim import server as yonetim  # noqa: E402
import http.client  # noqa: E402
import threading  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--theme", default="c", choices=site_build.THEMES)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    out = ROOT / "dist" / "yerel"
    if site_build.main(["--theme", args.theme, "--out", str(out), "--base-url", f"http://localhost:{args.port}", "--noindex"]) != 0:
        raise SystemExit("build failed")
    db = str(ROOT / "yerel-form.sqlite")
    form.connect(db).close()
    FormH = form.make_handler(db, form.RateLimiter(per_window=100), "yerel")

    tarama.H.db_yolu = str(ROOT / "yerel-tarama.sqlite")
    tarama.H.sinir = form.RateLimiter(per_window=100)
    tarama.H.motorlar = ("postgresql", "mssql")  # locally the SQL Server preview is enabled
    tarama.H.dogrudan = True  # locally the Mode B form is enabled; target validation is real, local and internal addresses are rejected
    depo.baglan(tarama.H.db_yolu).close()
    try:
        puan.yukle()   # if ALIG_PUAN_AYARI is given, those coefficients are used locally too
    except puan.PuanAyarHatasi as ex:
        raise SystemExit("error: %s" % ex)
    if os.environ.get("ALIG_EPOSTA_DOGRULAMA") == "1":
        # Local email verification: messages wait in the outbox; to read them
        #   ALIG_POSTA_DIZINI=yerel-posta python3 tarama/posta.py --db yerel-tarama.sqlite
        tarama.eposta_ayarla({"ALIG_EPOSTA_DOGRULAMA": "1", "ALIG_SITE_ADRESI": f"http://localhost:{args.port}"}, tarama.H)
        if os.environ.get("ALIG_PORTAL") == "1":   # customer portal: only together with email verification
            tarama.portal_ayarla(os.environ, tarama.H)

    # The admin panel is a separate server (as in production); /yonetim/ requests are forwarded to it
    yonetim.H.ydb = str(ROOT / "yerel-yonetim.sqlite")
    yonetim.H.form_db, yonetim.H.tarama_db = db, tarama.H.db_yolu
    yonetim.H.form_portu = yonetim.H.tarama_portu = args.port
    yonetim.H.guvenli_cerez = False  # HTTP locally
    ydepo.baglan(yonetim.H.ydb).close()
    ysrv = ThreadingHTTPServer(("127.0.0.1", 0), yonetim.H)
    threading.Thread(target=ysrv.serve_forever, daemon=True).start()

    def aktar(h):
        n = int(h.headers.get("Content-Length") or 0)
        govde = h.rfile.read(n) if n else None
        c = http.client.HTTPConnection("127.0.0.1", ysrv.server_port, timeout=15)
        basliklar = {k: v for k, v in h.headers.items() if k.lower() in ("cookie", "content-type", "origin", "host")}
        basliklar["X-Real-IP"] = h.client_address[0]
        c.request(h.command, h.path, body=govde, headers=basliklar)
        r = c.getresponse()
        veri = r.read()
        h.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() in ("content-type", "set-cookie", "location", "cache-control"):
                h.send_header(k, v)
        h.send_header("Content-Length", str(len(veri)))
        h.end_headers()
        h.wfile.write(veri)

    class Local(SimpleHTTPRequestHandler, tarama.H, FormH):
        def log_message(self, fmt, *a):
            tarama.H.log_message(self, fmt, *a)

        def do_GET(self):
            if self.path.startswith("/yonetim"):
                return aktar(self)
            if self.path == "/healthz":
                return FormH.do_GET(self)
            if self.path.startswith("/rapor/") or self.path.startswith("/portal") or self.path == "/api/tarama/saglik" or self.path.startswith("/api/tarama/baglan"):
                return tarama.H.do_GET(self)
            return SimpleHTTPRequestHandler.do_GET(self)

        def do_POST(self):
            if self.path.startswith("/yonetim"):
                return aktar(self)
            if self.path.startswith("/api/tarama/") or self.path.startswith("/rapor/") or self.path.startswith("/portal/"):
                return tarama.H.do_POST(self)
            return FormH.do_POST(self)

    handler = functools.partial(Local, directory=str(out))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://localhost:{args.port}/"
    print(f"Site ready: {url}  (Ctrl+C to stop)", flush=True)
    print(f"Admin panel: {url}yonetim/  First user: python3 yonetim/kullanici.py --db yerel-yonetim.sqlite ekle ali", flush=True)
    print("  To try locally without an authenticator app, instant code: python3 yonetim/kullanici.py --db yerel-yonetim.sqlite kod ali", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
