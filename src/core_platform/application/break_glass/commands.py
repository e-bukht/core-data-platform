from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core_platform.platform_kernel.break_glass import (
    BreakGlassScope,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
)


@dataclass(frozen=True, slots=True)
class BreakGlassIssueCommand:
    actor_id: ActorId
    capabilities: tuple[str, ...]
    scope: BreakGlassScope
    reason: str
    valid_from: datetime
    valid_until: datetime
    accepted_acr_values: frozenset[str]
    required_amr: frozenset[str]


@dataclass(frozen=True, slots=True)
class BreakGlassIssueResult:
    grant_id: BreakGlassGrantId
    version: int
