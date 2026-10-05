from __future__ import annotations

from typing import Protocol

from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import EvidenceRecord
from core_platform.transaction_kernel.models import (
    AuditRecord,
    TransactionContext,
)


class BreakGlassActivationPersistence(Protocol):
    async def persist(
        self,
        *,
        transaction_context: TransactionContext,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> None: ...


class BreakGlassActivationRecorder(Protocol):
    async def record(
        self,
        context: ExecutionContext,
    ) -> None: ...