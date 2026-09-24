from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import StrEnum

from core_platform.transaction_kernel.errors import (
    InboxMessageConflictError,
)
from core_platform.transaction_kernel.ids import MessageId
from core_platform.transaction_kernel.models import (
    InboxMessage,
)


class InboxAction(StrEnum):
    PROCESS = "PROCESS"
    DUPLICATE = "DUPLICATE"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True, slots=True)
class InboxDecision:
    action: InboxAction
    record: InboxMessage | None = None


def evaluate_inbox(
    *,
    existing: InboxMessage | None,
    consumer_name: str,
    message_id: MessageId,
    payload_hash: str,
) -> InboxDecision:
    if existing is None:
        return InboxDecision(InboxAction.PROCESS)

    if existing.consumer_name != consumer_name or existing.message_id != message_id:
        raise ValueError("Existing inbox record does not belong to the requested consumer/message")

    if not hmac.compare_digest(
        existing.payload_hash,
        payload_hash,
    ):
        raise InboxMessageConflictError(
            consumer_name=consumer_name,
            message_id=str(message_id),
            expected_hash=existing.payload_hash,
            actual_hash=payload_hash,
        )

    if existing.processed_at is None:
        return InboxDecision(
            InboxAction.IN_PROGRESS,
            existing,
        )

    return InboxDecision(
        InboxAction.DUPLICATE,
        existing,
    )
