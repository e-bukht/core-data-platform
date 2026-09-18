#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f uv.lock ]]; then
  echo "[bootstrap] uv.lock absent: generating with the validated Python 3.12 constraint..."
  uv lock --python 3.12
fi
uv sync --frozen
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
docker compose -f deploy/local/compose.yaml up -d postgres18
uv run alembic upgrade head
./scripts/check.sh
echo "P0-I1 bootstrap complete. Run ./scripts/dev.sh"
