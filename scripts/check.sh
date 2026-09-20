#!/usr/bin/env bash
set -euo pipefail
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run lint-imports
uv run pytest -m "not integration and not compatibility and not identity"
uv run pip-audit
uv run bandit -q -r src
