#!/usr/bin/env python3
"""alig.tech saglik taramasi toplayicisi. Yalnizca standart kutuphane, Python 3.9+.

Musterinin kendi agi icinde calisir, AGA HICBIR SEY GONDERMEZ. Sabit, salt okunur
sorgu katalogunu `psql` ile calistirir ve tek bir JSON dosyasi yazar. Dosyayi okuyup,
istediginizde siteye kendiniz yuklersiniz.

Kullanim:
  python3 alig-toplayici.py --host db.ornek.local --user alig_hc --dbname postgres --maskele
Parola: PGPASSWORD ortam degiskeni ya da ~/.pgpass. Komut satirindan parola kabul edilmez.
Calisan sorgularin tam listesi: sorgu-katalogu.txt (ayni SHA-256 sayfada yazar).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

KATALOG = json.loads(r'''{"format": "alig-toplayici/1", "kontroller": [{"id": "pg_surum", "kolonlar": ["surum_num"], "maske": [], "sql": "SELECT current_setting('server_version_num')::int AS surum_num"}, {"id": "pg_xid_yasi", "kolonlar": ["datname", "yas", "mxid_yas", "freeze_max_age"], "maske": ["datname"], "sql": "SELECT datname, age(datfrozenxid) AS yas, mxid_age(datminmxid) AS mxid_yas, current_setting('autovacuum_freeze_max_age')::bigint AS freeze_max_age FROM pg_database WHERE datallowconn"}, {"id": "pg_bosta_islem", "kolonlar": ["usename", "durum", "sure_sn"], "maske": ["usename"], "sql": "SELECT usename, state AS durum, extract(epoch FROM now() - xact_start)::int AS sure_sn FROM pg_stat_activity WHERE state IN ('idle in transaction','idle in transaction (aborted)') AND backend_type = 'client backend' AND pid <> pg_backend_pid() ORDER BY 3 DESC LIMIT 20"}, {"id": "pg_baglanti", "kolonlar": ["kullanilan", "ust"], "maske": [], "sql": "SELECT (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend')::int AS kullanilan, current_setting('max_connections')::int AS ust"}, {"id": "pg_olu_satir", "kolonlar": ["schemaname", "relname", "canli", "olu", "son_autovacuum"], "maske": ["schemaname", "relname"], "sql": "SELECT schemaname, relname, n_live_tup AS canli, n_dead_tup AS olu, to_char(last_autovacuum AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_autovacuum FROM pg_stat_user_tables WHERE n_dead_tup > 10000 ORDER BY n_dead_tup DESC LIMIT 20"}, {"id": "pg_gecersiz_indeks", "kolonlar": ["schemaname", "indexrelname"], "maske": ["schemaname", "indexrelname"], "sql": "SELECT n.nspname AS schemaname, c.relname AS indexrelname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE NOT i.indisvalid LIMIT 50"}, {"id": "pg_kullanilmayan_indeks", "kolonlar": ["schemaname", "indexrelname", "bayt"], "maske": ["schemaname", "indexrelname"], "sql": "SELECT s.schemaname, s.indexrelname, pg_relation_size(s.indexrelid)::bigint AS bayt FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary AND pg_relation_size(s.indexrelid) > 10485760 ORDER BY 3 DESC LIMIT 20"}, {"id": "pg_sequence", "kolonlar": ["schemaname", "sequencename", "oran"], "maske": ["schemaname", "sequencename"], "sql": "SELECT schemaname, sequencename, round((last_value::numeric / max_value::numeric), 4)::float8 AS oran FROM pg_sequences WHERE last_value IS NOT NULL AND last_value::numeric / max_value::numeric > 0.5 ORDER BY 3 DESC LIMIT 20"}, {"id": "pg_slot", "kolonlar": ["slot_name", "active", "wal_status", "geri_bayt"], "maske": ["slot_name"], "sql": "SELECT slot_name, active, wal_status, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint AS geri_bayt FROM pg_replication_slots LIMIT 50"}, {"id": "pg_arsiv", "kolonlar": ["archive_mode", "basarili", "hatali", "son_basari_utc", "son_hata_utc"], "maske": [], "sql": "SELECT current_setting('archive_mode') AS archive_mode, archived_count AS basarili, failed_count AS hatali, to_char(last_archived_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_basari_utc, to_char(last_failed_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_hata_utc FROM pg_stat_archiver"}, {"id": "pg_tls_parola", "kolonlar": ["ssl", "password_encryption", "ssl_min_protocol_version"], "maske": [], "sql": "SELECT current_setting('ssl') AS ssl, current_setting('password_encryption') AS password_encryption, current_setting('ssl_min_protocol_version') AS ssl_min_protocol_version"}, {"id": "pg_md5_roller", "kolonlar": ["sayi"], "maske": [], "sql": "SELECT count(*)::int AS sayi FROM pg_authid WHERE rolpassword LIKE 'md5%'"}, {"id": "pg_super_roller", "kolonlar": ["rolname", "rolcanlogin"], "maske": ["rolname"], "sql": "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolsuper AND rolname !~ '^pg_' LIMIT 50"}, {"id": "pg_public_create", "kolonlar": ["public_create"], "maske": [], "sql": "SELECT has_schema_privilege('public', 'public', 'CREATE') AS public_create"}, {"id": "pg_log_ayarlari", "kolonlar": ["name", "setting"], "maske": [], "sql": "SELECT name, setting FROM pg_settings WHERE name IN ('log_connections','log_disconnections','log_min_duration_statement')"}, {"id": "pg_eklentiler", "kolonlar": ["extname", "extversion"], "maske": [], "sql": "SELECT extname, extversion FROM pg_extension"}], "motor": "postgresql"}''')
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech saglik taramasi toplayicisi (salt okunur)")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--user")
    ap.add_argument("--dbname", default="postgres")
    ap.add_argument("--sslmode", default="prefer")
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--out", default="alig-toplama.json")
    ap.add_argument("--maskele", action="store_true", help="veritabani, sema, tablo, indeks, rol ve slot adlarini takma adla degistir")
    args = ap.parse_args(argv)

    baglanti = ["-d", "dbname=%s sslmode=%s" % (args.dbname, args.sslmode)]
    if args.host:
        baglanti += ["-h", args.host]
    if args.port:
        baglanti += ["-p", args.port]
    if args.user:
        baglanti += ["-U", args.user]

    ilk = calistir(args.psql, baglanti, "SELECT current_setting('is_superuser') = 'on' AS super, pg_is_in_recovery() AS yedek")
    if ilk["durum"] != "ok":
        raise SystemExit("baglanti kurulamadi (%s). Sunucu, kullanici, parola ve sslmode'u denetleyin." % ilk.get("neden"))
    super_ = bool(ilk["satirlar"][0]["super"])
    if super_:
        print("UYARI: super kullanici ile calisiyorsunuz. Yetkisiz bir rol (pg_monitor uyesi) onerilir.", file=sys.stderr)

    maske = Maske() if args.maskele else None
    kontroller = {}
    for c in KATALOG["kontroller"]:
        sonuc = calistir(args.psql, baglanti, c["sql"])
        if sonuc["durum"] == "ok" and maske:
            for satir in sonuc["satirlar"]:
                for kolon in c["maske"]:
                    if kolon in satir:
                        satir[kolon] = maske.al(kolon, satir[kolon])
        kontroller[c["id"]] = sonuc
        print("%-26s %s" % (c["id"], sonuc["durum"] if sonuc["durum"] == "ok" else "ATLANDI (%s)" % sonuc["neden"]))

    belge = {"format": FORMAT, "motor": KATALOG["motor"], "katalog_sha256": KATALOG_OZETI,
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": super_, "kontroller": kontroller}
    veri = json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    with open(args.out, "wb") as f:
        f.write(veri)
    print("\nYazildi: %s\nSHA-256: %s\nDosyayi acip inceleyebilirsiniz. Siteye yuklemeden once hicbir sey gonderilmedi." % (
        args.out, hashlib.sha256(veri).hexdigest()))


if __name__ == "__main__":
    main()
