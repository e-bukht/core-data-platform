from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from core_platform.foundation.identifiers import new_uuid7


@dataclass(frozen=True, slots=True)
class TenantId:
    value: UUID

    @classmethod
    def new(cls) -> TenantId:
        return cls(new_uuid7())

    @classmethod
    def parse(cls, raw: str) -> TenantId:
        return cls(UUID(raw))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ActorId:
    value: UUID

    @classmethod
    def new(cls) -> ActorId:
        return cls(new_uuid7())

    @classmethod
    def parse(cls, raw: str) -> ActorId:
        return cls(UUID(raw))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class IdentityId:
    value: UUID

    @classmethod
    def new(cls) -> IdentityId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CapabilityId:
    value: UUID

    @classmethod
    def new(cls) -> CapabilityId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class GrantId:
    value: UUID

    @classmethod
    def new(cls) -> GrantId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class EvidenceRecordId:
    value: UUID

    @classmethod
    def new(cls) -> EvidenceRecordId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class BreakGlassGrantId:
    value: UUID

    @classmethod
    def new(cls) -> BreakGlassGrantId:
        return cls(new_uuid7())

    def __str__(self) -> str:
        return str(self.value)
