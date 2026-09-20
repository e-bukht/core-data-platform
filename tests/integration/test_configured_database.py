from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core_platform.host.settings import get_settings
from core_platform.infrastructure.persistence.schema import EXPECTED_ALEMBIC_REVISION

pytestmark = pytest.mark.integration


async def _query() -> tuple[int, str | None]:
    settings = get_settings()
    url = settings.database_url.get_secret_value()
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            one = int((await connection.execute(text("SELECT 1"))).scalar_one())
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            revision = result.scalar_one_or_none()
            return one, revision
    finally:
        await engine.dispose()


def test_configured_database_is_migrated() -> None:
    one, revision = asyncio.run(_query())
    assert one == 1
    assert revision == EXPECTED_ALEMBIC_REVISION
