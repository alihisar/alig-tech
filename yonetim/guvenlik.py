"""Parola ozeti (scrypt), TOTP (RFC 6238) ve rastgele kodlar. Yalnizca standart kutuphane."""
import base64
import hashlib
import hmac
import secrets
import struct
import time

SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
PAROLA_EN_AZ = 12


def parola_ozetle(parola):
    tuz = secrets.token_bytes(16)
    oz = hashlib.scrypt(parola.encode("utf-8"), salt=tuz, maxmem=2 ** 27, dklen=32, **SCRYPT)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT["n"], SCRYPT["r"], SCRYPT["p"], tuz.hex(), oz.hex())


def parola_dogrula(parola, kayit):
    try:
        ad, n, r, p, tuz, oz = kayit.split("$")
        if ad != "scrypt":
            return False
        hesap = hashlib.scrypt(parola.encode("utf-8"), salt=bytes.fromhex(tuz), n=int(n), r=int(r), p=int(p), maxmem=2 ** 27, dklen=32)
        return hmac.compare_digest(hesap.hex(), oz)
    except (ValueError, TypeError):
        return False


# Kullanici yokken de ayni sureyi harcamak icin (zamanlama ile kullanici adi sizmasin)
SAHTE_OZET = parola_ozetle("sahte-parola-zamanlama-icin")


def totp_gizli():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def totp_kod(gizli, sayac):
    anahtar = base64.b32decode(gizli, casefold=True)
    h = hmac.new(anahtar, struct.pack(">Q", sayac), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


def totp_dogrula(gizli, kod, son_sayac=0, simdi=None, pencere=1):
    """Gecerliyse kullanilan sayaci, degilse None doner. son_sayac'tan buyuk olmayan sayac reddedilir (tekrar kullanim)."""
    kod = (kod or "").strip().replace(" ", "")
    if len(kod) != 6 or not kod.isdigit():
        return None
    su = int((simdi if simdi is not None else time.time()) // 30)
    for s in range(su - pencere, su + pencere + 1):
        if s > son_sayac and hmac.compare_digest(totp_kod(gizli, s), kod):
            return s
    return None


def totp_uri(gizli, kullanici, yayinci="alig.tech"):
    return "otpauth://totp/%s:%s?secret=%s&issuer=%s&algorithm=SHA1&digits=6&period=30" % (yayinci, kullanici, gizli, yayinci)


def rastgele_kod():
    return secrets.token_urlsafe(32)


def ozet(metin):
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()
