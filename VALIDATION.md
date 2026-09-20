# Validation status — P0-I2 Context & Trust implementation

Generated: 2026-09-19

## Release posture

This artifact is an **implementation candidate**, not a certified P0-I2 release. Certification remains
bound to the validated workstation and requires all `C-I2-01` through `C-I2-20` to pass. Any
cross-tenant read/write, RLS bypass, execution-context leakage or permissive authentication fallback
is an immediate **NO-GO**.

## Passed in the artifact-generation environment

- `pyproject.toml` TOML validation — **PASS**.
- Keycloak realm JSON validation — **PASS**.
- Docker Compose / GitHub Actions YAML parse validation — **PASS**.
- Python compilation for `src/`, `migrations/`, `tests/` and `scripts/` — **PASS**.
- Available P0-I1 foundation, P0-I2 Platform Kernel, application, settings and OIDC tests —
  **46 passed** after final release hardening.
- Architecture source/AST fitness tests available without the full dependency graph — **PASS**.
- OIDC tests cover valid RS256, wrong audience, expiration, disallowed algorithm, wrong issuer,
  invalid signature, unknown `kid`, JWKS outage, and concurrent JWKS refresh coalescing.
- Execution-context tests cover deterministic reset and 100 concurrent async executions without
  `contextvars` leakage.
- Upgrade logic was hardened so an existing P0-I1 PostgreSQL volume keeps its original local bootstrap
  identity until dedicated migrator/runtime roles are created.
- The compatibility test now models a true P0-I1→P0-I2 transition: revision `0001` is first applied by
  the original owner, ownership is transferred, then `0002` is applied by `coredata_migrator`.

## Not executable in the artifact-generation environment

The generator is Python 3.13 and has no Docker daemon, PostgreSQL service, Keycloak service, certified
Python 3.12 virtual environment or complete P0-I2 dependency graph. Therefore the following gates are
supplied as executable tests/runbooks but are **not claimed as passed here**:

- final P0-I2 `uv.lock` resolution after adding PyJWT/HTTPX/cryptography;
- Ruff 0.16.3 and Ruff format on the final dependency graph;
- mypy 2.3.1 strict;
- Import Linter CLI;
- PostgreSQL 12.22 / 18 migration `0002_context_trust` execution;
- runtime/migrator role certification;
- PostgreSQL RLS cross-tenant read/write tests;
- pool reuse / transaction-local tenant leakage tests;
- Keycloak 26.7.4 end-to-end RS256 token test;
- pip-audit, Bandit, Gitleaks and final CycloneDX SBOM after lockfile regeneration.

## Required certification on the certified P0-I1 workstation

1. Apply `p0-i1-to-p0-i2-context-trust.patch` to the clean certified P0-I1 repository.
2. Run `uv lock`, review the dependency delta and commit the updated `uv.lock` only after all gates pass.
3. Run `uv sync --locked`.
4. Bootstrap dedicated database roles on each existing P0-I1 database with
   `scripts/bootstrap_db_roles.py` using a temporary admin/current-owner connection.
5. Set runtime and migration URLs in `.env`; do not persist the admin URL.
6. Run `uv run alembic upgrade head` and confirm `0002_context_trust (head)`.
7. Run Ruff, Ruff format, mypy strict, Import Linter and the complete pytest suite.
8. Run PostgreSQL compatibility/RLS tests on 12.22 and 18.
9. Start the Keycloak `identity` profile and run `scripts/test_keycloak_e2e.ps1`.
10. Re-run pip-audit, Bandit and Gitleaks.
11. Regenerate runtime/full CycloneDX SBOMs and validate them.
12. Confirm a clean Git tree and record the certification evidence in `CERTIFICATION_P0_I2.md`.

## Go/No-Go rule

P0-I3 must not start until every `C-I2-01` through `C-I2-20` criterion in
`CERTIFICATION_P0_I2.md` is **PASS**.
