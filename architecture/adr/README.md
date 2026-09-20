# Architecture Decision Records

P0-I1 accepted decisions remain in force. P0-I2 adds:

- I2-ADR-001 — external IdP; platform is an OAuth2/OIDC resource server
- I2-ADR-002 — token claims are not business authorization
- I2-ADR-003 — `(issuer, subject)` is the external identity key
- I2-ADR-004 — Actor is distinct from Party
- I2-ADR-005 — tenant selector is untrusted input
- I2-ADR-006 — `contextvars` for ExecutionContext
- I2-ADR-007 — in-process default-deny PDP
- I2-ADR-008 — RLS mandatory for tenant-scoped data
- I2-ADR-009 — transaction-local DB tenant context
- I2-ADR-010 — migrator role distinct from runtime role
- I2-ADR-011 — RS256 allowlist initially
- I2-ADR-012 — no Actor auto-provisioning from unknown tokens
