from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core_platform.application.break_glass import (
    BREAK_GLASS_ACTIVATION_EVIDENCE_TYPE,
    BREAK_GLASS_ACTIVATION_OPERATION,
    BREAK_GLASS_RESOURCE_TYPE,
    DurableBreakGlassActivationRecorder,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
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
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)

NOW = datetime(
    2026,
    9,
    27,
    9,
    15,
    tzinfo=UTC,
)

ACTIVATED_AT = NOW - timedelta(seconds=2)
VALID_UNTIL = NOW + timedelta(minutes=18)

TENANT_ID = TenantId(UUID("00000000-0000-7b00-8000-000000001001"))
ACTOR_ID = ActorId(UUID("00000000-0000-7b00-8000-000000001002"))
ISSUER_ID = ActorId(UUID("00000000-0000-7b00-8000-000000001003"))
GRANT_ID = BreakGlassGrantId(UUID("00000000-0000-7b00-8000-000000001004"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7b00-8000-000000001005"))


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Signer:
    algorithm = "Ed25519"
    key_id = "break-glass-test-key"

    def __init__(
        self,
        *,
        fail: bool = False,
    ) -> None:
        self.fail = fail
        self.calls = 0
        self.last_payload: bytes | None = None

    async def sign(
        self,
        payload: bytes,
    ) -> bytes:
        self.calls += 1
        self.last_payload = payload

        if self.fail:
            raise RuntimeError("signing unavailable")

        return b"break-glass-signature"


class _Persistence:
    def __init__(
        self,
        *,
        fail: bool = False,
    ) -> None:
        self.fail = fail
        self.calls = 0
        self.transaction_context: TransactionContext | None = None
        self.audit_record: AuditRecord | None = None
        self.evidence_record: EvidenceRecord | None = None

    async def persist(
        self,
        *,
        transaction_context: TransactionContext,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> None:
        self.calls += 1
        self.transaction_context = transaction_context
        self.audit_record = audit_record
        self.evidence_record = evidence_record

        if self.fail:
            raise RuntimeError("persistence unavailable")


def _context(
    *,
    elevated: bool = True,
) -> ExecutionContext:
    authentication = AuthenticationContext(
        issuer="https://issuer.example",
        subject="break-glass-subject",
        audience=("core-data-api",),
        client_id=None,
        scopes=frozenset(),
        acr="urn:core-platform:acr:elevated",
        amr=("pwd", "mfa"),
        authenticated_at=NOW - timedelta(minutes=1),
        token_id=None,
        expires_at=NOW + timedelta(minutes=4),
    )

    elevation = None

    if elevated:
        elevation = BreakGlassElevationContext(
            grant_id=GRANT_ID,
            issued_by_actor_id=ISSUER_ID,
            capability="platform.outbox.retry",
            scope=BreakGlassScope(
                BreakGlassScopeKind.RESOURCE,
                resource_type="outbox-message",
                resource_id="message-42",
            ),
            reason="Emergency recovery approval",
            activated_at=ACTIVATED_AT,
            valid_until=VALID_UNTIL,
        )

    return ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        actor_type=ActorType.HUMAN,
        authentication=authentication,
        correlation_id=CORRELATION_ID,
        break_glass=elevation,
    )


def test_recorder_builds_linked_audit_and_signed_evidence() -> None:
    async def run() -> None:
        signer = _Signer()
        persistence = _Persistence()

        recorder = DurableBreakGlassActivationRecorder(
            persistence=persistence,
            signer=signer,
            clock=_Clock(),
        )

        await recorder.record(_context())

        assert persistence.calls == 1
        assert signer.calls == 1

        transaction = persistence.transaction_context
        audit = persistence.audit_record
        evidence = persistence.evidence_record

        assert transaction is not None
        assert audit is not None
        assert evidence is not None

        assert transaction.tenant_id == TENANT_ID
        assert transaction.actor_id == ACTOR_ID
        assert transaction.correlation_id == CORRELATION_ID
        assert transaction.operation == (BREAK_GLASS_ACTIVATION_OPERATION)
        assert transaction.capability == ("platform.outbox.retry")
        assert transaction.started_at == NOW

        assert audit.tenant_id == TENANT_ID
        assert audit.actor_id == ACTOR_ID
        assert audit.transaction_id == (transaction.transaction_id)
        assert audit.correlation_id == CORRELATION_ID
        assert audit.capability == ("platform.outbox.retry")
        assert audit.action == (BREAK_GLASS_ACTIVATION_OPERATION)
        assert audit.resource_type == (BREAK_GLASS_RESOURCE_TYPE)
        assert audit.resource_id == str(GRANT_ID.value)
        assert audit.outcome is AuditOutcome.SUCCESS
        assert audit.occurred_at == ACTIVATED_AT

        envelope = evidence.envelope

        assert envelope.tenant_id == TENANT_ID
        assert envelope.actor_id == ACTOR_ID
        assert envelope.transaction_id == (transaction.transaction_id.value)
        assert envelope.audit_record_id == (audit.record_id.value)
        assert envelope.correlation_id == CORRELATION_ID
        assert envelope.evidence_type == (BREAK_GLASS_ACTIVATION_EVIDENCE_TYPE)
        assert envelope.occurred_at == ACTIVATED_AT
        assert envelope.signed_at == NOW
        assert envelope.signature_algorithm == (signer.algorithm)
        assert envelope.key_id == signer.key_id
        assert evidence.signature == (b"break-glass-signature")
        assert signer.last_payload == (envelope.signing_bytes())
        assert evidence.payload_hash_matches()

        payload = json.loads(evidence.canonical_payload)

        assert payload["grant_id"] == str(GRANT_ID.value)
        assert payload["issued_by_actor_id"] == str(ISSUER_ID.value)
        assert payload["reason"] == ("Emergency recovery approval")
        assert payload["scope"] == {
            "kind": "RESOURCE",
            "resource_id": "message-42",
            "resource_type": "outbox-message",
        }
        assert payload["authentication"] == {
            "acr": "urn:core-platform:acr:elevated",
            "amr": [
                "pwd",
                "mfa",
            ],
        }

        assert audit.details == payload

    asyncio.run(run())


def test_missing_elevation_is_rejected_before_signing_or_persistence() -> None:
    async def run() -> None:
        signer = _Signer()
        persistence = _Persistence()

        recorder = DurableBreakGlassActivationRecorder(
            persistence=persistence,
            signer=signer,
            clock=_Clock(),
        )

        with pytest.raises(
            ValueError,
            match="has no break-glass elevation",
        ):
            await recorder.record(_context(elevated=False))

        assert signer.calls == 0
        assert persistence.calls == 0

    asyncio.run(run())


def test_signer_failure_is_fail_closed_before_persistence() -> None:
    async def run() -> None:
        signer = _Signer(fail=True)
        persistence = _Persistence()

        recorder = DurableBreakGlassActivationRecorder(
            persistence=persistence,
            signer=signer,
            clock=_Clock(),
        )

        with pytest.raises(
            RuntimeError,
            match="signing unavailable",
        ):
            await recorder.record(_context())

        assert signer.calls == 1
        assert persistence.calls == 0

    asyncio.run(run())


def test_persistence_failure_is_propagated_fail_closed() -> None:
    async def run() -> None:
        signer = _Signer()
        persistence = _Persistence(fail=True)

        recorder = DurableBreakGlassActivationRecorder(
            persistence=persistence,
            signer=signer,
            clock=_Clock(),
        )

        with pytest.raises(
            RuntimeError,
            match="persistence unavailable",
        ):
            await recorder.record(_context())

        assert signer.calls == 1
        assert persistence.calls == 1

    asyncio.run(run())
