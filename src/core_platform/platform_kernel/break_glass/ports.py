from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core_platform.platform_kernel.break_glass.models import (
    BreakGlassGrant,
)
from core_platform.platform_kernel.ids import ActorId, TenantId


class BreakGlassRepository(Protocol):
    async def list_candidate_grants(
        self,
        tenant_id: TenantId,
        actor_id: ActorId,
        capability: str,
        *,
        now: datetime,
    ) -> tuple[BreakGlassGrant, ...]: ...
