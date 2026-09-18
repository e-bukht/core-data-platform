# Contributing

## Mandatory gates

Before opening a pull request:

```bash
./scripts/check.sh
```

For SQL/migration changes also run:

```bash
./scripts/test-compat.sh
```

## Architecture

- Domain/foundation code must stay framework-independent.
- FastAPI belongs to `host`.
- SQLAlchemy/Psycopg/Alembic belong to `infrastructure` and `migrations`.
- Do not modify a migration that has already been merged/released; add a new revision.
- Do not use SQLite/H2 as a persistence substitute for PostgreSQL tests.
- Do not introduce `float` for monetary or precise quantity calculations.
