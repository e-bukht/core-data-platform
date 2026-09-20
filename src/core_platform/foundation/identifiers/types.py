from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from core_platform.foundation.identifiers.uuid7 import new_uuid7


@dataclass(frozen=True, slots=True)
class DomainId:
    value: UUID

    @classmethod
    def new(cls) -> DomainId:
        return cls(new_uuid7())

    @classmethod
    def parse(cls, raw: str) -> DomainId:
        return cls(UUID(raw))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CorrelationId:
    value: UUID

    @classmethod
    def new(cls) -> CorrelationId:
        return cls(new_uuid7())

    @classmethod
    def parse(cls, raw: str) -> CorrelationId:
        return cls(UUID(raw))

    def __str__(self) -> str:
        return str(self.value)
