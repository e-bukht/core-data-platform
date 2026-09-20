# Context & Trust threat model — P0-I2

## Critical threats

- Cross-tenant reads/writes caused by missing application filters.
- RLS bypass because the runtime role owns tables, is superuser, or has BYPASSRLS.
- Tenant context leaking between pooled database connections.
- OIDC algorithm confusion or trusting an algorithm supplied by an untrusted JWT header.
- Mapping external IdP roles/scopes directly to internal authorization.
- ContextVar state leaking across concurrent requests/tasks.
- Unknown signing-key refresh storms or permissive fallback during IdP outage.

## Controls

- Application tenant validation + PostgreSQL RLS defense in depth.
- Distinct migrator/runtime roles; runtime `NOSUPERUSER NOBYPASSRLS` and non-owner.
- `set_config('app.current_tenant_id', ..., true)` inside every tenant transaction.
- Fixed server-side RS256 allowlist, issuer/audience/time validation and JWKS cache.
- Explicit `(issuer, subject) -> Actor` mapping and default-deny capability PDP.
- `ContextVar` token reset in `finally` and 100-task concurrency tests.
- Locked JWKS refresh, one refresh for an unknown `kid`, fail closed if unresolved.
