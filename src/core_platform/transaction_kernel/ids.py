from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from core_platform.foundation.identifiers import new_uuid7


@dataclass(frozen=True, slots=True)
class TransactionId:
    value: UUID

    @classmethod
    def new(cls) -> TransactionId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class IdempotencyRecordId:
    value: UUID

    @classmethod
    def new(cls) -> IdempotencyRecordId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class MessageId:
    value: UUID

    @classmethod
    def new(cls) -> MessageId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class InboxRecordId:
    value: UUID

    @classmethod
    def new(cls) -> InboxRecordId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AuditRecordId:
    value: UUID

    @classmethod
    def new(cls) -> AuditRecordId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)
