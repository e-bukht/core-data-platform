from __future__ import annotations

from datetime import datetime

from core_platform.application.break_glass.ports import (
    BreakGlassLifecyclePersistence,
)
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
)
from core_platform.platform_kernel.evidence import EvidenceRecord
from core_platform.platform_kernel.ids import BreakGlassGrantId
from core_platform.transaction_kernel.models import (
    AuditRecord,
    TransactionContext,
)


class PostgresBreakGlassLifecyclePersistence(BreakGlassLifecyclePersistence):
    def __init__(
        self,
        factory: PostgresUnitOfWorkFactory,
    ) -> None:
        self._factory = factory

    async def persist_issue(
        self,
        *,
        transaction_context: TransactionContext,
        grant: BreakGlassGrant,
        issued_at: datetime,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> int:
        if audit_record.transaction_id != (transaction_context.transaction_id):
            raise ValueError(
                "Break-glass lifecycle audit transaction does not match persistence context"
            )

        if evidence_record.envelope.audit_record_id != audit_record.record_id.value:
            raise ValueError("Break-glass lifecycle evidence does not reference transition audit")

        uow = self._factory.create(transaction_context)

        async with uow as active:
            version = await active.break_glass_lifecycle.issue(
                grant=grant,
                issued_at=issued_at,
            )

            await active.audit.append(audit_record)

            await active.evidence.append(evidence_record)

            await active.commit()

        return version

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
        if audit_record.transaction_id != (transaction_context.transaction_id):
            raise ValueError(
                "Break-glass lifecycle audit transaction does not match persistence context"
            )

        if evidence_record.envelope.audit_record_id != audit_record.record_id.value:
            raise ValueError("Break-glass lifecycle evidence does not reference transition audit")

        uow = self._factory.create(transaction_context)

        async with uow as active:
            new_version = await active.break_glass_lifecycle.transition_status(
                grant_id=grant_id,
                expected_version=expected_version,
                expected_current_status=(expected_current_status),
                target_status=target_status,
                changed_at=changed_at,
            )

            await active.audit.append(audit_record)

            await active.evidence.append(evidence_record)

            await active.commit()

        return new_version
