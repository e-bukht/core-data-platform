from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import StrEnum

from core_platform.transaction_kernel.errors import (
    IdempotencyKeyConflictError,
)
from core_platform.transaction_kernel.models import (
    IdempotencyRecord,
    IdempotencyStatus,
)


class IdempotencyAction(StrEnum):
    EXECUTE = "EXECUTE"
    REPLAY = "REPLAY"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    action: IdempotencyAction
    record: IdempotencyRecord | None = None


def evaluate_idempotency(
    *,
    existing: IdempotencyRecord | None,
    operation: str,
    request_hash: str,
) -> IdempotencyDecision:
    if existing is None:
        return IdempotencyDecision(IdempotencyAction.EXECUTE)

    if existing.operation != operation:
        raise ValueError("Existing idempotency record does not belong to the requested operation")

    if not hmac.compare_digest(existing.request_hash, request_hash):
        raise IdempotencyKeyConflictError(
            operation=operation,
            expected_hash=existing.request_hash,
            actual_hash=request_hash,
        )

    if existing.status is IdempotencyStatus.COMPLETED:
        return IdempotencyDecision(
            IdempotencyAction.REPLAY,
            existing,
        )

    return IdempotencyDecision(
        IdempotencyAction.IN_PROGRESS,
        existing,
    )
