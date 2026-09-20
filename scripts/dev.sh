#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f uv.lock ]]; then
  uv lock --python 3.12
fi
uv sync --frozen
[[ -f .env ]] || cp .env.example .env
docker compose -f deploy/local/compose.yaml up -d postgres18
uv run alembic upgrade head
uv run python scripts/bootstrap_context_trust.py
exec uv run uvicorn core_platform.host.main:app --reload --host 127.0.0.1 --port 8080
