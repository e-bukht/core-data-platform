from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if not Path(".env").exists():
    os.environ.setdefault(
        "CORE_PLATFORM_DATABASE_URL",
        "postgresql+psycopg://coredata_runtime:local-runtime-only@localhost:5434/coredata",
    )
    os.environ.setdefault(
        "CORE_PLATFORM_MIGRATION_DATABASE_URL",
        "postgresql+psycopg://coredata_migrator:local-migrator-only@localhost:5434/coredata",
    )
os.environ.setdefault("CORE_PLATFORM_ENVIRONMENT", "test")
os.environ.setdefault(
    "CORE_PLATFORM_OIDC_ISSUER", "http://localhost:8180/realms/core-data-platform"
)
os.environ.setdefault("CORE_PLATFORM_OIDC_AUDIENCE", "core-data-api")
