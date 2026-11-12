#!/usr/bin/env python3
"""Kip B calistiricisi: dogrudan baglantili taramayi web surecinden AYRI bir surecte calistirir.

Neden ayri: web sureci disariya baglanti acamaz (IPAddressDeny=any) ve veritabanlarimiza erisir;
calistirici disariya baglanir ama veri dizinimize, servis sirlarina ve ic aga erisemez.

Iletisim: yerel Unix soketi, baglanti basina tek is. Cerceve: 4 bayt uzunluk (big-endian) + JSON.
Parola yalnizca bu soket uzerinden, bellekte tasinir; diske ve gunluge yazilmaz.
Calistirici web surecine guvenmez: hedef adresini, portu ve alanlari kendisi yeniden denetler.
Web sureci de calistiriciya guvenmez: donen belgeyi `yukleme.dogrula` ile yeniden dogrular.

Kullanim: python3 tarama/calistirici.py --soket /run/alig-calistirici/calistirici.sock --izinli-kullanici alig-web
Tasarim: docs/kip-b-tasarim.md
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

ISTEK_SINIRI = 16 * 1024
YANIT_SINIRI = yukleme.MAX_BAYT + 64 * 1024
KANIT = re.compile(r"^[0-9a-f]{32}$")
ALANLAR = {"ad", "ip", "port", "veritabani", "kullanici", "parola", "kanit", "maskele"}
SURE = 150


def paketle(nesne):
    veri = json.dumps(nesne, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(veri)) + veri


def _oku(sok, n):
    veri = b""
    while len(veri) < n:
        parca = sok.recv(min(65536, n - len(veri)))
        if not parca:
            raise ConnectionError("erken kapandi")
        veri += parca
    return veri


def cerceve_al(sok, sinir):
    n = struct.unpack(">I", _oku(sok, 4))[0]
    if n > sinir:
        raise ValueError("cok buyuk")
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
        if not isinstance(i, dict) or set(i) != ALANLAR:
            return {"hata": "bicim"}
        if (not isinstance(i["kanit"], str) or not KANIT.match(i["kanit"]) or not isinstance(i["parola"], str) or not i["parola"]
                or not isinstance(i["maskele"], bool) or not isinstance(i["veritabani"], str) or not isinstance(i["kullanici"], str)
                or not baglanti.AD.match(i["veritabani"]) or not baglanti.AD.match(i["kullanici"])):
            return {"hata": "bicim"}
        try:   # hedefi yeniden denetle: web surecine guvenilmez
            ip = ipaddress.ip_address(i["ip"]) if isinstance(i["ip"], str) else None
            port = hedef._port(i["port"])
            ad, ad_ip = hedef._ad(i["ad"])
            if ip is None or not hedef.adres_uygun(ip, s.yasak_aglar) or (ad_ip is not None and ad_ip != ip):
                raise hedef.Reddedildi("ic_adres")
        except (ValueError, hedef.Reddedildi):
            return {"hata": "hedef"}
        if not s.yuva.acquire(blocking=False):
            return {"hata": "mesgul"}
        try:
            belge = s.tara(hedef.Hedef(ad if ad_ip is None else str(ip), str(ip), port), veritabani=i["veritabani"],
                           kullanici=i["kullanici"], parola=i["parola"], kanit=i["kanit"], psql=s.psql, sslmode="require",
                           maskele=i["maskele"])
            return {"belge": belge}
        except baglanti.BaglantiHatasi as e:
            return {"hata": e.kod}
        except Exception:   # ayrinti disari verilmez
            return {"hata": "baglanti"}
        finally:
            s.yuva.release()


class Sunucu(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, soket, tara=baglanti.tara, yasak_aglar=(), izinli_uidler=None, psql="psql", es_zamanli=2):
        if os.path.exists(soket):
            os.unlink(soket)
        eski = os.umask(0o117)   # soket 0660: sahip ve grup
        try:
            super().__init__(soket, _Isleyici)
        finally:
            os.umask(eski)
        os.chmod(soket, 0o660)
        self.tara, self.psql = tara, psql
        self.yasak_aglar = [ipaddress.ip_network(a) for a in yasak_aglar]
        self.izinli_uidler = None if izinli_uidler is None else set(izinli_uidler)
        self.yuva = threading.BoundedSemaphore(es_zamanli)


def uzaktan_tara(soket, h, veritabani, kullanici, parola, kanit, maskele=False, **_):
    """Web sureci tarafi. Dogrulanmis belgeyi dondurur ya da BaglantiHatasi firlatir."""
    istek = {"ad": h.ad, "ip": h.ip, "port": h.port, "veritabani": veritabani, "kullanici": kullanici,
             "parola": parola, "kanit": kanit, "maskele": bool(maskele)}
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
        raise baglanti.BaglantiHatasi(kod if kod in ("baglanti", "kanit", "super", "zaman", "bicim", "hedef", "mesgul", "calistirici") else "baglanti")
    try:
        return yukleme.dogrula(yanit.get("belge"))   # calistiriciya da guvenilmez
    except (yukleme.Gecersiz, TypeError, KeyError):
        raise baglanti.BaglantiHatasi("bicim")


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech Kip B calistiricisi")
    ap.add_argument("--soket", required=True)
    ap.add_argument("--izinli-kullanici", action="append", default=[], help="sokete baglanabilecek sistem kullanicisi (tekrarlanabilir)")
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--es-zamanli", type=int, default=2)
    a = ap.parse_args(argv)
    import pwd
    uidler = [pwd.getpwnam(k).pw_uid for k in a.izinli_kullanici] or None
    aglar = tuple(x.strip() for x in os.environ.get("ALIG_YASAK_AGLAR", "").split(",") if x.strip())
    srv = Sunucu(a.soket, yasak_aglar=aglar, izinli_uidler=uidler, psql=a.psql, es_zamanli=a.es_zamanli)
    print("alig calistirici: %s" % a.soket, flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
