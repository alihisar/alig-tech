#!/usr/bin/env python3
"""Siteyi yerelde derler ve calistirir (Python 3.9+, ek paket gerekmez).

  python3 yerel.py            # http://localhost:8080/
  python3 yerel.py --port 9000

Iletisim formu da calisir: kayitlar yerel-form.sqlite dosyasina yazilir.
"""
import argparse
import functools
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
from tarama import depo  # noqa: E402
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
        raise SystemExit("derleme basarisiz")
    db = str(ROOT / "yerel-form.sqlite")
    form.connect(db).close()
    FormH = form.make_handler(db, form.RateLimiter(per_window=100), "yerel")

    tarama.H.db_yolu = str(ROOT / "yerel-tarama.sqlite")
    tarama.H.sinir = form.RateLimiter(per_window=100)
    depo.baglan(tarama.H.db_yolu).close()

    # Yonetim paneli ayri bir sunucu (canlidaki gibi); /yonetim/ istekleri ona aktarilir
    yonetim.H.ydb = str(ROOT / "yerel-yonetim.sqlite")
    yonetim.H.form_db, yonetim.H.tarama_db = db, tarama.H.db_yolu
    yonetim.H.form_portu = yonetim.H.tarama_portu = args.port
    yonetim.H.guvenli_cerez = False  # yerelde HTTP
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
            if self.path.startswith("/rapor/") or self.path == "/api/tarama/saglik":
                return tarama.H.do_GET(self)
            return SimpleHTTPRequestHandler.do_GET(self)

        def do_POST(self):
            if self.path.startswith("/yonetim"):
                return aktar(self)
            if self.path.startswith("/api/tarama/") or self.path.startswith("/rapor/"):
                return tarama.H.do_POST(self)
            return FormH.do_POST(self)

    handler = functools.partial(Local, directory=str(out))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://localhost:{args.port}/"
    print(f"Site hazir: {url}  (durdurmak icin Ctrl+C)", flush=True)
    print(f"Yonetim paneli: {url}yonetim/  Ilk kullanici: python3 yonetim/kullanici.py --db yerel-yonetim.sqlite ekle ali", flush=True)
    print("  Dogrulama uygulamasi olmadan yerelde denemek icin anlik kod: python3 yonetim/kullanici.py --db yerel-yonetim.sqlite kod ali", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nkapatildi")


if __name__ == "__main__":
    main()
