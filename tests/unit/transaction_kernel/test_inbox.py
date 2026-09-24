from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from core_platform.foundation.identifiers import (
    CorrelationId,
)
from core_platform.platform_kernel.ids import TenantId
from core_platform.transaction_kernel.errors import (
    InboxMessageConflictError,
)
from core_platform.transaction_kernel.ids import (
    InboxRecordId,
    MessageId,
)
from core_platform.transaction_kernel.inbox import (
    InboxAction,
    evaluate_inbox,
)
from core_platform.transaction_kernel.models import (
    InboxMessage,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000801"))
MESSAGE_ID = MessageId(UUID("00000000-0000-7000-8000-000000000802"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000803"))
CONSUMER_NAME = "billing-projection"
PAYLOAD_HASH = "sha256:" + ("a" * 64)


def _message(
    *,
    processed: bool,
    payload_hash: str = PAYLOAD_HASH,
) -> InboxMessage:
    now = datetime.now(UTC)

    return InboxMessage(
        record_id=InboxRecordId(UUID("00000000-0000-7000-8000-000000000804")),
        tenant_id=TENANT_ID,
        consumer_name=CONSUMER_NAME,
        message_id=MESSAGE_ID,
        message_type="order.confirmed",
        correlation_id=CORRELATION_ID,
        causation_id=None,
        payload_hash=payload_hash,
        received_at=now,
        processed_at=now if processed else None,
    )


def test_missing_inbox_record_requires_processing() -> None:
    decision = evaluate_inbox(
        existing=None,
        consumer_name=CONSUMER_NAME,
        message_id=MESSAGE_ID,
        payload_hash=PAYLOAD_HASH,
    )

    assert decision.action is InboxAction.PROCESS
    assert decision.record is None


def test_processed_same_payload_is_duplicate() -> None:
    existing = _message(processed=True)

    decision = evaluate_inbox(
        existing=existing,
        consumer_name=CONSUMER_NAME,
        message_id=MESSAGE_ID,
        payload_hash=PAYLOAD_HASH,
    )

    assert decision.action is InboxAction.DUPLICATE
    assert decision.record is existing


def test_unprocessed_same_payload_is_in_progress() -> None:
    existing = _message(processed=False)

    decision = evaluate_inbox(
        existing=existing,
        consumer_name=CONSUMER_NAME,
        message_id=MESSAGE_ID,
        payload_hash=PAYLOAD_HASH,
    )

    assert decision.action is InboxAction.IN_PROGRESS
    assert decision.record is existing


def test_same_message_with_different_payload_is_rejected() -> None:
    existing = _message(processed=True)

    with pytest.raises(
        InboxMessageConflictError,
        match=("Inbox message is already bound to a different payload"),
    ) as conflict:
        evaluate_inbox(
            existing=existing,
            consumer_name=CONSUMER_NAME,
            message_id=MESSAGE_ID,
            payload_hash="sha256:" + ("b" * 64),
        )

    assert conflict.value.consumer_name == (CONSUMER_NAME)
    assert conflict.value.message_id == str(MESSAGE_ID)
    assert conflict.value.expected_hash == (PAYLOAD_HASH)


def test_existing_record_identity_mismatch_is_rejected() -> None:
    existing = _message(processed=True)

    with pytest.raises(
        ValueError,
        match=("Existing inbox record does not belong"),
    ):
        evaluate_inbox(
            existing=existing,
            consumer_name="other-consumer",
            message_id=MESSAGE_ID,
            payload_hash=PAYLOAD_HASH,
        )
