from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core_platform.platform_kernel.ids import ActorId


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SERVICE = "SERVICE"
    INTEGRATION = "INTEGRATION"
    SYSTEM = "SYSTEM"


class ActorStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class Actor:
    actor_id: ActorId
    actor_type: ActorType
    status: ActorStatus
    display_name: str
    created_at: datetime
    updated_at: datetime

    @property
    def active(self) -> bool:
        return self.status is ActorStatus.ACTIVE
