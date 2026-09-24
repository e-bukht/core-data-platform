from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from core_platform.foundation.identifiers import (
    CorrelationId,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    TenantId,
)
from core_platform.transaction_kernel.hashing import (
    JsonValue,
    canonical_request_hash,
)
from core_platform.transaction_kernel.ids import (
    MessageId,
    TransactionId,
)
from core_platform.transaction_kernel.message_envelope import (
    create_message_envelope,
)
from core_platform.transaction_kernel.models import (
    TransactionContext,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000001001"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000001002"))
TRANSACTION_ID = TransactionId(UUID("00000000-0000-7000-8000-000000001003"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000001004"))
MESSAGE_ID = MessageId(UUID("00000000-0000-7000-8000-000000001005"))
CAUSATION_ID = MessageId(UUID("00000000-0000-7000-8000-000000001006"))

OCCURRED_AT = datetime(
    2026,
    9,
    23,
    22,
    45,
    tzinfo=UTC,
)


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TRANSACTION_ID,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation="order.confirm",
        capability="order.confirm",
        started_at=OCCURRED_AT,
    )


def test_envelope_preserves_transaction_and_message_context() -> None:
    payload: dict[str, JsonValue] = {
        "order_id": "ORD-1001",
        "amount": 12500,
        "metadata": {
            "channel": "api",
            "confirmed": True,
        },
    }

    envelope = create_message_envelope(
        context=_context(),
        message_id=MESSAGE_ID,
        message_type="order.confirmed",
        schema_version=3,
        source="core-data-platform",
        occurred_at=OCCURRED_AT,
        causation_id=CAUSATION_ID,
        aggregate_type="Order",
        aggregate_id="ORD-1001",
        aggregate_version=7,
        payload=payload,
    )

    assert envelope.message_id == MESSAGE_ID
    assert envelope.message_type == "order.confirmed"
    assert envelope.schema_version == 3
    assert envelope.source == "core-data-platform"

    assert envelope.tenant_id == TENANT_ID
    assert envelope.transaction_id == TRANSACTION_ID
    assert envelope.actor_id == ACTOR_ID
    assert envelope.correlation_id == CORRELATION_ID

    assert envelope.occurred_at == OCCURRED_AT
    assert envelope.causation_id == CAUSATION_ID

    assert envelope.aggregate_type == "Order"
    assert envelope.aggregate_id == "ORD-1001"
    assert envelope.aggregate_version == 7

    assert envelope.payload == payload
    assert envelope.payload_hash == (canonical_request_hash(payload))


def test_payload_hash_is_canonical_and_deterministic() -> None:
    first = create_message_envelope(
        context=_context(),
        message_id=MESSAGE_ID,
        message_type="order.confirmed",
        schema_version=1,
        source="core-data-platform",
        occurred_at=OCCURRED_AT,
        payload={
            "b": 2,
            "a": {
                "name": "Café",
                "active": True,
            },
        },
    )

    second = create_message_envelope(
        context=_context(),
        message_id=MESSAGE_ID,
        message_type="order.confirmed",
        schema_version=1,
        source="core-data-platform",
        occurred_at=OCCURRED_AT,
        payload={
            "a": {
                "active": True,
                "name": "Cafe\u0301",
            },
            "b": 2,
        },
    )

    assert first.payload_hash == second.payload_hash


@pytest.mark.parametrize(
    "schema_version",
    [0, -1],
)
def test_schema_version_must_be_positive(
    schema_version: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="schema_version must be >= 1",
    ):
        create_message_envelope(
            context=_context(),
            message_id=MESSAGE_ID,
            message_type="order.confirmed",
            schema_version=schema_version,
            source="core-data-platform",
            occurred_at=OCCURRED_AT,
            payload={},
        )


@pytest.mark.parametrize(
    ("aggregate_type", "aggregate_id"),
    [
        ("Order", None),
        (None, "ORD-1001"),
    ],
)
def test_aggregate_identity_must_be_coherent(
    aggregate_type: str | None,
    aggregate_id: str | None,
) -> None:
    with pytest.raises(ValueError):
        create_message_envelope(
            context=_context(),
            message_id=MESSAGE_ID,
            message_type="order.confirmed",
            schema_version=1,
            source="core-data-platform",
            occurred_at=OCCURRED_AT,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload={},
        )


def test_aggregate_version_requires_identity() -> None:
    with pytest.raises(
        ValueError,
        match=("aggregate_version requires aggregate identity"),
    ):
        create_message_envelope(
            context=_context(),
            message_id=MESSAGE_ID,
            message_type="order.confirmed",
            schema_version=1,
            source="core-data-platform",
            occurred_at=OCCURRED_AT,
            aggregate_version=1,
            payload={},
        )


def test_negative_aggregate_version_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="aggregate_version must be >= 0",
    ):
        create_message_envelope(
            context=_context(),
            message_id=MESSAGE_ID,
            message_type="order.confirmed",
            schema_version=1,
            source="core-data-platform",
            occurred_at=OCCURRED_AT,
            aggregate_type="Order",
            aggregate_id="ORD-1001",
            aggregate_version=-1,
            payload={},
        )


def test_occurred_at_must_be_timezone_aware() -> None:
    with pytest.raises(
        ValueError,
        match=("occurred_at must be timezone-aware"),
    ):
        create_message_envelope(
            context=_context(),
            message_id=MESSAGE_ID,
            message_type="order.confirmed",
            schema_version=1,
            source="core-data-platform",
            occurred_at=datetime(
                2026,
                9,
                23,
                22,
                45,
            ),
            payload={},
        )
