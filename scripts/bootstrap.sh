#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f uv.lock ]]; then
  echo "[bootstrap] uv.lock absent: generate it on a connected Python 3.12 environment."
  uv lock --python 3.12
fi
uv sync --frozen
[[ -f .env ]] || cp .env.example .env
docker compose -f deploy/local/compose.yaml up -d postgres18
uv run alembic upgrade head
uv run python scripts/bootstrap_context_trust.py
./scripts/check.sh
echo "P0-I2 bootstrap complete. Optional: start Keycloak with --profile identity."
