from __future__ import annotations

from core_platform.platform_kernel.break_glass.models import (
    BreakGlassGrantStatus,
)

_ALLOWED_TRANSITIONS: dict[
    BreakGlassGrantStatus,
    frozenset[BreakGlassGrantStatus],
] = {
    BreakGlassGrantStatus.ACTIVE: frozenset(
        {
            BreakGlassGrantStatus.SUSPENDED,
            BreakGlassGrantStatus.REVOKED,
        }
    ),
    BreakGlassGrantStatus.SUSPENDED: frozenset(
        {
            BreakGlassGrantStatus.ACTIVE,
            BreakGlassGrantStatus.REVOKED,
        }
    ),
    BreakGlassGrantStatus.REVOKED: frozenset(),
}


def require_break_glass_status_transition(
    current: BreakGlassGrantStatus,
    target: BreakGlassGrantStatus,
) -> None:
    """Require one explicit legal break-glass grant status transition."""

    if target in _ALLOWED_TRANSITIONS[current]:
        return

    raise ValueError(
        "Break-glass grant status transition "
        f"{current.value} -> {target.value} is not allowed"
    )
