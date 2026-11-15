-- 0001: roller, veritabani yetkileri, alig semasi ve schema_migrations (ALIG-DB-003a).
-- Bu dosya yalniz ilk kurulumda, CREATEROLE yetkili bir yonetici (ya da superuser) ile uygulanir.
-- Parola ICERMEZ: roller parolasiz olusur; parola ayri bir adimda ALTER ROLE ile verilir (db/README.md).
-- Roller kume geneldir; dosya birden cok veritabaninda (staging, test) tekrar uygulanabilir (idempotent).

DO $rol$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['alig_owner', 'alig_app', 'alig_migrator', 'alig_readonly', 'alig_backup'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END
$rol$;

-- Nesne sahibi: oturum acmaz. Uygulama ve gocu rolu nesne sahibi degildir.
ALTER ROLE alig_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Uygulama: yalniz gereken DML (0005_yetkiler.sql). DDL, rol yonetimi, kopyalama, RLS atlama yok.
ALTER ROLE alig_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Gocu: nesne sahibi rolune gecerek (SET ROLE) DDL yapar; kendi basina nesne sahibi degildir.
ALTER ROLE alig_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Salt okuma: secili tablo ve sutunlarda SELECT.
ALTER ROLE alig_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Yedek: pg_basebackup icin REPLICATION; veritabaninda hicbir yetkisi yok.
ALTER ROLE alig_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE REPLICATION NOBYPASSRLS NOINHERIT;

GRANT alig_owner TO alig_migrator WITH INHERIT FALSE, SET TRUE;

-- Arama yolu ve saat dilimi rol duzeyinde sabit. SET ROLE bu ayarlari yeniden uygulamaz: gocler semayi acikca yazar.
ALTER ROLE alig_app SET search_path = alig, pg_catalog;
ALTER ROLE alig_migrator SET search_path = alig, pg_catalog;
ALTER ROLE alig_readonly SET search_path = alig, pg_catalog;
ALTER ROLE alig_app SET TimeZone = 'UTC';
ALTER ROLE alig_migrator SET TimeZone = 'UTC';
ALTER ROLE alig_readonly SET TimeZone = 'UTC';

-- Veritabani: PUBLIC baglanti ve gecici tablo yetkisi kalkar; yalniz uc rol baglanir.
-- alig_backup baglanmaz: kopyalama baglantisi veritabani yetkisi istemez.
DO $db$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO alig_app, alig_migrator, alig_readonly', current_database());
END
$db$;

-- public semasinda CREATE kalkar. (PostgreSQL 15 ve sonrasinda varsayilan zaten bu; surum farkina bagli kalmamak icin acik yazilir.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS alig AUTHORIZATION alig_owner;
ALTER SCHEMA alig OWNER TO alig_owner;
REVOKE ALL ON SCHEMA alig FROM PUBLIC;
GRANT USAGE ON SCHEMA alig TO alig_app, alig_migrator, alig_readonly;

-- Gocleri kayit tablosu. Satiri db/uygula.py ayni islemde ekler (dosya adi ve SHA-256).
SET ROLE alig_owner;
CREATE TABLE IF NOT EXISTS alig.schema_migrations(
  surum        text PRIMARY KEY CHECK (surum ~ '^[0-9]{4}_[a-z0-9_]+[.]sql$'),
  uygulama_utc timestamptz NOT NULL DEFAULT now(),
  dosya_sha256 text NOT NULL CHECK (dosya_sha256 ~ '^[0-9a-f]{64}$')
);
RESET ROLE;
REVOKE ALL ON alig.schema_migrations FROM PUBLIC;
GRANT SELECT ON alig.schema_migrations TO alig_app, alig_readonly;
-- Gocu rolu kaydi kendisi yazar (db/uygula.py); baska satir degistiremez ya da silemez.
GRANT SELECT, INSERT ON alig.schema_migrations TO alig_migrator;
