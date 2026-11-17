#!/usr/bin/env python3
"""Read-only monitoring list (ALIG-OPS-001). stdlib only. 0 = no critical finding, 1 = at least one CRIT.

  python3 deploy/izle.py --veri /var/lib/alig --yedek /var/backups/alig [--taban http://127.0.0.1:8081]
                         [--sertifika-ad alig.tech] [--json]

The checks (the KONTROLLER table): health endpoint, disk, outbox backlog, pending requests, audit chain verification,
backup age, certificate expiry. Every check only reads: databases are opened with mode=ro (no migration, no WAL switch,
nothing written), directories and files are only listed, the health endpoint gets GET requests, the certificate is only
read from the TLS handshake. Nothing on a customer system is touched.

There is no alert channel. The output is only a log (stdout, one line per check plus a summary line); the systemd unit
sends it to the journal. A channel is connected outside this file (alig-uyari.service, docs/runbook.md "Monitoring").

Status: OK, WARN, CRIT, UNKNOWN (could not be read, never reported as OK), SKIP (not configured). Only CRIT changes the
exit code; WARN and UNKNOWN are visible in the log without triggering alig-uyari.service every 5 minutes.
All thresholds are defaults (Ayar), changeable by flag; they are starting points, not agreed service levels.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import ssl
import socket
import sys
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from urllib.parse import quote, urlparse

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
from tarama import depo  # noqa: E402  (only denetim_durum / denetim_anahtari are used; baglan() would migrate)

BICIM = "%Y-%m-%dT%H:%M:%SZ"
VERITABANLARI = ("form", "tarama", "yonetim")
SAGLIK_YOLLARI = ("/healthz", "/api/tarama/saglik")

Sonuc = namedtuple("Sonuc", "ad durum ayrinti")


def sertifika_bitisi(host, port, ad, zaman_asimi=5):
    """notAfter (epoch seconds) of the certificate the server presents for the name; the chain and name are verified."""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=zaman_asimi) as ham:
        with ctx.wrap_socket(ham, server_hostname=ad) as s:
            return not_after_saniye(s.getpeercert()["notAfter"])


def not_after_saniye(metin):
    return ssl.cert_time_to_seconds(metin)


@dataclass
class Ayar:
    veri: str
    yedek: str
    taban: str = ""                    # health endpoint base URL; empty = check skipped
    sertifika_ad: str = ""             # TLS server name; empty = check skipped
    sertifika_host: str = "127.0.0.1"
    sertifika_port: int = 443
    ortam: dict = None                 # environment (audit key); None = os.environ
    disk_kullanim: object = shutil.disk_usage
    sertifika_oku: object = sertifika_bitisi
    disk_uyari: float = 0.15           # free fraction below which: WARN
    disk_kritik: float = 0.05
    posta_adet: int = 20               # pending outbox messages at which: WARN
    posta_yas_dk: int = 60             # age of the oldest pending message at which: WARN
    talep_yas_gun: int = 3             # age of the oldest open request at which: WARN
    yedek_uyari_saat: int = 36         # daily job at 02:17 UTC: one missed run is WARN, three is CRIT
    yedek_kritik_saat: int = 72
    sertifika_uyari_gun: int = 21
    sertifika_kritik_gun: int = 7
    zaman_asimi: float = 5.0

    def ortam_al(self):
        return os.environ if self.ortam is None else self.ortam


# ---------------------------------------------------------------- helpers
def ro_ac(yol):
    """Read-only connection or None if the file is missing. Raises sqlite3.Error if it cannot be opened.
    A WAL database opened with mode=ro still creates the -shm/-wal side files when no process has it open, which would put new
    files in the data directory (and fails on a read-only mount). When neither side file exists nobody has the database
    open, so it is opened immutable (no locks, no side files); otherwise mode=ro attaches to the running service's files."""
    if not Path(yol).is_file():
        return None
    p = str(yol)
    canli = os.path.exists(p + "-wal") or os.path.exists(p + "-shm")
    con = sqlite3.connect("file:%s?%s" % (quote(p), "mode=ro" if canli else "mode=ro&immutable=1"), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def _zaman(metin):
    return datetime.strptime(metin, BICIM).replace(tzinfo=timezone.utc)


def _yas(metin, simdi):
    return simdi - _zaman(metin)


def _gun(td):
    return td.total_seconds() / 86400


def _birlestir(ad, parcalar):
    """parcalar: [(durum, metin)]. Worst status wins; the text lists every part."""
    sira = {"OK": 0, "UNKNOWN": 1, "WARN": 2, "CRIT": 3}
    en_kotu = max((d for d, _ in parcalar), key=lambda d: sira[d])
    return Sonuc(ad, en_kotu, "; ".join(m for _, m in parcalar))


# ---------------------------------------------------------------- checks
def kontrol_saglik(a, simdi):
    if not a.taban:
        return Sonuc("health", "SKIP", "no --taban given")
    u = urlparse(a.taban)
    if u.scheme not in ("http", "https") or not u.hostname:
        return Sonuc("health", "UNKNOWN", "invalid --taban")
    cls = HTTPSConnection if u.scheme == "https" else HTTPConnection
    parcalar = []
    for yol in SAGLIK_YOLLARI:
        try:
            c = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=a.zaman_asimi)
            try:
                c.request("GET", yol)
                r = c.getresponse()
                govde = r.read(64).decode("utf-8", "replace").strip()
            finally:
                c.close()
        except (OSError, ValueError) as ex:
            parcalar.append(("CRIT", "%s unreachable (%s)" % (yol, type(ex).__name__)))
            continue
        if r.status != 200 or govde != "ok":
            parcalar.append(("CRIT", "%s answered %d %r" % (yol, r.status, govde[:20])))
        else:
            parcalar.append(("OK", "%s ok" % yol))
    return _birlestir("health", parcalar)


def kontrol_disk(a, simdi):
    parcalar = []
    for yol in (a.veri, a.yedek):
        try:
            d = a.disk_kullanim(str(yol))
        except OSError as ex:
            parcalar.append(("UNKNOWN", "%s unreadable (%s)" % (yol, type(ex).__name__)))
            continue
        oran = d.free / d.total if d.total else 0.0
        durum = "CRIT" if oran < a.disk_kritik else "WARN" if oran < a.disk_uyari else "OK"
        parcalar.append((durum, "%s %d%% free (%d MB)" % (yol, round(100 * oran), d.free >> 20)))
    return _birlestir("disk", parcalar)


def kontrol_posta(a, simdi):
    try:
        con = ro_ac(Path(a.veri) / "tarama.sqlite")
        if con is None:
            return Sonuc("outbox", "UNKNOWN", "tarama.sqlite not found")
        try:
            bekleyen, en_eski = con.execute("SELECT count(*), min(olusturma_utc) FROM posta WHERE durum='bekliyor'").fetchone()
            basarisiz = con.execute("SELECT count(*) FROM posta WHERE durum='basarisiz'").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as ex:
        return Sonuc("outbox", "UNKNOWN", "unreadable (%s)" % type(ex).__name__)
    yas_dk = int(_yas(en_eski, simdi).total_seconds() // 60) if en_eski else 0
    durum = "WARN" if bekleyen >= a.posta_adet or (bekleyen and yas_dk >= a.posta_yas_dk) else "OK"
    return Sonuc("outbox", durum, "pending %d (oldest %d min), failed %d" % (bekleyen, max(yas_dk, 0), basarisiz))


def kontrol_talepler(a, simdi):
    veri = Path(a.veri)
    parcalar = []
    try:
        y, f = ro_ac(veri / "yonetim.sqlite"), ro_ac(veri / "form.sqlite")
    except sqlite3.Error as ex:
        return Sonuc("pending_requests", "UNKNOWN", "unreadable (%s)" % type(ex).__name__)
    try:
        if y is None or f is None:
            parcalar.append(("UNKNOWN", "contact requests unknown: %s missing" % ("yonetim.sqlite" if y is None else "form.sqlite")))
        else:
            kapali = {r[0] for r in y.execute("SELECT talep_id FROM talep_durum WHERE durum='kapandi'")}
            acik = [r[1] for r in f.execute("SELECT id, created_utc FROM contact") if r[0] not in kapali]
            parcalar.append(_talep_parca("contact", acik, a, simdi))
    except sqlite3.Error as ex:
        parcalar.append(("UNKNOWN", "contact requests unreadable (%s)" % type(ex).__name__))
    finally:
        for c in (y, f):
            if c is not None:
                c.close()
    try:
        t = ro_ac(veri / "tarama.sqlite")
        if t is None:
            parcalar.append(("UNKNOWN", "portal requests unknown: tarama.sqlite missing"))
        else:
            try:
                acik = [r[0] for r in t.execute("SELECT olusturma_utc FROM portal_talep WHERE durum IN ('yeni','inceleniyor')")]
            finally:
                t.close()
            parcalar.append(_talep_parca("portal", acik, a, simdi))
    except sqlite3.Error as ex:
        parcalar.append(("UNKNOWN", "portal requests unreadable (%s)" % type(ex).__name__))
    return _birlestir("pending_requests", parcalar)


def _talep_parca(ad, zamanlar, a, simdi):
    en_eski = max((_gun(_yas(z, simdi)) for z in zamanlar), default=0)
    durum = "WARN" if zamanlar and en_eski >= a.talep_yas_gun else "OK"
    return durum, "%s %d (oldest %d d)" % (ad, len(zamanlar), int(max(en_eski, 0)))


def kontrol_denetim(a, simdi):
    try:
        anahtar = depo.denetim_anahtari(a.ortam_al())
    except depo.AnahtarHatasi as ex:
        return Sonuc("audit_chain", "UNKNOWN", str(ex))
    parcalar = []
    for ad in ("tarama", "yonetim"):
        try:
            con = ro_ac(Path(a.veri) / (ad + ".sqlite"))
            if con is None:
                parcalar.append(("UNKNOWN", "%s: database not found" % ad))
                continue
            try:
                d = depo.denetim_durum(con, anahtar)
            finally:
                con.close()
        except sqlite3.Error as ex:
            parcalar.append(("UNKNOWN", "%s: unreadable (%s)" % (ad, type(ex).__name__)))
            continue
        if d["bozuk"] is not None:
            parcalar.append(("CRIT", "%s: chain broken at record #%d" % (ad, d["bozuk"])))
        elif d["dogrulanamayan"]:
            parcalar.append(("WARN", "%s: %d keyed records not verified, audit key missing" % (ad, d["dogrulanamayan"])))
        else:
            parcalar.append(("OK", "%s: %d records intact" % (ad, d["kayit"])))
    return _birlestir("audit_chain", parcalar)


YEDEK_AD = re.compile(r"^(?P<ad>[a-z]+)-(?P<z>\d{8}T\d{6}Z)\.sqlite$")


def kontrol_yedek(a, simdi):
    beklenen = [ad for ad in VERITABANLARI if (Path(a.veri) / (ad + ".sqlite")).is_file()]
    if not beklenen:
        return Sonuc("backup_age", "UNKNOWN", "no database found in the data directory")
    try:
        dosyalar = [p.name for p in Path(a.yedek).iterdir()]
    except OSError as ex:
        return Sonuc("backup_age", "UNKNOWN", "backup directory unreadable (%s)" % type(ex).__name__)
    en_yeni = {}
    for ad in dosyalar:
        m = YEDEK_AD.match(ad)
        if m:
            z = datetime.strptime(m["z"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            en_yeni[m["ad"]] = max(en_yeni.get(m["ad"], z), z)
    parcalar = []
    for ad in beklenen:
        if ad not in en_yeni:
            parcalar.append(("CRIT", "%s: no backup" % ad))
            continue
        saat = (simdi - en_yeni[ad]).total_seconds() / 3600
        durum = "CRIT" if saat >= a.yedek_kritik_saat else "WARN" if saat >= a.yedek_uyari_saat else "OK"
        parcalar.append((durum, "%s: %d h old" % (ad, int(saat))))
    return _birlestir("backup_age", parcalar)


def kontrol_sertifika(a, simdi):
    if not a.sertifika_ad:
        return Sonuc("cert_expiry", "SKIP", "no --sertifika-ad given")
    try:
        bitis = a.sertifika_oku(a.sertifika_host, a.sertifika_port, a.sertifika_ad)
    except (OSError, ssl.SSLError, KeyError, ValueError) as ex:
        return Sonuc("cert_expiry", "CRIT", "certificate could not be read or verified (%s)" % type(ex).__name__)
    gun = (bitis - simdi.timestamp()) / 86400
    if gun <= a.sertifika_kritik_gun:
        durum = "CRIT"
    elif gun <= a.sertifika_uyari_gun:
        durum = "WARN"
    else:
        durum = "OK"
    return Sonuc("cert_expiry", durum, "%s expires in %d days" % (a.sertifika_ad, int(gun)) if gun >= 0 else "%s expired %d days ago" % (a.sertifika_ad, int(-gun)))


@dataclass
class Kontrol:
    ad: str
    aciklama: str
    calistir: object


# The list of things to watch. Adding a check = adding a row; nothing else changes.
KONTROLLER = [
    Kontrol("health", "GET /healthz and /api/tarama/saglik answer 200 ok", kontrol_saglik),
    Kontrol("disk", "free space of the data and backup directories", kontrol_disk),
    Kontrol("outbox", "pending and failed mail in the tarama.sqlite outbox, age of the oldest", kontrol_posta),
    Kontrol("pending_requests", "open contact and portal requests, age of the oldest", kontrol_talepler),
    Kontrol("audit_chain", "hash chain of both audit logs verifies (needs the audit key for keyed records)", kontrol_denetim),
    Kontrol("backup_age", "age of the newest backup of every database present", kontrol_yedek),
    Kontrol("cert_expiry", "days until the served TLS certificate expires", kontrol_sertifika),
]


def calistir(ayar, simdi=None, kontroller=None):
    simdi = simdi or datetime.now(timezone.utc)
    sonuclar = []
    for k in (KONTROLLER if kontroller is None else kontroller):
        try:
            sonuclar.append(k.calistir(ayar, simdi))
        except Exception as ex:  # noqa: BLE001 - one broken check must not hide the others
            sonuclar.append(Sonuc(k.ad, "UNKNOWN", "check failed: %s: %s" % (type(ex).__name__, str(ex)[:100])))
    return sonuclar


def cikis_kodu(sonuclar):
    return 1 if any(s.durum == "CRIT" for s in sonuclar) else 0


def ozet_satiri(sonuclar):
    sayi = {d: sum(1 for s in sonuclar if s.durum == d) for d in ("OK", "WARN", "CRIT", "UNKNOWN", "SKIP")}
    return "izle: %d checks, %s" % (len(sonuclar), ", ".join("%d %s" % (n, d) for d, n in sayi.items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only monitoring list; output is only a log.")
    ap.add_argument("--veri", default="/var/lib/alig")
    ap.add_argument("--yedek", default="/var/backups/alig")
    ap.add_argument("--taban", default="", help="health endpoint base URL, e.g. http://127.0.0.1:8081")
    ap.add_argument("--sertifika-ad", default="", help="TLS server name to check, e.g. alig.tech")
    ap.add_argument("--sertifika-host", default="127.0.0.1")
    ap.add_argument("--sertifika-port", type=int, default=443)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ayar = Ayar(veri=a.veri, yedek=a.yedek, taban=a.taban, sertifika_ad=a.sertifika_ad,
                sertifika_host=a.sertifika_host, sertifika_port=a.sertifika_port)
    sonuclar = calistir(ayar)
    if a.json:
        print(json.dumps({"sonuclar": [s._asdict() for s in sonuclar], "cikis": cikis_kodu(sonuclar)}, ensure_ascii=False))
    else:
        for s in sonuclar:
            print("%-7s %s: %s" % (s.durum, s.ad, s.ayrinti))
        print(ozet_satiri(sonuclar))
    return cikis_kodu(sonuclar)


if __name__ == "__main__":
    sys.exit(main())
