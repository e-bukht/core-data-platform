from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, CapabilityId, GrantId, TenantId


class RiskClass(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CapabilityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: CapabilityId
    code: str
    description: str
    risk_class: RiskClass
    status: CapabilityStatus


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    grant_id: GrantId
    tenant_id: TenantId
    actor_id: ActorId
    capability_id: CapabilityId
    capability_code: str
    valid_from: datetime
    valid_until: datetime | None
    status: GrantStatus

    def is_active_at(self, instant: datetime) -> bool:
        if self.status is not GrantStatus.ACTIVE:
            return False
        if instant < self.valid_from:
            return False
        return self.valid_until is None or instant < self.valid_until


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    tenant_id: TenantId
    actor_id: ActorId
    capability: str
    environment: str
    authentication_context: AuthenticationContext
    resource_type: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    effect: PolicyEffect
    reason_code: str
    policy_code: str = "capability-grant"
    policy_version: str = "1"
    obligations: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.effect is PolicyEffect.ALLOW
