# Core Data Model Platform — Phase 0 / P0-I2 Context & Trust

Executable Python implementation of the validated **P0-I2 Implementation Blueprint — Context & Trust v1.0**, built on the certified P0-I1 foundation.

## What P0-I2 adds

- `Tenant` and `TenantMembership`
- generic `Actor` (`HUMAN`, `AGENT`, `SERVICE`, `INTEGRATION`, `SYSTEM`)
- external OIDC identity mapping by `(issuer, subject)`
- hardened JWT validation with RS256 allowlist, OIDC discovery and JWKS cache
- immutable `AuthenticationContext` and `ExecutionContext`
- async-safe context propagation with `contextvars`
- `Capability`, tenant-scoped grants and a default-deny in-process PDP
- FastAPI Policy Enforcement Point dependencies
- separate PostgreSQL migration/runtime connections
- transaction-local tenant DB context via `set_config(..., true)`
- PostgreSQL Row-Level Security on tenant-scoped tables
- Keycloak 26.7.4 local reference provider

A valid JWT **never authorizes a business action by itself**. Authorization requires an active Actor,
an active Tenant, an active membership, and an explicit capability grant. RLS is a second independent
barrier against cross-tenant access.

## Reference stack

- CPython 3.12
- uv 0.12.15
- FastAPI / Uvicorn
- PyJWT 2.14 + cryptography
- HTTPX 0.28.1
- SQLAlchemy 2.0 + Psycopg 3
- Alembic
- PostgreSQL 12.22 compatibility floor / PostgreSQL 18 reference runtime
- Keycloak 26.7.4 for local OIDC certification
- pytest + Testcontainers + Hypothesis
- Ruff + mypy strict + Import Linter

## Architecture dependency rule

```text
host / infrastructure
        ↓
application
        ↓
platform_kernel
        ↓
foundation
```

`foundation` and `platform_kernel` must remain independent of FastAPI, Pydantic, SQLAlchemy, Psycopg,
PyJWT, HTTPX, structlog and host/infrastructure adapters.

## Database identities

P0-I2 intentionally separates database identities:

- `coredata_migrator`: schema owner / Alembic connection
- `coredata_runtime`: application connection, `NOSUPERUSER`, `NOBYPASSRLS`, non-owner

The runtime URL is `CORE_PLATFORM_DATABASE_URL`; Alembic uses
`CORE_PLATFORM_MIGRATION_DATABASE_URL`.

## Fresh local P0-I2 environment

Prerequisites: Python 3.12, uv, Docker Desktop/Compose.

```bash
cp .env.example .env
uv lock
uv sync --locked
docker compose -f deploy/local/compose.yaml up -d postgres18
uv run alembic upgrade head
uv run python scripts/bootstrap_context_trust.py
```

On a **new** PostgreSQL data volume, the compose init script creates `coredata_migrator` and
`coredata_runtime` before Alembic runs. On an **existing certified P0-I1** volume, Docker init scripts
are not replayed; run `scripts/bootstrap_db_roles.py` first as described below.

The default compose mapping is PostgreSQL 18 on `localhost:5434` so it can coexist with the native
PostgreSQL 12 installation used during P0-I1.

Start the API:

```bash
uv run uvicorn core_platform.host.main:app --reload --port 8080
```

Public technical endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /version`

Protected platform endpoints:

- `GET /platform/context` → `platform.context.read`
- `GET /platform/tenant` → `platform.tenant.read`
- `GET /platform/actor/me` → `platform.actor.read.self`
- `GET /platform/capabilities` → `platform.capability.read.self`

Protected calls require `Authorization: Bearer ...` and `X-Tenant-Id`.

## Upgrading an existing certified P0-I1 database

Do **not** delete the existing database or Docker volume. Create the new DB roles with an admin/current
owner connection, transfer P0-I1 ownership to the migrator, then run migration `0002`.

PowerShell example for the existing native PostgreSQL 12 instance:

```powershell
$env:CORE_PLATFORM_ADMIN_DATABASE_URL="postgresql+psycopg://postgres:<admin-password>@localhost:5433/coredata"
$env:CORE_PLATFORM_MIGRATION_DATABASE_URL="postgresql+psycopg://coredata_migrator:local-migrator-only@localhost:5433/coredata"
$env:CORE_PLATFORM_DATABASE_URL="postgresql+psycopg://coredata_runtime:local-runtime-only@localhost:5433/coredata"
uv run python scripts/bootstrap_db_roles.py
uv run alembic upgrade head
```

Then update `.env` with the migration/runtime URLs. The admin URL is needed only for the role bootstrap
and must not be kept as an application secret. The bootstrap is idempotent for the P0-I2 local roles
and transfers the P0-I1 `platform` schema plus `public.alembic_version` ownership to the migrator.

## Local Keycloak certification

Start the reference IdP:

```powershell
docker compose -f deploy/local/compose.yaml --profile identity up -d keycloak
```

The imported local realm contains a development-only `alice` account and the `core-data-cli` client.
All credentials in the compose/realm files are strictly local test credentials.

After PostgreSQL migration and fixture bootstrap, execute:

```powershell
./scripts/test_keycloak_e2e.ps1
```

This obtains a real RS256 Keycloak token and calls `/platform/context` through the complete
Authentication → Actor → Tenant → PDP → ExecutionContext pipeline.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run lint-imports
uv run pytest -m "not integration and not compatibility and not identity"
uv run pip-audit
uv run bandit -r src
```

Integration/security matrix with Docker:

```bash
uv run pytest tests/integration/test_postgres_compatibility.py -v
uv run pytest tests/integration/test_rls.py -v
```

The matrix certifies migrations and RLS on PostgreSQL 12.22 and 18.x.

## Lockfile

This generated artifact is produced in an offline environment and therefore does not contain the final
P0-I2 `uv.lock`. The upgrade patch is intended for the certified P0-I1 repository, where the existing
lockfile remains in place. Run `uv lock`, review the PyJWT/HTTPX/cryptography delta, then run
`uv sync --locked`. Commit the updated lockfile only after all P0-I2 certification gates pass.
