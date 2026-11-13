#!/usr/bin/env python3
"""Surum dogrulamasi: sitedeki toplayiciyi gercek bir PostgreSQL sunucusunda ve akisli yedeginde calistirir, sonucu kaydeder.

Gecici bir kume kurar (initdb), senaryo nesneleri olusturur, pg_basebackup ile akisli bir yedek sunucu baslatir ve
toplayiciyi su hesaplarla calistirir:
  pg_monitor  alig-rol.sql'deki gibi yalniz pg_monitor uyesi rol (onerilen tarama hesabi)
  yetkisiz    hicbir ek yetkisi olmayan rol
  super       kurulum super kullanicisi
  yedek       pg_monitor rolu, yedek sunucuda (yedekte calisan sorgularin kaniti)
Senaryo: gecersiz indeks, etkin olmayan replikasyon slotu (birincilde ve yedekte), olu satir ve autovacuum'u kapatilmis
tablo, sinira yakin sequence, bosta acik islem, MD5 parolali rol, baglanma yetkisi olmayan veritabani, PUBLIC'e CREATE
verilmis public semasi, gecici dosyaya yazan siralama, yeniden oynatmasi duraklatilmis (geride kalan) replika; pakette
varsa pg_stat_statements yuklenir. Her denetimin durumu (ok ya da atlandi ve nedeni), satir ve bos deger sayisi kaydedilir;
kumeler sonunda silinir. Yalniz kendi kurdugu gecici kumelere dokunur.

  python3 tarama/surum_dogrula.py --pg-bin /usr/lib/postgresql/16/bin --cikti docs/surum-dogrulama.json \
      --belge-dizini tests/veri/surum

--belge-dizini verilirse toplanan ham belgeler <dizin>/<ana surum>/<hesap>.json olarak yazilir; testler bunlari gercek
sunucu ciktisi olarak kullanir (yalniz senaryo nesneleri, musteri verisi yok).

Root olarak calismaz (initdb izin vermez). Sonuc docs/surum-matrisi.md belgesine girer (tarama/uret_kurallar.py).
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import katalog, yukleme  # noqa: E402
from tarama.uret_toplayici import katalog_ozeti  # noqa: E402

TOPLAYICI = ROOT / "site" / "assets" / "alig-toplayici.py"
KURUCU = "alig_kurulum"
HESAPLAR = {"pg_monitor": "alig_hc", "yetkisiz": "alig_duz", "super": KURUCU}   # birincil sunucuda
YEDEK_HESABI = ("yedek", "alig_hc")                                              # yedek sunucuda

KURULUM = [
    "CREATE ROLE alig_hc LOGIN",
    "GRANT pg_monitor TO alig_hc",
    "ALTER ROLE alig_hc SET default_transaction_read_only = on",
    "CREATE ROLE alig_duz LOGIN",
    "SET password_encryption = 'md5'; CREATE ROLE eski_md5 LOGIN PASSWORD 'alig-deneme-md5'",
    'CREATE DATABASE "satis db"',
    "CREATE DATABASE gizli",
    "REVOKE CONNECT ON DATABASE gizli FROM PUBLIC",
    "SELECT pg_create_physical_replication_slot('bos_slot', true)",
]
VERITABANI = [   # postgres ve "satis db" icinde
    "CREATE TABLE olu (i int) WITH (autovacuum_enabled = false)",
    "INSERT INTO olu SELECT generate_series(1, 30000)",
    "DELETE FROM olu",
    "CREATE TABLE cift (x int)",
    "INSERT INTO cift VALUES (1), (1)",
    "CREATE TABLE buyuk (i int)",
    "INSERT INTO buyuk SELECT generate_series(1, 700000)",
    "CREATE INDEX buyuk_i ON buyuk (i)",   # 10 MB ustu, hic taranmamis indeks
    "CREATE SEQUENCE yakin_seq MAXVALUE 100",
    "SELECT setval('yakin_seq', 99)",
]
GECERSIZ_INDEKS = "CREATE UNIQUE INDEX CONCURRENTLY cift_x ON cift (x)"   # yinelenen deger yuzunden basarisiz olur, gecersiz kalir
GECICI_DOSYA = "SET work_mem = '64kB'; SELECT count(*) FROM (SELECT i FROM buyuk ORDER BY i + 0 DESC) s"   # ifade indeksi kullanmaz


def _bos_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _calistir(komut, beklenen_hata=False, **kw):
    r = subprocess.run(komut, capture_output=True, text=True, timeout=180, **kw)
    if (r.returncode != 0) != beklenen_hata:
        raise SystemExit("komut %s: %s\n%s" % ("basarili oldu" if beklenen_hata else "basarisiz", " ".join(map(str, komut)), r.stderr[-2000:]))
    return r.stdout


def _pss_var(pg_bin):
    """pg_stat_statements kutuphanesi bu PostgreSQL paketinde var mi (contrib)?"""
    try:
        lib = subprocess.run([str(Path(pg_bin) / "pg_config"), "--pkglibdir"], capture_output=True, text=True, timeout=30).stdout.strip()
    except OSError:
        lib = ""
    return any((Path(d) / "pg_stat_statements.so").exists() for d in (lib, Path(pg_bin).parent / "lib") if d)


class Kume:
    """Gecici PostgreSQL kumesi: yalniz unix soketi, rastgele port. Birincil ve ondan alinan akisli yedek."""

    def __init__(self, pg_bin, psql):
        self.bin, self.psql = Path(pg_bin), psql
        self.dizin = Path(tempfile.mkdtemp(prefix="alig-surum-"))
        self.veri, self.soket, self.port = self.dizin / "veri", self.dizin / "soket", _bos_port()
        self.yveri, self.ysoket, self.yport = self.dizin / "yedek", self.dizin / "ysoket", _bos_port()
        self.soket.mkdir()
        self.ysoket.mkdir()
        self.pss = _pss_var(pg_bin)
        self.ortak = " -c shared_preload_libraries=pg_stat_statements" if self.pss else ""

    def kur(self):
        _calistir([str(self.bin / "initdb"), "-D", str(self.veri), "-U", KURUCU, "--auth=trust", "-E", "UTF8", "--no-locale"])
        _calistir([str(self.bin / "pg_ctl"), "-D", str(self.veri), "-l", str(self.dizin / "gunluk"), "-w", "start",
                   "-o", "-k %s -p %d -c listen_addresses='' -c wal_level=replica -c max_replication_slots=4%s" % (self.soket, self.port, self.ortak)])

    def yedek_kur(self):
        """Akisli yedek: pg_basebackup -R, ayri soket ve port. Akisa gecene kadar bekler."""
        _calistir([str(self.bin / "pg_basebackup"), "-h", str(self.soket), "-p", str(self.port), "-U", KURUCU, "-D", str(self.yveri),
                   "-R", "-X", "stream", "--checkpoint=fast"])   # yayilmis denetim noktasi dakikalar surebilir
        _calistir([str(self.bin / "pg_ctl"), "-D", str(self.yveri), "-l", str(self.dizin / "ygunluk"), "-w", "start",
                   "-o", "-k %s -p %d -c listen_addresses=''%s" % (self.ysoket, self.yport, self.ortak)])
        for _ in range(150):
            if self.sql("SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'") == "1":
                return
            time.sleep(0.2)
        raise SystemExit("yedek sunucu akisa gecmedi")

    def sql(self, sql, db="postgres", beklenen_hata=False, yedek=False):
        soket, port = (self.ysoket, self.yport) if yedek else (self.soket, self.port)
        return _calistir([self.psql, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", str(soket), "-p", str(port),
                          "-U", KURUCU, "-d", db, "-c", sql], beklenen_hata=beklenen_hata).strip()

    def kapat(self):
        for veri in (self.yveri, self.veri):
            if veri.exists():
                subprocess.run([str(self.bin / "pg_ctl"), "-D", str(veri), "-m", "immediate", "stop"], capture_output=True, timeout=60)
        shutil.rmtree(self.dizin, ignore_errors=True)


def senaryo(k):
    for s in KURULUM:
        k.sql(s)
    for db in ("postgres", "satis db"):
        for s in VERITABANI:
            k.sql(s, db)
        k.sql(GECERSIZ_INDEKS, db, beklenen_hata=True)
    k.sql("GRANT CREATE ON SCHEMA public TO PUBLIC", "satis db")
    if k.pss:
        k.sql("CREATE EXTENSION pg_stat_statements")
    k.sql(GECICI_DOSYA)


def yedek_senaryosu(k):
    """Yedekte etkin olmayan slot; yeniden oynatma duraklatilir, birincilde WAL uretilir: replika geride kalir."""
    k.yedek_kur()
    k.sql("SELECT pg_create_physical_replication_slot('yedek_slot', true)", yedek=True)
    k.sql("SELECT pg_wal_replay_pause()", yedek=True)
    k.sql("CREATE TABLE gecikme AS SELECT generate_series(1, 100000) AS i")
    for _ in range(50):   # geride kalma birincilde gorunene kadar
        if k.sql("SELECT coalesce(max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)), 0) > 0 FROM pg_stat_replication") == "t":
            return
        time.sleep(0.2)
    raise SystemExit("yedek geride kalmadi")


def bosta_islem(k):
    """Kurulum hesabiyla bosta bekleyen acik islem: BEGIN, SELECT, sonra kabuk beklemesi (oturum islemde bekler)."""
    p = subprocess.Popen([k.psql, "-X", "-q", "-h", str(k.soket), "-p", str(k.port), "-U", KURUCU, "-d", "postgres"],
                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                         start_new_session=True)   # sonunda kabugun sleep sureciyle birlikte kapatilir (_kapat)
    p.stdin.write("BEGIN;\nSELECT 1;\n\\! sleep 300\n")
    p.stdin.flush()
    for _ in range(50):
        if k.sql("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'") != "0":
            return p
        time.sleep(0.1)
    _kapat(p)
    raise SystemExit("bosta islem olusmadi")


def _kapat(p):
    """psql ve \\! ile baslattigi kabuk: ayni oturum grubundalar, hepsi kapatilir."""
    try:
        os.killpg(p.pid, 9)
    except OSError:
        p.kill()


def topla(k, hesap, kullanici, yedek=False):
    cikti = k.dizin / ("%s.json" % hesap)
    soket, port = (k.ysoket, k.yport) if yedek else (k.soket, k.port)
    _calistir([sys.executable, str(TOPLAYICI), "--host", str(soket), "--port", str(port), "--user", kullanici,
               "--dbname", "postgres", "--out", str(cikti)])
    return yukleme.coz(cikti.read_bytes())


def ozetle(belge):
    """Denetim basina durum, satir ve bos deger sayisi; ad tasimayan tek satirli denetimde degerler de (hesaplar arasi
    karsilastirma). Bos deger sayisi, satiri gorup degerini goremeyen hesabi ayirir (ornegin pg_stat_replication)."""
    kontroller = {}
    for cid, e in sorted(belge["kontroller"].items()):
        if e["durum"] == "ok":
            kontroller[cid] = {"durum": "ok", "satir": len(e["satirlar"]), "atlanan": len(e.get("atlanan") or []),
                               "bos": sum(1 for s in e["satirlar"] for v in s.values() if v is None)}
            if len(e["satirlar"]) == 1 and not katalog.PG_BY_ID[cid]["maske"]:
                kontroller[cid]["deger"] = e["satirlar"][0]
        else:
            kontroller[cid] = {"durum": "hata", "neden": e["neden"]}
    return {"kontroller": kontroller}


def dogrula(pg_bin, psql):
    """(ana surum, ozet, {hesap: ham belge})."""
    k = Kume(pg_bin, psql)
    p = None
    try:
        k.kur()
        tam = k.sql("SELECT version()")
        senaryo(k)
        time.sleep(1.5)   # PostgreSQL 14 ve oncesinde istatistik toplayicisinin yazmasi icin
        yedek_senaryosu(k)
        p = bosta_islem(k)
        belgeler = {h: topla(k, h, kullanici) for h, kullanici in HESAPLAR.items()}
        belgeler[YEDEK_HESABI[0]] = topla(k, YEDEK_HESABI[0], YEDEK_HESABI[1], yedek=True)
        ana = int(k.sql("SHOW server_version_num")) // 10000
    finally:
        if p:
            _kapat(p)
        k.kapat()
    return ana, {"tam_surum": tam, "tarih": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "katalog_sha256": katalog_ozeti(),
                 "hesaplar": {h: ozetle(b) for h, b in belgeler.items()}}, belgeler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pg-bin", action="append", required=True, help="initdb, pg_ctl ve postgres dizini (birden cok verilebilir)")
    ap.add_argument("--psql", default=shutil.which("psql") or "psql")
    ap.add_argument("--cikti", default="-", help="sonuc JSON dosyasi (var olan dosyaya eklenir) ya da - (standart cikti)")
    ap.add_argument("--belge-dizini", help="ham belgelerin yazilacagi dizin (<dizin>/<ana surum>/<hesap>.json)")
    a = ap.parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("hata: root olarak calismaz (initdb izin vermez); ayri bir kullaniciyla calistirin", file=sys.stderr)
        return 2
    kayit = {"surumler": {}}
    if a.cikti != "-" and Path(a.cikti).exists():
        kayit = json.loads(Path(a.cikti).read_text(encoding="utf-8"))
    for b in a.pg_bin:
        ana, sonuc, belgeler = dogrula(b, a.psql)
        kayit["surumler"][str(ana)] = sonuc
        if a.belge_dizini:
            d = Path(a.belge_dizini) / str(ana)
            d.mkdir(parents=True, exist_ok=True)
            for h, belge in belgeler.items():
                (d / ("%s.json" % h)).write_text(json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        print("PostgreSQL %d: %s" % (ana, sonuc["tam_surum"]), file=sys.stderr)
    metin = json.dumps(kayit, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if a.cikti == "-":
        sys.stdout.write(metin)
    else:
        Path(a.cikti).write_text(metin, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
