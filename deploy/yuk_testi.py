#!/usr/bin/env python3
"""Local load measurement of the scan/report server (ALIG-TEST-001). Standard library only.

  python3 deploy/yuk_testi.py [--yukleme 200] [--goruntuleme 1000] [--esanlilik 16] [--cikti olcum.txt]

What it does: starts the scan server (`tarama/server.py`) as a child process on a free loopback port against a temporary SQLite
database (deleted afterwards), then measures
  1. concurrent upload      (POST /api/tarama/yukle, one company per upload, so the per-company allowance is not hit),
  2. concurrent report view (GET /rapor/<token>/ on the reports created in step 1),
  3. the 429 behaviour of the two rate limits with the server's real defaults:
     the per-address limit (`RateLimiter`) and the per-company free-scan allowance (`depo.SINIR_ADET`).
It prints measurements only: counts per status, errors, latency percentiles, requests per second. It states no capacity target
and no SLA; the numbers describe one run on one machine (the environment is printed with them).

Safety: it refuses any target that is not a loopback address (127.0.0.0/8, ::1, localhost). The check runs at start and again
before every connection. The servers it starts bind to the loopback address only. It never touches a real database or site.
"""
import argparse
import http.client
import ipaddress
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Reddedildi(Exception):
    """The target is not a loopback address."""


def loopback_mi(host):
    """True only for 'localhost' or a literal loopback IP address. A name that merely contains 'localhost' or '127.0.0.1' is not accepted."""
    if not isinstance(host, str):
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def loopback_zorunlu(host):
    if not loopback_mi(host):
        raise Reddedildi("refused: %r is not a loopback address; this script only runs against 127.0.0.0/8, ::1 or localhost" % (host,))


# ---- measurement helpers ----

def yuzdelik(degerler, p):
    """Nearest-rank percentile of a list of numbers; None for an empty list."""
    if not degerler:
        return None
    s = sorted(degerler)
    return s[max(0, math.ceil(p / 100.0 * len(s)) - 1)]


def ozet(olcumler, toplam_sn):
    """olcumler: [(seconds, status or None, error name or None)]. Latency is computed over the requests that got a response."""
    durumlar, hatalar, sureler = {}, {}, []
    for sure, durum, hata in olcumler:
        if hata:
            hatalar[hata] = hatalar.get(hata, 0) + 1
        else:
            durumlar[str(durum)] = durumlar.get(str(durum), 0) + 1
            sureler.append(sure)
    gecikme = None
    if sureler:
        gecikme = {"min": min(sureler) * 1000.0, "p50": yuzdelik(sureler, 50) * 1000.0, "p90": yuzdelik(sureler, 90) * 1000.0,
                   "p95": yuzdelik(sureler, 95) * 1000.0, "p99": yuzdelik(sureler, 99) * 1000.0, "max": max(sureler) * 1000.0}
    return {"istek": len(olcumler), "durumlar": durumlar, "hatalar": hatalar, "gecikme_ms": gecikme,
            "toplam_sn": toplam_sn, "saniyede_istek": (len(olcumler) / toplam_sn) if toplam_sn > 0 else None}


def esanli(is_, adet, esanlilik):
    """Runs is_(i) for i in range(adet) with at most `esanlilik` threads; keeps the order. An exception becomes an error record."""
    def sar(i):
        try:
            return is_(i)
        except Reddedildi:
            raise
        except Exception as e:   # a failed request is a measurement, not a crash
            return (0.0, None, type(e).__name__)
    with ThreadPoolExecutor(max_workers=max(1, esanlilik)) as havuz:
        return list(havuz.map(sar, range(adet)))


def istek(host, port, yontem, yol, govde=None, basliklar=None, zaman_asimi=30):
    """One HTTP request. The loopback rule is checked here as well, before anything is connected."""
    loopback_zorunlu(host)
    c = http.client.HTTPConnection(host, port, timeout=zaman_asimi)
    try:
        c.request(yontem, yol, body=govde, headers=basliklar or {})
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        c.close()


def olculu(host, port, yontem, yol, govde=None, basliklar=None):
    t = time.perf_counter()
    durum, bas, ic = istek(host, port, yontem, yol, govde, basliklar)
    return time.perf_counter() - t, durum, bas, ic


# ---- test data ----

def ornek_belge(n=0):
    """A valid collection document (the shape tests/test_tarama.py uses). n changes the timestamp, so the digest changes."""
    from tarama import katalog, uret_toplayici
    k = {c["id"]: {"durum": "ok", "satirlar": []} for c in katalog.PG}
    k["pg_surum"]["satirlar"] = [{"surum_num": 160015}]
    k["pg_sunucu_rolu"]["satirlar"] = [{"yedek": False}]
    k["pg_hesap"]["satirlar"] = [{"super_kullanici": False, "pg_read_all_stats": True, "pg_read_all_settings": True}]
    k["pg_baglanti"]["satirlar"] = [{"kullanilan": 10, "ust": 100}]
    k["pg_tls_parola"]["satirlar"] = [{"ssl": "on", "password_encryption": "scram-sha-256", "ssl_min_protocol_version": "TLSv1.2"}]
    k["pg_kapsam"]["satirlar"] = [{"veritabani": "postgres", "veritabani_sayisi": 1}]
    k["pg_md5_roller"]["satirlar"] = [{"sayi": 0}]
    k["pg_xid_yasi"]["satirlar"] = [{"datname": "postgres", "yas": 1000, "mxid_yas": 1, "freeze_max_age": 200000000, "mxid_freeze_max_age": 400000000}]
    k["pg_autovacuum"]["satirlar"] = [{"name": "autovacuum", "setting": "on"}, {"name": "track_counts", "setting": "on"}]
    k["pg_olu_satir"]["satirlar"] = [{"veritabani": "postgres", "schemaname": "public", "relname": "t%d" % i, "canli": 1000 + i, "olu": 300 + i,
                                       "son_autovacuum": None} for i in range(20)]
    return {"format": katalog.FORMAT, "motor": katalog.MOTOR, "katalog_sha256": uret_toplayici.katalog_ozeti(),
            "olusturma_utc": "2026-11-10T12:%02d:%02dZ" % ((n // 60) % 60, n % 60), "maskeli": False, "superuser": False, "kontroller": k}


def eposta(n):
    """A different company key for every n (the key of a corporate address is its domain). The .test domain never resolves."""
    return "yuk%d@sirket%d.yuk.test" % (n, n)


def yukleme_govdesi(veri, eposta_, sirket, dil="en"):
    sinir = "----yuk" + uuid.uuid4().hex
    parcalar = [("sirket", sirket), ("eposta", eposta_), ("yetki", "on"), ("dil", dil)]
    govde = "".join('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (sinir, a, d) for a, d in parcalar).encode()
    govde += ('--%s\r\nContent-Disposition: form-data; name="dosya"; filename="toplama.json"\r\nContent-Type: application/json\r\n\r\n' % sinir).encode()
    govde += veri + ("\r\n--%s--\r\n" % sinir).encode()
    return govde, "multipart/form-data; boundary=" + sinir


# ---- the server under test ----

_SUNUCU_MODU = "--sunucu-modu"


def _sunucu_modu(argv):
    """Child process: the real scan server handler with the database and (optionally) the per-address limit changed. Prints the port."""
    from http.server import ThreadingHTTPServer
    from tarama import depo, server
    host, db, sinir = argv[0], argv[1], argv[2]
    depo.baglan(db).close()
    server.H.db_yolu = db
    if sinir != "-":
        server.H.sinir = server.RateLimiter(per_window=int(sinir))
    cls = ThreadingHTTPServer
    if ":" in host:
        import socket

        class cls(ThreadingHTTPServer):   # noqa: N801
            address_family = socket.AF_INET6
    srv = cls((host, 0), server.H)
    print("port %d" % srv.server_address[1], flush=True)
    srv.serve_forever()


@contextmanager
def sunucu(host, sinir=None):
    """Starts the scan server on a free loopback port with a temporary database. sinir: per-address requests per window, None = the server default."""
    loopback_zorunlu(host)
    gecici = tempfile.mkdtemp(prefix="yuk-testi-")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALIG_")}   # every optional switch stays at its default (off)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), _SUNUCU_MODU, host, os.path.join(gecici, "yuk.sqlite"),
                          "-" if sinir is None else str(sinir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(ROOT), text=True)
    try:
        satir = p.stdout.readline()
        if not satir.startswith("port "):
            p.kill()
            raise RuntimeError("the server did not start: " + (p.stderr.read() or "")[-300:])
        yield int(satir.split()[1])
    finally:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        p.stdout.close()
        p.stderr.close()
        shutil.rmtree(gecici, ignore_errors=True)


# ---- the three measurements ----

def _yukle_bir(host, port, n, belge=None, eposta_=None):
    veri = json.dumps(belge if belge is not None else ornek_belge(n)).encode()
    govde, ctype = yukleme_govdesi(veri, eposta_ or eposta(n), "Yuk Testi %d" % n)
    sure, durum, bas, _ = olculu(host, port, "POST", "/api/tarama/yukle", govde, {"Content-Type": ctype})
    return sure, durum, None, bas


def goruntuleme_olc(host, port, yollar, adet, esanlilik):
    """Concurrent report viewing; the server must still be running. Every view also writes one audit row."""
    if not yollar:
        return ozet([], 0.0)

    def is_(i):
        sure, durum, _, _ = olculu(host, port, "GET", yollar[i % len(yollar)])
        return (sure, durum, None)
    t = time.perf_counter()
    olcum = esanli(is_, adet, esanlilik)
    return ozet(olcum, time.perf_counter() - t)


def hiz_siniri_olc(host):
    """429 behaviour with the real defaults. Sequential on purpose: the order decides which request is the first refused one."""
    from tarama import depo, server
    ip_adet = server.H.sinir.n + 3
    sirket_adet = depo.SINIR_ADET + 2
    sonuc = {"ayar": {"adres_siniri": server.H.sinir.n, "pencere_sn": server.H.sinir.w, "sirket_hakki": depo.SINIR_ADET, "sirket_gun": depo.SINIR_GUN}}

    def say(olcumler):
        d, ra = {}, []
        for durum, bas in olcumler:
            d[str(durum)] = d.get(str(durum), 0) + 1
            if durum == 429 and bas.get("retry-after") not in ra:
                ra.append(bas.get("retry-after"))
        return d, ra

    with sunucu(host) as port:   # default per-address limit; a different company for every request
        ol = []
        for i in range(ip_adet):
            _, durum, _, bas = _yukle_bir(host, port, 1000 + i)
            ol.append((durum, bas))
        d, ra = say(ol)
        sonuc["ip"] = {"adet": ip_adet, "durumlar": d, "retry_after": ra, "ilk_429_sirasi": next((i + 1 for i, (c, _) in enumerate(ol) if c == 429), None)}
    with sunucu(host, sinir=sirket_adet + 10) as port:   # per-address limit raised; the same company, a different file each time
        ol = []
        for i in range(sirket_adet):
            _, durum, _, bas = _yukle_bir(host, port, 2000 + i, belge=ornek_belge(i), eposta_="ayni@tek-sirket.yuk.test")
            ol.append((durum, bas))
        d, ra = say(ol)
        sonuc["sirket"] = {"adet": sirket_adet, "durumlar": d, "retry_after": ra, "ilk_429_sirasi": next((i + 1 for i, (c, _) in enumerate(ol) if c == 429), None)}
    return sonuc


def ortam():
    return {"cpu": os.cpu_count() or 0, "python": platform.python_version(), "sistem": "%s %s" % (platform.system(), platform.release()),
            "sunucu": "tarama/server.py (ThreadingHTTPServer + SQLite, no reverse proxy, loopback)"}


def olc(yukleme=200, goruntuleme=1000, esanlilik=16, host="127.0.0.1"):
    """Runs the three measurements and returns one result dictionary."""
    loopback_zorunlu(host)
    with sunucu(host, sinir=yukleme + 10) as port:   # per-address limit raised above the upload count, so only load is measured here
        yollar, kilit = [], threading.Lock()

        def yuk(i):
            sure, durum, hata, bas = _yukle_bir(host, port, i)
            yer = bas.get("location", "")
            if durum == 303 and yer.startswith("/rapor/"):
                with kilit:
                    yollar.append(yer)
            return (sure, durum, hata)
        t = time.perf_counter()
        yuk_ozet = ozet(esanli(yuk, yukleme, esanlilik), time.perf_counter() - t)
        gor_ozet = goruntuleme_olc(host, port, list(yollar), goruntuleme, esanlilik)
    return {"ortam": ortam(), "parametre": {"yukleme": yukleme, "goruntuleme": goruntuleme, "esanlilik": esanlilik},
            "yukleme": yuk_ozet, "goruntuleme": gor_ozet, "hiz_siniri": hiz_siniri_olc(host)}


# ---- output ----

def _satir(ad, o):
    g = o["gecikme_ms"]
    gec = " | ".join("%.1f" % g[k] for k in ("min", "p50", "p90", "p95", "p99", "max")) if g else " | ".join(["-"] * 6)
    return "| %s | %d | %s | %s | %s | %.1f |" % (
        ad, o["istek"], ", ".join("%s: %d" % kv for kv in sorted(o["durumlar"].items())) or "-",
        ", ".join("%s: %d" % kv for kv in sorted(o["hatalar"].items())) or "none", gec, o["saniyede_istek"] or 0.0)


def rapor_metni(s):
    o, p = s["ortam"], s["parametre"]
    m = ["Environment", "- CPU count: %s" % o["cpu"], "- Python: %s" % o["python"], "- System: %s" % o["sistem"], "- Server: %s" % o["sunucu"],
         "- Parameters: %d uploads, %d report views, concurrency %d" % (p["yukleme"], p["goruntuleme"], p["esanlilik"]), "",
         "Concurrent upload and report viewing (latency in milliseconds; client and server share this machine)", "",
         "| Scenario | Requests | Status counts | Errors | min | p50 | p90 | p95 | p99 | max | Requests/s |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
         _satir("upload (POST /api/tarama/yukle)", s["yukleme"]),
         _satir("report view (GET /rapor/<token>/)", s["goruntuleme"]), "",
         "429 behaviour (real defaults, sequential requests)", ""]
    a = s["hiz_siniri"]["ayar"]
    m.append("- Configured in code: per-address limit %d uploads per %d s; per-company free scans %d per %d days" % (
        a["adres_siniri"], a["pencere_sn"], a["sirket_hakki"], a["sirket_gun"]))
    for ad, k in (("per-address limit", "ip"), ("per-company allowance", "sirket")):
        r = s["hiz_siniri"][k]
        m.append("- %s: %d requests, statuses %s, first 429 at request %s, Retry-After seen: %s" % (
            ad, r["adet"], ", ".join("%s: %d" % kv for kv in sorted(r["durumlar"].items())), r.get("ilk_429_sirasi", "-"),
            ", ".join(map(str, r["retry_after"])) or "none"))
    m += ["", "These are measurements from one run on one machine. They are not a capacity statement."]
    return "\n".join(m) + "\n"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == _SUNUCU_MODU:
        _sunucu_modu(argv[1:])
        return 0
    ap = argparse.ArgumentParser(description="Local load measurement of the scan/report server (loopback only).")
    ap.add_argument("--host", default="127.0.0.1", help="loopback address to bind and connect to (anything else is refused)")
    ap.add_argument("--yukleme", type=int, default=200, help="number of uploads")
    ap.add_argument("--goruntuleme", type=int, default=1000, help="number of report views")
    ap.add_argument("--esanlilik", type=int, default=16, help="concurrent client threads")
    ap.add_argument("--cikti", help="also write the result text to this file")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the text")
    a = ap.parse_args(argv)
    try:
        loopback_zorunlu(a.host)
    except Reddedildi as e:
        print(e, file=sys.stderr)
        return 2
    if min(a.yukleme, a.goruntuleme, a.esanlilik) < 1:
        print("error: counts must be at least 1", file=sys.stderr)
        return 2
    s = olc(a.yukleme, a.goruntuleme, a.esanlilik, a.host)
    metin = json.dumps(s, indent=2, sort_keys=True) + "\n" if a.json else rapor_metni(s)
    sys.stdout.write(metin)
    if a.cikti:
        Path(a.cikti).write_text(metin, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
