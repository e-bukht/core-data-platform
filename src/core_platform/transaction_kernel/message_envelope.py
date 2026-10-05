from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from core_platform.foundation.canonical_json import (
    JsonValue,
    canonical_json_sha256,
)
from core_platform.transaction_kernel.ids import MessageId
from core_platform.transaction_kernel.models import (
    MessageEnvelope,
    TransactionContext,
)


def create_message_envelope(
    *,
    context: TransactionContext,
    message_id: MessageId,
    message_type: str,
    schema_version: int,
    source: str,
    occurred_at: datetime,
    payload: Mapping[str, JsonValue],
    causation_id: MessageId | None = None,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    aggregate_version: int | None = None,
) -> MessageEnvelope:
    """Create a trusted message envelope from a TransactionContext."""

    if not message_type.strip():
        raise ValueError("message_type must not be empty")

    if schema_version < 1:
        raise ValueError("schema_version must be >= 1")

    if not source.strip():
        raise ValueError("source must not be empty")

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")

    if aggregate_type is None and aggregate_id is not None:
        raise ValueError("aggregate_id requires aggregate_type")

    if aggregate_type is not None and aggregate_id is None:
        raise ValueError("aggregate_type requires aggregate_id")

    if aggregate_type is not None and not aggregate_type.strip():
        raise ValueError("aggregate_type must not be empty")

    if aggregate_id is not None and not aggregate_id.strip():
        raise ValueError("aggregate_id must not be empty")

    if aggregate_version is not None:
        if aggregate_type is None:
            raise ValueError("aggregate_version requires aggregate identity")

        if aggregate_version < 0:
            raise ValueError("aggregate_version must be >= 0")

    payload_snapshot = dict(payload)

    return MessageEnvelope(
        message_id=message_id,
        message_type=message_type,
        schema_version=schema_version,
        source=source,
        tenant_id=context.tenant_id,
        transaction_id=context.transaction_id,
        actor_id=context.actor_id,
        occurred_at=occurred_at,
        correlation_id=context.correlation_id,
        causation_id=causation_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        payload=payload_snapshot,
        payload_hash=canonical_json_sha256(payload_snapshot),
    )
