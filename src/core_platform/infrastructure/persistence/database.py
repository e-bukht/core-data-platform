from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core_platform.infrastructure.persistence.schema import EXPECTED_ALEMBIC_REVISION


@dataclass(slots=True)
class DatabaseReadiness:
    reachable: bool
    migrated: bool
    revision: str | None = None
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.reachable and self.migrated


class Database:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def readiness(self) -> DatabaseReadiness:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                result = await connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                revision = result.scalar_one_or_none()
                return DatabaseReadiness(
                    reachable=True,
                    migrated=revision == EXPECTED_ALEMBIC_REVISION,
                    revision=revision,
                )
        except Exception as exc:  # boundary converts infrastructure errors to readiness state
            return DatabaseReadiness(
                reachable=False,
                migrated=False,
                error=type(exc).__name__,
            )
