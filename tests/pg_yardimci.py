"""ALIG-CI-001: PostgreSQL entegrasyon testleri icin ortak gecici kume yardimcisi (yalniz standart kutuphane).

- pg_bul(): PostgreSQL ikilisini bulur; bulamazsa acik bir "yok" nedeni dondurur (test SKIP olur, PASS sayilmaz).
- GeciciKume: initdb, bos port, soket dizini, kimlik dogrulama secenegi, rol ve veritabani, durdurma ve silme.
  Surec SIGKILL ile bile olse artik dizin ve calisan sunucu kalmasin diye ayri oturumda bir bekci surec calisir.
- dis_hedef() / HedefTestleri: ALIG_TEST_PG_HOST verilmisse dis sunucu, verilmemisse gecici kume.
- pg_testi(): sinifi PostgreSQL testi olarak etiketler (ci/pg_adimi.py bunlari ayri sayar) ve kosul yoksa SKIP eder.

Yalniz sistem PostgreSQL ikilisi kullanilir (varsayilan /usr/lib/postgresql/16/bin); indirme yok.
"""
import atexit
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path

ONEK = "alig-pg-"
ADAY_DIZINLER = ("/usr/lib/postgresql/16/bin",)
GEREKLI = ("initdb", "pg_ctl", "psql", "postgres")
PAROLASIZ_KUR = "trust"

PgBulgu = namedtuple("PgBulgu", "dizin surum neden")
PgBulgu.var = property(lambda self: self.dizin is not None)


class PgYok(RuntimeError):
    """PostgreSQL ikilisi bulunamadi ya da kume kurulamadi."""


def _surum(dizin):
    try:
        r = subprocess.run([str(Path(dizin) / "postgres"), "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    import re
    m = re.search(r"(\d+(?:\.\d+)*)", r.stdout)
    return m.group(1) if m else None


def pg_bul(adaylar=None, ortam=None):
    """PgBulgu(dizin, surum, neden): dizin None ise neden okunur bir Turkce aciklamadir."""
    ortam = os.environ if ortam is None else ortam
    liste = []
    if ortam.get("ALIG_TEST_PG_BIN"):
        liste.append(ortam["ALIG_TEST_PG_BIN"])
    liste += list(ADAY_DIZINLER if adaylar is None else adaylar)
    eksikler = []
    for d in liste:
        eksik = [a for a in GEREKLI if not (Path(d) / a).is_file()]
        if eksik:
            eksikler.append("%s (eksik: %s)" % (d, ", ".join(eksik)))
            continue
        if os.geteuid() == 0:
            try:
                pwd.getpwnam("postgres")
            except KeyError:
                return PgBulgu(None, None, "root olarak calisiyor ama postgres kullanicisi yok (initdb root'ta calismaz)")
        return PgBulgu(str(d), _surum(d), "")
    return PgBulgu(None, None, "PostgreSQL ikilisi yok: initdb, pg_ctl, psql, postgres su dizinlerde aranadi: "
                   + ("; ".join(eksikler) if eksikler else "(aday dizin yok)"))


def _bos_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _postgres_olarak(argv):
    return ["runuser", "-u", "postgres", "--"] + list(argv) if os.geteuid() == 0 else list(argv)


# Bekci: ana surec (testler) olunce sunucuyu durdurur ve dizini siler. Ayri oturumda calisir, ana surecin sinyalinden etkilenmez.
_BEKCI = r"""
import os, shutil, subprocess, sys, time
ana, dizin, pgctl, veri = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
onek = sys.argv[5:]
def canli(p):
    try:
        os.kill(p, 0)
        with open("/proc/%d/stat" % p) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        return False
    except Exception:
        return True
while canli(ana):
    time.sleep(0.4)
if os.path.isdir(veri):
    try:
        subprocess.run(onek + [pgctl, "-D", veri, "-m", "immediate", "-w", "-t", "20", "stop"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)
    except Exception:
        pass
shutil.rmtree(dizin, ignore_errors=True)
"""


class GeciciKume:
    """Tek kullanimlik PostgreSQL kumesi. Unix soketi ve TCP kapali (listen_addresses bos); yalniz soket dizini.

    Varsayilan kimlik dogrulama trust'tir (kurulum icin, yalniz bu gecici kume); kimlik_dogrulama("scram-sha-256")
    ile degistirilir.
    """

    def __init__(self, bulgu=None, onek=ONEK):
        self.bulgu = bulgu if bulgu is not None else pg_bul()
        self.onek = onek
        self.dizin = self.veri = self.soket = None
        self.port = None
        self.calisiyor = False
        self._bekci = None
        self._atexit = None
        self._bitti = False

    # --- ozellikler ---
    @property
    def surum(self):
        return self.bulgu.surum or "bilinmiyor"

    def _ikili(self, ad):
        return str(Path(self.bulgu.dizin) / ad)

    def _calistir(self, argv, kontrol=True, timeout=60, girdi=None, env=None):
        return subprocess.run(_postgres_olarak(argv), capture_output=True, text=True, timeout=timeout,
                              input=girdi, check=kontrol, env=env)

    # --- yasam dongusu ---
    def baslat(self):
        if not self.bulgu.var:
            raise PgYok(self.bulgu.neden)
        self.dizin = tempfile.mkdtemp(prefix=self.onek)
        self._atexit = atexit.register(self.durdur)
        try:
            os.chmod(self.dizin, 0o755)
            if os.geteuid() == 0:
                pw = pwd.getpwnam("postgres")
                os.chown(self.dizin, pw.pw_uid, pw.pw_gid)
            self.veri = os.path.join(self.dizin, "veri")
            self.soket = os.path.join(self.dizin, "soket")
            os.mkdir(self.soket)
            if os.geteuid() == 0:
                os.chown(self.soket, pw.pw_uid, pw.pw_gid)
            self._bekci_baslat()
            self._calistir([self._ikili("initdb"), "-D", self.veri, "-A", PAROLASIZ_KUR, "-U", "postgres",
                            "--no-locale", "-E", "UTF8"], timeout=90)
            son = None
            for _ in range(3):   # bos port yarisi: baska surec ayni portu kaparsa yeni portla dene
                self.port = _bos_port()
                try:
                    self._calistir([self._ikili("pg_ctl"), "-D", self.veri, "-w", "-t", "30",
                                    "-l", os.path.join(self.dizin, "gunluk.txt"), "-o",
                                    "-p %d -k %s -c listen_addresses= -c fsync=off -c synchronous_commit=off "
                                    "-c full_page_writes=off" % (self.port, self.soket), "start"], timeout=60)
                    self.calisiyor = True
                    break
                except subprocess.CalledProcessError as e:
                    son = e
            if not self.calisiyor:
                raise PgYok("PostgreSQL kumesi baslatilamadi: %s" % ((son.stderr or "")[-300:] if son else ""))
        except BaseException:
            self.durdur()
            raise
        return self

    def _bekci_baslat(self):
        onek = _postgres_olarak([])
        self._bekci = subprocess.Popen(
            [sys.executable, "-I", "-c", _BEKCI, str(os.getpid()), self.dizin, self._ikili("pg_ctl"), self.veri] + onek,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def sunucuyu_durdur(self):
        """Yalniz sunucuyu hizlica durdurur (kesinti denemesi icin); dizin kalir."""
        if self.calisiyor:
            try:
                self._calistir([self._ikili("pg_ctl"), "-D", self.veri, "-m", "immediate", "-w", "-t", "30", "stop"])
            finally:
                self.calisiyor = False

    def durdur(self):
        """Sunucuyu durdurur, dizini siler, bekciyi kaldirir. Birden cok kez cagrilabilir."""
        if self.dizin is None or self._bitti:
            return
        self._bitti = True
        try:
            try:
                self.sunucuyu_durdur()
            except Exception:
                self.calisiyor = False
            shutil.rmtree(self.dizin, ignore_errors=True)
        finally:
            if self._bekci is not None:
                self._bekci.kill()
                self._bekci.wait()
                self._bekci = None
            if self._atexit is not None:
                atexit.unregister(self.durdur)
                self._atexit = None

    # --- baglanti ve SQL ---
    def ortam(self, db="postgres", kullanici="postgres", parola=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        e.update(PATH="%s:%s" % (self.bulgu.dizin, e.get("PATH", "")), PGHOST=self.soket, PGPORT=str(self.port),
                 PGDATABASE=db, PGUSER=kullanici, PGCONNECT_TIMEOUT="10")
        if parola is not None:
            e["PGPASSWORD"] = parola
        return e

    def sql(self, sorgu, db="postgres", kullanici="postgres", parola=None):
        """Tek bir SQL metnini psql ile calistirir (yalniz sabit kurulum metinleri; degisken deger sql_degeri ile kacislanir)."""
        r = self._calistir([self._ikili("psql"), "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                           girdi=sorgu, env=self.ortam(db, kullanici, parola), timeout=60)
        return r.stdout.strip()

    @staticmethod
    def _kimlik(ad):
        return '"%s"' % ad.replace('"', '""')

    @staticmethod
    def _deger(metin):
        return "'%s'" % metin.replace("'", "''")

    def rol_olustur(self, ad, parola=None, secenekler="LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"):
        s = "CREATE ROLE %s %s" % (self._kimlik(ad), secenekler)
        if parola is not None:
            s += " PASSWORD %s" % self._deger(parola)
        self.sql(s)

    def veritabani_olustur(self, ad, sahip=None):
        s = "CREATE DATABASE %s" % self._kimlik(ad)
        if sahip:
            s += " OWNER %s" % self._kimlik(sahip)
        self.sql(s)

    def kimlik_dogrulama(self, yontem="scram-sha-256"):
        """Yerel (Unix soketi) baglantilar icin pg_hba.conf'u yazar ve yeniden yukler: 'trust' ya da 'scram-sha-256'."""
        if yontem not in ("trust", "scram-sha-256", "md5", "password"):
            raise ValueError("bilinmeyen kimlik dogrulama yontemi: %r" % yontem)
        hba = Path(self.veri) / "pg_hba.conf"
        hba.write_text("local all all %s\n" % yontem, encoding="utf-8")   # root yazarsa dosya sahibi (postgres) korunur
        self._calistir([self._ikili("pg_ctl"), "-D", self.veri, "reload"])


# ---------------------------------------------------------------- testler icin

class DisHedef(namedtuple("DisHedef", "host port kullanici")):
    pass


def dis_hedef(ortam=None):
    """ALIG_TEST_PG_HOST verilmisse dis sunucu bilgisi (host/soket dizini, port, kullanici); yoksa None."""
    ortam = os.environ if ortam is None else ortam
    host = ortam.get("ALIG_TEST_PG_HOST")
    if not host:
        return None
    return DisHedef(host, ortam.get("ALIG_TEST_PG_PORT", "5432"), ortam.get("ALIG_TEST_PG_USER", "alig_hc"))


def pg_testi(kosul=True, neden=""):
    """Sinifi PostgreSQL testi olarak etiketler; kosul yoksa SKIP eder (PASS sayilmaz)."""
    def dekor(sinif):
        sinif.PG_TESTI = True
        return unittest.skipUnless(kosul, neden or "PostgreSQL yok")(sinif)
    return dekor


def dis_veya_gecici_var():
    """(var mi, yoksa neden) - ALIG_TEST_PG_HOST ya da sistem PostgreSQL ikilisi."""
    if dis_hedef():
        return True, ""
    b = pg_bul()
    return b.var, b.neden


ALIG_HC_KURULUM = (
    "CREATE ROLE alig_hc LOGIN",
    "GRANT pg_monitor TO alig_hc",
    "ALTER ROLE alig_hc SET default_transaction_read_only = on",
)


def hedef_hazirla(sinif, kurulum=ALIG_HC_KURULUM):
    """setUpClass icinde: dis sunucu (ALIG_TEST_PG_HOST) ya da gecici kume (alig_hc rolu, trust, yalniz soket).
    sinif.pg_host, pg_port, pg_kullanici atanir; temizlik sinif temizligine eklenir. Surumu dondurur."""
    d = dis_hedef()
    if d:
        sinif.pg_host, sinif.pg_port, sinif.pg_kullanici = d.host, d.port, d.kullanici
        return None
    k = GeciciKume()
    k.baslat()
    sinif.addClassCleanup(k.durdur)
    for s in kurulum:
        k.sql(s)
    sinif.pg_kume = k
    sinif.pg_host, sinif.pg_port, sinif.pg_kullanici = k.soket, str(k.port), "alig_hc"
    return k.surum
