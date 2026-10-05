from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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


def _test_only_evidence_key() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


# Applied during pytest bootstrap, before test modules import the global ASGI app.
# Test-only material remains process-local and is never printed or persisted.
os.environ.setdefault("CORE_PLATFORM_EVIDENCE_SIGNING_KEY_ID", "test-ephemeral-ed25519")
if not os.environ.get("CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64"):
    os.environ["CORE_PLATFORM_EVIDENCE_SIGNING_PRIVATE_KEY_B64"] = (
        _test_only_evidence_key()
    )
