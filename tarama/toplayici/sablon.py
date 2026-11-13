#!/usr/bin/env python3
"""alig.tech saglik taramasi toplayicisi. Yalnizca standart kutuphane, Python 3.9+.

Musterinin kendi agi icinde calisir, AGA HICBIR SEY GONDERMEZ. Sabit, salt okunur
sorgu katalogunu `psql` ile calistirir ve tek bir JSON dosyasi yazar. Dosyayi okuyup,
istediginizde siteye kendiniz yuklersiniz.

Kullanim:
  python3 alig-toplayici.py --host db.ornek.local --user alig_hc --dbname postgres --maskele
Parola: PGPASSWORD ortam degiskeni ya da ~/.pgpass. Komut satirindan parola kabul edilmez.
Sunucu geneli denetimler --dbname veritabaninda bir kez calisir. Tablo, indeks ve sequence denetimleri
baglanma yetkisi olan her veritabaninda ayri calisir (en cok --en-cok-veritabani); --veritabanlari ile secilebilir.
--maskele verilirse takma ad -> gercek ad eslemesi yalniz bu bilgisayarda <cikti>-maske.json dosyasina yazilir; yuklemeyin.
Calisan sorgularin tam listesi: sorgu-katalogu.txt (ayni SHA-256 sayfada yazar).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

KATALOG = json.loads(r'''__KATALOG_JSON__''')
FORMAT = KATALOG["format"]
KATALOG_OZETI = hashlib.sha256(json.dumps(KATALOG["kontroller"], sort_keys=True).encode()).hexdigest()


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


def sorgu_sec(c, ana):
    """Denetimin bu ana surumde calisacak sorgusu; desteklenmeyen surumde None (tarama/katalog.py sorgu ile ayni)."""
    if ana is None:
        return c["sql"]
    if ana < c.get("en_az", 12) or (c.get("en_cok") is not None and ana > c["en_cok"]):
        return None
    for v in c.get("eski_surum", ()):
        if ana <= v["en_cok"]:
            return v["sql"]
    return c["sql"]


def _ci(deger):
    """libpq baglanti dizgisi degeri: bosluk, tirnak ya da ters bolu iceriyorsa tirnaklanir ve kacirilir."""
    d = str(deger)
    if d and not any(ch in d for ch in " '\\=\t\n"):
        return d
    return "'" + d.replace("\\", "\\\\").replace("'", "\\'") + "'"


def calistir(psql, baglanti, sql):
    sarmal = "SELECT coalesce(json_agg(t), '[]'::json) FROM (" + sql + ") t"
    env = dict(os.environ)
    env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000"
    env["PGAPPNAME"] = "alig-toplayici"
    cmd = [psql, "-X", "-A", "-t", "--no-psqlrc", "-v", "ON_ERROR_STOP=1"] + baglanti + ["-c", sarmal]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    except subprocess.TimeoutExpired:
        return {"durum": "hata", "neden": "zaman_asimi"}
    except FileNotFoundError:
        raise SystemExit("psql bulunamadi: --psql ile yolunu verin")
    if r.returncode != 0:
        return {"durum": "hata", "neden": hata_sinifi(r.stderr)}
    try:
        return {"durum": "ok", "satirlar": json.loads(r.stdout.strip() or "[]")}
    except ValueError:
        return {"durum": "hata", "neden": "hata"}


class Maske:
    def __init__(self):
        self.harita = {}

    def al(self, kolon, deger):
        if deger is None or not isinstance(deger, str):
            return deger
        return self.harita.setdefault(deger, "nesne-%d" % (len(self.harita) + 1))


def _yaz_600(yol, veri):
    """Yalniz sahibinin okuyabildigi dosya (var olan dosyanin izni de daraltilir)."""
    fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(veri)
    os.chmod(yol, 0o600)


def veritabanlari(psql, args, baglanti):
    """(taranacak, atlanan). Liste alinamazsa yalniz --dbname taranir."""
    sonuc = calistir(psql, baglanti(args.dbname), KATALOG["veritabani_listesi"])
    if sonuc["durum"] != "ok":
        return [args.dbname], []
    secim = {x for x in (args.veritabanlari or "").split(",") if x} or None
    taranacak, atlanan = [], []
    for s in sonuc["satirlar"]:
        ad = s.get("veritabani")
        if not isinstance(ad, str) or (secim is not None and ad not in secim):
            continue
        if not s.get("baglanir"):
            atlanan.append({"veritabani": ad, "neden": "yetki"})
        elif len(taranacak) >= args.en_cok_veritabani:
            atlanan.append({"veritabani": ad, "neden": "sinir"})
        else:
            taranacak.append(ad)
    return taranacak, atlanan


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech saglik taramasi toplayicisi (salt okunur)")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--user")
    ap.add_argument("--dbname", default="postgres", help="ilk baglanti ve sunucu geneli denetimler icin veritabani")
    ap.add_argument("--veritabanlari", default="", help="yalniz bu veritabanlarini tara (virgulle)")
    ap.add_argument("--en-cok-veritabani", type=int, default=KATALOG.get("en_cok_veritabani", 50))
    ap.add_argument("--sslmode", default="prefer")
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--out", default="alig-toplama.json")
    ap.add_argument("--maskele", action="store_true", help="veritabani, sema, tablo, indeks, rol ve slot adlarini takma adla degistir")
    args = ap.parse_args(argv)

    def baglanti(db):
        b = ["-d", "dbname=%s sslmode=%s" % (_ci(db), _ci(args.sslmode))]
        if args.host:
            b += ["-h", args.host]
        if args.port:
            b += ["-p", args.port]
        if args.user:
            b += ["-U", args.user]
        return b

    ilk = calistir(args.psql, baglanti(args.dbname), "SELECT current_setting('is_superuser') = 'on' AS super, pg_is_in_recovery() AS yedek, "
                   "(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()) AS tls, current_setting('server_version_num')::int AS surum")
    if ilk["durum"] != "ok":
        raise SystemExit("baglanti kurulamadi (%s). Sunucu, kullanici, parola ve sslmode'u denetleyin." % ilk.get("neden"))
    super_ = bool(ilk["satirlar"][0]["super"])
    surum = ilk["satirlar"][0].get("surum")
    ana = surum // 10000 if isinstance(surum, int) and not isinstance(surum, bool) else None
    if ana is not None:
        print("PostgreSQL ana surumu: %d" % ana)
        if not KATALOG.get("surum_alt", 12) <= ana <= KATALOG.get("surum_ust", 18):
            print("UYARI: PostgreSQL %d icin denetimler sinanmadi; desteklenmeyen denetimler atlanir." % ana, file=sys.stderr)
    if super_:
        print("UYARI: super kullanici ile calisiyorsunuz. Yetkisiz bir rol (pg_monitor uyesi) onerilir.", file=sys.stderr)
    if ilk["satirlar"][0].get("tls") is False and args.host and not args.host.startswith("/"):
        print("UYARI: baglanti sifresiz (TLS yok). Parola ve sonuclar agda acik gitmis olabilir; --sslmode require kullanin.", file=sys.stderr)

    taranacak, atlanan = veritabanlari(args.psql, args, baglanti)
    print("taranacak veritabani: %d, atlanan: %d" % (len(taranacak), len(atlanan)))
    maske = Maske() if args.maskele else None
    kontroller = {}
    for c in KATALOG["kontroller"]:
        sql = sorgu_sec(c, ana)
        if sql is None:   # bu surumde olmayan ozellik: sorgu calismaz
            kontroller[c["id"]] = {"durum": "hata", "neden": "desteklenmiyor"}
            print("%-26s ATLANDI (desteklenmiyor: PostgreSQL %d)" % (c["id"], ana))
            continue
        if c.get("kapsam") == "veritabani":
            satirlar, at, calisti, ilk_neden = [], list(atlanan), False, None
            for db in taranacak:
                r = calistir(args.psql, baglanti(db), sql)
                if r["durum"] == "ok":
                    calisti = True
                    for satir in r["satirlar"]:
                        satir["veritabani"] = db
                    satirlar += r["satirlar"]
                else:
                    at.append({"veritabani": db, "neden": r["neden"]})
                    ilk_neden = ilk_neden or r["neden"]
            if calisti:
                sonuc = {"durum": "ok", "satirlar": satirlar}
                if at:
                    sonuc["atlanan"] = at
            else:
                sonuc = {"durum": "hata", "neden": ilk_neden or ("yetki" if at else "calistirilmadi")}
        else:
            sonuc = calistir(args.psql, baglanti(args.dbname), sql)
        if sonuc["durum"] == "ok" and maske:
            for satir in sonuc["satirlar"]:
                for kolon in c["maske"]:
                    if kolon in satir:
                        satir[kolon] = maske.al(kolon, satir[kolon])
            for a in sonuc.get("atlanan", []):
                a["veritabani"] = maske.al("veritabani", a["veritabani"])
        kontroller[c["id"]] = sonuc
        durum = sonuc["durum"] if sonuc["durum"] == "ok" else "ATLANDI (%s)" % sonuc["neden"]
        if sonuc.get("atlanan"):
            durum += " (%d veritabani atlandi)" % len(sonuc["atlanan"])
        print("%-26s %s" % (c["id"], durum))

    belge = {"format": FORMAT, "motor": KATALOG["motor"], "katalog_sha256": KATALOG_OZETI,
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": super_, "kontroller": kontroller}
    veri = json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    _yaz_600(args.out, veri)
    print("\nYazildi: %s\nSHA-256: %s\nDosyayi acip inceleyebilirsiniz. Siteye yuklemeden once hicbir sey gonderilmedi." % (
        args.out, hashlib.sha256(veri).hexdigest()))
    if maske:
        kok, _ = os.path.splitext(args.out)
        esleme = kok + "-maske.json"
        _yaz_600(esleme, json.dumps({v: k for k, v in maske.harita.items()}, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
        print("Takma ad eslemesi: %s\nBu dosya yalniz sizde kalir; raporda gorunen nesne-N adlarini bulmak icindir. YUKLEMEYIN." % esleme)


if __name__ == "__main__":
    main()
