from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from core_platform.transaction_kernel.ids import MessageId
from core_platform.transaction_kernel.models import (
    AuditRecord,
    IdempotencyRecord,
    InboxMessage,
    MessageEnvelope,
    OutboxMessage,
    TransactionContext,
)


class IdempotencyStore(Protocol):
    async def get(
        self,
        *,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecord | None: ...

    async def add(self, record: IdempotencyRecord) -> None: ...

    async def complete(
        self,
        *,
        operation: str,
        idempotency_key: str,
        result_reference: str | None,
        response_status: int,
        response_payload: dict[str, object] | None,
        completed_at: datetime,
    ) -> IdempotencyRecord: ...


class MessagePublisher(Protocol):
    async def publish(
        self,
        envelope: MessageEnvelope,
    ) -> None: ...


class OutboxStore(Protocol):
    async def add(self, message: OutboxMessage) -> None: ...

    async def claim_ready(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
        limit: int,
    ) -> tuple[OutboxMessage, ...]: ...

    async def mark_published(
        self,
        *,
        message_id: MessageId,
        worker_id: str,
        expected_attempt: int,
        published_at: datetime,
    ) -> None: ...

    async def release(
        self,
        *,
        message_id: MessageId,
        worker_id: str,
        expected_attempt: int,
        available_at: datetime,
        error: str,
    ) -> None: ...


class InboxStore(Protocol):
    async def get(
        self,
        *,
        consumer_name: str,
        message_id: MessageId,
    ) -> InboxMessage | None: ...

    async def add(self, message: InboxMessage) -> None: ...

    async def mark_processed(
        self,
        *,
        consumer_name: str,
        message_id: MessageId,
        processed_at: datetime,
    ) -> None: ...


class AuditStore(Protocol):
    async def append(self, record: AuditRecord) -> None: ...


class UnitOfWork(Protocol):
    @property
    def context(self) -> TransactionContext: ...

    @property
    def idempotency(self) -> IdempotencyStore: ...

    @property
    def outbox(self) -> OutboxStore: ...

    @property
    def inbox(self) -> InboxStore: ...

    @property
    def audit(self) -> AuditStore: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def create(self, context: TransactionContext) -> UnitOfWork: ...
