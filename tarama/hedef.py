"""Target validation for Mode B (direct connection). Standard library only. DOES NOT OPEN CONNECTIONS.

Purpose: to prevent the server address typed by the customer from being redirected to our internal network, to local addresses or to the cloud metadata
service (SSRF), and to prevent the address from changing after the check (DNS rebinding).

Rules:
- The name is resolved only once. EVERY address returned is checked; if even one is unsuitable, the target is rejected.
- The connection is opened to the validated IP, not to the name; the name is used only as the TLS server name (`Hedef.baglanti_adresi()`).
- The message sent to the customer is of a single kind; the reason goes to the internal log only through `Reddedildi.kod`.

Design: docs/kip-b-tasarim.md
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
    """kod: 'ad', 'port', 'cozulemedi', 'ic_adres'. The code is not shown to the customer."""

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
        """The connection is opened to this pair; the name is not resolved again."""
        return (self.ip, self.port)

    def ozet(self):
        """For the audit record: the SHA-256 digest instead of the address itself."""
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
    """Extracts IPv4 addresses embedded in IPv6 (mapped, compatible, 6to4, Teredo)."""
    out = []
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            out.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            out.append(ip.sixtofour)
        if ip.teredo is not None:
            out.extend(ip.teredo)
        if int(ip) >> 32 == 0 and int(ip) > 1:   # ::a.b.c.d (old IPv4-compatible form)
            out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return out


def _kapsamsiz(ip):
    """Drops the IPv6 scope id (%eth0); the scope id does not change whether the address is internal or public."""
    return ipaddress.IPv6Address(int(ip)) if ip.version == 6 and getattr(ip, "scope_id", None) else ip


def adres_uygun(ip, yasak_aglar=()):
    """Only public internet addresses are suitable. An address with a scope id (%...) is never suitable:
    the id could carry arbitrary text and, by entering the connection string, override the hostaddr/options fields."""
    if getattr(ip, "scope_id", None):
        return False
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
    """(name, ip or None). The name is lowercased and the trailing dot is dropped."""
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
    if SAYISAL.match(ad):   # anything that looks numeric must be a strict dotted quad (no decimal, hexadecimal, octal or short forms)
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
    """Returns a Hedef or raises Reddedildi. Opens no connection; resolves the name at most once."""
    aglar = [ipaddress.ip_network(a) for a in yasak_aglar]
    ad, ip = _ad(ad)
    port = _port(port)
    if ip is not None:
        if not adres_uygun(_kapsamsiz(ip), aglar):
            raise Reddedildi("ic_adres")
        if getattr(ip, "scope_id", None):
            raise Reddedildi("ad")
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
    secilen = sorted(adresler, key=lambda a: a.version)[0]   # IPv4 first
    return Hedef(ad, str(secilen), port)
