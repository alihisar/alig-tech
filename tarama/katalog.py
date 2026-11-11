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


# ---- SQL Server (on surum: gercek sunucuda sinanana kadar genel sayfada yayimlanmaz) ----
# Her sorgu tek bir SELECT'tir; toplayici sonuna `FOR JSON PATH, INCLUDE_NULL_VALUES` ekler (SQL Server 2016+).
# Gereken yetki: VIEW SERVER STATE ve VIEW ANY DEFINITION. Kullanici tablolarindan satir okunmaz.
MSSQL = [
    {"id": "ms_surum", "kolonlar": ["ana_surum", "surum", "motor_turu"], "maske": [],
     "sql": "SELECT CAST(SERVERPROPERTY('ProductMajorVersion') AS int) AS ana_surum, "
            "CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(40)) AS surum, "
            "CAST(SERVERPROPERTY('EngineEdition') AS int) AS motor_turu"},
    {"id": "ms_yedek", "kolonlar": ["veritabani", "kurtarma_modeli", "tam_saat", "log_saat"], "maske": ["veritabani"],
     "sql": "SELECT d.name AS veritabani, d.recovery_model_desc AS kurtarma_modeli, "
            "DATEDIFF(hour, MAX(CASE WHEN b.type = 'D' THEN b.backup_finish_date END), GETDATE()) AS tam_saat, "
            "DATEDIFF(hour, MAX(CASE WHEN b.type = 'L' THEN b.backup_finish_date END), GETDATE()) AS log_saat "
            "FROM sys.databases d LEFT JOIN msdb.dbo.backupset b ON b.database_name = d.name "
            "WHERE d.database_id NOT IN (2, 3) AND d.state = 0 AND d.source_database_id IS NULL "
            "GROUP BY d.name, d.recovery_model_desc"},
    {"id": "ms_checkdb", "kolonlar": ["veritabani", "gun"], "maske": ["veritabani"],
     "sql": "SELECT d.name AS veritabani, "
            "DATEDIFF(day, CAST(DATABASEPROPERTYEX(d.name, 'LastGoodCheckDbTime') AS datetime), GETDATE()) AS gun "
            "FROM sys.databases d WHERE d.database_id <> 2 AND d.state = 0"},
    {"id": "ms_db_ayar", "kolonlar": ["veritabani", "kimlik", "auto_shrink", "auto_close", "sayfa_dogrulama", "durum", "trustworthy"],
     "maske": ["veritabani"],
     "sql": "SELECT name AS veritabani, database_id AS kimlik, CAST(is_auto_shrink_on AS int) AS auto_shrink, "
            "CAST(is_auto_close_on AS int) AS auto_close, page_verify_option_desc AS sayfa_dogrulama, "
            "state_desc AS durum, CAST(is_trustworthy_on AS int) AS trustworthy FROM sys.databases WHERE database_id <> 2"},
    {"id": "ms_sunucu_ayar", "kolonlar": ["ad", "deger"], "maske": [],
     "sql": "SELECT name AS ad, CAST(value_in_use AS bigint) AS deger FROM sys.configurations WHERE name IN "
            "('max server memory (MB)', 'max degree of parallelism', 'cost threshold for parallelism', 'xp_cmdshell', "
            "'Ad Hoc Distributed Queries', 'cross db ownership chaining', 'remote admin connections', "
            "'backup compression default', 'clr enabled')"},
    {"id": "ms_sa", "kolonlar": ["devre_disi", "adi_sa"], "maske": [],
     "sql": "SELECT CAST(is_disabled AS int) AS devre_disi, CASE WHEN name = 'sa' THEN 1 ELSE 0 END AS adi_sa "
            "FROM sys.sql_logins WHERE sid = 0x01"},
    {"id": "ms_sysadmin", "kolonlar": ["giris", "tur", "devre_disi"], "maske": ["giris"],
     "sql": "SELECT TOP 50 p.name AS giris, p.type_desc AS tur, CAST(p.is_disabled AS int) AS devre_disi "
            "FROM sys.server_role_members m JOIN sys.server_principals r ON r.principal_id = m.role_principal_id "
            "JOIN sys.server_principals p ON p.principal_id = m.member_principal_id WHERE r.name = 'sysadmin'"},
    {"id": "ms_parola_politikasi", "kolonlar": ["sayi"], "maske": [],
     "sql": "SELECT COUNT(*) AS sayi FROM sys.sql_logins WHERE is_policy_checked = 0 AND is_disabled = 0 AND name NOT LIKE '##%'"},
    {"id": "ms_tempdb", "kolonlar": ["veri_dosyasi", "cpu"], "maske": [],
     "sql": "SELECT (SELECT COUNT(*) FROM tempdb.sys.database_files WHERE type = 0) AS veri_dosyasi, "
            "(SELECT cpu_count FROM sys.dm_os_sys_info) AS cpu"},
    {"id": "ms_ag", "kolonlar": ["grup", "replika", "saglik", "rol", "baglanti"], "maske": ["grup", "replika"],
     "sql": "SELECT TOP 50 ag.name AS grup, ar.replica_server_name AS replika, rs.synchronization_health_desc AS saglik, "
            "rs.role_desc AS rol, rs.connected_state_desc AS baglanti FROM sys.dm_hadr_availability_replica_states rs "
            "JOIN sys.availability_replicas ar ON ar.replica_id = rs.replica_id "
            "JOIN sys.availability_groups ag ON ag.group_id = rs.group_id"},
    {"id": "ms_dosya_buyume", "kolonlar": ["veritabani", "dosya", "tur"], "maske": ["veritabani", "dosya"],
     "sql": "SELECT TOP 50 DB_NAME(database_id) AS veritabani, name AS dosya, type_desc AS tur FROM sys.master_files "
            "WHERE is_percent_growth = 1 AND database_id <> 2"},
    {"id": "ms_sifreleme", "kolonlar": ["toplam", "sifreli"], "maske": [],
     "sql": "SELECT COUNT(*) AS toplam, ISNULL(SUM(CASE WHEN encrypt_option = 'TRUE' THEN 1 ELSE 0 END), 0) AS sifreli "
            "FROM sys.dm_exec_connections WHERE net_transport = 'TCP'"},
    {"id": "ms_acik_islem", "kolonlar": ["giris", "sure_sn"], "maske": ["giris"],
     "sql": "SELECT TOP 20 s.login_name AS giris, DATEDIFF(second, t.transaction_begin_time, GETDATE()) AS sure_sn "
            "FROM sys.dm_tran_session_transactions st "
            "JOIN sys.dm_tran_active_transactions t ON t.transaction_id = st.transaction_id "
            "JOIN sys.dm_exec_sessions s ON s.session_id = st.session_id WHERE s.is_user_process = 1 ORDER BY 2 DESC"},
    {"id": "ms_kimlik", "kolonlar": ["yalniz_windows"], "maske": [],
     "sql": "SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int) AS yalniz_windows"},
]
MSSQL_BY_ID = {c["id"]: c for c in MSSQL}

# Metin sabitleri (tek tirnak icleri) cikarildiktan sonra aranir.
YASAKLI_MSSQL = ("insert", "update", "delete", "merge", "alter", "drop", "create", "truncate", "grant", "revoke", "deny",
                 "exec", "sp_", "xp_", "openrowset", "openquery", "opendatasource", "into", "dbcc", "backup", "restore",
                 "kill", "shutdown", "waitfor", "reconfigure", "use ", "set ", "declare", "bulk", "--", "/*", ";")

MOTORLAR = {"postgresql": PG, "mssql": MSSQL}
MOTOR_BY_ID = {"postgresql": PG_BY_ID, "mssql": MSSQL_BY_ID}
MOTOR_AD = {"postgresql": "PostgreSQL", "mssql": "SQL Server"}
