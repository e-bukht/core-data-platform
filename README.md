# Core Data Model Platform — Phase 0 / P0-I1

Executable Python skeleton for the validated **Phase 0 Implementation Blueprint — Increment P0-I1**.

## Reference stack

- CPython 3.12
- uv
- FastAPI / Uvicorn
- Pydantic at system boundaries only
- SQLAlchemy 2.0 Core-first + Psycopg 3
- Alembic
- PostgreSQL 12.22 compatibility floor / PostgreSQL 18 reference runtime
- pytest + Testcontainers + Hypothesis
- Ruff + mypy strict + Import Linter

## Architectural rule

`core_platform.foundation` is pure Python domain foundation. It must not import FastAPI, Pydantic,
SQLAlchemy, Psycopg, Alembic, structlog, asyncio, the infrastructure layer, or the host.

## First run — one command

Prerequisites: Python 3.12, uv, Docker with Compose.

```bash
./scripts/dev.sh
```

On first run the script generates `uv.lock` when absent (network required once), synchronizes the environment, creates `.env` from `.env.example`, starts PostgreSQL 18, applies Alembic migrations, and starts the API.

To bootstrap **and** run the verification suite without keeping the API process attached:

```bash
./scripts/bootstrap.sh
```

Health endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /version`

## Quality gates

```bash
./scripts/check.sh
```

The full CI additionally executes PostgreSQL 12/18 compatibility tests.

## PostgreSQL compatibility

PostgreSQL 12.22 is an **EOL compatibility floor**, not the preferred new-production runtime.
PostgreSQL 18 is the reference runtime. Migrations must pass on both while the PG12 floor is active.

## Lockfile note

The delivered artifact may not contain a generated `uv.lock` when produced in an offline build
environment. `scripts/bootstrap.sh` generates it on the first connected Python 3.12 environment and
requires that it then be committed. CI rejects a missing or stale lockfile.
