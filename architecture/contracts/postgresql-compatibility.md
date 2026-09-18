# PostgreSQL compatibility contract

While PostgreSQL 12.22 remains the declared compatibility floor:

- every Alembic revision MUST apply cleanly on PostgreSQL 12.22 and PostgreSQL 18.x;
- Core transaction SQL MUST avoid features absent from PostgreSQL 12;
- PostgreSQL 18-only optimizations require an explicit adapter/fallback decision;
- PostgreSQL 12 is not the recommended runtime for new installations because it is EOL.

CI provides PostgreSQL as a service per matrix entry. The Testcontainers compatibility tests are an
additional local/pre-release gate and intentionally do not launch nested containers in that matrix.
