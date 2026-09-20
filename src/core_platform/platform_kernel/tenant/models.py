from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core_platform.platform_kernel.ids import ActorId, TenantId


class TenantStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATING = "TERMINATING"
    ARCHIVED = "ARCHIVED"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class Tenant:
    tenant_id: TenantId
    code: str
    display_name: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime

    @property
    def active(self) -> bool:
        return self.status is TenantStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class TenantMembership:
    tenant_id: TenantId
    actor_id: ActorId
    status: MembershipStatus
    valid_from: datetime
    valid_until: datetime | None
    version: int

    def is_active_at(self, instant: datetime) -> bool:
        if self.status is not MembershipStatus.ACTIVE:
            return False
        if instant < self.valid_from:
            return False
        return self.valid_until is None or instant < self.valid_until
