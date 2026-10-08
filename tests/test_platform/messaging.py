from __future__ import annotations

import pytest

from core_platform.transaction_kernel.models import MessageEnvelope


class RecordingMessageTransport:
    """Deterministic in-memory reference transport for certification tests."""

    def __init__(self) -> None:
        self._deliveries: list[MessageEnvelope] = []

    @property
    def deliveries(self) -> tuple[MessageEnvelope, ...]:
        return tuple(self._deliveries)

    async def publish(self, envelope: MessageEnvelope) -> None:
        self._deliveries.append(envelope)

    def clear(self) -> None:
        self._deliveries.clear()


@pytest.fixture
def cert_message_transport() -> RecordingMessageTransport:
    return RecordingMessageTransport()
