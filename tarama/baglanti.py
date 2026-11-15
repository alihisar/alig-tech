"""Mode B: scan over a direct connection. Standard library only; runs through the `psql` subprocess.

Security rules (docs/kip-b-tasarim.md):
- The target is first validated with `tarama.hedef.dogrula`; the connection is opened to the validated IP, not the name (hostaddr).
- The password lives only in the subprocess environment; it is not written to the argument list, the log or the disk.
- The ownership proof is read first. If it does not match, or the account is a superuser, no catalog query runs.
- Every value coming from the server is validated with `yukleme.dogrula` (strict schema).
- Table, index and sequence checks run in every database that can be connected to; a database whose name does not match the `AD` pattern
  never enters the connection string and is skipped with the reason "ad" (name).
"""
import base64
import binascii
import json
import os
import re
import selectors
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from tarama import katalog, yukleme
from tarama.uret_toplayici import katalog_ozeti

AD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}\Z")   # \Z: a trailing newline is also rejected
EN_COK_VERITABANI = 20   # lower than the collector's, so it stays within the time budget (toplam_sure)
CIKTI_SINIRI = 2 * 1024 * 1024   # psql stdout; the server chosen by the customer may be hostile, so memory does not grow without bound
HATA_SINIRI = 64 * 1024
GUVENLI_AD = re.compile(r"^[0-9A-Za-z.:-]{1,255}\Z")   # host/hostaddr entering the connection string: no spaces, quotes, % or =
CA_PEM_SINIRI = 16 * 1024   # upper limit for the CA PEM pasted by the customer (including the chain)
CA_EN_COK_SERTIFIKA = 5
SSLROOTCERT_YOLU = re.compile(r"^/[0-9A-Za-z._/-]{1,255}\Z")   # file path entering the string: no spaces, quotes, backslash, = or newline
_PEM_BAS, _PEM_SON = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
_PEM_SATIR = re.compile(r"^[A-Za-z0-9+/]{1,100}={0,2}\Z")
KANIT_ON_EK = "alig-kanit-"
ILK_SORGU = ("SELECT current_setting('is_superuser') = 'on' AS super, "
             "shobj_description((SELECT oid FROM pg_roles WHERE rolname = current_user), 'pg_authid') AS kanit, "
             "current_setting('server_version_num')::int AS surum")


class BaglantiHatasi(Exception):
    """kod: 'baglanti', 'kanit', 'super', 'zaman', 'bicim', 'ca'."""

    def __init__(self, kod):
        super().__init__("dogrudan baglanti: " + kod)
        self.kod = kod


def kanit_metni(kanit):
    return KANIT_ON_EK + kanit


def kanit_komutu(kullanici, kanit):
    return "COMMENT ON ROLE %s IS '%s';" % (kullanici, kanit_metni(kanit))


def hata_sinifi(stderr):
    s = (stderr or "").lower()
    if "permission denied" in s or "must be superuser" in s or "must be member" in s:
        return "yetki"
    if "statement timeout" in s or "canceling statement" in s:
        return "zaman_asimi"
    if "does not exist" in s or "unrecognized" in s:
        return "desteklenmiyor"
    if "in recovery" in s or "recovery is in progress" in s:
        return "yedek_sunucu"
    return "hata"


def ca_dogrula(pem):
    """Validates the CA PEM given by the customer and returns the normalized text (certificate blocks only, LF line endings).
    A private key, a block with headers, extra text, NUL, non-ASCII, bad base64, or oversized or multi-certificate input raises BaglantiHatasi('ca')."""
    if not isinstance(pem, str) or len(pem) > CA_PEM_SINIRI or "\x00" in pem or not pem.isascii():
        raise BaglantiHatasi("ca")
    satirlar = [x.strip() for x in pem.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    bloklar, govde, icinde = [], [], False
    for x in satirlar:
        if not x:
            continue
        if x == _PEM_BAS:
            if icinde:
                raise BaglantiHatasi("ca")
            icinde, govde = True, []
        elif x == _PEM_SON:
            if not icinde or not govde:
                raise BaglantiHatasi("ca")
            icinde = False
            bloklar.append(govde)
        elif icinde and _PEM_SATIR.match(x):
            govde.append(x)
        else:
            raise BaglantiHatasi("ca")   # text outside blocks, another PEM type (private key), a header line, a bad character
    if icinde or not 1 <= len(bloklar) <= CA_EN_COK_SERTIFIKA:
        raise BaglantiHatasi("ca")
    cikti = []
    for govde in bloklar:
        if any("=" in x for x in govde[:-1]):
            raise BaglantiHatasi("ca")
        try:
            ham = base64.b64decode("".join(govde), validate=True)
        except (binascii.Error, ValueError):
            raise BaglantiHatasi("ca")
        if len(ham) < 16 or ham[0] != 0x30:   # a body that does not start with a DER SEQUENCE is not a certificate
            raise BaglantiHatasi("ca")
        cikti.append("\n".join([_PEM_BAS] + govde + [_PEM_SON]) + "\n")
    return "".join(cikti)


def baglanti_dizgisi(hedef, veritabani, kullanici, sslmode="require", sslrootcert=None):
    if not AD.match(veritabani or "") or not AD.match(kullanici or ""):
        raise BaglantiHatasi("bicim")
    if sslmode not in ("require", "verify-ca", "verify-full", "prefer"):
        raise BaglantiHatasi("bicim")
    # verify-* is not accepted without a root certificate (libpq would fall back to the file in the home directory); a root certificate is not silently ignored outside verify-*
    if (sslrootcert is None) == (sslmode in ("verify-ca", "verify-full")):
        raise BaglantiHatasi("bicim")
    if sslrootcert is not None and not (isinstance(sslrootcert, str) and SSLROOTCERT_YOLU.match(sslrootcert)):
        raise BaglantiHatasi("bicim")
    # the target object also comes from the runner socket: no extra keys may be injected into the string (hostaddr, options, sslmode...)
    if not (isinstance(hedef.ad, str) and GUVENLI_AD.match(hedef.ad) and isinstance(hedef.ip, str) and GUVENLI_AD.match(hedef.ip)
            and isinstance(hedef.port, int) and not isinstance(hedef.port, bool) and 1 <= hedef.port <= 65535):
        raise BaglantiHatasi("bicim")
    # channel_binding=require: the server must authenticate with SCRAM-SHA-256-PLUS bound to the TLS channel. This way the password
    # is not sent in plain text or MD5, and a relay (MITM) attack against a server whose certificate cannot be verified does not work.
    kok = (" sslrootcert=" + sslrootcert) if sslrootcert is not None else ""
    return ("host=%s hostaddr=%s port=%d dbname=%s user=%s sslmode=%s%s channel_binding=require connect_timeout=10 gssencmode=disable"
            % (hedef.ad, hedef.ip, hedef.port, veritabani, kullanici, sslmode, kok))


def _ortam(parola):
    """Only what is needed is passed to the subprocess; the service environment (salts, keys, proxy settings) is not inherited."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "PGPASSWORD": parola,
            "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000",
            "PGAPPNAME": "alig-tarama", "PGCONNECT_TIMEOUT": "10", "PGPASSFILE": os.devnull, "PGSERVICEFILE": os.devnull,
            "PGSYSCONFDIR": os.devnull}


def _surec_calistir(cmd, env, sure):
    """(return code, stdout, stderr). TimeoutError if the time is exceeded, OverflowError if stdout exceeds CIKTI_SINIRI; the process is
    killed in every case. stderr beyond HATA_SINIRI is discarded."""
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    sec = selectors.DefaultSelector()
    sec.register(p.stdout, selectors.EVENT_READ, "out")
    sec.register(p.stderr, selectors.EVENT_READ, "err")
    tampon = {"out": bytearray(), "err": bytearray()}
    bitis = time.monotonic() + sure
    try:
        while sec.get_map():
            kalan = bitis - time.monotonic()
            if kalan <= 0:
                raise TimeoutError("time limit exceeded")
            for anahtar, _ in sec.select(kalan):
                parca = os.read(anahtar.fd, 65536)
                if not parca:
                    sec.unregister(anahtar.fileobj)
                    continue
                t = tampon[anahtar.data]
                t += parca
                if anahtar.data == "out" and len(t) > CIKTI_SINIRI:
                    raise OverflowError("output limit")
                if anahtar.data == "err" and len(t) > HATA_SINIRI:
                    del t[HATA_SINIRI:]
        p.wait(timeout=max(0.1, bitis - time.monotonic()))
    except subprocess.TimeoutExpired:
        raise TimeoutError("time limit exceeded")
    finally:
        sec.close()
        if p.poll() is None:
            p.kill()
        p.wait()
        p.stdout.close()
        p.stderr.close()
    return p.returncode, tampon["out"].decode("utf-8", "replace"), tampon["err"].decode("utf-8", "replace")


def _calistir(psql, dizgi, parola, sql, sure):
    sarmal = "SELECT coalesce(json_agg(t), '[]'::json) FROM (" + sql + ") t"
    cmd = [psql, "-X", "-A", "-t", "-w", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-d", dizgi, "-c", sarmal]
    try:
        kod, cikti, hata = _surec_calistir(cmd, _ortam(parola), max(1, sure))
    except TimeoutError:
        return {"durum": "hata", "neden": "zaman_asimi"}, ""
    except OverflowError:
        return {"durum": "hata", "neden": "hata"}, ""
    if kod != 0:
        return {"durum": "hata", "neden": hata_sinifi(hata)}, hata
    try:
        satirlar = json.loads(cikti.strip() or "[]")
    except ValueError:
        return {"durum": "hata", "neden": "hata"}, ""
    return ({"durum": "ok", "satirlar": satirlar} if isinstance(satirlar, list) else {"durum": "hata", "neden": "hata"}), ""


class _Maske:
    def __init__(self):
        self.harita = {}

    def al(self, deger):
        if deger is None or not isinstance(deger, str):
            return deger
        return self.harita.setdefault(deger, "nesne-%d" % (len(self.harita) + 1))


def _temizle(c, satirlar, limit=yukleme.MAX_SATIR):
    """Of the rows coming from the server, only the catalog columns remain."""
    return [{k: v for k, v in s.items() if k in c["kolonlar"]} for s in satirlar[:limit] if isinstance(s, dict)]


def _veritabanlari(psql, dizgi, parola, ilk_db, bitis):
    """(to scan, skipped). If the list cannot be obtained, only the first database."""
    sonuc, _ = _calistir(psql, dizgi, parola, katalog.VT_LISTE_SQL, max(1, min(30, bitis - time.monotonic())))
    if sonuc["durum"] != "ok":
        return [ilk_db], []
    taranacak, atlanan = [], []
    for s in sonuc["satirlar"][:yukleme.MAX_ATLANAN]:
        ad = s.get("veritabani") if isinstance(s, dict) else None
        if not isinstance(ad, str) or len(ad) > yukleme.MAX_METIN:
            continue
        if not AD.match(ad):
            atlanan.append({"veritabani": ad, "neden": "ad"})
        elif s.get("baglanir") is not True:
            atlanan.append({"veritabani": ad, "neden": "yetki"})
        elif len(taranacak) >= EN_COK_VERITABANI:
            atlanan.append({"veritabani": ad, "neden": "sinir"})
        else:
            taranacak.append(ad)
    return taranacak, atlanan


def _her_veritabani(psql, parola, hedef, kullanici, sslmode, c, sql, taranacak, atlanan, bitis, sslrootcert=None):
    satirlar, at, calisti, ilk_neden = [], list(atlanan), False, None
    for db in taranacak:
        kalan = bitis - time.monotonic()
        if kalan <= 1:
            at.append({"veritabani": db, "neden": "zaman_asimi"})
            continue
        sonuc, _ = _calistir(psql, baglanti_dizgisi(hedef, db, kullanici, sslmode, sslrootcert), parola, sql, min(30, kalan))
        if sonuc["durum"] == "ok":
            calisti = True
            for s in _temizle(c, sonuc["satirlar"]):
                s["veritabani"] = db
                satirlar.append(s)
        else:
            at.append({"veritabani": db, "neden": sonuc["neden"]})
            ilk_neden = ilk_neden or sonuc["neden"]
    if not calisti:
        return {"durum": "hata", "neden": ilk_neden or ("yetki" if at else "calistirilmadi")}
    sonuc = {"durum": "ok", "satirlar": satirlar[:yukleme.MAX_SATIR_VT]}
    if at:
        sonuc["atlanan"] = at
    return sonuc


def tara(hedef, veritabani, kullanici, parola, kanit, psql="psql", sslmode="require", maskele=False, toplam_sure=90, ca_pem=None):
    """Returns the validated collection document or raises BaglantiHatasi.

    Server certificate: by default `sslmode=require` + `channel_binding=require` (the certificate is not checked). If ca_pem is given
    (the customer's CA), sslmode=verify-full is used: the chain is validated against this CA and the certificate against `hedef.ad`. If the CA is invalid,
    it does not silently fall back to the weak mode; BaglantiHatasi('ca') is raised. The CA file sits in a 0600 temporary directory and is deleted when the job ends."""
    if not isinstance(parola, str) or not parola or len(parola) > 1024 or "\x00" in parola:
        raise BaglantiHatasi("baglanti")
    if ca_pem is None:
        return _tara(hedef, veritabani, kullanici, parola, kanit, psql, sslmode, None, maskele, toplam_sure)
    pem = ca_dogrula(ca_pem)
    dizin = tempfile.mkdtemp(prefix="alig-ca-")   # mkdtemp: 0700
    try:
        yol = os.path.join(dizin, "ca.pem")
        fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as f:
            f.write(pem)
        return _tara(hedef, veritabani, kullanici, parola, kanit, psql, "verify-full", yol, maskele, toplam_sure)
    finally:
        shutil.rmtree(dizin, ignore_errors=True)


def _tara(hedef, veritabani, kullanici, parola, kanit, psql, sslmode, sslrootcert, maskele, toplam_sure):
    dizgi = baglanti_dizgisi(hedef, veritabani, kullanici, sslmode, sslrootcert)
    bitis = time.monotonic() + toplam_sure

    ilk, _ = _calistir(psql, dizgi, parola, ILK_SORGU, min(30, toplam_sure))
    if ilk["durum"] != "ok" or len(ilk["satirlar"]) != 1 or not isinstance(ilk["satirlar"][0], dict):
        raise BaglantiHatasi("zaman" if ilk.get("neden") == "zaman_asimi" else "baglanti")
    satir = ilk["satirlar"][0]
    if satir.get("kanit") != kanit_metni(kanit):
        raise BaglantiHatasi("kanit")
    if satir.get("super") is not False:
        raise BaglantiHatasi("super")
    surum = satir.get("surum")
    ana = surum // 10000 if isinstance(surum, int) and not isinstance(surum, bool) else None

    maske = _Maske() if maskele else None
    taranacak, atlanan = _veritabanlari(psql, dizgi, parola, veritabani, bitis)
    kontroller = {}
    for c in katalog.PG:
        sql = katalog.sorgu(c, ana)
        if sql is None:   # feature not present in this version: the query does not run
            kontroller[c["id"]] = {"durum": "hata", "neden": "desteklenmiyor"}
            continue
        if c.get("kapsam") == "veritabani":
            sonuc = _her_veritabani(psql, parola, hedef, kullanici, sslmode, c, sql, taranacak, atlanan, bitis, sslrootcert)
        else:
            kalan = bitis - time.monotonic()
            if kalan <= 1:
                kontroller[c["id"]] = {"durum": "hata", "neden": "zaman_asimi"}
                continue
            sonuc, _ = _calistir(psql, dizgi, parola, sql, min(30, kalan))
            if sonuc["durum"] == "ok":
                sonuc = {"durum": "ok", "satirlar": _temizle(c, sonuc["satirlar"])}
        if sonuc["durum"] == "ok" and maske:
            for s in sonuc["satirlar"]:
                for kolon in c["maske"]:
                    if kolon in s:
                        s[kolon] = maske.al(s[kolon])
            for a in sonuc.get("atlanan", []):
                a["veritabani"] = maske.al(a["veritabani"])
        kontroller[c["id"]] = sonuc

    belge = {"format": katalog.FORMAT, "motor": "postgresql", "katalog_sha256": katalog_ozeti(),
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": False, "kontroller": kontroller}
    try:
        return yukleme.dogrula(belge)   # every value coming from the server is untrusted
    except yukleme.Gecersiz:
        raise BaglantiHatasi("bicim")
