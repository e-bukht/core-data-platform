from __future__ import annotations

from datetime import UTC, datetime

from core_platform.platform_kernel.policy.models import (
    CapabilityGrant,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
)


class CapabilityGrantPdp:
    """P0-I2 default-deny PDP based on explicit tenant-scoped capability grants."""

    def decide(
        self,
        request: PolicyRequest,
        grant: CapabilityGrant | None,
        *,
        now: datetime | None = None,
    ) -> PolicyDecision:
        instant = now or datetime.now(UTC)
        if grant is None:
            return PolicyDecision(PolicyEffect.DENY, "grant_not_found")
        if grant.tenant_id != request.tenant_id or grant.actor_id != request.actor_id:
            return PolicyDecision(PolicyEffect.DENY, "grant_subject_mismatch")
        if grant.capability_code != request.capability:
            return PolicyDecision(PolicyEffect.DENY, "capability_mismatch")
        if not grant.is_active_at(instant):
            return PolicyDecision(PolicyEffect.DENY, "grant_not_active")
        return PolicyDecision(PolicyEffect.ALLOW, "explicit_active_grant")
