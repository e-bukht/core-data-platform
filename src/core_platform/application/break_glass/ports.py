from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import EvidenceRecord
from core_platform.platform_kernel.ids import (
    BreakGlassGrantId,
)
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


class BreakGlassLifecycleStore(Protocol):
    async def issue(
        self,
        *,
        grant: BreakGlassGrant,
        issued_at: datetime,
    ) -> int: ...

    async def transition_status(
        self,
        *,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        expected_current_status: BreakGlassGrantStatus,
        target_status: BreakGlassGrantStatus,
        changed_at: datetime,
    ) -> int: ...


class BreakGlassLifecyclePersistence(Protocol):
    async def persist_issue(
        self,
        *,
        transaction_context: TransactionContext,
        grant: BreakGlassGrant,
        issued_at: datetime,
        audit_record: AuditRecord,
        evidence_record: EvidenceRecord,
    ) -> int: ...

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
    ) -> int: ...
