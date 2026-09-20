-- LOCAL DEVELOPMENT ONLY. Static credentials are intentionally non-production.
-- This script runs only when the PostgreSQL data directory is initialized for the first time.
-- Existing P0-I1 volumes must use scripts/bootstrap_db_roles.py instead.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'coredata_migrator') THEN
        CREATE ROLE coredata_migrator
            LOGIN PASSWORD 'local-migrator-only'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    ELSE
        ALTER ROLE coredata_migrator WITH
            LOGIN PASSWORD 'local-migrator-only'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'coredata_runtime') THEN
        CREATE ROLE coredata_runtime
            LOGIN PASSWORD 'local-runtime-only'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    ELSE
        ALTER ROLE coredata_runtime WITH
            LOGIN PASSWORD 'local-runtime-only'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

ALTER DATABASE coredata OWNER TO coredata_migrator;
GRANT CONNECT ON DATABASE coredata TO coredata_migrator, coredata_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
