# Security policy — P0-I2 Context & Trust

- Never commit production secrets, private keys, access tokens or `.env`.
- OIDC tokens authenticate identities; they do **not** directly grant domain capabilities.
- Unknown identities are denied; P0-I2 performs no just-in-time actor provisioning.
- JWT verification is fail-closed and restricted to the configured RS256 policy.
- Tenant selectors from HTTP are untrusted and must be validated through membership and policy checks.
- Runtime database users must be `NOSUPERUSER`, `NOBYPASSRLS` and must not own tenant-scoped tables.
- Tenant-scoped database access uses transaction-local context and PostgreSQL Row-Level Security.
- The migration/admin database URLs are operational secrets and must never be used by the application runtime.
- Local Compose/Keycloak credentials are development-only fixtures and must never be reused outside local/CI environments.
- Any cross-tenant read/write, RLS bypass, context leak or permissive authentication fallback is a release blocker.
- Security scans and the C-I2 certification record are merge/release gates.
