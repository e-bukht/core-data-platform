# Context & Trust contract — P0-I2

1. A valid OIDC token authenticates an external identity; it does not authorize a business action.
2. `(issuer, subject)` is the canonical external identity key.
3. Unknown identities never auto-provision an Actor.
4. Every tenant-scoped request requires an explicit tenant selector, an active Tenant, an active TenantMembership and an explicit capability grant.
5. Authorization is default-deny.
6. OAuth/OIDC roles or scopes are never translated automatically into internal capabilities.
7. `ExecutionContext` is immutable and bound through `contextvars` only for the current execution flow.
8. Tenant-scoped PostgreSQL tables require RLS and transaction-local `app.current_tenant_id`.
9. The runtime role must not own tenant tables and must be `NOSUPERUSER NOBYPASSRLS`.
10. The migration/owner connection is distinct from the runtime connection.
