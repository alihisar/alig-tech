"""PostgreSQL denetim kataloginin sorgulari. Yalnizca sabit, gozden gecirilmis SELECT'ler.

Her sorgu `SELECT coalesce(json_agg(t),'[]') FROM (<sql>) t` icinde calisir.
Kullanici tablolarindan satir verisi okunmaz; yalniz katalog, istatistik ve ayar gorunumleri.
`kolonlar`: yuklemede izin verilen kolonlar. `maske`: --maskele ile takma adlanan kolonlar.
`kapsam: veritabani`: denetim baglanilabilen her veritabaninda ayri calisir; toplayici her satira `veritabani`
kolonunu ekler. Digerleri sunucu geneli kataloglari okur ve bir kez calisir.
`kaynak`: sorgunun okudugu gorunum, islev ya da ayar adlari; kanit kaydinda gosterilir (tarama/kanit.py). Toplayiciya
gitmez, katalog ozetini degistirmez.

Surum matrisi (PostgreSQL): `en_az` denetimin calistigi en eski ana surum, istege bagli `en_cok` en yeni ana surum,
`eski_surum` eski surumler icin degisik sorgu ([{"en_cok": 12, "sql": ...}]). Toplayici sunucunun ana surumune gore
sorguyu secer (`sorgu`); desteklenmeyen surumde sorgu hic calismaz, denetim "desteklenmiyor" olarak yazilir.
`yetki`: dogru sonuc icin tarama hesabinda gereken yetki (YETKILER). pg_read_all_stats ve pg_read_all_settings
pg_monitor uyeligiyle gelir; hesapta yoksa kanit motoru sonucu kismi sayar (tarama/kanit.py, pg_hesap denetimi).
Matris ve gercek sunucudaki dogrulama sonuclari: docs/surum-matrisi.md (uretilir).
"""

FORMAT = "alig-toplayici/1"
MOTOR = "postgresql"
SURUM_ALT, SURUM_UST = 12, 18   # matrisin kapsadigi ana surumler; daha yenisinde ana sorgu calisir (sinanmadi)
# Butun sorgularin gercek sunucuda sinandigi ana surumler (tarama/surum_dogrula.py; kanit docs/surum-dogrulama.json,
# tutarliligini tests/test_surum.py denetler). Disindaki surumde rapordaki kanit guveni en cok MEDIUM.
SINANAN = (16,)
YETKILER = ("herkes", "pg_read_all_stats", "pg_read_all_settings", "superuser")
# Yedek sunucuda pg_current_wal_lsn() hata verir: orada son alinan WAL konumu kullanilir (CASE gereken dali calistirir).
WAL_KONUMU = "CASE WHEN pg_is_in_recovery() THEN pg_last_wal_receive_lsn() ELSE pg_current_wal_lsn() END"

PG = [
    {"id": "pg_surum", "en_az": 0, "yetki": "herkes", "kaynak": ["server_version_num"], "kolonlar": ["surum_num"], "maske": [],
     "sql": "SELECT current_setting('server_version_num')::int AS surum_num"},
    {"id": "pg_sunucu_rolu", "en_az": 0, "yetki": "herkes", "kaynak": ["pg_is_in_recovery"], "kolonlar": ["yedek"], "maske": [],
     "sql": "SELECT pg_is_in_recovery() AS yedek"},
    # Veritabani kimligi (gecmis karsilastirmasi, tarama/gecmis.py): kume tanimlayicisinin ozeti; ham deger sunucudan cikmaz.
    {"id": "pg_kume_kimligi", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_control_system"], "kolonlar": ["kume"], "maske": [],
     "sql": "SELECT encode(sha256(system_identifier::text::bytea), 'hex') AS kume FROM pg_control_system()"},
    {"id": "pg_hesap", "en_az": 0, "yetki": "herkes", "kaynak": ["pg_roles", "pg_has_role"],
     "kolonlar": ["super_kullanici", "pg_read_all_stats", "pg_read_all_settings"], "maske": [],
     "sql": "SELECT rolsuper AS super_kullanici, pg_has_role(current_user, 'pg_read_all_stats', 'USAGE') AS pg_read_all_stats, "
            "pg_has_role(current_user, 'pg_read_all_settings', 'USAGE') AS pg_read_all_settings "
            "FROM pg_roles WHERE rolname = current_user"},
    {"id": "pg_kapsam", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_database"], "kapsam": "veritabani", "kolonlar": ["veritabani", "veritabani_sayisi"], "maske": ["veritabani"],
     "sql": "SELECT current_database() AS veritabani, "
            "(SELECT count(*) FROM pg_database WHERE datallowconn AND NOT datistemplate)::int AS veritabani_sayisi"},
    {"id": "pg_xid_yasi", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_database", "autovacuum_freeze_max_age", "autovacuum_multixact_freeze_max_age"],
     "kolonlar": ["datname", "yas", "mxid_yas", "freeze_max_age", "mxid_freeze_max_age"], "maske": ["datname"],
     "sql": "SELECT datname, age(datfrozenxid) AS yas, mxid_age(datminmxid) AS mxid_yas, "
            "current_setting('autovacuum_freeze_max_age')::bigint AS freeze_max_age, "
            "current_setting('autovacuum_multixact_freeze_max_age')::bigint AS mxid_freeze_max_age "
            "FROM pg_database WHERE datallowconn"},
    {"id": "pg_bosta_islem", "en_az": 12, "yetki": "pg_read_all_stats", "kaynak": ["pg_stat_activity"], "kolonlar": ["usename", "durum", "sure_sn"], "maske": ["usename"],
     "sql": "SELECT usename, state AS durum, extract(epoch FROM now() - xact_start)::int AS sure_sn "
            "FROM pg_stat_activity WHERE state IN ('idle in transaction','idle in transaction (aborted)') "
            "AND backend_type = 'client backend' AND pid <> pg_backend_pid() ORDER BY 3 DESC LIMIT 20"},
    {"id": "pg_baglanti", "en_az": 12, "yetki": "pg_read_all_stats", "kaynak": ["pg_stat_activity", "max_connections"], "kolonlar": ["kullanilan", "ust"], "maske": [],
     "sql": "SELECT (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend')::int AS kullanilan, "
            "current_setting('max_connections')::int AS ust"},
    {"id": "pg_olu_satir", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_stat_user_tables"], "kapsam": "veritabani", "kolonlar": ["veritabani", "schemaname", "relname", "canli", "olu", "son_autovacuum"],
     "maske": ["veritabani", "schemaname", "relname"],
     "sql": "SELECT schemaname, relname, n_live_tup AS canli, n_dead_tup AS olu, "
            "to_char(last_autovacuum AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_autovacuum "
            "FROM pg_stat_user_tables WHERE n_dead_tup > 10000 ORDER BY n_dead_tup DESC LIMIT 20"},
    {"id": "pg_gecersiz_indeks", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_index"], "kapsam": "veritabani", "kolonlar": ["veritabani", "schemaname", "indexrelname"],
     "maske": ["veritabani", "schemaname", "indexrelname"],
     "sql": "SELECT n.nspname AS schemaname, c.relname AS indexrelname FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE NOT i.indisvalid LIMIT 50"},
    {"id": "pg_kullanilmayan_indeks", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_stat_user_indexes"], "kapsam": "veritabani", "kolonlar": ["veritabani", "schemaname", "indexrelname", "bayt"],
     "maske": ["veritabani", "schemaname", "indexrelname"],
     "sql": "SELECT s.schemaname, s.indexrelname, pg_relation_size(s.indexrelid)::bigint AS bayt "
            "FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid "
            "WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary "
            "AND pg_relation_size(s.indexrelid) > 10485760 ORDER BY 3 DESC LIMIT 20"},
    {"id": "pg_sequence", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_sequences"], "kapsam": "veritabani", "kolonlar": ["veritabani", "schemaname", "sequencename", "oran"],
     "maske": ["veritabani", "schemaname", "sequencename"],
     "sql": "SELECT schemaname, sequencename, round((last_value::numeric / max_value::numeric), 4)::float8 AS oran "
            "FROM pg_sequences WHERE last_value IS NOT NULL AND last_value::numeric / max_value::numeric > 0.5 "
            "ORDER BY 3 DESC LIMIT 20"},
    {"id": "pg_sequence_gorunurluk", "en_az": 12, "yetki": "herkes", "kaynak": ["has_sequence_privilege"], "kapsam": "veritabani", "kolonlar": ["veritabani", "toplam", "okunamayan"], "maske": ["veritabani"],
     "sql": "SELECT count(*)::int AS toplam, count(*) FILTER (WHERE NOT has_sequence_privilege(c.oid, 'USAGE,SELECT'))::int AS okunamayan "
            "FROM pg_class c WHERE c.relkind = 'S'"},
    {"id": "pg_slot", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_replication_slots"], "kolonlar": ["slot_name", "active", "wal_status", "geri_bayt"], "maske": ["slot_name"],
     "sql": "SELECT slot_name, active, wal_status, pg_wal_lsn_diff(%s, restart_lsn)::bigint AS geri_bayt "
            "FROM pg_replication_slots LIMIT 50" % WAL_KONUMU,
     "eski_surum": [{"en_cok": 12, "not": "wal_status kolonu PostgreSQL 13'te geldi, 12'de boş döner",
                     "sql": "SELECT slot_name, active, NULL::text AS wal_status, "
                            "pg_wal_lsn_diff(%s, restart_lsn)::bigint AS geri_bayt FROM pg_replication_slots LIMIT 50" % WAL_KONUMU}]},
    {"id": "pg_replikasyon", "en_az": 12, "yetki": "pg_read_all_stats", "kaynak": ["pg_stat_replication"],
     "kolonlar": ["uygulama", "durum", "senkron", "gecikme_sn", "gecikme_bayt"], "maske": ["uygulama"],
     "sql": "SELECT application_name AS uygulama, state AS durum, sync_state AS senkron, "
            "date_part('epoch', replay_lag)::float8 AS gecikme_sn, "
            "pg_wal_lsn_diff(%s, replay_lsn)::bigint AS gecikme_bayt "
            "FROM pg_stat_replication ORDER BY 5 DESC NULLS LAST LIMIT 50" % WAL_KONUMU},
    {"id": "pg_arsiv", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_stat_archiver", "archive_mode"], "kolonlar": ["archive_mode", "basarili", "hatali", "son_basari_utc", "son_hata_utc"], "maske": [],
     "sql": "SELECT current_setting('archive_mode') AS archive_mode, archived_count AS basarili, failed_count AS hatali, "
            "to_char(last_archived_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_basari_utc, "
            "to_char(last_failed_time AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS son_hata_utc "
            "FROM pg_stat_archiver"},
    {"id": "pg_tls_parola", "en_az": 12, "yetki": "pg_read_all_settings", "kaynak": ["ssl", "ssl_min_protocol_version", "password_encryption"], "kolonlar": ["ssl", "password_encryption", "ssl_min_protocol_version"], "maske": [],
     "sql": "SELECT current_setting('ssl') AS ssl, current_setting('password_encryption') AS password_encryption, "
            "current_setting('ssl_min_protocol_version') AS ssl_min_protocol_version"},
    {"id": "pg_md5_roller", "en_az": 12, "yetki": "superuser", "kaynak": ["pg_authid"], "kolonlar": ["sayi"], "maske": [],
     "sql": "SELECT count(*)::int AS sayi FROM pg_authid WHERE rolpassword LIKE 'md5%'"},
    {"id": "pg_super_roller", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_roles"], "kolonlar": ["rolname", "rolcanlogin"], "maske": ["rolname"],
     "sql": "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolsuper AND rolname !~ '^pg_' LIMIT 50"},
    {"id": "pg_public_create", "en_az": 12, "yetki": "herkes", "kaynak": ["has_schema_privilege"], "kapsam": "veritabani", "kolonlar": ["veritabani", "public_create"], "maske": ["veritabani"],
     "sql": "SELECT has_schema_privilege('public', 'public', 'CREATE') AS public_create"},
    {"id": "pg_log_ayarlari", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_settings"], "kolonlar": ["name", "setting"], "maske": [],
     "sql": "SELECT name, setting FROM pg_settings WHERE name IN ('log_connections','log_disconnections','log_min_duration_statement')"},
    {"id": "pg_autovacuum", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_settings"], "kolonlar": ["name", "setting"], "maske": [],
     "sql": "SELECT name, setting FROM pg_settings WHERE name IN ('autovacuum', 'track_counts')"},
    {"id": "pg_tablo_autovacuum", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_class"], "kapsam": "veritabani",
     "kolonlar": ["veritabani", "schemaname", "relname"], "maske": ["veritabani", "schemaname", "relname"],
     # reloptions degeri yazildigi gibi saklanir: PostgreSQL'in kabul ettigi butun "kapali" yazimlari (parse_bool)
     "sql": "SELECT n.nspname AS schemaname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'm') AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND array_to_string(c.reloptions, ',') ~* '(^|,)autovacuum_enabled=(f|fa|fal|fals|false|n|no|of|off|0)(,|$)' "
            "ORDER BY 1, 2 LIMIT 50"},
    {"id": "pg_sorgu_istatistigi", "en_az": 12, "yetki": "pg_read_all_settings", "kaynak": ["shared_preload_libraries", "pg_stat_statements.track"],
     "kolonlar": ["shared_preload_libraries", "izleme"], "maske": [],
     "sql": "SELECT current_setting('shared_preload_libraries') AS shared_preload_libraries, "
            "current_setting('pg_stat_statements.track', true) AS izleme"},
    {"id": "pg_gecici_dosya", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_stat_database"], "kolonlar": ["datname", "dosya", "bayt", "sifirlama_utc"],
     "maske": ["datname"],
     "sql": "SELECT datname, temp_files AS dosya, temp_bytes AS bayt, "
            "to_char(stats_reset AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS sifirlama_utc "
            "FROM pg_stat_database WHERE datname IS NOT NULL ORDER BY temp_bytes DESC LIMIT 100"},
    {"id": "pg_eklentiler", "en_az": 12, "yetki": "herkes", "kaynak": ["pg_extension"], "kapsam": "veritabani", "kolonlar": ["veritabani", "extname", "extversion"], "maske": ["veritabani"],
     "sql": "SELECT extname, extversion FROM pg_extension"},
]

PG_BY_ID = {c["id"]: c for c in PG}


def sorgu(c, ana):
    """Denetimin bu ana surumde calisacak sorgusu; surum desteklenmiyorsa None. Surum bilinmiyorsa ana sorgu."""
    if ana is None:
        return c["sql"]
    if ana < c.get("en_az", SURUM_ALT) or (c.get("en_cok") is not None and ana > c["en_cok"]):
        return None
    for v in c.get("eski_surum", ()):
        if ana <= v["en_cok"]:
            return v["sql"]
    return c["sql"]


def sorgular(c):
    """Denetimin butun sorgu bicimleri (ana ve eski surum)."""
    return [c["sql"]] + [v["sql"] for v in c.get("eski_surum", ())]

# Toplayicinin dolasacagi veritabanlari. CONNECT yetkisi olmayanlara baglanilmaz, "yetki" ile atlanir.
VT_LISTE_SQL = ("SELECT datname AS veritabani, has_database_privilege(datname, 'CONNECT') AS baglanir "
                "FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname")
EN_COK_VERITABANI = 50

YASAKLI = ("analyze", "insert", "update", "delete", "alter", "drop", "create", "truncate", "copy", "grant", "revoke",
           "vacuum", "reindex", "cluster", "pg_terminate", "pg_cancel", "dblink", "lo_", "pg_read_file",
           "pg_ls_dir", "set ", "call ", "do ", "execute", "explain", "xp_", "pg_sleep", "pg_reload_conf",
           "pg_rotate", "pg_switch", "pg_start_backup", "pg_promote")


# ---- SQL Server (on surum: gercek sunucuda sinanana kadar genel sayfada yayimlanmaz) ----
# Her sorgu tek bir SELECT'tir; toplayici sonuna `FOR JSON PATH, INCLUDE_NULL_VALUES` ekler (SQL Server 2016+).
# Gereken yetki: VIEW SERVER STATE ve VIEW ANY DEFINITION. Kullanici tablolarindan satir okunmaz.
MSSQL = [
    {"id": "ms_surum", "kaynak": ["SERVERPROPERTY"], "kolonlar": ["ana_surum", "surum", "motor_turu"], "maske": [],
     "sql": "SELECT CAST(SERVERPROPERTY('ProductMajorVersion') AS int) AS ana_surum, "
            "CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(40)) AS surum, "
            "CAST(SERVERPROPERTY('EngineEdition') AS int) AS motor_turu"},
    {"id": "ms_yedek", "kaynak": ["msdb.dbo.backupset", "sys.databases"], "kolonlar": ["veritabani", "kurtarma_modeli", "tam_saat", "log_saat"], "maske": ["veritabani"],
     "sql": "SELECT d.name AS veritabani, d.recovery_model_desc AS kurtarma_modeli, "
            "DATEDIFF(hour, MAX(CASE WHEN b.type = 'D' THEN b.backup_finish_date END), GETDATE()) AS tam_saat, "
            "DATEDIFF(hour, MAX(CASE WHEN b.type = 'L' THEN b.backup_finish_date END), GETDATE()) AS log_saat "
            "FROM sys.databases d LEFT JOIN msdb.dbo.backupset b ON b.database_name = d.name "
            "WHERE d.database_id NOT IN (2, 3) AND d.state = 0 AND d.source_database_id IS NULL "
            "GROUP BY d.name, d.recovery_model_desc"},
    {"id": "ms_checkdb", "kaynak": ["DATABASEPROPERTYEX", "sys.databases"], "kolonlar": ["veritabani", "gun"], "maske": ["veritabani"],
     "sql": "SELECT d.name AS veritabani, "
            "DATEDIFF(day, CAST(DATABASEPROPERTYEX(d.name, 'LastGoodCheckDbTime') AS datetime), GETDATE()) AS gun "
            "FROM sys.databases d WHERE d.database_id <> 2 AND d.state = 0"},
    {"id": "ms_db_ayar", "kaynak": ["sys.databases"], "kolonlar": ["veritabani", "kimlik", "auto_shrink", "auto_close", "sayfa_dogrulama", "durum", "trustworthy"],
     "maske": ["veritabani"],
     "sql": "SELECT name AS veritabani, database_id AS kimlik, CAST(is_auto_shrink_on AS int) AS auto_shrink, "
            "CAST(is_auto_close_on AS int) AS auto_close, page_verify_option_desc AS sayfa_dogrulama, "
            "state_desc AS durum, CAST(is_trustworthy_on AS int) AS trustworthy FROM sys.databases WHERE database_id <> 2"},
    {"id": "ms_sunucu_ayar", "kaynak": ["sys.configurations"], "kolonlar": ["ad", "deger"], "maske": [],
     "sql": "SELECT name AS ad, CAST(value_in_use AS bigint) AS deger FROM sys.configurations WHERE name IN "
            "('max server memory (MB)', 'max degree of parallelism', 'cost threshold for parallelism', 'xp_cmdshell', "
            "'Ad Hoc Distributed Queries', 'cross db ownership chaining', 'remote admin connections', "
            "'backup compression default', 'clr enabled')"},
    {"id": "ms_sa", "kaynak": ["sys.sql_logins"], "kolonlar": ["devre_disi", "adi_sa"], "maske": [],
     "sql": "SELECT CAST(is_disabled AS int) AS devre_disi, CASE WHEN name = 'sa' THEN 1 ELSE 0 END AS adi_sa "
            "FROM sys.sql_logins WHERE sid = 0x01"},
    {"id": "ms_sysadmin", "kaynak": ["sys.server_role_members", "sys.server_principals"], "kolonlar": ["giris", "tur", "devre_disi"], "maske": ["giris"],
     "sql": "SELECT TOP 50 p.name AS giris, p.type_desc AS tur, CAST(p.is_disabled AS int) AS devre_disi "
            "FROM sys.server_role_members m JOIN sys.server_principals r ON r.principal_id = m.role_principal_id "
            "JOIN sys.server_principals p ON p.principal_id = m.member_principal_id WHERE r.name = 'sysadmin'"},
    {"id": "ms_parola_politikasi", "kaynak": ["sys.sql_logins"], "kolonlar": ["sayi"], "maske": [],
     "sql": "SELECT COUNT(*) AS sayi FROM sys.sql_logins WHERE is_policy_checked = 0 AND is_disabled = 0 AND name NOT LIKE '##%'"},
    {"id": "ms_tempdb", "kaynak": ["tempdb.sys.database_files", "sys.dm_os_sys_info"], "kolonlar": ["veri_dosyasi", "cpu"], "maske": [],
     "sql": "SELECT (SELECT COUNT(*) FROM tempdb.sys.database_files WHERE type = 0) AS veri_dosyasi, "
            "(SELECT cpu_count FROM sys.dm_os_sys_info) AS cpu"},
    {"id": "ms_ag", "kaynak": ["sys.dm_hadr_availability_replica_states", "sys.availability_groups"], "kolonlar": ["grup", "replika", "saglik", "rol", "baglanti"], "maske": ["grup", "replika"],
     "sql": "SELECT TOP 50 ag.name AS grup, ar.replica_server_name AS replika, rs.synchronization_health_desc AS saglik, "
            "rs.role_desc AS rol, rs.connected_state_desc AS baglanti FROM sys.dm_hadr_availability_replica_states rs "
            "JOIN sys.availability_replicas ar ON ar.replica_id = rs.replica_id "
            "JOIN sys.availability_groups ag ON ag.group_id = rs.group_id"},
    {"id": "ms_dosya_buyume", "kaynak": ["sys.master_files"], "kolonlar": ["veritabani", "dosya", "tur"], "maske": ["veritabani", "dosya"],
     "sql": "SELECT TOP 50 DB_NAME(database_id) AS veritabani, name AS dosya, type_desc AS tur FROM sys.master_files "
            "WHERE is_percent_growth = 1 AND database_id <> 2"},
    {"id": "ms_sifreleme", "kaynak": ["sys.dm_exec_connections"], "kolonlar": ["toplam", "sifreli"], "maske": [],
     "sql": "SELECT COUNT(*) AS toplam, ISNULL(SUM(CASE WHEN encrypt_option = 'TRUE' THEN 1 ELSE 0 END), 0) AS sifreli "
            "FROM sys.dm_exec_connections WHERE net_transport = 'TCP'"},
    {"id": "ms_acik_islem", "kaynak": ["sys.dm_tran_active_transactions", "sys.dm_exec_sessions"], "kolonlar": ["giris", "sure_sn"], "maske": ["giris"],
     "sql": "SELECT TOP 20 s.login_name AS giris, DATEDIFF(second, t.transaction_begin_time, GETDATE()) AS sure_sn "
            "FROM sys.dm_tran_session_transactions st "
            "JOIN sys.dm_tran_active_transactions t ON t.transaction_id = st.transaction_id "
            "JOIN sys.dm_exec_sessions s ON s.session_id = st.session_id WHERE s.is_user_process = 1 ORDER BY 2 DESC"},
    {"id": "ms_kimlik", "kaynak": ["SERVERPROPERTY"], "kolonlar": ["yalniz_windows"], "maske": [],
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
