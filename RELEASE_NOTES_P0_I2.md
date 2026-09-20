# Release notes — P0-I2 Context & Trust implementation candidate

## Added

- Tenant, Actor, ExternalIdentity, TenantMembership, Capability and CapabilityGrant platform model.
- Immutable AuthenticationContext and ExecutionContext with async-safe `contextvars` propagation.
- OIDC discovery, RS256 JWT validation and JWKS cache with concurrent refresh coalescing.
- Default-deny capability PDP and FastAPI policy-enforcement dependencies.
- PostgreSQL transaction-local tenant context and RLS policies.
- Dedicated `coredata_migrator` and `coredata_runtime` roles.
- Alembic revision `0002_context_trust`.
- PostgreSQL 12.22 / 18 migration and RLS compatibility tests.
- Keycloak local reference realm and end-to-end certification script.
- P0-I2 certification record covering C-I2-01 through C-I2-20.

## Upgrade compatibility

The Docker Compose PostgreSQL bootstrap identity remains compatible with the certified P0-I1 local
volume (`coredata` / `local-only`). New volumes create the P0-I2 migrator/runtime roles during initial
bootstrap; existing volumes use `scripts/bootstrap_db_roles.py` before applying migration `0002`.

## Certification state

This package is **not yet P0-I2 certified**. It is the implementation candidate to install on the
certified P0-I1 workstation and run through all C-I2 gates.
