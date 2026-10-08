from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self, cast
from uuid import UUID

import pytest

from core_platform.foundation.canonical_json import (
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.break_glass_activation_persistence import (
    PostgresBreakGlassActivationPersistence,
)
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.ids import ActorId, TenantId
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)

NOW = datetime(
    2026,
    9,
    27,
    9,
    30,
    tzinfo=UTC,
)

TENANT_ID = TenantId(UUID("00000000-0000-7c00-8000-000000001001"))
ACTOR_ID = ActorId(UUID("00000000-0000-7c00-8000-000000001002"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7c00-8000-000000001003"))
TRANSACTION_ID = TransactionId(UUID("00000000-0000-7c00-8000-000000001004"))
AUDIT_ID = AuditRecordId(UUID("00000000-0000-7c00-8000-000000001005"))


def _transaction_context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TRANSACTION_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="security.break-glass.activate",
        capability="platform.outbox.retry",
        started_at=NOW,
    )


def _audit() -> AuditRecord:
    return AuditRecord(
        record_id=AUDIT_ID,
        tenant_id=TENANT_ID,
        transaction_id=TRANSACTION_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        capability="platform.outbox.retry",
        action="security.break-glass.activate",
        resource_type="BreakGlassGrant",
        resource_id=("00000000-0000-7c00-8000-000000001006"),
        outcome=AuditOutcome.SUCCESS,
        occurred_at=NOW,
        details={
            "event": "break-glass.activation",
        },
    )


def _evidence() -> EvidenceRecord:
    payload = {
        "event": "break-glass.activation",
    }

    return EvidenceRecord(
        envelope=EvidenceEnvelope(
            envelope_version=1,
            record_id=EvidenceRecordId(UUID("00000000-0000-7c00-8000-000000001007")),
            tenant_id=TENANT_ID,
            audit_record_id=AUDIT_ID.value,
            transaction_id=TRANSACTION_ID.value,
            actor_id=ACTOR_ID,
            correlation_id=CORRELATION_ID,
            evidence_type=("security.break-glass.activation"),
            occurred_at=NOW,
            signed_at=NOW,
            payload_hash=canonical_json_sha256(payload),
            signature_algorithm="Ed25519",
            key_id="test-key",
        ),
        canonical_payload=canonical_json_bytes(payload),
        signature=b"signature",
    )


class _AuditStore:
    def __init__(
        self,
        events: list[str],
        *,
        fail: bool = False,
    ) -> None:
        self._events = events
        self._fail = fail

    async def append(
        self,
        record: AuditRecord,
    ) -> None:
        self._events.append("audit")

        if self._fail:
            raise RuntimeError("audit failure")


class _EvidenceStore:
    def __init__(
        self,
        events: list[str],
        *,
        fail: bool = False,
    ) -> None:
        self._events = events
        self._fail = fail

    async def append(
        self,
        record: EvidenceRecord,
    ) -> None:
        self._events.append("evidence")

        if self._fail:
            raise RuntimeError("evidence failure")


class _UnitOfWork:
    def __init__(
        self,
        *,
        fail_audit: bool = False,
        fail_evidence: bool = False,
    ) -> None:
        self.events: list[str] = []
        self.audit = _AuditStore(
            self.events,
            fail=fail_audit,
        )
        self.evidence = _EvidenceStore(
            self.events,
            fail=fail_evidence,
        )

    async def __aenter__(
        self,
    ) -> Self:
        self.events.append("enter")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.events.append("exit")

    async def commit(
        self,
    ) -> None:
        self.events.append("commit")


class _Factory:
    def __init__(
        self,
        uow: _UnitOfWork,
    ) -> None:
        self._uow = uow
        self.context: TransactionContext | None = None

    def create(
        self,
        context: TransactionContext,
    ) -> _UnitOfWork:
        self.context = context
        return self._uow


def _persistence(
    uow: _UnitOfWork,
) -> PostgresBreakGlassActivationPersistence:
    factory = cast(
        PostgresUnitOfWorkFactory,
        _Factory(uow),
    )

    return PostgresBreakGlassActivationPersistence(factory)


def test_persistence_orders_audit_evidence_then_commit() -> None:
    async def run() -> None:
        uow = _UnitOfWork()

        await _persistence(uow).persist(
            transaction_context=_transaction_context(),
            audit_record=_audit(),
            evidence_record=_evidence(),
        )

        assert uow.events == [
            "enter",
            "audit",
            "evidence",
            "commit",
            "exit",
        ]

    asyncio.run(run())


def test_evidence_failure_prevents_commit() -> None:
    async def run() -> None:
        uow = _UnitOfWork(fail_evidence=True)

        with pytest.raises(
            RuntimeError,
            match="evidence failure",
        ):
            await _persistence(uow).persist(
                transaction_context=_transaction_context(),
                audit_record=_audit(),
                evidence_record=_evidence(),
            )

        assert uow.events == [
            "enter",
            "audit",
            "evidence",
            "exit",
        ]

    asyncio.run(run())


def test_linkage_guard_rejects_mismatched_audit_before_uow() -> None:
    async def run() -> None:
        uow = _UnitOfWork()

        wrong_audit = replace(
            _audit(),
            transaction_id=TransactionId(UUID("00000000-0000-7c00-8000-000000009999")),
        )

        with pytest.raises(
            ValueError,
            match="audit transaction",
        ):
            await _persistence(uow).persist(
                transaction_context=_transaction_context(),
                audit_record=wrong_audit,
                evidence_record=_evidence(),
            )

        assert uow.events == []

    asyncio.run(run())


def test_evidence_must_reference_activation_audit() -> None:
    async def run() -> None:
        uow = _UnitOfWork()

        evidence = _evidence()
        broken = replace(
            evidence,
            envelope=replace(
                evidence.envelope,
                audit_record_id=UUID("00000000-0000-7c00-8000-000000009998"),
            ),
        )

        with pytest.raises(
            ValueError,
            match="does not reference activation audit",
        ):
            await _persistence(uow).persist(
                transaction_context=_transaction_context(),
                audit_record=_audit(),
                evidence_record=broken,
            )

        assert uow.events == []

    asyncio.run(run())
