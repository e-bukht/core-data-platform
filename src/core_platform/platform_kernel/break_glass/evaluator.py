from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core_platform.platform_kernel.break_glass.models import (
    BreakGlassElevationContext,
    BreakGlassGrant,
)
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, TenantId


def _normalize_optional(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} must not be empty")

    return normalized


@dataclass(frozen=True, slots=True)
class BreakGlassRequest:
    tenant_id: TenantId
    actor_id: ActorId
    capability: str
    authentication_context: AuthenticationContext
    resource_type: str | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        capability = self.capability.strip()

        if not capability:
            raise ValueError("capability must not be empty")

        resource_type = _normalize_optional(
            self.resource_type,
            field_name="resource_type",
        )
        resource_id = _normalize_optional(
            self.resource_id,
            field_name="resource_id",
        )

        if resource_id is not None and resource_type is None:
            raise ValueError("resource_id requires resource_type")

        object.__setattr__(
            self,
            "capability",
            capability,
        )
        object.__setattr__(
            self,
            "resource_type",
            resource_type,
        )
        object.__setattr__(
            self,
            "resource_id",
            resource_id,
        )


@dataclass(frozen=True, slots=True)
class BreakGlassDecision:
    allowed: bool
    reason_code: str
    elevation: BreakGlassElevationContext | None = None

    def __post_init__(self) -> None:
        reason_code = self.reason_code.strip()

        if not reason_code:
            raise ValueError("reason_code must not be empty")

        if self.allowed and self.elevation is None:
            raise ValueError("allowed break-glass decision requires elevation")

        if not self.allowed and self.elevation is not None:
            raise ValueError("denied break-glass decision must not contain elevation")

        object.__setattr__(
            self,
            "reason_code",
            reason_code,
        )


def _deny(
    reason_code: str,
) -> BreakGlassDecision:
    return BreakGlassDecision(
        allowed=False,
        reason_code=reason_code,
    )


def evaluate_break_glass(
    request: BreakGlassRequest,
    grant: BreakGlassGrant | None,
    *,
    now: datetime,
) -> BreakGlassDecision:
    if grant is None:
        return _deny("grant_not_found")

    if grant.tenant_id != request.tenant_id or grant.actor_id != request.actor_id:
        return _deny("grant_subject_mismatch")

    if not grant.is_active_at(now):
        return _deny("grant_not_active")

    if not grant.permits_capability(request.capability):
        return _deny("capability_not_permitted")

    if not grant.scope.matches(
        resource_type=request.resource_type,
        resource_id=request.resource_id,
    ):
        return _deny("scope_mismatch")

    if (
        grant.accepted_acr_values
        and request.authentication_context.acr not in grant.accepted_acr_values
    ):
        return _deny("acr_insufficient")

    authentication_amr = frozenset(request.authentication_context.amr)

    if grant.required_amr and not grant.required_amr.issubset(authentication_amr):
        return _deny("amr_insufficient")

    elevation = BreakGlassElevationContext(
        grant_id=grant.grant_id,
        issued_by_actor_id=grant.issued_by_actor_id,
        capability=request.capability,
        scope=grant.scope,
        reason=grant.reason,
        activated_at=now,
        valid_until=grant.valid_until,
    )

    return BreakGlassDecision(
        allowed=True,
        reason_code="explicit_break_glass_grant",
        elevation=elevation,
    )
