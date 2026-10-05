from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import QueuePool

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


@dataclass(frozen=True, slots=True)
class DatabasePoolSnapshot:
    size: int
    checked_in: int
    checked_out: int
    overflow: int


class Database:
    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    @property
    def instrumentation_engine(self) -> Engine:
        """Expose the synchronous engine only to infrastructure instrumentation adapters."""
        return self._engine.sync_engine

    def pool_snapshot(self) -> DatabasePoolSnapshot:
        pool = self._engine.sync_engine.pool

        if not isinstance(pool, QueuePool):
            raise RuntimeError("Database pool does not expose QueuePool metrics")

        return DatabasePoolSnapshot(
            size=pool.size(),
            checked_in=pool.checkedin(),
            checked_out=pool.checkedout(),
            overflow=pool.overflow(),
        )

    async def close(self) -> None:
        await self._engine.dispose()

    @asynccontextmanager
    async def open_connection(self) -> AsyncIterator[AsyncConnection]:
        async with self._engine.connect() as connection:
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self._engine.connect() as connection, connection.begin():
            yield connection

    @asynccontextmanager
    async def tenant_transaction(self, tenant_id: UUID) -> AsyncIterator[AsyncConnection]:
        async with self._engine.connect() as connection, connection.begin():
            await connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            yield connection

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
