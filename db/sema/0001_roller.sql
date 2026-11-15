-- 0001: roles, database privileges, the alig schema and schema_migrations (ALIG-DB-003a).
-- This file is applied only at first installation, by an administrator with CREATEROLE privilege (or a superuser).
-- It contains NO credentials: roles are created without a login secret; the secret is given in a separate step with ALTER ROLE (db/README.md).
-- Roles are cluster-wide; the file can be applied again (idempotent) in several databases (staging, test).

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

-- Object owner: does not log in. The application and migrator roles are not the object owner.
ALTER ROLE alig_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Application: only the DML that is needed (0005_yetkiler.sql). No DDL, role management, replication or RLS bypass.
ALTER ROLE alig_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Migrator: does DDL by switching to the object owner role (SET ROLE); it is not the object owner itself.
ALTER ROLE alig_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Read-only: SELECT on selected tables and columns.
ALTER ROLE alig_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
-- Backup: REPLICATION for pg_basebackup; it has no privileges in the database.
ALTER ROLE alig_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE REPLICATION NOBYPASSRLS NOINHERIT;

GRANT alig_owner TO alig_migrator WITH INHERIT FALSE, SET TRUE;

-- The search path and time zone are fixed at role level. SET ROLE does not re-apply these settings: migrations write the schema explicitly.
ALTER ROLE alig_app SET search_path = alig, pg_catalog;
ALTER ROLE alig_migrator SET search_path = alig, pg_catalog;
ALTER ROLE alig_readonly SET search_path = alig, pg_catalog;
ALTER ROLE alig_app SET TimeZone = 'UTC';
ALTER ROLE alig_migrator SET TimeZone = 'UTC';
ALTER ROLE alig_readonly SET TimeZone = 'UTC';

-- Database: PUBLIC loses connect and temporary table privileges; only three roles connect.
-- alig_backup does not connect: a replication connection does not need a database privilege.
DO $db$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO alig_app, alig_migrator, alig_readonly', current_database());
END
$db$;

-- CREATE is removed from the public schema. (This is already the default in PostgreSQL 15 and later; it is written explicitly so as not to depend on the version.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS alig AUTHORIZATION alig_owner;
ALTER SCHEMA alig OWNER TO alig_owner;
REVOKE ALL ON SCHEMA alig FROM PUBLIC;
GRANT USAGE ON SCHEMA alig TO alig_app, alig_migrator, alig_readonly;

-- Migration record table. db/uygula.py adds the row in the same transaction (file name and SHA-256).
SET ROLE alig_owner;
CREATE TABLE IF NOT EXISTS alig.schema_migrations(
  surum        text PRIMARY KEY CHECK (surum ~ '^[0-9]{4}_[a-z0-9_]+[.]sql$'),
  uygulama_utc timestamptz NOT NULL DEFAULT now(),
  dosya_sha256 text NOT NULL CHECK (dosya_sha256 ~ '^[0-9a-f]{64}$')
);
RESET ROLE;
REVOKE ALL ON alig.schema_migrations FROM PUBLIC;
GRANT SELECT ON alig.schema_migrations TO alig_app, alig_readonly;
-- The migrator role writes the record itself (db/uygula.py); it cannot change or delete other rows.
GRANT SELECT, INSERT ON alig.schema_migrations TO alig_migrator;
