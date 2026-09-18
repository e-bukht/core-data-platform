from __future__ import annotations

import re
from pathlib import Path

from core_platform.infrastructure.persistence.schema import EXPECTED_ALEMBIC_REVISION


def test_expected_revision_matches_latest_bootstrap_migration() -> None:
    versions_dir = Path(__file__).parents[2] / "migrations" / "versions"
    revisions: list[str] = []
    for file in versions_dir.glob("*.py"):
        match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', file.read_text(), re.MULTILINE)
        if match:
            revisions.append(match.group(1))
    assert EXPECTED_ALEMBIC_REVISION in revisions
