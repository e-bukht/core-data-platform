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
        "postgresql+psycopg://coredata:local-only@localhost:5432/coredata",
    )

os.environ.setdefault("CORE_PLATFORM_ENVIRONMENT", "test")
