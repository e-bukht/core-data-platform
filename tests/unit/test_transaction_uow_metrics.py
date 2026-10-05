from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import cast
from uuid import UUID

from core_platform.infrastructure.observability.metrics import (
    TransactionOutcome,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWork,
)
from core_platform.transaction_kernel.models import TransactionContext


class _FakeTransaction:
    def __init__(self) -> None:
        self.is_active = True

    async def commit(self) -> None:
        self.is_active = False

    async def rollback(self) -> None:
        self.is_active = False


class _FakeConnection:
    def __init__(self) -> None:
        self.transaction = _FakeTransaction()

    async def begin(self) -> _FakeTransaction:
        return self.transaction

    async def execute(
        self,
        statement: object,
        parameters: object | None = None,
    ) -> None:
        del statement, parameters


class _FakeConnectionContext(
    AbstractAsyncContextManager[_FakeConnection],
):
    def __init__(self) -> None:
        self.connection = _FakeConnection()

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class _FakeDatabase:
    def open_connection(self) -> _FakeConnectionContext:
        return _FakeConnectionContext()


@dataclass(frozen=True)
class _Identifier:
    value: UUID


@dataclass(frozen=True)
class _FakeContext:
    tenant_id: _Identifier
    actor_id: _Identifier
    correlation_id: _Identifier


class _RecordingMetrics:
    def __init__(self) -> None:
        self.started = 0
        self.completed: list[tuple[TransactionOutcome, float]] = []

    def observe_database_pool(self, database: Database) -> None:
        del database

    def record_transaction_started(self) -> None:
        self.started += 1

    def record_transaction_completed(
        self,
        *,
        outcome: TransactionOutcome,
        duration_seconds: float,
    ) -> None:
        self.completed.append((outcome, duration_seconds))


def _context() -> TransactionContext:
    return cast(
        TransactionContext,
        _FakeContext(
            tenant_id=_Identifier(
                UUID("00000000-0000-0000-0000-000000000001")
            ),
            actor_id=_Identifier(
                UUID("00000000-0000-0000-0000-000000000002")
            ),
            correlation_id=_Identifier(
                UUID("00000000-0000-0000-0000-000000000003")
            ),
        ),
    )


def _database() -> Database:
    return cast(Database, _FakeDatabase())


async def _exercise_uow_metrics() -> _RecordingMetrics:
    metrics = _RecordingMetrics()

    async with PostgresUnitOfWork(
        _database(),
        _context(),
        metrics=metrics,
    ) as uow:
        await uow.commit()

    async with PostgresUnitOfWork(
        _database(),
        _context(),
        metrics=metrics,
    ) as uow:
        await uow.rollback()

    try:
        async with PostgresUnitOfWork(
            _database(),
            _context(),
            metrics=metrics,
        ):
            raise RuntimeError("simulated business failure")
    except RuntimeError:
        pass

    return metrics


def test_uow_records_low_cardinality_transaction_outcomes() -> None:
    metrics = asyncio.run(_exercise_uow_metrics())

    assert metrics.started == 3
    assert [outcome for outcome, _ in metrics.completed] == [
        "committed",
        "rolled_back",
        "failed",
    ]
    assert all(duration >= 0.0 for _, duration in metrics.completed)