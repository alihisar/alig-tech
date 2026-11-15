#!/usr/bin/env python3
"""Mode B runner: runs the direct-connection scan in a process SEPARATE from the web process.

Why separate: the web process cannot open outbound connections (IPAddressDeny=any) and it reaches our databases;
the runner connects outward but cannot reach our data directory, service secrets or the internal network.

Communication: a local Unix socket, one job per connection. Frame: 4-byte length (big-endian) + JSON.
The password travels only over this socket, in memory; it is not written to disk or the log.
The runner does not trust the web process: it re-checks the target address, port and fields itself.
The web process does not trust the runner either: it re-validates the returned document with `yukleme.dogrula`.

Usage: python3 tarama/calistirici.py --soket /run/alig-calistirici/calistirici.sock --izinli-kullanici alig-web
Design: docs/kip-b-tasarim.md
"""
import argparse
import ipaddress
import json
import os
import re
import socket
import socketserver
import struct
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tarama import baglanti, hedef, yukleme  # noqa: E402

ISTEK_SINIRI = 16 * 1024 + 2 * baglanti.CA_PEM_SINIRI   # + CA PEM (JSON escaping doubles a newline to two bytes)
YANIT_SINIRI = yukleme.MAX_BAYT + 64 * 1024
KANIT = re.compile(r"^[0-9a-f]{32}$")
ALANLAR = {"ad", "ip", "port", "veritabani", "kullanici", "parola", "kanit", "maskele"}
ISTEGE_BAGLI = {"ca_pem"}   # if not given, the existing behavior: sslmode=require
SURE = 150


def paketle(nesne):
    veri = json.dumps(nesne, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(veri)) + veri


def _oku(sok, n):
    veri = b""
    while len(veri) < n:
        parca = sok.recv(min(65536, n - len(veri)))
        if not parca:
            raise ConnectionError("closed early")
        veri += parca
    return veri


def cerceve_al(sok, sinir):
    n = struct.unpack(">I", _oku(sok, 4))[0]
    if n > sinir:
        raise ValueError("too large")
    return json.loads(_oku(sok, n).decode("utf-8"))


class _Isleyici(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.server
        self.request.settimeout(SURE)
        try:
            self.request.sendall(paketle(self._is(s)))
        except OSError:
            pass

    def _is(self, s):
        if s.izinli_uidler is not None:
            try:
                kimlik = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                uid = struct.unpack("3i", kimlik)[1]
            except (OSError, AttributeError, struct.error):
                return {"hata": "calistirici"}
            if uid not in s.izinli_uidler:
                return {"hata": "calistirici"}
        try:
            i = cerceve_al(self.request, ISTEK_SINIRI)
        except (ValueError, ConnectionError, OSError, UnicodeError, struct.error):
            return {"hata": "bicim"}
        if not isinstance(i, dict) or not ALANLAR <= set(i) <= ALANLAR | ISTEGE_BAGLI:
            return {"hata": "bicim"}
        if (not isinstance(i["kanit"], str) or not KANIT.match(i["kanit"]) or not isinstance(i["parola"], str) or not i["parola"]
                or not isinstance(i["maskele"], bool) or not isinstance(i["veritabani"], str) or not isinstance(i["kullanici"], str)
                or not baglanti.AD.match(i["veritabani"]) or not baglanti.AD.match(i["kullanici"])):
            return {"hata": "bicim"}
        ca_pem = i.get("ca_pem")
        if "ca_pem" in i:
            try:
                ca_pem = baglanti.ca_dogrula(ca_pem)
            except baglanti.BaglantiHatasi:
                return {"hata": "ca"}
        try:   # re-check the target: the web process is not trusted
            ip = ipaddress.ip_address(i["ip"]) if isinstance(i["ip"], str) else None
            port = hedef._port(i["port"])
            ad, ad_ip = hedef._ad(i["ad"])
            if ip is None or not hedef.adres_uygun(ip, s.yasak_aglar) or (ad_ip is not None and ad_ip != ip):
                raise hedef.Reddedildi("ic_adres")
        except (ValueError, hedef.Reddedildi):
            return {"hata": "hedef"}
        if not s.yuva.acquire(blocking=False):
            return {"hata": "mesgul"}
        ek = {"ca_pem": ca_pem} if ca_pem is not None else {}
        try:
            belge = s.tara(hedef.Hedef(ad if ad_ip is None else str(ip), str(ip), port), veritabani=i["veritabani"],
                           kullanici=i["kullanici"], parola=i["parola"], kanit=i["kanit"], psql=s.psql, sslmode="require",
                           maskele=i["maskele"], **ek)
            return {"belge": belge}
        except baglanti.BaglantiHatasi as e:
            return {"hata": e.kod}
        except Exception:   # the detail is not sent outward
            return {"hata": "baglanti"}
        finally:
            s.yuva.release()


class Sunucu(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, soket, tara=baglanti.tara, yasak_aglar=(), izinli_uidler=None, psql="psql", es_zamanli=2):
        if os.path.exists(soket):
            os.unlink(soket)
        eski = os.umask(0o117)   # socket 0660: owner and group
        try:
            super().__init__(soket, _Isleyici)
        finally:
            os.umask(eski)
        os.chmod(soket, 0o660)
        self.tara, self.psql = tara, psql
        self.yasak_aglar = [ipaddress.ip_network(a) for a in yasak_aglar]
        self.izinli_uidler = None if izinli_uidler is None else set(izinli_uidler)
        self.yuva = threading.BoundedSemaphore(es_zamanli)


def uzaktan_tara(soket, h, veritabani, kullanici, parola, kanit, maskele=False, ca_pem=None, **_):
    """Web process side. Returns the validated document or raises BaglantiHatasi."""
    istek = {"ad": h.ad, "ip": h.ip, "port": h.port, "veritabani": veritabani, "kullanici": kullanici,
             "parola": parola, "kanit": kanit, "maskele": bool(maskele)}
    if ca_pem:
        istek["ca_pem"] = ca_pem
    sok = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sok.settimeout(SURE + 10)
    try:
        sok.connect(soket)
        sok.sendall(paketle(istek))
        yanit = cerceve_al(sok, YANIT_SINIRI)
    except (OSError, ValueError, UnicodeError, struct.error):
        raise baglanti.BaglantiHatasi("calistirici")
    finally:
        sok.close()
    if not isinstance(yanit, dict):
        raise baglanti.BaglantiHatasi("calistirici")
    if "hata" in yanit:
        kod = yanit["hata"]
        raise baglanti.BaglantiHatasi(kod if kod in ("baglanti", "kanit", "super", "zaman", "bicim", "hedef", "mesgul", "calistirici", "ca") else "baglanti")
    try:
        return yukleme.dogrula(yanit.get("belge"))   # the runner is not trusted either
    except (yukleme.Gecersiz, TypeError, KeyError):
        raise baglanti.BaglantiHatasi("bicim")


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech Mode B runner")
    ap.add_argument("--soket", required=True)
    ap.add_argument("--izinli-kullanici", action="append", default=[], help="system user allowed to connect to the socket (repeatable)")
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--es-zamanli", type=int, default=2)
    a = ap.parse_args(argv)
    import pwd
    uidler = [pwd.getpwnam(k).pw_uid for k in a.izinli_kullanici] or None
    aglar = tuple(x.strip() for x in os.environ.get("ALIG_YASAK_AGLAR", "").split(",") if x.strip())
    srv = Sunucu(a.soket, yasak_aglar=aglar, izinli_uidler=uidler, psql=a.psql, es_zamanli=a.es_zamanli)
    print("alig runner: %s" % a.soket, flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
