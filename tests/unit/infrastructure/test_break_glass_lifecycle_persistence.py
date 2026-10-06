from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.break_glass_lifecycle_persistence import (
    PostgresBreakGlassLifecyclePersistence,
)
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)

TENANT_ID = TenantId(
    UUID("00000000-0000-7000-8000-000000000021")
)
ACTOR_ID = ActorId(
    UUID("00000000-0000-7000-8000-000000000022")
)
GRANT_ID = BreakGlassGrantId(
    UUID("00000000-0000-7000-8000-000000000023")
)
TRANSACTION_ID = TransactionId(
    UUID("00000000-0000-7000-8000-000000000024")
)
AUDIT_ID = AuditRecordId(
    UUID("00000000-0000-7000-8000-000000000025")
)
CORRELATION_ID = CorrelationId(
    UUID("00000000-0000-7000-8000-000000000026")
)
NOW = datetime(
    2026,
    10,
    5,
    17,
    45,
    tzinfo=UTC,
)


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TRANSACTION_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="security.break-glass.suspend",
        capability="platform.break-glass.manage",
        started_at=NOW,
        idempotency_key=None,
    )


def _audit() -> AuditRecord:
    return AuditRecord(
        record_id=AUDIT_ID,
        tenant_id=TENANT_ID,
        transaction_id=TRANSACTION_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        capability="platform.break-glass.manage",
        action="security.break-glass.suspend",
        resource_type="BreakGlassGrant",
        resource_id=str(GRANT_ID.value),
        outcome=AuditOutcome.SUCCESS,
        occurred_at=NOW,
        details={
            "event": "break-glass.lifecycle",
        },
    )


def _evidence() -> EvidenceRecord:
    envelope = EvidenceEnvelope(
        envelope_version=1,
        record_id=EvidenceRecordId(
            UUID(
                "00000000-0000-7000-8000-000000000027"
            )
        ),
        tenant_id=TENANT_ID,
        audit_record_id=AUDIT_ID.value,
        transaction_id=TRANSACTION_ID.value,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        evidence_type="security.break-glass.lifecycle",
        occurred_at=NOW,
        signed_at=NOW,
        payload_hash="sha256:" + ("a" * 64),
        signature_algorithm="Ed25519",
        key_id="test-key",
    )

    return EvidenceRecord(
        envelope=envelope,
        canonical_payload=b'{"event":"break-glass.lifecycle"}',
        signature=b"x" * 64,
    )


class _LifecycleStore:
    def __init__(self) -> None:
        self.calls = 0
        self.issue_calls = 0
        self.fail = False
        self.issue_fail = False

    async def issue(
        self,
        **kwargs: object,
    ) -> int:
        del kwargs
        self.issue_calls += 1

        if self.issue_fail:
            raise RuntimeError("issue failed")

        return 0

    async def transition_status(
        self,
        **kwargs: object,
    ) -> int:
        del kwargs
        self.calls += 1

        if self.fail:
            raise RuntimeError("transition failed")

        return 8


class _AppendStore:
    def __init__(
        self,
        events: list[str],
        name: str,
    ) -> None:
        self._events = events
        self._name = name
        self.fail = False

    async def append(
        self,
        record: object,
    ) -> None:
        del record
        self._events.append(self._name)

        if self.fail:
            raise RuntimeError(
                f"{self._name} failed"
            )


class _UnitOfWork:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.break_glass_lifecycle = _LifecycleStore()
        self.audit = _AppendStore(
            self.events,
            "audit",
        )
        self.evidence = _AppendStore(
            self.events,
            "evidence",
        )
        self.committed = False
        self.exited_with_error = False

    async def __aenter__(self) -> _UnitOfWork:
        self.events.append("enter")
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        del exc_value, traceback

        self.exited_with_error = (
            exc_type is not None
        )
        self.events.append("exit")

    async def commit(self) -> None:
        self.events.append("commit")
        self.committed = True


class _Factory:
    def __init__(
        self,
        uow: _UnitOfWork,
    ) -> None:
        self.uow = uow
        self.context: TransactionContext | None = None

    def create(
        self,
        context: TransactionContext,
    ) -> _UnitOfWork:
        self.context = context
        return self.uow


def test_transition_audit_evidence_commit_order() -> None:
    async def scenario() -> None:
        uow = _UnitOfWork()
        factory = _Factory(uow)

        persistence = (
            PostgresBreakGlassLifecyclePersistence(
                factory,  # type: ignore[arg-type]
            )
        )

        version = await persistence.persist_transition(
            transaction_context=_context(),
            grant_id=GRANT_ID,
            expected_version=7,
            expected_current_status=BreakGlassGrantStatus.ACTIVE,
            target_status=BreakGlassGrantStatus.SUSPENDED,
            changed_at=NOW,
            audit_record=_audit(),
            evidence_record=_evidence(),
        )

        assert version == 8
        assert factory.context == _context()
        assert uow.break_glass_lifecycle.calls == 1
        assert uow.events == [
            "enter",
            "audit",
            "evidence",
            "commit",
            "exit",
        ]
        assert uow.committed is True
        assert uow.exited_with_error is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failing_store",
    [
        "audit",
        "evidence",
    ],
)
def test_failure_never_commits(
    failing_store: str,
) -> None:
    async def scenario() -> None:
        uow = _UnitOfWork()

        if failing_store == "audit":
            uow.audit.fail = True
        else:
            uow.evidence.fail = True

        persistence = (
            PostgresBreakGlassLifecyclePersistence(
                _Factory(uow),  # type: ignore[arg-type]
            )
        )

        with pytest.raises(
            RuntimeError,
            match=f"{failing_store} failed",
        ):
            await persistence.persist_transition(
                transaction_context=_context(),
                grant_id=GRANT_ID,
                expected_version=7,
                expected_current_status=BreakGlassGrantStatus.ACTIVE,
                target_status=(
                    BreakGlassGrantStatus.SUSPENDED
                ),
                changed_at=NOW,
                audit_record=_audit(),
                evidence_record=_evidence(),
            )

        assert uow.committed is False
        assert uow.exited_with_error is True

    asyncio.run(scenario())


def test_transition_failure_never_writes_audit_or_evidence() -> None:
    async def scenario() -> None:
        uow = _UnitOfWork()
        uow.break_glass_lifecycle.fail = True

        persistence = (
            PostgresBreakGlassLifecyclePersistence(
                _Factory(uow),  # type: ignore[arg-type]
            )
        )

        with pytest.raises(
            RuntimeError,
            match="transition failed",
        ):
            await persistence.persist_transition(
                transaction_context=_context(),
                grant_id=GRANT_ID,
                expected_version=7,
                expected_current_status=BreakGlassGrantStatus.ACTIVE,
                target_status=(
                    BreakGlassGrantStatus.SUSPENDED
                ),
                changed_at=NOW,
                audit_record=_audit(),
                evidence_record=_evidence(),
            )

        assert uow.events == [
            "enter",
            "exit",
        ]
        assert uow.committed is False
        assert uow.exited_with_error is True

    asyncio.run(scenario())


def test_linkage_mismatch_fails_before_uow_creation() -> None:
    context = _context()
    uow = _UnitOfWork()
    factory = _Factory(uow)

    bad_evidence = _evidence()

    object.__setattr__(
        bad_evidence.envelope,
        "audit_record_id",
        UUID(
            "00000000-0000-7000-8000-000000000099"
        ),
    )

    persistence = (
        PostgresBreakGlassLifecyclePersistence(
            factory,  # type: ignore[arg-type]
        )
    )

    with pytest.raises(
        ValueError,
        match="does not reference transition audit",
    ):
        asyncio.run(
            persistence.persist_transition(
                transaction_context=context,
                grant_id=GRANT_ID,
                expected_version=7,
                expected_current_status=BreakGlassGrantStatus.ACTIVE,
                target_status=(
                    BreakGlassGrantStatus.SUSPENDED
                ),
                changed_at=NOW,
                audit_record=_audit(),
                evidence_record=bad_evidence,
            )
        )

    assert factory.context is None

# === C-I4-12l ATOMIC ISSUE PERSISTENCE ===


def _grant() -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=GRANT_ID,
        tenant_id=TENANT_ID,
        actor_id=ActorId(
            UUID(
                "00000000-0000-7000-8000-000000000028"
            )
        ),
        issued_by_actor_id=ACTOR_ID,
        capabilities=(
            "platform.outbox.retry",
        ),
        scope=BreakGlassScope(
            BreakGlassScopeKind.TENANT
        ),
        reason="Emergency recovery",
        valid_from=NOW,
        valid_until=datetime(
            2026,
            10,
            5,
            18,
            15,
            tzinfo=UTC,
        ),
        status=BreakGlassGrantStatus.ACTIVE,
        accepted_acr_values=frozenset(
            {"urn:core-platform:acr:elevated"}
        ),
        required_amr=frozenset(
            {"mfa"}
        ),
    )


def test_issue_audit_evidence_commit_order() -> None:
    async def scenario() -> None:
        uow = _UnitOfWork()
        factory = _Factory(uow)

        persistence = (
            PostgresBreakGlassLifecyclePersistence(
                factory,  # type: ignore[arg-type]
            )
        )

        version = await persistence.persist_issue(
            transaction_context=_context(),
            grant=_grant(),
            issued_at=NOW,
            audit_record=_audit(),
            evidence_record=_evidence(),
        )

        assert version == 0
        assert factory.context == _context()
        assert uow.break_glass_lifecycle.issue_calls == 1
        assert uow.events == [
            "enter",
            "audit",
            "evidence",
            "commit",
            "exit",
        ]
        assert uow.committed is True
        assert uow.exited_with_error is False

    asyncio.run(scenario())


def test_issue_failure_never_writes_audit_or_evidence() -> None:
    async def scenario() -> None:
        uow = _UnitOfWork()
        uow.break_glass_lifecycle.issue_fail = True

        persistence = (
            PostgresBreakGlassLifecyclePersistence(
                _Factory(uow),  # type: ignore[arg-type]
            )
        )

        with pytest.raises(
            RuntimeError,
            match="issue failed",
        ):
            await persistence.persist_issue(
                transaction_context=_context(),
                grant=_grant(),
                issued_at=NOW,
                audit_record=_audit(),
                evidence_record=_evidence(),
            )

        assert uow.events == [
            "enter",
            "exit",
        ]
        assert uow.committed is False
        assert uow.exited_with_error is True

    asyncio.run(scenario())


def test_issue_evidence_failure_never_commits() -> None:
    async def scenario() -> None:
        uow = _UnitOfWork()
        uow.evidence.fail = True

        persistence = (
            PostgresBreakGlassLifecyclePersistence(
                _Factory(uow),  # type: ignore[arg-type]
            )
        )

        with pytest.raises(
            RuntimeError,
            match="evidence failed",
        ):
            await persistence.persist_issue(
                transaction_context=_context(),
                grant=_grant(),
                issued_at=NOW,
                audit_record=_audit(),
                evidence_record=_evidence(),
            )

        assert uow.break_glass_lifecycle.issue_calls == 1
        assert uow.events == [
            "enter",
            "audit",
            "evidence",
            "exit",
        ]
        assert uow.committed is False
        assert uow.exited_with_error is True

    asyncio.run(scenario())
