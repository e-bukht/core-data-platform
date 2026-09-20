from __future__ import annotations

import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def _psycopg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _role_credentials(sqlalchemy_url: str) -> tuple[str, str]:
    parsed = make_url(sqlalchemy_url)
    if not parsed.username or parsed.password is None:
        raise RuntimeError("Database URL must contain username and password")
    return parsed.username, parsed.password


def _database_name(sqlalchemy_url: str) -> str:
    parsed = make_url(sqlalchemy_url)
    if not parsed.database:
        raise RuntimeError("Database URL must contain a database name")
    return parsed.database


def _ensure_login_role(
    cursor: psycopg.Cursor[tuple[object, ...]], role: str, password: str
) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        return

    cursor.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN PASSWORD {} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
        ).format(sql.Identifier(role), sql.Literal(password))
    )


def _transfer_existing_p0_i1_ownership(
    cursor: psycopg.Cursor[tuple[object, ...]], *, database: str, migrator_role: str
) -> None:
    cursor.execute(
        sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
            sql.Identifier(database), sql.Identifier(migrator_role)
        )
    )

    cursor.execute("SELECT to_regnamespace('platform')")
    row = cursor.fetchone()
    if row is not None and row[0] is not None:
        cursor.execute(
            sql.SQL("ALTER SCHEMA platform OWNER TO {}").format(sql.Identifier(migrator_role))
        )

    # P0-I1 stores Alembic's version table in public. Transfer it so the dedicated
    # migrator can update the revision during the P0-I2 upgrade.
    cursor.execute("SELECT to_regclass('public.alembic_version')")
    row = cursor.fetchone()
    if row is not None and row[0] is not None:
        cursor.execute(
            sql.SQL("ALTER TABLE public.alembic_version OWNER TO {}").format(
                sql.Identifier(migrator_role)
            )
        )


def main() -> None:
    admin_url = os.environ["CORE_PLATFORM_ADMIN_DATABASE_URL"]
    migration_url = os.environ["CORE_PLATFORM_MIGRATION_DATABASE_URL"]
    runtime_url = os.environ["CORE_PLATFORM_DATABASE_URL"]

    migrator_role, migrator_password = _role_credentials(migration_url)
    runtime_role, runtime_password = _role_credentials(runtime_url)
    database = _database_name(migration_url)

    if migrator_role == runtime_role:
        raise RuntimeError("Migration and runtime database roles must be distinct")

    with (
        psycopg.connect(_psycopg_dsn(admin_url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        _ensure_login_role(cursor, migrator_role, migrator_password)
        _ensure_login_role(cursor, runtime_role, runtime_password)
        _transfer_existing_p0_i1_ownership(cursor, database=database, migrator_role=migrator_role)
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                sql.Identifier(database),
                sql.Identifier(migrator_role),
                sql.Identifier(runtime_role),
            )
        )
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

    print(f"Database roles ready: migrator={migrator_role}, runtime={runtime_role}")


if __name__ == "__main__":
    main()
