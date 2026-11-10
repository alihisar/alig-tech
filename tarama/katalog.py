"""PostgreSQL denetim kataloginin sorgulari. Yalnizca sabit, gozden gecirilmis SELECT'ler.

Her sorgu `SELECT coalesce(json_agg(t),'[]') FROM (<sql>) t` icinde calisir.
Kullanici tablolarindan satir verisi okunmaz; yalniz katalog, istatistik ve ayar gorunumleri.
`kolonlar`: yuklemede izin verilen kolonlar. `maske`: --maskele ile takma adlanan kolonlar.
"""

FORMAT = "alig-toplayici/1"
MOTOR = "postgresql"

PG = [
    {"id": "pg_surum", "kolonlar": ["surum_num"], "maske": [],
     "sql": "SELECT current_setting('server_version_num')::int AS surum_num"},
    {"id": "pg_xid_yasi", "kolonlar": ["datname", "yas", "mxid_yas", "freeze_max_age"], "maske": ["datname"],
     "sql": "SELECT datname, age(datfrozenxid) AS yas, mxid_age(datminmxid) AS mxid_yas, "
            "current_setting('autovacuum_freeze_max_age')::bigint AS freeze_max_age "
            "FROM pg_database WHERE datallowconn"},
    {"id": "pg_bosta_islem", "kolonlar": ["usename", "durum", "sure_sn"], "maske": ["usename"],
     "sql": "SELECT usename, state AS durum, extract(epoch FROM now() - xact_start)::int AS sure_sn "
            "FROM pg_stat_activity WHERE state IN ('idle in transaction','idle in transaction (aborted)') "
            "AND backend_type = 'client backend' AND pid <> pg_backend_pid() ORDER BY 3 DESC LIMIT 20"},
    {"id": "pg_baglanti", "kolonlar": ["kullanilan", "ust"], "maske": [],
     "sql": "SELECT (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend')::int AS kullanilan, "
            "current_setting('max_connections')::int AS ust"},
    {"id": "pg_olu_satir", "kolonlar": ["schemaname", "relname", "canli", "olu", "son_autovacuum"],
     "maske": ["schemaname", "relname"],
     "sql": "SELECT schemaname, relname, n_live_tup AS canli, n_dead_tup AS olu, "
            "to_char(last_autovacuum AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_autovacuum "
            "FROM pg_stat_user_tables WHERE n_dead_tup > 10000 ORDER BY n_dead_tup DESC LIMIT 20"},
    {"id": "pg_gecersiz_indeks", "kolonlar": ["schemaname", "indexrelname"], "maske": ["schemaname", "indexrelname"],
     "sql": "SELECT n.nspname AS schemaname, c.relname AS indexrelname FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE NOT i.indisvalid LIMIT 50"},
    {"id": "pg_kullanilmayan_indeks", "kolonlar": ["schemaname", "indexrelname", "bayt"],
     "maske": ["schemaname", "indexrelname"],
     "sql": "SELECT s.schemaname, s.indexrelname, pg_relation_size(s.indexrelid)::bigint AS bayt "
            "FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid "
            "WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary "
            "AND pg_relation_size(s.indexrelid) > 10485760 ORDER BY 3 DESC LIMIT 20"},
    {"id": "pg_sequence", "kolonlar": ["schemaname", "sequencename", "oran"], "maske": ["schemaname", "sequencename"],
     "sql": "SELECT schemaname, sequencename, round((last_value::numeric / max_value::numeric), 4)::float8 AS oran "
            "FROM pg_sequences WHERE last_value IS NOT NULL AND last_value::numeric / max_value::numeric > 0.5 "
            "ORDER BY 3 DESC LIMIT 20"},
    {"id": "pg_slot", "kolonlar": ["slot_name", "active", "wal_status", "geri_bayt"], "maske": ["slot_name"],
     "sql": "SELECT slot_name, active, wal_status, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint AS geri_bayt "
            "FROM pg_replication_slots LIMIT 50"},
    {"id": "pg_arsiv", "kolonlar": ["archive_mode", "basarili", "hatali", "son_basari_utc", "son_hata_utc"], "maske": [],
     "sql": "SELECT current_setting('archive_mode') AS archive_mode, archived_count AS basarili, failed_count AS hatali, "
            "to_char(last_archived_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_basari_utc, "
            "to_char(last_failed_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_hata_utc "
            "FROM pg_stat_archiver"},
    {"id": "pg_tls_parola", "kolonlar": ["ssl", "password_encryption", "ssl_min_protocol_version"], "maske": [],
     "sql": "SELECT current_setting('ssl') AS ssl, current_setting('password_encryption') AS password_encryption, "
            "current_setting('ssl_min_protocol_version') AS ssl_min_protocol_version"},
    {"id": "pg_md5_roller", "kolonlar": ["sayi"], "maske": [],
     "yetki": "superuser",
     "sql": "SELECT count(*)::int AS sayi FROM pg_authid WHERE rolpassword LIKE 'md5%'"},
    {"id": "pg_super_roller", "kolonlar": ["rolname", "rolcanlogin"], "maske": ["rolname"],
     "sql": "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolsuper AND rolname !~ '^pg_' LIMIT 50"},
    {"id": "pg_public_create", "kolonlar": ["public_create"], "maske": [],
     "sql": "SELECT has_schema_privilege('public', 'public', 'CREATE') AS public_create"},
    {"id": "pg_log_ayarlari", "kolonlar": ["name", "setting"], "maske": [],
     "sql": "SELECT name, setting FROM pg_settings WHERE name IN ('log_connections','log_disconnections','log_min_duration_statement')"},
    {"id": "pg_eklentiler", "kolonlar": ["extname", "extversion"], "maske": [],
     "sql": "SELECT extname, extversion FROM pg_extension"},
]

PG_BY_ID = {c["id"]: c for c in PG}

YASAKLI = ("analyze", "insert", "update", "delete", "alter", "drop", "create", "truncate", "copy", "grant", "revoke",
           "vacuum", "reindex", "cluster", "pg_terminate", "pg_cancel", "dblink", "lo_", "pg_read_file",
           "pg_ls_dir", "set ", "call ", "do ", "execute", "explain", "xp_", "pg_sleep", "pg_reload_conf",
           "pg_rotate", "pg_switch", "pg_start_backup", "pg_promote")
