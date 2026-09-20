# P0-I2 Context & Trust - Certification Record

Status: **CERTIFIED - PASS WITH OBSERVATIONS - GO P0-I3**

Certification date: 2026-09-20
Blueprint: `P0-I2 Implementation Blueprint - Context & Trust v1.0`

## Certified environment

- OS: Windows 11
- Python: CPython 3.12.4
- pytest: 9.0.3
- PostgreSQL compatibility floor: 12.22
- PostgreSQL reference: 18
- Keycloak: local OIDC provider
- Database runtime isolation: PostgreSQL RLS with FORCE ROW LEVEL SECURITY
- Runtime role: non-owner, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOBYPASSRLS

## Certification matrix

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| C-I2-01 | Valid Keycloak RS256 token accepted. | PASS | Live Keycloak -> discovery/JWKS -> RS256 JWT -> `/platform/context` returned HTTP 200 with expected tenant, actor, issuer and subject. |
| C-I2-02 | Invalid signature, issuer, audience, expiry or algorithm rejected. | PASS | Final unit suite passes wrong-audience, expired-token, forbidden-algorithm, wrong-issuer and invalid-signature tests. |
| C-I2-03 | Unknown identity is denied and never auto-provisioned. | PASS | `test_unknown_identity_is_denied` passes; authorization denies unknown `(issuer, subject)` and no auto-provisioning path is used. |
| C-I2-04 | Suspended Actor denied. | PASS | `test_suspended_actor_is_denied` passes with `ACTOR.NOT.ACTIVE`. |
| C-I2-05 | Missing, invalid or inactive tenant and missing/inactive membership denied per contract. | PASS | Missing tenant, malformed tenant ID, suspended tenant, missing membership and suspended membership tests all pass. |
| C-I2-06 | Default-deny capability policy; explicit grant permits action. | PASS | PDP default-deny and explicit-active-grant tests pass; live E2E logs `effect=ALLOW` only for granted capability. |
| C-I2-07 | ExecutionContext is correct and reset after execution. | PASS | Context construction and `test_execution_context_is_reset` pass. |
| C-I2-08 | Concurrent executions do not leak `contextvars`. | PASS | `test_execution_context_isolated_across_100_async_tasks` passes. |
| C-I2-09 | RLS blocks cross-tenant reads on PostgreSQL 12.22 and 18. | PASS | `test_rls_and_runtime_role_isolation` passes on PostgreSQL 12.22 and 18 with FORCE RLS enabled. |
| C-I2-10 | RLS blocks cross-tenant writes on PostgreSQL 12.22 and 18. | PASS | Cross-tenant write assertions pass on PostgreSQL 12.22 and 18. |
| C-I2-11 | Missing DB tenant context returns no tenant-scoped rows. | PASS | RLS integration assertions confirm zero tenant-scoped rows without `app.current_tenant_id`. |
| C-I2-12 | Connection-pool reuse does not leak transaction-local tenant context. | PASS | Pool-reuse A -> B isolation assertions pass using transaction-local tenant context. |
| C-I2-13 | Runtime role is not owner, superuser or BYPASSRLS. | PASS | Integration role assertions pass; live PostgreSQL verification shows runtime and migrator roles with all privileged flags false. |
| C-I2-14 | OIDC/JWKS outage fails closed; no permissive fallback. | PASS | `test_jwks_outage_fails_closed_when_no_valid_cached_key` passes. |
| C-I2-15 | Unknown `kid` refresh is controlled and fails closed. | PASS | Unknown-kid fail-closed, single-refresh and concurrent-refresh coalescing tests pass. |
| C-I2-16 | Correlation ID is preserved/generated and present in policy logs. | PASS | Contract tests verify preservation and generation; live authorization log contains the supplied correlation ID. |
| C-I2-17 | Import Linter and architecture fitness rules pass. | PASS | 4 architecture contracts kept, 0 broken; architecture tests pass. |
| C-I2-18 | Ruff, mypy, pytest, security scans and SBOM are green. | PASS | Ruff PASS; 100 files formatted; mypy 81 files/0 errors; pytest 62/62; pip-audit 0 known vulnerabilities; Bandit 0 findings; Gitleaks history/worktree 0 leaks; CycloneDX SBOM generated. |
| C-I2-19 | Fresh migration and P0-I1 -> P0-I2 upgrade pass on supported PostgreSQL matrix. | PASS | Fresh and existing-P0-I1 upgrade paths pass on PostgreSQL 12.22 and 18; local pre-P0-I2 dump replayed successfully to `0002_context_trust`. |
| C-I2-20 | Local runbook reproduces Keycloak + PostgreSQL 18 + protected API. | PASS | `scripts/test_keycloak_e2e.ps1` starts the API through the Windows SelectorEventLoop launcher and returns HTTP 200 from `/platform/context`. |

## RLS certification evidence

The certified PostgreSQL 18 replay reports:

- `platform.capability_grant`: RLS enabled = true, FORCE RLS = true
- `platform.tenant_membership`: RLS enabled = true, FORCE RLS = true

The certified database roles report:

- `coredata_migrator`: NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOBYPASSRLS
- `coredata_runtime`: NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOBYPASSRLS

## Quality and security evidence

Final code-quality run:

- Ruff check: PASS
- Ruff format check: PASS
- mypy: 81 source files, 0 errors
- Import Linter: 4 contracts kept, 0 broken
- pytest: 62 passed, 2 non-blocking dependency deprecation warnings
- pip-audit: no known vulnerabilities
- Bandit: 0 findings
- Gitleaks Git history: no leaks
- Gitleaks worktree: no leaks
- CycloneDX SBOM: `sbom.cdx.json`
- SBOM SHA256: `0CC6C5C105D7E9DA4856C0A408E702DEE2F3E521939F8D65154F387CDAE2E1B8`

## Live OIDC evidence

The certified local E2E path successfully exercised:

Keycloak -> OIDC discovery -> JWKS -> RS256 JWT validation -> external identity resolution -> Actor validation -> Tenant validation -> Membership validation -> explicit Capability grant -> PDP ALLOW -> ExecutionContext -> PostgreSQL runtime access -> protected HTTP endpoint.

Observed result:

- HTTP endpoint: `GET /platform/context`
- HTTP status: `200 OK`
- tenant: `00000000-0000-7000-8000-000000000001`
- actor: `00000000-0000-7000-8000-000000000002`
- actor type: `HUMAN`
- subject: `11111111-1111-4111-8111-111111111111`
- correlation ID: `00000000-0000-7000-8000-000000000099`
- authorization decision: `ALLOW`

## Observations

1. Local CPython is 3.12.4. The project remains on the certified Python 3.12 minor line; patch-level alignment can be handled independently.
2. pytest reports two dependency deprecation warnings involving FastAPI/Starlette TestClient internals. They are non-blocking for P0-I2.
3. On Windows, async Psycopg requires a SelectorEventLoop. `scripts/run_api.py` provides the certified launcher for the local E2E path.

## Final decision

All C-I2-01 through C-I2-20 technical criteria are satisfied.

No unresolved cross-tenant isolation, RLS bypass, context leakage or permissive authentication fallback finding remains.

The repository seal for this record consists of the final secret scan, Git integrity check, certification commit and post-commit clean-working-tree verification.

**P0-I2 PASS WITH OBSERVATIONS - GO P0-I3**
