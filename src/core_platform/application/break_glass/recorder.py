from __future__ import annotations

from datetime import UTC, datetime

from core_platform.application.break_glass.ports import (
    BreakGlassActivationPersistence,
)
from core_platform.application.evidence.factory import (
    SignedEvidenceFactory,
)
from core_platform.foundation.canonical_json import JsonValue
from core_platform.foundation.temporal import Clock
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import EvidenceSigner
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)

BREAK_GLASS_ACTIVATION_OPERATION = (
    "security.break-glass.activate"
)
BREAK_GLASS_ACTIVATION_EVIDENCE_TYPE = (
    "security.break-glass.activation"
)
BREAK_GLASS_RESOURCE_TYPE = "BreakGlassGrant"


def _utc_iso(value: datetime) -> str:
    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "Break-glass timestamp must be timezone-aware"
        )

    normalized = value.astimezone(UTC)

    return (
        normalized.isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _activation_payload(
    context: ExecutionContext,
) -> dict[str, JsonValue]:
    elevation = context.break_glass

    if elevation is None:
        raise ValueError(
            "ExecutionContext has no break-glass elevation"
        )

    return {
        "event": "break-glass.activation",
        "outcome": "SUCCESS",
        "tenant_id": str(
            context.tenant_id.value
        ),
        "actor_id": str(
            context.actor_id.value
        ),
        "grant_id": str(
            elevation.grant_id.value
        ),
        "issued_by_actor_id": str(
            elevation.issued_by_actor_id.value
        ),
        "capability": elevation.capability,
        "scope": {
            "kind": elevation.scope.kind.value,
            "resource_type": (
                elevation.scope.resource_type
            ),
            "resource_id": (
                elevation.scope.resource_id
            ),
        },
        "reason": elevation.reason,
        "activated_at": _utc_iso(
            elevation.activated_at
        ),
        "valid_until": _utc_iso(
            elevation.valid_until
        ),
        "authentication": {
            "acr": context.authentication.acr,
            "amr": list(
                context.authentication.amr
            ),
        },
    }


class DurableBreakGlassActivationRecorder:
    def __init__(
        self,
        *,
        persistence: BreakGlassActivationPersistence,
        signer: EvidenceSigner,
        clock: Clock,
    ) -> None:
        self._persistence = persistence
        self._clock = clock
        self._evidence_factory = SignedEvidenceFactory(
            signer=signer,
            clock=clock,
        )

    async def record(
        self,
        context: ExecutionContext,
    ) -> None:
        elevation = context.break_glass

        if elevation is None:
            raise ValueError(
                "ExecutionContext has no break-glass elevation"
            )

        started_at = self._clock.now()

        if (
            started_at.tzinfo is None
            or started_at.utcoffset() is None
        ):
            raise ValueError(
                "Clock returned a naive timestamp"
            )

        transaction_id = TransactionId.new()
        audit_record_id = AuditRecordId.new()

        transaction_context = TransactionContext(
            transaction_id=transaction_id,
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            operation=BREAK_GLASS_ACTIVATION_OPERATION,
            capability=elevation.capability,
            started_at=started_at,
            idempotency_key=None,
        )

        payload = _activation_payload(
            context
        )

        audit_record = AuditRecord(
            record_id=audit_record_id,
            tenant_id=context.tenant_id,
            transaction_id=transaction_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            capability=elevation.capability,
            action=BREAK_GLASS_ACTIVATION_OPERATION,
            resource_type=BREAK_GLASS_RESOURCE_TYPE,
            resource_id=str(
                elevation.grant_id.value
            ),
            outcome=AuditOutcome.SUCCESS,
            occurred_at=elevation.activated_at,
            details=payload,
        )

        evidence_record = await self._evidence_factory.create(
            context=context,
            audit_record_id=audit_record_id.value,
            transaction_id=transaction_id.value,
            evidence_type=(
                BREAK_GLASS_ACTIVATION_EVIDENCE_TYPE
            ),
            occurred_at=elevation.activated_at,
            payload=payload,
            signed_at=started_at,
        )

        await self._persistence.persist(
            transaction_context=transaction_context,
            audit_record=audit_record,
            evidence_record=evidence_record,
        )
