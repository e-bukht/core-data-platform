from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core_platform.platform_kernel.ids import TenantId
from core_platform.transaction_kernel import (
    IdempotencyAction,
    IdempotencyKeyConflictError,
    IdempotencyRecord,
    IdempotencyRecordId,
    IdempotencyStatus,
    TransactionId,
    canonical_request_hash,
    evaluate_idempotency,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _record(
    *,
    request_hash: str,
    status: IdempotencyStatus,
) -> IdempotencyRecord:
    return IdempotencyRecord(
        record_id=IdempotencyRecordId.new(),
        tenant_id=TenantId.new(),
        operation="order.submit",
        idempotency_key="idem-001",
        request_hash=request_hash,
        status=status,
        transaction_id=TransactionId.new(),
        result_reference="order-001" if status is IdempotencyStatus.COMPLETED else None,
        response_status=200 if status is IdempotencyStatus.COMPLETED else None,
        response_payload={"order_id": "order-001"}
        if status is IdempotencyStatus.COMPLETED
        else None,
        created_at=NOW,
        completed_at=NOW if status is IdempotencyStatus.COMPLETED else None,
        expires_at=NOW + timedelta(days=1),
    )


def test_request_hash_is_independent_of_object_key_order() -> None:
    first = canonical_request_hash(
        {
            "quantity": 2,
            "product": "ABC",
            "metadata": {"b": 2, "a": 1},
        }
    )
    second = canonical_request_hash(
        {
            "metadata": {"a": 1, "b": 2},
            "product": "ABC",
            "quantity": 2,
        }
    )

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == 71


def test_request_hash_normalizes_unicode_to_nfc() -> None:
    composed = canonical_request_hash({"name": "Café"})
    decomposed = canonical_request_hash({"name": "Cafe\u0301"})

    assert composed == decomposed


def test_request_hash_changes_when_payload_changes() -> None:
    first = canonical_request_hash({"quantity": 1})
    second = canonical_request_hash({"quantity": 2})

    assert first != second


def test_request_hash_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="Non-finite"):
        canonical_request_hash({"amount": float("nan")})


def test_new_idempotency_key_executes() -> None:
    request_hash = canonical_request_hash({"quantity": 1})

    decision = evaluate_idempotency(
        existing=None,
        operation="order.submit",
        request_hash=request_hash,
    )

    assert decision.action is IdempotencyAction.EXECUTE
    assert decision.record is None


def test_completed_same_request_replays_previous_result() -> None:
    request_hash = canonical_request_hash({"quantity": 1})
    existing = _record(
        request_hash=request_hash,
        status=IdempotencyStatus.COMPLETED,
    )

    decision = evaluate_idempotency(
        existing=existing,
        operation="order.submit",
        request_hash=request_hash,
    )

    assert decision.action is IdempotencyAction.REPLAY
    assert decision.record is existing


def test_in_progress_same_request_does_not_execute_again() -> None:
    request_hash = canonical_request_hash({"quantity": 1})
    existing = _record(
        request_hash=request_hash,
        status=IdempotencyStatus.IN_PROGRESS,
    )

    decision = evaluate_idempotency(
        existing=existing,
        operation="order.submit",
        request_hash=request_hash,
    )

    assert decision.action is IdempotencyAction.IN_PROGRESS
    assert decision.record is existing


def test_same_key_with_different_request_is_rejected() -> None:
    existing = _record(
        request_hash=canonical_request_hash({"quantity": 1}),
        status=IdempotencyStatus.COMPLETED,
    )

    with pytest.raises(IdempotencyKeyConflictError) as caught:
        evaluate_idempotency(
            existing=existing,
            operation="order.submit",
            request_hash=canonical_request_hash({"quantity": 2}),
        )

    assert caught.value.operation == "order.submit"


def test_existing_record_for_wrong_operation_is_rejected() -> None:
    request_hash = canonical_request_hash({"quantity": 1})
    existing = _record(
        request_hash=request_hash,
        status=IdempotencyStatus.COMPLETED,
    )

    with pytest.raises(ValueError, match="requested operation"):
        evaluate_idempotency(
            existing=existing,
            operation="order.cancel",
            request_hash=request_hash,
        )
