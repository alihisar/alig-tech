"""Kip B (dogrudan baglanti) icin hedef dogrulamasi. Yalnizca standart kutuphane. BAGLANTI ACMAZ.

Amac: musterinin yazdigi sunucu adresinin bizim ic agimiza, yerel adreslere ya da bulut meta veri
servisine yonlenmesini (SSRF) ve denetimden sonra adresin degismesini (DNS rebinding) onlemek.

Kurallar:
- Ad yalnizca bir kez cozulur. Donen HER adres denetlenir; biri bile uygun degilse hedef reddedilir.
- Baglanti ada degil, dogrulanan IP'ye acilir (`Hedef.baglanti_adresi()`); ad yalnizca TLS sunucu adi icindir.
- Musteriye giden ileti tek tiptir; neden yalnizca `Reddedildi.kod` ile ic kayda gecer.

Tasarim: docs/kip-b-tasarim.md
"""
import hashlib
import ipaddress
import re
import socket

IZINLI_PORTLAR = (5432, 1433)
EN_COK_ADRES = 16
ETIKET = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
SAYISAL = re.compile(r"^[0-9a-fx.]+$")
YEREL_SON_EKLER = ("localhost", "local", "internal", "lan", "home", "corp", "intranet", "arpa", "test", "invalid", "example", "onion")
NAT64 = ipaddress.ip_network("64:ff9b::/96")
NAT64_YEREL = ipaddress.ip_network("64:ff9b:1::/48")

ILETI = {"tr": "Bu sunucuya bağlanılamadı. Adresi ve portu denetleyin; yalnızca internetten erişilebilen adresler kabul edilir.",
         "en": "Could not connect to this server. Check the address and port; only addresses reachable from the internet are accepted."}


class Reddedildi(ValueError):
    """kod: 'ad', 'port', 'cozulemedi', 'ic_adres'. Musteriye kod gosterilmez."""

    def __init__(self, kod):
        super().__init__("hedef reddedildi: " + kod)
        self.kod = kod

    def ileti(self, dil="tr"):
        return ILETI.get(dil, ILETI["tr"])


class Hedef:
    __slots__ = ("ad", "ip", "port")

    def __init__(self, ad, ip, port):
        self.ad, self.ip, self.port = ad, ip, port

    def baglanti_adresi(self):
        """Baglanti bu cifte acilir; ad yeniden cozulmez."""
        return (self.ip, self.port)

    def ozet(self):
        """Denetim kaydi icin: adresin kendisi yerine SHA-256 ozeti."""
        return hashlib.sha256(("%s|%s|%d" % (self.ad, self.ip, self.port)).encode("utf-8")).hexdigest()


def _port(port):
    if isinstance(port, bool):
        raise Reddedildi("port")
    if isinstance(port, str) and re.fullmatch(r"[0-9]{1,5}", port):
        port = int(port)
    if not isinstance(port, int):
        raise Reddedildi("port")
    if port in IZINLI_PORTLAR or 1024 <= port <= 65535:
        return port
    raise Reddedildi("port")


def _gomulu(ip):
    """IPv6 icine gomulu IPv4 adreslerini cikarir (eslemeli, uyumlu, 6to4, Teredo)."""
    out = []
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            out.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            out.append(ip.sixtofour)
        if ip.teredo is not None:
            out.extend(ip.teredo)
        if int(ip) >> 32 == 0 and int(ip) > 1:   # ::a.b.c.d (eski IPv4 uyumlu bicim)
            out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return out


def adres_uygun(ip, yasak_aglar=()):
    """Yalnizca genel internet adresleri uygundur."""
    if ip.version == 6 and (ip in NAT64 or ip in NAT64_YEREL):
        return False
    for a in [ip] + _gomulu(ip):
        if (not a.is_global or a.is_multicast or a.is_private or a.is_loopback or a.is_link_local
                or a.is_reserved or a.is_unspecified):
            return False
        for ag in yasak_aglar:
            if a.version == ag.version and a in ag:
                return False
    return True


def _ad(ham):
    """(ad, ip ya da None). Ad kucuk harfe cevrilir, sondaki nokta atilir."""
    if not isinstance(ham, str) or not ham or len(ham) > 255 or ham != ham.strip():
        raise Reddedildi("ad")
    ad = ham
    if ad.startswith("[") or ad.endswith("]"):
        if not (ad.startswith("[") and ad.endswith("]")):
            raise Reddedildi("ad")
        try:
            return ad, ipaddress.IPv6Address(ad[1:-1])
        except ValueError:
            raise Reddedildi("ad")
    ad = ad.lower()
    if ad.endswith("."):
        ad = ad[:-1]
    if SAYISAL.match(ad):   # sayisal gorunen her sey kati noktalı dortlu olmali (onluk, onaltilik, sekizlik, kisa bicim yok)
        try:
            return ad, ipaddress.IPv4Address(ad)
        except ValueError:
            raise Reddedildi("ad")
    etiketler = ad.split(".")
    if len(ad) > 253 or len(etiketler) < 2 or not all(ETIKET.match(e) for e in etiketler):
        raise Reddedildi("ad")
    if etiketler[-1] in YEREL_SON_EKLER or etiketler[-1].isdigit():
        raise Reddedildi("ad")
    return ad, None


def dogrula(ad, port, cozumleyici=socket.getaddrinfo, yasak_aglar=()):
    """Hedef dondurur ya da Reddedildi firlatir. Baglanti acmaz; adi en cok bir kez cozer."""
    aglar = [ipaddress.ip_network(a) for a in yasak_aglar]
    ad, ip = _ad(ad)
    port = _port(port)
    if ip is not None:
        if not adres_uygun(ip, aglar):
            raise Reddedildi("ic_adres")
        return Hedef(str(ip), str(ip), port)
    try:
        sonuc = cozumleyici(ad, port, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise Reddedildi("cozulemedi")
    adresler = []
    for kayit in sonuc:
        try:
            a = ipaddress.ip_address(str(kayit[4][0]).split("%")[0])
        except (ValueError, IndexError, TypeError):
            raise Reddedildi("cozulemedi")
        if a not in adresler:
            adresler.append(a)
    if not adresler or len(adresler) > EN_COK_ADRES:
        raise Reddedildi("cozulemedi")
    if not all(adres_uygun(a, aglar) for a in adresler):
        raise Reddedildi("ic_adres")
    secilen = sorted(adresler, key=lambda a: a.version)[0]   # once IPv4
    return Hedef(ad, str(secilen), port)
