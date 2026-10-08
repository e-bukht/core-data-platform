from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

import pytest

from core_platform.application.break_glass import (
    BREAK_GLASS_ISSUE_EVIDENCE_TYPE,
    BREAK_GLASS_ISSUE_OPERATION,
    BREAK_GLASS_MANAGEMENT_CAPABILITY,
    BREAK_GLASS_RESUME_EVIDENCE_TYPE,
    BREAK_GLASS_RESUME_OPERATION,
    BREAK_GLASS_REVOKE_EVIDENCE_TYPE,
    BREAK_GLASS_REVOKE_OPERATION,
    BREAK_GLASS_SUSPEND_EVIDENCE_TYPE,
    BREAK_GLASS_SUSPEND_OPERATION,
    BreakGlassIssueCommand,
    BreakGlassLifecycleService,
)
from core_platform.foundation.errors import AuthorizationError, ValidationError
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import EvidenceRecord
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)
from core_platform.transaction_kernel.models import (
    AuditRecord,
    TransactionContext,
)

NOW = datetime(
    2026,
    10,
    5,
    19,
    0,
    tzinfo=UTC,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000201"))
ADMIN_ID = ActorId(UUID("00000000-0000-7000-8000-000000000202"))
SUBJECT_ID = ActorId(UUID("00000000-0000-7000-8000-000000000203"))
GRANT_ID = BreakGlassGrantId(UUID("00000000-0000-7000-8000-000000000204"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000205"))


class _Clock:
    def __init__(
        self,
        now: datetime,
    ) -> None:
        self._now = now
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self._now


class _Signer:
    algorithm = "Ed25519"
    key_id = "test-key"

    def __init__(self) -> None:
        self.calls = 0

    async def sign(
        self,
        payload: bytes,
    ) -> bytes:
        assert payload
        self.calls += 1
        return b"signature"


class _IssuePersistenceCall(TypedDict):
    transaction_context: TransactionContext
    grant: BreakGlassGrant
    issued_at: datetime
    audit_record: AuditRecord
    evidence_record: EvidenceRecord


class _TransitionPersistenceCall(TypedDict):
    transaction_context: TransactionContext
    grant_id: BreakGlassGrantId
    expected_version: int
    expected_current_status: BreakGlassGrantStatus
    target_status: BreakGlassGrantStatus
    changed_at: datetime
    audit_record: AuditRecord
    evidence_record: EvidenceRecord


class _Persistence:
    def __init__(self) -> None:
        self.calls = 0
        self.kwargs: _IssuePersistenceCall | None = None
        self.transition_calls = 0
        self.transition_kwargs: _TransitionPersistenceCall | None = None

    async def persist_issue(
        self,
        *,
        transaction_context: TransactionContext,
        grant: BreakGlassGrant,
        issued_at: datetime,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> int:
        self.calls += 1
        self.kwargs = {
            "transaction_context": transaction_context,
            "grant": grant,
            "issued_at": issued_at,
            "audit_record": audit_record,
            "evidence_record": evidence_record,
        }
        return 0

    async def persist_transition(
        self,
        *,
        transaction_context: TransactionContext,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        expected_current_status: BreakGlassGrantStatus,
        target_status: BreakGlassGrantStatus,
        changed_at: datetime,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> int:
        self.transition_calls += 1
        self.transition_kwargs = {
            "transaction_context": transaction_context,
            "grant_id": grant_id,
            "expected_version": expected_version,
            "expected_current_status": expected_current_status,
            "target_status": target_status,
            "changed_at": changed_at,
            "audit_record": audit_record,
            "evidence_record": evidence_record,
        }
        return 8


def _authentication() -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example.test",
        subject="admin",
        audience=("core-data-api",),
        client_id="control-plane",
        scopes=frozenset(),
        acr="urn:core-platform:acr:loa2",
        amr=("pwd", "mfa"),
        authenticated_at=NOW - timedelta(minutes=1),
        token_id="token-1",
        expires_at=NOW + timedelta(minutes=15),
    )


def _context(
    *,
    elevated: bool = False,
) -> ExecutionContext:
    elevation = None

    if elevated:
        elevation = BreakGlassElevationContext(
            grant_id=BreakGlassGrantId(UUID("00000000-0000-7000-8000-000000000206")),
            issued_by_actor_id=ActorId(UUID("00000000-0000-7000-8000-000000000207")),
            capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
            scope=BreakGlassScope(BreakGlassScopeKind.TENANT),
            reason="Emergency recovery",
            activated_at=NOW,
            valid_until=NOW + timedelta(minutes=20),
        )

    return ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=ADMIN_ID,
        actor_type=ActorType.HUMAN,
        authentication=_authentication(),
        correlation_id=CORRELATION_ID,
        break_glass=elevation,
    )


def _grant() -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=GRANT_ID,
        tenant_id=TENANT_ID,
        actor_id=SUBJECT_ID,
        issued_by_actor_id=ADMIN_ID,
        capabilities=(
            "platform.outbox.retry",
            "platform.audit.read",
        ),
        scope=BreakGlassScope(
            kind=BreakGlassScopeKind.RESOURCE_TYPE,
            resource_type="OutboxMessage",
        ),
        reason="Emergency operational recovery",
        valid_from=NOW,
        valid_until=NOW + timedelta(minutes=30),
        status=BreakGlassGrantStatus.ACTIVE,
        accepted_acr_values=frozenset({"urn:core-platform:acr:loa2"}),
        required_amr=frozenset({"mfa"}),
    )


def _issue_command() -> BreakGlassIssueCommand:
    grant = _grant()

    return BreakGlassIssueCommand(
        actor_id=grant.actor_id,
        capabilities=grant.capabilities,
        scope=grant.scope,
        reason=grant.reason,
        valid_from=grant.valid_from,
        valid_until=grant.valid_until,
        accepted_acr_values=(grant.accepted_acr_values),
        required_amr=grant.required_amr,
    )


def test_issue_builds_linked_audit_and_signed_evidence() -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        result = await service.issue(
            context=_context(),
            command=_issue_command(),
        )

        assert result.version == 0
        assert clock.calls == 1
        assert signer.calls == 1
        assert persistence.calls == 1
        assert persistence.kwargs is not None

        transaction_context = persistence.kwargs["transaction_context"]
        audit_record = persistence.kwargs["audit_record"]
        evidence_record = persistence.kwargs["evidence_record"]

        assert transaction_context.operation == BREAK_GLASS_ISSUE_OPERATION
        assert transaction_context.capability == BREAK_GLASS_MANAGEMENT_CAPABILITY
        assert transaction_context.started_at == NOW

        assert audit_record.action == BREAK_GLASS_ISSUE_OPERATION
        assert audit_record.resource_type == "BreakGlassGrant"
        assert audit_record.resource_id == str(result.grant_id.value)
        assert audit_record.occurred_at == NOW

        persisted_grant = persistence.kwargs["grant"]

        assert persisted_grant.grant_id == result.grant_id
        assert persisted_grant.tenant_id == TENANT_ID
        assert persisted_grant.issued_by_actor_id == ADMIN_ID
        assert persisted_grant.status is (BreakGlassGrantStatus.ACTIVE)

        assert audit_record.details["event"] == ("break-glass.issuance")
        assert audit_record.details["actor_id"] == str(SUBJECT_ID.value)
        assert audit_record.details["issued_by_actor_id"] == str(ADMIN_ID.value)

        assert evidence_record.envelope.evidence_type == BREAK_GLASS_ISSUE_EVIDENCE_TYPE
        assert evidence_record.envelope.audit_record_id == audit_record.record_id.value
        assert evidence_record.envelope.transaction_id == transaction_context.transaction_id.value
        assert evidence_record.envelope.signed_at == NOW
        assert evidence_record.payload_hash_matches()

    asyncio.run(scenario())


def test_issue_rejects_recursive_break_glass_before_signing() -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        with pytest.raises(
            Exception,
        ) as exc:
            await service.issue(
                context=_context(
                    elevated=True,
                ),
                command=_issue_command(),
            )

        assert getattr(exc.value, "code", None) == (
            "BREAK_GLASS.MANAGEMENT.REQUIRES.DIRECT.AUTHORIZATION"
        )
        assert clock.calls == 0
        assert signer.calls == 0
        assert persistence.calls == 0

    asyncio.run(scenario())


def test_issue_rejects_naive_clock_before_signing() -> None:
    async def scenario() -> None:
        clock = _Clock(
            datetime(
                2026,
                10,
                5,
                19,
                0,
            )
        )
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        with pytest.raises(
            ValueError,
            match="Clock returned a naive timestamp",
        ):
            await service.issue(
                context=_context(),
                command=_issue_command(),
            )

        assert clock.calls == 1
        assert signer.calls == 0
        assert persistence.calls == 0

    asyncio.run(scenario())


# === C-I4-12t SUSPEND SERVICE ===


def test_suspend_builds_linked_audit_and_signed_evidence() -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        version = await service.suspend(
            context=_context(),
            grant_id=GRANT_ID,
            expected_version=7,
            transition_reason=("  Incident contained; suspend access  "),
        )

        assert version == 8
        assert clock.calls == 1
        assert signer.calls == 1
        assert persistence.calls == 0
        assert persistence.transition_calls == 1
        assert persistence.transition_kwargs is not None

        transaction_context = persistence.transition_kwargs["transaction_context"]
        audit_record = persistence.transition_kwargs["audit_record"]
        evidence_record = persistence.transition_kwargs["evidence_record"]

        assert transaction_context.operation == BREAK_GLASS_SUSPEND_OPERATION
        assert transaction_context.capability == BREAK_GLASS_MANAGEMENT_CAPABILITY
        assert transaction_context.started_at == NOW

        assert persistence.transition_kwargs["grant_id"] == GRANT_ID
        assert persistence.transition_kwargs["expected_version"] == 7
        assert (
            persistence.transition_kwargs["expected_current_status"] == BreakGlassGrantStatus.ACTIVE
        )
        assert persistence.transition_kwargs["target_status"] == BreakGlassGrantStatus.SUSPENDED
        assert persistence.transition_kwargs["changed_at"] == NOW

        assert audit_record.action == BREAK_GLASS_SUSPEND_OPERATION
        assert audit_record.resource_type == "BreakGlassGrant"
        assert audit_record.resource_id == str(GRANT_ID.value)
        assert audit_record.occurred_at == NOW

        assert audit_record.details["event"] == ("break-glass.suspension")
        assert audit_record.details["from_status"] == "ACTIVE"
        assert audit_record.details["to_status"] == "SUSPENDED"
        assert audit_record.details["expected_version"] == 7
        assert audit_record.details["transition_reason"] == ("Incident contained; suspend access")

        assert evidence_record.envelope.evidence_type == BREAK_GLASS_SUSPEND_EVIDENCE_TYPE
        assert evidence_record.envelope.audit_record_id == audit_record.record_id.value
        assert evidence_record.envelope.transaction_id == transaction_context.transaction_id.value
        assert evidence_record.envelope.signed_at == NOW
        assert evidence_record.payload_hash_matches()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("expected_version", "transition_reason"),
    [
        (
            -1,
            "Emergency suspension",
        ),
        (
            7,
            "   ",
        ),
    ],
)
def test_suspend_rejects_invalid_intent_before_clock_or_signing(
    expected_version: int,
    transition_reason: str,
) -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        with pytest.raises(ValidationError) as caught:
            await service.suspend(
                context=_context(),
                grant_id=GRANT_ID,
                expected_version=expected_version,
                transition_reason=transition_reason,
            )

        assert caught.value.code == ("BREAK_GLASS.TRANSITION.INVALID")
        assert caught.value.correlation_id == str(CORRELATION_ID)
        assert clock.calls == 0
        assert signer.calls == 0
        assert persistence.transition_calls == 0

    asyncio.run(scenario())


def test_suspend_rejects_recursive_break_glass_before_clock() -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        with pytest.raises(
            AuthorizationError,
        ) as exc:
            await service.suspend(
                context=_context(
                    elevated=True,
                ),
                grant_id=GRANT_ID,
                expected_version=7,
                transition_reason="Emergency suspension",
            )

        assert exc.value.code == ("BREAK_GLASS.MANAGEMENT.REQUIRES.DIRECT.AUTHORIZATION")
        assert clock.calls == 0
        assert signer.calls == 0
        assert persistence.transition_calls == 0

    asyncio.run(scenario())


# === C-I4-12v RESUME SERVICE ===


def test_resume_builds_linked_audit_and_signed_evidence() -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        version = await service.resume(
            context=_context(),
            grant_id=GRANT_ID,
            expected_version=8,
            transition_reason=("  Recovery still active; restore access  "),
        )

        assert version == 8
        assert clock.calls == 1
        assert signer.calls == 1
        assert persistence.calls == 0
        assert persistence.transition_calls == 1
        assert persistence.transition_kwargs is not None

        transaction_context = persistence.transition_kwargs["transaction_context"]
        audit_record = persistence.transition_kwargs["audit_record"]
        evidence_record = persistence.transition_kwargs["evidence_record"]

        assert transaction_context.operation == BREAK_GLASS_RESUME_OPERATION
        assert transaction_context.capability == BREAK_GLASS_MANAGEMENT_CAPABILITY
        assert transaction_context.started_at == NOW

        assert persistence.transition_kwargs["grant_id"] == GRANT_ID
        assert persistence.transition_kwargs["expected_version"] == 8
        assert (
            persistence.transition_kwargs["expected_current_status"]
            == BreakGlassGrantStatus.SUSPENDED
        )
        assert persistence.transition_kwargs["target_status"] == BreakGlassGrantStatus.ACTIVE
        assert persistence.transition_kwargs["changed_at"] == NOW

        assert audit_record.action == BREAK_GLASS_RESUME_OPERATION
        assert audit_record.resource_type == "BreakGlassGrant"
        assert audit_record.resource_id == str(GRANT_ID.value)
        assert audit_record.occurred_at == NOW

        assert audit_record.details["event"] == ("break-glass.resumption")
        assert audit_record.details["from_status"] == "SUSPENDED"
        assert audit_record.details["to_status"] == "ACTIVE"
        assert audit_record.details["expected_version"] == 8
        assert audit_record.details["transition_reason"] == (
            "Recovery still active; restore access"
        )

        assert evidence_record.envelope.evidence_type == BREAK_GLASS_RESUME_EVIDENCE_TYPE
        assert evidence_record.envelope.audit_record_id == audit_record.record_id.value
        assert evidence_record.envelope.transaction_id == transaction_context.transaction_id.value
        assert evidence_record.envelope.signed_at == NOW
        assert evidence_record.payload_hash_matches()

    asyncio.run(scenario())


# === C-I4-12x REVOKE SERVICE ===


@pytest.mark.parametrize(
    "source_status",
    [
        BreakGlassGrantStatus.ACTIVE,
        BreakGlassGrantStatus.SUSPENDED,
    ],
)
def test_revoke_builds_verified_source_audit_and_evidence(
    source_status: BreakGlassGrantStatus,
) -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        version = await service.revoke(
            context=_context(),
            grant_id=GRANT_ID,
            expected_version=9,
            expected_current_status=source_status,
            transition_reason=("  Emergency access no longer required  "),
        )

        assert version == 8
        assert clock.calls == 1
        assert signer.calls == 1
        assert persistence.calls == 0
        assert persistence.transition_calls == 1
        assert persistence.transition_kwargs is not None

        transaction_context = persistence.transition_kwargs["transaction_context"]
        audit_record = persistence.transition_kwargs["audit_record"]
        evidence_record = persistence.transition_kwargs["evidence_record"]

        assert transaction_context.operation == BREAK_GLASS_REVOKE_OPERATION
        assert transaction_context.capability == BREAK_GLASS_MANAGEMENT_CAPABILITY
        assert transaction_context.started_at == NOW

        assert persistence.transition_kwargs["grant_id"] == GRANT_ID
        assert persistence.transition_kwargs["expected_version"] == 9
        assert persistence.transition_kwargs["expected_current_status"] == source_status
        assert persistence.transition_kwargs["target_status"] == BreakGlassGrantStatus.REVOKED
        assert persistence.transition_kwargs["changed_at"] == NOW

        assert audit_record.action == BREAK_GLASS_REVOKE_OPERATION
        assert audit_record.resource_type == "BreakGlassGrant"
        assert audit_record.resource_id == str(GRANT_ID.value)
        assert audit_record.occurred_at == NOW

        assert audit_record.details["event"] == ("break-glass.revocation")
        assert audit_record.details["from_status"] == source_status.value
        assert audit_record.details["to_status"] == "REVOKED"
        assert audit_record.details["expected_version"] == 9
        assert audit_record.details["transition_reason"] == ("Emergency access no longer required")

        assert evidence_record.envelope.evidence_type == BREAK_GLASS_REVOKE_EVIDENCE_TYPE
        assert evidence_record.envelope.audit_record_id == audit_record.record_id.value
        assert evidence_record.envelope.transaction_id == transaction_context.transaction_id.value
        assert evidence_record.envelope.signed_at == NOW
        assert evidence_record.payload_hash_matches()

    asyncio.run(scenario())


def test_revoke_rejects_terminal_source_before_clock_or_signing() -> None:
    async def scenario() -> None:
        clock = _Clock(NOW)
        signer = _Signer()
        persistence = _Persistence()

        service = BreakGlassLifecycleService(
            persistence=persistence,
            signer=signer,
            clock=clock,
        )

        with pytest.raises(ValidationError) as caught:
            await service.revoke(
                context=_context(),
                grant_id=GRANT_ID,
                expected_version=9,
                expected_current_status=(BreakGlassGrantStatus.REVOKED),
                transition_reason="Duplicate revocation",
            )

        assert caught.value.code == ("BREAK_GLASS.REVOKE.INVALID_SOURCE_STATUS")
        assert caught.value.correlation_id == str(CORRELATION_ID)
        assert clock.calls == 0
        assert signer.calls == 0
        assert persistence.transition_calls == 0

    asyncio.run(scenario())
