from __future__ import annotations

import pytest

from core_platform.platform_kernel.break_glass.lifecycle import (
    require_break_glass_status_transition,
)
from core_platform.platform_kernel.break_glass.models import (
    BreakGlassGrantStatus,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (
            BreakGlassGrantStatus.ACTIVE,
            BreakGlassGrantStatus.SUSPENDED,
        ),
        (
            BreakGlassGrantStatus.ACTIVE,
            BreakGlassGrantStatus.REVOKED,
        ),
        (
            BreakGlassGrantStatus.SUSPENDED,
            BreakGlassGrantStatus.ACTIVE,
        ),
        (
            BreakGlassGrantStatus.SUSPENDED,
            BreakGlassGrantStatus.REVOKED,
        ),
    ],
)
def test_allowed_break_glass_status_transitions(
    current: BreakGlassGrantStatus,
    target: BreakGlassGrantStatus,
) -> None:
    require_break_glass_status_transition(
        current,
        target,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (
            BreakGlassGrantStatus.ACTIVE,
            BreakGlassGrantStatus.ACTIVE,
        ),
        (
            BreakGlassGrantStatus.SUSPENDED,
            BreakGlassGrantStatus.SUSPENDED,
        ),
        (
            BreakGlassGrantStatus.REVOKED,
            BreakGlassGrantStatus.REVOKED,
        ),
        (
            BreakGlassGrantStatus.REVOKED,
            BreakGlassGrantStatus.ACTIVE,
        ),
        (
            BreakGlassGrantStatus.REVOKED,
            BreakGlassGrantStatus.SUSPENDED,
        ),
    ],
)
def test_forbidden_break_glass_status_transitions(
    current: BreakGlassGrantStatus,
    target: BreakGlassGrantStatus,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            f"Break-glass grant status transition {current.value} -> {target.value} is not allowed"
        ),
    ):
        require_break_glass_status_transition(
            current,
            target,
        )
