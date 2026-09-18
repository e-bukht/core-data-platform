# Validation status of delivered P0-I1 skeleton

Generated: 2026-09-17

## Passed in the artifact-generation environment

- `pyproject.toml` TOML/metadata validation — **PASS**.
- Python source compilation for `src/`, `migrations/`, and `tests/` — **PASS**.
- Pure foundation + architecture tests — **PASS: 17 passed**.
- Framework-independence AST gate for `core_platform.foundation` — included in the passing tests.
- Alembic expected-head consistency gate — included in the passing tests.

## Not executable in the artifact-generation environment

The generator host has **Python 3.13**, no Docker daemon, and no outbound package-network access.
Therefore the following certification gates are intentionally **NOT claimed as passed**:

- Python 3.12 runtime execution.
- `uv lock` / `uv sync --frozen` with the validated dependency versions.
- Ruff, mypy strict, Import Linter, Hypothesis, pip-audit, Bandit, CycloneDX tools.
- FastAPI host startup with the exact locked stack.
- Docker/Testcontainers.
- PostgreSQL 12.22 and PostgreSQL 18 Alembic matrix.
- CI workflow execution.

## Required first-run certification

On a connected machine with Python 3.12, uv and Docker:

1. `./scripts/dev.sh` — generates `uv.lock` if absent and starts the platform locally.
2. Commit the generated `uv.lock`.
3. `./scripts/check.sh`.
4. `./scripts/test-compat.sh`.
5. Push and require the GitHub Actions CI matrix to pass.

A missing `uv.lock` is deliberate in this delivered archive because generating a trustworthy lockfile
requires package-index access. CI is configured to reject a missing lockfile after bootstrap.
