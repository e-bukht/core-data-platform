from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from core_platform.application.evidence import (
    EvidenceService,
    EvidenceVerificationStatus,
)
from core_platform.foundation.canonical_json import canonical_json_bytes
from core_platform.foundation.errors import ResourceNotFound
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import (
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, TenantId

_FIXED_NOW = datetime(2026, 9, 26, 17, 0, tzinfo=UTC)
_OCCURRED_AT = datetime(2026, 9, 26, 16, 59, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _FIXED_NOW


class _Signer:
    algorithm = "TEST-SHA256"
    key_id = "evidence-test-key"

    def __init__(self) -> None:
        self.last_payload: bytes | None = None

    async def sign(self, payload: bytes) -> bytes:
        self.last_payload = payload
        return hashlib.sha256(payload).digest()


class _Verifier:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid
        self.calls = 0

    async def verify(
        self,
        payload: bytes,
        *,
        signature: bytes,
        algorithm: str,
        key_id: str,
    ) -> bool:
        del payload, signature, algorithm, key_id
        self.calls += 1
        return self.valid


class _Repository:
    def __init__(self) -> None:
        self.records: dict[EvidenceRecordId, EvidenceRecord] = {}
        self.override_get: EvidenceRecord | None = None

    async def append(self, record: EvidenceRecord) -> None:
        self.records[record.envelope.record_id] = record

    async def get(
        self,
        tenant_id: TenantId,
        record_id: EvidenceRecordId,
    ) -> EvidenceRecord | None:
        if self.override_get is not None:
            return self.override_get

        record = self.records.get(record_id)
        if record is None:
            return None

        if record.envelope.tenant_id != tenant_id:
            return None

        return record


def _context(
    *,
    tenant_id: TenantId | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        tenant_id=tenant_id
        or TenantId(UUID("20000000-0000-7000-8000-000000000001")),
        actor_id=ActorId(
            UUID("50000000-0000-7000-8000-000000000001")
        ),
        actor_type=ActorType.HUMAN,
        authentication=AuthenticationContext(
            issuer="https://issuer.example.test",
            subject="alice",
            audience=("core-data-api",),
            client_id="test-client",
            scopes=frozenset(),
            acr=None,
            amr=(),
            authenticated_at=_FIXED_NOW,
            token_id="token-1",
            expires_at=datetime(
                2026,
                9,
                26,
                18,
                0,
                tzinfo=UTC,
            ),
        ),
        correlation_id=CorrelationId(
            UUID("60000000-0000-7000-8000-000000000001")
        ),
    )


async def _create_record(
    *,
    repository: _Repository,
    signer: _Signer,
    verifier: _Verifier,
    context: ExecutionContext | None = None,
) -> EvidenceRecord:
    service = EvidenceService(
        repository=repository,
        signer=signer,
        verifier=verifier,
        clock=_FixedClock(),
    )

    return await service.create_evidence(
        context=context or _context(),
        audit_record_id=UUID(
            "30000000-0000-7000-8000-000000000001"
        ),
        transaction_id=UUID(
            "40000000-0000-7000-8000-000000000001"
        ),
        evidence_type="transaction.audit",
        occurred_at=_OCCURRED_AT,
        payload={
            "action": "test-resource.create",
            "outcome": "SUCCESS",
        },
    )


def test_create_evidence_binds_context_and_signs_envelope() -> None:
    async def run() -> None:
        repository = _Repository()
        signer = _Signer()
        verifier = _Verifier(valid=True)
        context = _context()

        record = await _create_record(
            repository=repository,
            signer=signer,
            verifier=verifier,
            context=context,
        )

        assert record.envelope.tenant_id == context.tenant_id
        assert record.envelope.actor_id == context.actor_id
        assert record.envelope.correlation_id == context.correlation_id
        assert record.envelope.signed_at == _FIXED_NOW
        assert record.envelope.signature_algorithm == signer.algorithm
        assert record.envelope.key_id == signer.key_id

        assert signer.last_payload == record.envelope.signing_bytes()
        assert record.payload_hash_matches()
        assert (
            repository.records[record.envelope.record_id]
            == record
        )

    asyncio.run(run())


def test_create_evidence_canonicalizes_payload() -> None:
    async def run() -> None:
        repository = _Repository()
        signer = _Signer()
        verifier = _Verifier(valid=True)

        service = EvidenceService(
            repository=repository,
            signer=signer,
            verifier=verifier,
            clock=_FixedClock(),
        )

        record = await service.create_evidence(
            context=_context(),
            audit_record_id=UUID(
                "30000000-0000-7000-8000-000000000001"
            ),
            transaction_id=UUID(
                "40000000-0000-7000-8000-000000000001"
            ),
            evidence_type="transaction.audit",
            occurred_at=_OCCURRED_AT,
            payload={"z": 1, "a": "Cafe\u0301"},
        )

        assert record.canonical_payload == canonical_json_bytes(
            {"a": "Café", "z": 1}
        )

    asyncio.run(run())


def test_verify_valid_evidence() -> None:
    async def run() -> None:
        repository = _Repository()
        signer = _Signer()
        verifier = _Verifier(valid=True)

        record = await _create_record(
            repository=repository,
            signer=signer,
            verifier=verifier,
        )

        service = EvidenceService(
            repository=repository,
            signer=signer,
            verifier=verifier,
            clock=_FixedClock(),
        )

        result = await service.verify_evidence(
            context=_context(),
            record_id=record.envelope.record_id,
        )

        assert result.status is EvidenceVerificationStatus.VALID
        assert result.key_id == signer.key_id
        assert result.signature_algorithm == signer.algorithm
        assert verifier.calls == 1

    asyncio.run(run())


def test_verify_detects_payload_hash_mismatch_before_crypto() -> None:
    async def run() -> None:
        repository = _Repository()
        signer = _Signer()
        verifier = _Verifier(valid=True)

        record = await _create_record(
            repository=repository,
            signer=signer,
            verifier=verifier,
        )

        repository.records[record.envelope.record_id] = replace(
            record,
            canonical_payload=canonical_json_bytes(
                {"action": "tampered"}
            ),
        )

        service = EvidenceService(
            repository=repository,
            signer=signer,
            verifier=verifier,
            clock=_FixedClock(),
        )

        result = await service.verify_evidence(
            context=_context(),
            record_id=record.envelope.record_id,
        )

        assert (
            result.status
            is EvidenceVerificationStatus.PAYLOAD_HASH_MISMATCH
        )
        assert verifier.calls == 0

    asyncio.run(run())


def test_verify_reports_invalid_signature() -> None:
    async def run() -> None:
        repository = _Repository()
        signer = _Signer()
        verifier = _Verifier(valid=False)

        record = await _create_record(
            repository=repository,
            signer=signer,
            verifier=verifier,
        )

        service = EvidenceService(
            repository=repository,
            signer=signer,
            verifier=verifier,
            clock=_FixedClock(),
        )

        result = await service.verify_evidence(
            context=_context(),
            record_id=record.envelope.record_id,
        )

        assert (
            result.status
            is EvidenceVerificationStatus.SIGNATURE_INVALID
        )
        assert verifier.calls == 1

    asyncio.run(run())


def test_missing_evidence_raises_resource_not_found() -> None:
    async def run() -> None:
        service = EvidenceService(
            repository=_Repository(),
            signer=_Signer(),
            verifier=_Verifier(valid=True),
            clock=_FixedClock(),
        )

        with pytest.raises(ResourceNotFound) as exc_info:
            await service.verify_evidence(
                context=_context(),
                record_id=EvidenceRecordId(
                    UUID("10000000-0000-7000-8000-000000000099")
                ),
            )

        assert exc_info.value.code == "EVIDENCE.NOT_FOUND"
        assert (
            exc_info.value.correlation_id
            == str(_context().correlation_id)
        )

    asyncio.run(run())


def test_cross_tenant_record_is_not_disclosed() -> None:
    async def run() -> None:
        repository = _Repository()
        signer = _Signer()
        verifier = _Verifier(valid=True)

        foreign_context = _context(
            tenant_id=TenantId(
                UUID("20000000-0000-7000-8000-000000000099")
            )
        )

        foreign_record = await _create_record(
            repository=repository,
            signer=signer,
            verifier=verifier,
            context=foreign_context,
        )

        repository.override_get = foreign_record

        service = EvidenceService(
            repository=repository,
            signer=signer,
            verifier=verifier,
            clock=_FixedClock(),
        )

        with pytest.raises(ResourceNotFound) as exc_info:
            await service.verify_evidence(
                context=_context(),
                record_id=foreign_record.envelope.record_id,
            )

        assert exc_info.value.code == "EVIDENCE.NOT_FOUND"
        assert verifier.calls == 0

    asyncio.run(run())