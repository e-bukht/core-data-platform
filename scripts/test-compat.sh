#!/usr/bin/env bash
set -euo pipefail
uv run pytest tests/integration/test_postgres_compatibility.py tests/integration/test_rls.py -v
