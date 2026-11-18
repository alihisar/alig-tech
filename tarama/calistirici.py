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
ISTEGE_BAGLI = {"ca_pem", "firma_id", "istek_id"}   # ca_pem: if not given, the existing behavior (sslmode=require); the ids: only used with the job queue (--kuyruk)
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
        ek = {"ca_pem": ca_pem} if ca_pem is not None else {}

        def tara():
            return s.tara(hedef.Hedef(ad if ad_ip is None else str(ip), str(ip), port), veritabani=i["veritabani"],
                          kullanici=i["kullanici"], parola=i["parola"], kanit=i["kanit"], psql=s.psql, sslmode="require",
                          maskele=i["maskele"], **ek)
        if s.kuyruk is not None:   # job queue (--kuyruk): fair admission by company; the database only sees the two ids, never the inputs
            return self._kuyrukta(s, i, tara)
        if not s.yuva.acquire(blocking=False):
            return {"hata": "mesgul"}
        try:
            return {"belge": tara()}
        except baglanti.BaglantiHatasi as e:
            return {"hata": e.kod}
        except Exception:   # the detail is not sent outward
            return {"hata": "baglanti"}
        finally:
            s.yuva.release()

    @staticmethod
    def _kuyrukta(s, i, tara):
        from ortak import is_kuyrugu_pg, pg
        firma_id, istek_id = i.get("firma_id"), i.get("istek_id")
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in (firma_id, istek_id)):
            return {"hata": "bicim"}
        try:
            return {"belge": s.kuyruk.calistir(firma_id, istek_id, tara)}
        except baglanti.BaglantiHatasi as e:
            return {"hata": e.kod}
        except (is_kuyrugu_pg.KuyrukDolu, is_kuyrugu_pg.KuyrukZamanAsimi):
            return {"hata": "mesgul"}
        except (is_kuyrugu_pg.KuyrukHatasi, pg.PgHata):   # the queue or the database is unusable: no silent direct scan
            return {"hata": "calistirici"}
        except Exception:   # the detail is not sent outward
            return {"hata": "baglanti"}


class Sunucu(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, soket, tara=baglanti.tara, yasak_aglar=(), izinli_uidler=None, psql="psql", es_zamanli=2, kuyruk=None):
        if os.path.exists(soket):
            os.unlink(soket)
        eski = os.umask(0o117)   # socket 0660: owner and group
        try:
            super().__init__(soket, _Isleyici)
        finally:
            os.umask(eski)
        os.chmod(soket, 0o660)
        self.tara, self.psql, self.kuyruk = tara, psql, kuyruk   # kuyruk: ortak.is_kuyrugu_pg.Kabul or None (default)
        self.yasak_aglar = [ipaddress.ip_network(a) for a in yasak_aglar]
        self.izinli_uidler = None if izinli_uidler is None else set(izinli_uidler)
        self.yuva = threading.BoundedSemaphore(es_zamanli)


def uzaktan_tara(soket, h, veritabani, kullanici, parola, kanit, maskele=False, ca_pem=None, firma_id=None, istek_id=None, **_):
    """Web process side. Returns the validated document or raises BaglantiHatasi."""
    istek = {"ad": h.ad, "ip": h.ip, "port": h.port, "veritabani": veritabani, "kullanici": kullanici,
             "parola": parola, "kanit": kanit, "maskele": bool(maskele)}
    if ca_pem:
        istek["ca_pem"] = ca_pem
    if firma_id is not None and istek_id is not None:   # only the ids of the request travel to the queue; the runner may ignore them
        istek["firma_id"], istek["istek_id"] = firma_id, istek_id
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


def _kuyruk_kur(a):
    """--kuyruk: PostgreSQL must be configured; if it is not (or is wrong) stop at start, never fall back to the in-process semaphore silently."""
    from ortak import is_kuyrugu_pg, pg, pg_ayar
    ayar = pg_ayar.yukle(os.environ)
    if ayar is None:
        sys.exit("alig runner: --kuyruk needs the ALIG_DB_* settings (PostgreSQL is not configured)")
    kb = is_kuyrugu_pg.Kabul(lambda: pg.Baglanti.baglan(**ayar), a.sahip, es_zamanli=a.es_zamanli)
    kb.baslat()   # raises when the database is unreachable
    return kb


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech Mode B runner")
    ap.add_argument("--soket", required=True)
    ap.add_argument("--izinli-kullanici", action="append", default=[], help="system user allowed to connect to the socket (repeatable)")
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--es-zamanli", type=int, default=2)
    ap.add_argument("--kuyruk", action="store_true", help="admit scans through the PostgreSQL job queue (needs ALIG_DB_*); default: off")
    ap.add_argument("--sahip", default="calistirici", help="name of this runner instance in the queue (one instance per name)")
    a = ap.parse_args(argv)
    import pwd
    uidler = [pwd.getpwnam(k).pw_uid for k in a.izinli_kullanici] or None
    aglar = tuple(x.strip() for x in os.environ.get("ALIG_YASAK_AGLAR", "").split(",") if x.strip())
    kuyruk = _kuyruk_kur(a) if a.kuyruk else None
    srv = Sunucu(a.soket, yasak_aglar=aglar, izinli_uidler=uidler, psql=a.psql, es_zamanli=a.es_zamanli, kuyruk=kuyruk)
    print("alig runner: %s" % a.soket, flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
