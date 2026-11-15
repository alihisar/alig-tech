"""Kip B sunucu sertifikasi dogrulamasi: gercek PostgreSQL 16 + TLS ve gecici kendinden imzali CA ile (openssl CLI).
PostgreSQL 16 ya da openssl yoksa SKIP. PG18 icin sayilmaz."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import baglanti, hedef  # noqa: E402

PG_BIN = Path("/usr/lib/postgresql/16/bin")
PG_VAR = all((PG_BIN / x).exists() for x in ("initdb", "pg_ctl", "psql"))
OPENSSL = shutil.which("openssl")
KANIT = "0123456789abcdef0123456789abcdef"
PAROLA = "Tls-Deneme-Parola-7"


def _komut(args, **k):
    if os.geteuid() == 0 and k.pop("postgres", False):
        args = ["runuser", "-u", "postgres", "--"] + list(args)
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60, **k)


def _bos_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _ca_uret(dizin, ad):
    """(ca.crt yolu, ca.key yolu): kendinden imzali CA."""
    crt, key = str(dizin / (ad + ".crt")), str(dizin / (ad + ".key"))
    _komut([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-subj", "/CN=alig test CA " + ad,
            "-days", "2", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign"])
    return crt, key


@unittest.skipUnless(PG_VAR and OPENSSL, "PostgreSQL 16 ya da openssl yok")
class SertifikaDogrulamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dizin = tempfile.mkdtemp(prefix="alig-pg-")
        cls.calisiyor = False
        try:
            os.chmod(cls.dizin, 0o755)
            if os.geteuid() == 0:
                import pwd
                pw = pwd.getpwnam("postgres")
                os.chown(cls.dizin, pw.pw_uid, pw.pw_gid)
            d = Path(cls.dizin)
            tls = d / "tls"
            tls.mkdir()
            cls.ca, ca_anahtar = _ca_uret(tls, "ca1")
            cls.yabanci_ca, _ = _ca_uret(tls, "ca2")
            sk, sc, ek = str(tls / "server.key"), str(tls / "server.crt"), tls / "san.cnf"
            ek.write_text("subjectAltName=DNS:localhost\nbasicConstraints=CA:FALSE\n", encoding="ascii")
            _komut([OPENSSL, "req", "-newkey", "rsa:2048", "-nodes", "-keyout", sk, "-out", str(tls / "server.csr"), "-subj", "/CN=localhost"])
            _komut([OPENSSL, "x509", "-req", "-in", str(tls / "server.csr"), "-CA", cls.ca, "-CAkey", ca_anahtar, "-CAcreateserial",
                    "-out", sc, "-days", "2", "-extfile", str(ek)])
            os.chmod(sk, 0o600)
            if os.geteuid() == 0:
                for yol in (tls, sk, sc):
                    os.chown(str(yol), pw.pw_uid, pw.pw_gid)
            cls.veri, cls.port = str(d / "veri"), _bos_port()
            _komut([str(PG_BIN / "initdb"), "-D", cls.veri, "-A", "trust", "-U", "postgres", "--no-locale", "-E", "UTF8"], postgres=True)
            secenek = ("-c listen_addresses=127.0.0.1 -c unix_socket_directories=%s -p %d -c fsync=off -c ssl=on -c ssl_cert_file=%s -c ssl_key_file=%s"
                       % (cls.dizin, cls.port, sc, sk))
            _komut([str(PG_BIN / "pg_ctl"), "-D", cls.veri, "-o", secenek, "-w", "-t", "30", "-l", str(d / "pg.log"), "start"], postgres=True)
            cls.calisiyor = True
            psql = [str(PG_BIN / "psql"), "-h", cls.dizin, "-p", str(cls.port), "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-q", "-c"]
            _komut(psql + ["CREATE ROLE alig_hc LOGIN NOSUPERUSER PASSWORD '%s'" % PAROLA], postgres=True)
            _komut(psql + ["COMMENT ON ROLE alig_hc IS '%s'" % baglanti.kanit_metni(KANIT)], postgres=True)
            Path(cls.veri, "pg_hba.conf").write_text("local all postgres trust\nhostssl all alig_hc 127.0.0.1/32 scram-sha-256\n", encoding="ascii")
            _komut([str(PG_BIN / "pg_ctl"), "-D", cls.veri, "reload"], postgres=True)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        if cls.calisiyor:
            subprocess.run((["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []) + [str(PG_BIN / "pg_ctl"), "-D", cls.veri, "-m", "immediate", "-w", "stop"],
                           capture_output=True, timeout=60)
            cls.calisiyor = False
        shutil.rmtree(cls.dizin, ignore_errors=True)

    def tara(self, ad="localhost", ca=None, **k):
        h = hedef.Hedef(ad, "127.0.0.1", self.port)
        pem = Path(ca).read_text(encoding="ascii") if ca else None
        return baglanti.tara(h, "postgres", "alig_hc", k.pop("parola", PAROLA), KANIT, psql=str(PG_BIN / "psql"), ca_pem=pem, toplam_sure=60, **k)

    def kod(self, **k):
        try:
            self.tara(**k)
        except baglanti.BaglantiHatasi as e:
            return e.kod
        return None

    def test_dogru_ca_ve_ad_ile_verify_full_basarili(self):
        belge = self.tara(ca=self.ca)
        self.assertEqual(belge["motor"], "postgresql")

    def test_yabanci_ca_ile_basarisiz(self):
        self.assertEqual(self.kod(ca=self.yabanci_ca), "baglanti")

    def test_sunucu_adi_sertifikayla_uyusmazsa_basarisiz(self):
        self.assertEqual(self.kod(ad="baska.ornek.com", ca=self.ca), "baglanti")

    def test_ayni_istek_ca_olmadan_mevcut_varsayilanla_baglanir(self):
        """Varsayilan (sslmode=require + channel_binding=require) degismedi: sertifika denetlenmez ama TLS ve SCRAM zorunlu."""
        self.assertEqual(self.tara(ad="baska.ornek.com")["motor"], "postgresql")

    def test_yanlis_parola_ca_ile_de_basarisiz(self):
        self.assertEqual(self.kod(ca=self.ca, parola="yanlis-parola"), "baglanti")

    def test_gecici_ca_dosyasi_birakilmaz(self):
        once = set(Path(tempfile.gettempdir()).glob("alig-ca-*"))
        self.tara(ca=self.ca)
        self.kod(ca=self.yabanci_ca)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("alig-ca-*")), once)


if __name__ == "__main__":
    unittest.main()
