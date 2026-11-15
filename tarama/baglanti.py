"""Kip B: dogrudan baglantiyla tarama. Yalnizca standart kutuphane; `psql` alt sureciyle calisir.

Guvenlik kurallari (docs/kip-b-tasarim.md):
- Hedef once `tarama.hedef.dogrula` ile dogrulanir; baglanti ada degil dogrulanan IP'ye acilir (hostaddr).
- Parola yalnizca alt surecin ortaminda durur; arguman listesine, gunluge, diske yazilmaz.
- Once sahiplik kaniti okunur. Uyusmazsa ya da hesap super kullaniciysa katalogdan hicbir sorgu calismaz.
- Sunucudan gelen her deger `yukleme.dogrula` ile (kati sema) dogrulanir.
- Tablo, indeks ve sequence denetimleri baglanilabilen her veritabaninda calisir; adi `AD` kalibina uymayan
  veritabani baglanti dizgisine hic girmez, "ad" nedeniyle atlanir.
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

AD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}\Z")   # \Z: sondaki satir sonu da reddedilir
EN_COK_VERITABANI = 20   # sure butcesi (toplam_sure) icinde kalsin diye toplayicidan dusuk
CIKTI_SINIRI = 2 * 1024 * 1024   # psql stdout; musterinin sectigi sunucu dusmanca olabilir, bellek sinirsiz buyumez
HATA_SINIRI = 64 * 1024
GUVENLI_AD = re.compile(r"^[0-9A-Za-z.:-]{1,255}\Z")   # baglanti dizgisine giren host/hostaddr: bosluk, tirnak, % ve = yok
CA_PEM_SINIRI = 16 * 1024   # musterinin yapistirdigi CA PEM'i icin ust sinir (zincir dahil)
CA_EN_COK_SERTIFIKA = 5
SSLROOTCERT_YOLU = re.compile(r"^/[0-9A-Za-z._/-]{1,255}\Z")   # dizgiye giren dosya yolu: bosluk, tirnak, ters bolu, = ve satir sonu yok
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
    """Musterinin verdigi CA PEM'ini dogrular ve normallestirilmis metni dondurur (yalniz sertifika bloklari, LF satir sonu).
    Ozel anahtar, baslikli blok, ek metin, NUL, ASCII disi, bozuk base64, cok buyuk ya da cok sertifikali girdi BaglantiHatasi('ca')."""
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
            raise BaglantiHatasi("ca")   # blok disi metin, baska PEM turu (ozel anahtar), baslik satiri, bozuk karakter
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
        if len(ham) < 16 or ham[0] != 0x30:   # DER SEQUENCE ile baslamayan govde sertifika degildir
            raise BaglantiHatasi("ca")
        cikti.append("\n".join([_PEM_BAS] + govde + [_PEM_SON]) + "\n")
    return "".join(cikti)


def baglanti_dizgisi(hedef, veritabani, kullanici, sslmode="require", sslrootcert=None):
    if not AD.match(veritabani or "") or not AD.match(kullanici or ""):
        raise BaglantiHatasi("bicim")
    if sslmode not in ("require", "verify-ca", "verify-full", "prefer"):
        raise BaglantiHatasi("bicim")
    # verify-* kok sertifikasiz kabul edilmez (libpq ev dizinindeki dosyaya duserdi); kok sertifika verify-* disinda sessizce yok sayilmaz
    if (sslrootcert is None) == (sslmode in ("verify-ca", "verify-full")):
        raise BaglantiHatasi("bicim")
    if sslrootcert is not None and not (isinstance(sslrootcert, str) and SSLROOTCERT_YOLU.match(sslrootcert)):
        raise BaglantiHatasi("bicim")
    # hedef nesnesi calistirici soketinden de gelir: dizgiye ek anahtar sokulamasin (hostaddr, options, sslmode...)
    if not (isinstance(hedef.ad, str) and GUVENLI_AD.match(hedef.ad) and isinstance(hedef.ip, str) and GUVENLI_AD.match(hedef.ip)
            and isinstance(hedef.port, int) and not isinstance(hedef.port, bool) and 1 <= hedef.port <= 65535):
        raise BaglantiHatasi("bicim")
    # channel_binding=require: sunucu SCRAM-SHA-256-PLUS ile TLS kanalina bagli kimlik dogrulamak zorunda. Boylece parola
    # duz metin ya da MD5 ile gonderilmez ve sertifikasi dogrulanamayan sunucuya karsi aktarma (MITM) saldirisi isleme girmez.
    kok = (" sslrootcert=" + sslrootcert) if sslrootcert is not None else ""
    return ("host=%s hostaddr=%s port=%d dbname=%s user=%s sslmode=%s%s channel_binding=require connect_timeout=10 gssencmode=disable"
            % (hedef.ad, hedef.ip, hedef.port, veritabani, kullanici, sslmode, kok))


def _ortam(parola):
    """Alt surece yalniz gerekenler verilir; servis ortami (tuzlar, anahtarlar, vekil ayarlari) devralinmaz."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "PGPASSWORD": parola,
            "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000",
            "PGAPPNAME": "alig-tarama", "PGCONNECT_TIMEOUT": "10", "PGPASSFILE": os.devnull, "PGSERVICEFILE": os.devnull,
            "PGSYSCONFDIR": os.devnull}


def _surec_calistir(cmd, env, sure):
    """(donus kodu, stdout, stderr). Sure asilirsa TimeoutError, stdout CIKTI_SINIRI'ni asarsa OverflowError; surec her
    durumda oldurulur. stderr HATA_SINIRI'ndan sonrasi atilir."""
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
                raise TimeoutError("sure doldu")
            for anahtar, _ in sec.select(kalan):
                parca = os.read(anahtar.fd, 65536)
                if not parca:
                    sec.unregister(anahtar.fileobj)
                    continue
                t = tampon[anahtar.data]
                t += parca
                if anahtar.data == "out" and len(t) > CIKTI_SINIRI:
                    raise OverflowError("cikti siniri")
                if anahtar.data == "err" and len(t) > HATA_SINIRI:
                    del t[HATA_SINIRI:]
        p.wait(timeout=max(0.1, bitis - time.monotonic()))
    except subprocess.TimeoutExpired:
        raise TimeoutError("sure doldu")
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
    """Sunucudan gelen satirlardan yalniz katalog kolonlari kalir."""
    return [{k: v for k, v in s.items() if k in c["kolonlar"]} for s in satirlar[:limit] if isinstance(s, dict)]


def _veritabanlari(psql, dizgi, parola, ilk_db, bitis):
    """(taranacak, atlanan). Liste alinamazsa yalniz ilk veritabani."""
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
    """Dogrulanmis toplama belgesini dondurur ya da BaglantiHatasi firlatir.

    Sunucu sertifikasi: varsayilan `sslmode=require` + `channel_binding=require` (sertifika denetlenmez). ca_pem verilirse
    (musterinin CA'si) sslmode=verify-full olur: zincir bu CA'ya ve sertifika `hedef.ad`'a karsi dogrulanir. CA gecersizse
    sessizce zayif moda dusulmez, BaglantiHatasi('ca') firlatilir. CA dosyasi 0600 gecici dizinde durur, is bitince silinir."""
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
        if sql is None:   # bu surumde olmayan ozellik: sorgu calismaz
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
        return yukleme.dogrula(belge)   # sunucudan gelen her deger guvenilmezdir
    except yukleme.Gecersiz:
        raise BaglantiHatasi("bicim")
