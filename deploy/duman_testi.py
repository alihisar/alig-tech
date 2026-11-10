#!/usr/bin/env python3
"""Yayin sonrasi duman testi. Yalnizca stdlib. 0 = tamam, 1 = basarisiz.

  python3 deploy/duman_testi.py http://127.0.0.1 [--host alig.tech] [--surum 1.0.0]
Ana adres yerine nginx'e 127.0.0.1 uzerinden, Host basligiyla baglanmak icin --host kullanin.
"""
import argparse
import http.client
import sys
from urllib.parse import urlparse

KONTROLLER = [
    ("/", 200, "<title>"), ("/en/", 200, "<title>"), ("/demo/", 200, "portal"), ("/saglik-taramasi/", 200, "alig-toplayici"),
    ("/kvkk/", 200, "<h1>"), ("/assets/alig-toplayici.py", 200, "KATALOG"), ("/healthz", 200, "ok"),
    ("/api/tarama/saglik", 200, "ok"), ("/yok-boyle-bir-sayfa/", 404, ""),
]
BASLIKLAR = ["content-security-policy", "x-content-type-options", "referrer-policy", "x-frame-options"]


def al(u, host, yol, ctx=None):
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    c = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=10)
    c.request("GET", yol, headers={"Host": host or u.hostname})
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")


def calistir(taban, host=None, surum=None):
    u = urlparse(taban)
    hatalar = []
    for yol, kod, icerik in KONTROLLER:
        try:
            durum, baslik, govde = al(u, host, yol)
        except OSError as e:
            hatalar.append(f"{yol}: baglanti hatasi {e}")
            continue
        if durum != kod:
            hatalar.append(f"{yol}: {durum} (beklenen {kod})")
        elif icerik and icerik not in govde:
            hatalar.append(f"{yol}: icerikte '{icerik}' yok")
        if yol == "/" and durum == 200:
            for b in BASLIKLAR:
                if b not in baslik:
                    hatalar.append(f"/: {b} basligi yok")
    if surum:
        try:
            durum, _, govde = al(u, host, "/surum.txt")
            if durum != 200 or govde.strip() != surum:
                hatalar.append(f"/surum.txt: {govde.strip()[:20]!r} (beklenen {surum})")
        except OSError as e:
            hatalar.append(f"/surum.txt: {e}")
    return hatalar


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("taban")
    ap.add_argument("--host")
    ap.add_argument("--surum")
    a = ap.parse_args(argv)
    hatalar = calistir(a.taban, a.host, a.surum)
    for h in hatalar:
        print("HATA", h)
    print("duman testi: " + ("BASARISIZ" if hatalar else "tamam"))
    return 1 if hatalar else 0


if __name__ == "__main__":
    sys.exit(main())
