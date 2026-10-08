from __future__ import annotations

from core_platform.application.break_glass import (
    BreakGlassActivationPersistence,
)
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWorkFactory,
)
from core_platform.platform_kernel.evidence import EvidenceRecord
from core_platform.transaction_kernel.models import (
    AuditRecord,
    TransactionContext,
)


class PostgresBreakGlassActivationPersistence(BreakGlassActivationPersistence):
    def __init__(
        self,
        factory: PostgresUnitOfWorkFactory,
    ) -> None:
        self._factory = factory

    async def persist(
        self,
        *,
        transaction_context: TransactionContext,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> None:
        if audit_record.transaction_id != transaction_context.transaction_id:
            raise ValueError("Break-glass audit transaction does not match persistence context")

        if evidence_record.envelope.audit_record_id != audit_record.record_id.value:
            raise ValueError("Break-glass evidence does not reference activation audit")

        uow = self._factory.create(transaction_context)

        async with uow as active:
            await active.audit.append(audit_record)
            await active.evidence.append(evidence_record)
            await active.commit()
