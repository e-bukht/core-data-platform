from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol

from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider

from core_platform.infrastructure.persistence.database import Database

TransactionOutcome = Literal[
    "committed",
    "rolled_back",
    "failed",
]


class InfrastructureMetrics(Protocol):
    def observe_database_pool(self, database: Database) -> None: ...

    def record_transaction_started(self) -> None: ...

    def record_transaction_completed(
        self,
        *,
        outcome: TransactionOutcome,
        duration_seconds: float,
    ) -> None: ...

    def record_outbox_added(self) -> None: ...

    def record_outbox_claimed(self, *, count: int) -> None: ...

    def record_outbox_published(self) -> None: ...

    def record_outbox_released(self) -> None: ...

    def record_inbox_lookup(self, *, found: bool) -> None: ...

    def record_inbox_added(self) -> None: ...

    def record_inbox_processed(self) -> None: ...

    def record_platform_error(
        self,
        *,
        category: str,
        status_code: int,
    ) -> None: ...


class NoopInfrastructureMetrics:
    def observe_database_pool(self, database: Database) -> None:
        del database

    def record_transaction_started(self) -> None:
        pass

    def record_transaction_completed(
        self,
        *,
        outcome: TransactionOutcome,
        duration_seconds: float,
    ) -> None:
        del outcome, duration_seconds

    def record_outbox_added(self) -> None:
        pass

    def record_outbox_claimed(self, *, count: int) -> None:
        del count

    def record_outbox_published(self) -> None:
        pass

    def record_outbox_released(self) -> None:
        pass

    def record_inbox_lookup(self, *, found: bool) -> None:
        del found

    def record_inbox_added(self) -> None:
        pass

    def record_inbox_processed(self) -> None:
        pass

    def record_platform_error(
        self,
        *,
        category: str,
        status_code: int,
    ) -> None:
        del category, status_code


class OpenTelemetryInfrastructureMetrics:
    def __init__(self, meter_provider: MeterProvider) -> None:
        self._meter = meter_provider.get_meter(
            "core_platform.infrastructure",
        )
        self._database_pool_observed = False

        self._transaction_started = self._meter.create_counter(
            "core_platform.transaction.started",
            unit="1",
            description="Transactions started by the PostgreSQL Unit of Work",
        )
        self._transaction_completed = self._meter.create_counter(
            "core_platform.transaction.completed",
            unit="1",
            description="Transactions completed by outcome",
        )
        self._transaction_duration = self._meter.create_histogram(
            "core_platform.transaction.duration",
            unit="s",
            description="PostgreSQL Unit of Work transaction duration",
        )

        self._outbox_added = self._meter.create_counter(
            "core_platform.outbox.added",
            unit="1",
            description="Messages added to the transactional Outbox",
        )
        self._outbox_claimed = self._meter.create_counter(
            "core_platform.outbox.claimed",
            unit="1",
            description="Messages successfully claimed from the Outbox",
        )
        self._outbox_published = self._meter.create_counter(
            "core_platform.outbox.published",
            unit="1",
            description="Outbox messages marked as published",
        )
        self._outbox_released = self._meter.create_counter(
            "core_platform.outbox.released",
            unit="1",
            description="Outbox messages released for retry",
        )

        self._inbox_lookup = self._meter.create_counter(
            "core_platform.inbox.lookup",
            unit="1",
            description="Inbox deduplication lookups by result",
        )
        self._inbox_added = self._meter.create_counter(
            "core_platform.inbox.added",
            unit="1",
            description="Messages added to the transactional Inbox",
        )
        self._inbox_processed = self._meter.create_counter(
            "core_platform.inbox.processed",
            unit="1",
            description="Inbox messages marked as processed",
        )

        self._platform_errors = self._meter.create_counter(
            "core_platform.platform.errors",
            unit="1",
            description="Handled platform errors by category and HTTP status",
        )

    def record_transaction_started(self) -> None:
        self._transaction_started.add(1)

    def record_transaction_completed(
        self,
        *,
        outcome: TransactionOutcome,
        duration_seconds: float,
    ) -> None:
        attributes = {"outcome": outcome}

        self._transaction_completed.add(1, attributes)
        self._transaction_duration.record(
            max(duration_seconds, 0.0),
            attributes,
        )

    def record_outbox_added(self) -> None:
        self._outbox_added.add(1)

    def record_outbox_claimed(self, *, count: int) -> None:
        if count < 0:
            raise ValueError("Outbox claimed count must be >= 0")
        if count > 0:
            self._outbox_claimed.add(count)

    def record_outbox_published(self) -> None:
        self._outbox_published.add(1)

    def record_outbox_released(self) -> None:
        self._outbox_released.add(1)

    def record_inbox_lookup(self, *, found: bool) -> None:
        self._inbox_lookup.add(
            1,
            {"result": "found" if found else "missing"},
        )

    def record_inbox_added(self) -> None:
        self._inbox_added.add(1)

    def record_inbox_processed(self) -> None:
        self._inbox_processed.add(1)

    def record_platform_error(
        self,
        *,
        category: str,
        status_code: int,
    ) -> None:
        self._platform_errors.add(
            1,
            {
                "category": category,
                "status_code": status_code,
            },
        )

    def observe_database_pool(self, database: Database) -> None:
        if self._database_pool_observed:
            raise RuntimeError("Database pool metrics are already registered")

        self._database_pool_observed = True

        def observe_size(
            options: CallbackOptions,
        ) -> Iterable[Observation]:
            del options
            snapshot = database.pool_snapshot()
            yield Observation(snapshot.size)

        def observe_checked_in(
            options: CallbackOptions,
        ) -> Iterable[Observation]:
            del options
            snapshot = database.pool_snapshot()
            yield Observation(snapshot.checked_in)

        def observe_checked_out(
            options: CallbackOptions,
        ) -> Iterable[Observation]:
            del options
            snapshot = database.pool_snapshot()
            yield Observation(snapshot.checked_out)

        def observe_overflow(
            options: CallbackOptions,
        ) -> Iterable[Observation]:
            del options
            snapshot = database.pool_snapshot()
            yield Observation(snapshot.overflow)

        self._meter.create_observable_gauge(
            "core_platform.db.pool.size",
            callbacks=[observe_size],
            description="Configured database connection pool size",
        )
        self._meter.create_observable_gauge(
            "core_platform.db.pool.checked_in",
            callbacks=[observe_checked_in],
            description="Database connections currently idle in the pool",
        )
        self._meter.create_observable_gauge(
            "core_platform.db.pool.checked_out",
            callbacks=[observe_checked_out],
            description="Database connections currently checked out",
        )
        self._meter.create_observable_gauge(
            "core_platform.db.pool.overflow",
            callbacks=[observe_overflow],
            description="Database pool overflow value reported by SQLAlchemy",
        )