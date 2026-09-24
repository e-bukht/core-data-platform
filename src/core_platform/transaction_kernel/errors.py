from __future__ import annotations


class IdempotencyKeyConflictError(Exception):
    """The same idempotency key was bound to a different request."""

    def __init__(
        self,
        *,
        operation: str,
        expected_hash: str,
        actual_hash: str,
    ) -> None:
        super().__init__("Idempotency key is already bound to a different request")
        self.operation = operation
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


class ConcurrencyConflict(Exception):
    """An optimistic compare-and-swap write did not match."""

    def __init__(
        self,
        *,
        resource_type: str,
        resource_id: str,
        expected_version: int,
    ) -> None:
        if expected_version < 0:
            raise ValueError("expected_version must be >= 0")

        super().__init__("Optimistic concurrency conflict")
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.expected_version = expected_version


class InboxMessageConflictError(Exception):
    """The same consumer/message identity was bound to another payload."""

    def __init__(
        self,
        *,
        consumer_name: str,
        message_id: str,
        expected_hash: str,
        actual_hash: str,
    ) -> None:
        super().__init__("Inbox message is already bound to a different payload")
        self.consumer_name = consumer_name
        self.message_id = message_id
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
