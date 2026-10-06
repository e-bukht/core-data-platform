from __future__ import annotations

from datetime import UTC, datetime

from core_platform.application.break_glass.authorization import (
    BREAK_GLASS_MANAGEMENT_CAPABILITY,
    require_direct_break_glass_management,
)
from core_platform.application.break_glass.commands import (
    BreakGlassIssueCommand,
    BreakGlassIssueResult,
)
from core_platform.application.break_glass.ports import (
    BreakGlassLifecyclePersistence,
)
from core_platform.application.evidence.factory import (
    SignedEvidenceFactory,
)
from core_platform.foundation.canonical_json import JsonValue
from core_platform.foundation.errors import ValidationError
from core_platform.foundation.temporal import Clock
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import EvidenceSigner
from core_platform.platform_kernel.ids import BreakGlassGrantId
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)

BREAK_GLASS_ISSUE_OPERATION = "security.break-glass.issue"
BREAK_GLASS_ISSUE_EVIDENCE_TYPE = (
    "security.break-glass.issuance"
)

BREAK_GLASS_SUSPEND_OPERATION = (
    "security.break-glass.suspend"
)
BREAK_GLASS_SUSPEND_EVIDENCE_TYPE = (
    "security.break-glass.suspension"
)

BREAK_GLASS_RESUME_OPERATION = (
    "security.break-glass.resume"
)
BREAK_GLASS_RESUME_EVIDENCE_TYPE = (
    "security.break-glass.resumption"
)

BREAK_GLASS_REVOKE_OPERATION = (
    "security.break-glass.revoke"
)
BREAK_GLASS_REVOKE_EVIDENCE_TYPE = (
    "security.break-glass.revocation"
)
BREAK_GLASS_RESOURCE_TYPE = "BreakGlassGrant"


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Break-glass timestamp must be timezone-aware"
        )

    return (
        value.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _issue_payload(
    *,
    context: ExecutionContext,
    grant: BreakGlassGrant,
    issued_at: datetime,
) -> dict[str, JsonValue]:
    return {
        "event": "break-glass.issuance",
        "outcome": "SUCCESS",
        "tenant_id": str(context.tenant_id.value),
        "grant_id": str(grant.grant_id.value),
        "actor_id": str(grant.actor_id.value),
        "issued_by_actor_id": str(
            grant.issued_by_actor_id.value
        ),
        "capabilities": list(grant.capabilities),
        "scope": {
            "kind": grant.scope.kind.value,
            "resource_type": grant.scope.resource_type,
            "resource_id": grant.scope.resource_id,
        },
        "reason": grant.reason,
        "valid_from": _utc_iso(grant.valid_from),
        "valid_until": _utc_iso(grant.valid_until),
        "status": grant.status.value,
        "accepted_acr_values": list(
            sorted(grant.accepted_acr_values)
        ),
        "required_amr": list(
            sorted(grant.required_amr)
        ),
        "issued_at": _utc_iso(issued_at),
    }


def _transition_payload(
    *,
    context: ExecutionContext,
    grant_id: BreakGlassGrantId,
    event: str,
    current_status: BreakGlassGrantStatus,
    target_status: BreakGlassGrantStatus,
    expected_version: int,
    transition_reason: str,
    changed_at: datetime,
) -> dict[str, JsonValue]:
    return {
        "event": event,
        "outcome": "SUCCESS",
        "tenant_id": str(context.tenant_id.value),
        "grant_id": str(grant_id.value),
        "changed_by_actor_id": str(
            context.actor_id.value
        ),
        "from_status": current_status.value,
        "to_status": target_status.value,
        "expected_version": expected_version,
        "transition_reason": transition_reason,
        "changed_at": _utc_iso(changed_at),
    }


class BreakGlassLifecycleService:
    def __init__(
        self,
        *,
        persistence: BreakGlassLifecyclePersistence,
        signer: EvidenceSigner,
        clock: Clock,
    ) -> None:
        self._persistence = persistence
        self._clock = clock
        self._evidence_factory = SignedEvidenceFactory(
            signer=signer,
            clock=clock,
        )

    async def issue(
        self,
        *,
        context: ExecutionContext,
        command: BreakGlassIssueCommand,
    ) -> BreakGlassIssueResult:
        require_direct_break_glass_management(
            context
        )

        issued_at = self._clock.now()

        if (
            issued_at.tzinfo is None
            or issued_at.utcoffset() is None
        ):
            raise ValueError(
                "Clock returned a naive timestamp"
            )

        try:
            grant = BreakGlassGrant(
                grant_id=BreakGlassGrantId.new(),
                tenant_id=context.tenant_id,
                actor_id=command.actor_id,
                issued_by_actor_id=context.actor_id,
                capabilities=command.capabilities,
                scope=command.scope,
                reason=command.reason,
                valid_from=command.valid_from,
                valid_until=command.valid_until,
                status=BreakGlassGrantStatus.ACTIVE,
                accepted_acr_values=(
                    command.accepted_acr_values
                ),
                required_amr=command.required_amr,
            )
        except ValueError as exc:
            raise ValidationError(
                "BREAK_GLASS.ISSUE.INVALID",
                "Break-glass issuance request is invalid",
                correlation_id=str(
                    context.correlation_id
                ),
            ) from exc

        if grant.valid_until <= issued_at:
            raise ValidationError(
                "BREAK_GLASS.ISSUE.EXPIRED",
                "Break-glass grant must expire after issuance",
                correlation_id=str(
                    context.correlation_id
                ),
            )

        transaction_id = TransactionId.new()
        audit_record_id = AuditRecordId.new()

        transaction_context = TransactionContext(
            transaction_id=transaction_id,
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            operation=BREAK_GLASS_ISSUE_OPERATION,
            capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
            started_at=issued_at,
            idempotency_key=None,
        )

        payload = _issue_payload(
            context=context,
            grant=grant,
            issued_at=issued_at,
        )

        audit_record = AuditRecord(
            record_id=audit_record_id,
            tenant_id=context.tenant_id,
            transaction_id=transaction_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
            action=BREAK_GLASS_ISSUE_OPERATION,
            resource_type=BREAK_GLASS_RESOURCE_TYPE,
            resource_id=str(grant.grant_id.value),
            outcome=AuditOutcome.SUCCESS,
            occurred_at=issued_at,
            details=payload,
        )

        evidence_record = (
            await self._evidence_factory.create(
                context=context,
                audit_record_id=audit_record_id.value,
                transaction_id=transaction_id.value,
                evidence_type=(
                    BREAK_GLASS_ISSUE_EVIDENCE_TYPE
                ),
                occurred_at=issued_at,
                payload=payload,
                signed_at=issued_at,
            )
        )

        version = await self._persistence.persist_issue(
            transaction_context=transaction_context,
            grant=grant,
            issued_at=issued_at,
            audit_record=audit_record,
            evidence_record=evidence_record,
        )

        return BreakGlassIssueResult(
            grant_id=grant.grant_id,
            version=version,
        )

    async def suspend(
        self,
        *,
        context: ExecutionContext,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        transition_reason: str,
    ) -> int:
        return await self._transition(
            context=context,
            grant_id=grant_id,
            expected_version=expected_version,
            transition_reason=transition_reason,
            operation=BREAK_GLASS_SUSPEND_OPERATION,
            evidence_type=(
                BREAK_GLASS_SUSPEND_EVIDENCE_TYPE
            ),
            event="break-glass.suspension",
            current_status=BreakGlassGrantStatus.ACTIVE,
            target_status=BreakGlassGrantStatus.SUSPENDED,
        )

    async def resume(
        self,
        *,
        context: ExecutionContext,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        transition_reason: str,
    ) -> int:
        return await self._transition(
            context=context,
            grant_id=grant_id,
            expected_version=expected_version,
            transition_reason=transition_reason,
            operation=BREAK_GLASS_RESUME_OPERATION,
            evidence_type=(
                BREAK_GLASS_RESUME_EVIDENCE_TYPE
            ),
            event="break-glass.resumption",
            current_status=BreakGlassGrantStatus.SUSPENDED,
            target_status=BreakGlassGrantStatus.ACTIVE,
        )

    async def revoke(
        self,
        *,
        context: ExecutionContext,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        expected_current_status: BreakGlassGrantStatus,
        transition_reason: str,
    ) -> int:
        if expected_current_status not in {
            BreakGlassGrantStatus.ACTIVE,
            BreakGlassGrantStatus.SUSPENDED,
        }:
            raise ValidationError(
                "BREAK_GLASS.REVOKE.INVALID_SOURCE_STATUS",
                (
                    "Break-glass grant can only be revoked "
                    "from ACTIVE or SUSPENDED"
                ),
                correlation_id=str(
                    context.correlation_id
                ),
            )

        return await self._transition(
            context=context,
            grant_id=grant_id,
            expected_version=expected_version,
            transition_reason=transition_reason,
            operation=BREAK_GLASS_REVOKE_OPERATION,
            evidence_type=(
                BREAK_GLASS_REVOKE_EVIDENCE_TYPE
            ),
            event="break-glass.revocation",
            current_status=expected_current_status,
            target_status=BreakGlassGrantStatus.REVOKED,
        )

    async def _transition(
        self,
        *,
        context: ExecutionContext,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        transition_reason: str,
        operation: str,
        evidence_type: str,
        event: str,
        current_status: BreakGlassGrantStatus,
        target_status: BreakGlassGrantStatus,
    ) -> int:
        require_direct_break_glass_management(
            context
        )

        if expected_version < 0:
            raise ValidationError(
                "BREAK_GLASS.TRANSITION.INVALID",
                "Break-glass transition request is invalid",
                correlation_id=str(
                    context.correlation_id
                ),
            )

        normalized_reason = transition_reason.strip()

        if not normalized_reason:
            raise ValidationError(
                "BREAK_GLASS.TRANSITION.INVALID",
                "Break-glass transition request is invalid",
                correlation_id=str(
                    context.correlation_id
                ),
            )

        changed_at = self._clock.now()

        if (
            changed_at.tzinfo is None
            or changed_at.utcoffset() is None
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
            operation=operation,
            capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
            started_at=changed_at,
            idempotency_key=None,
        )

        payload = _transition_payload(
            context=context,
            grant_id=grant_id,
            event=event,
            current_status=current_status,
            target_status=target_status,
            expected_version=expected_version,
            transition_reason=normalized_reason,
            changed_at=changed_at,
        )

        audit_record = AuditRecord(
            record_id=audit_record_id,
            tenant_id=context.tenant_id,
            transaction_id=transaction_id,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
            action=operation,
            resource_type=BREAK_GLASS_RESOURCE_TYPE,
            resource_id=str(grant_id.value),
            outcome=AuditOutcome.SUCCESS,
            occurred_at=changed_at,
            details=payload,
        )

        evidence_record = (
            await self._evidence_factory.create(
                context=context,
                audit_record_id=audit_record_id.value,
                transaction_id=transaction_id.value,
                evidence_type=evidence_type,
                occurred_at=changed_at,
                payload=payload,
                signed_at=changed_at,
            )
        )

        return await self._persistence.persist_transition(
            transaction_context=transaction_context,
            grant_id=grant_id,
            expected_version=expected_version,
            expected_current_status=current_status,
            target_status=target_status,
            changed_at=changed_at,
            audit_record=audit_record,
            evidence_record=evidence_record,
        )
