from __future__ import annotations

from core_platform.foundation.errors import AuthorizationError
from core_platform.platform_kernel.context import ExecutionContext

BREAK_GLASS_MANAGEMENT_CAPABILITY = (
    "platform.break-glass.manage"
)

BREAK_GLASS_MANAGEMENT_DIRECT_AUTHORIZATION_ERROR = (
    "BREAK_GLASS.MANAGEMENT.REQUIRES.DIRECT.AUTHORIZATION"
)


def require_direct_break_glass_management(
    context: ExecutionContext,
) -> None:
    """Reject recursive use of break-glass to administer break-glass."""

    if context.break_glass is None:
        return

    raise AuthorizationError(
        BREAK_GLASS_MANAGEMENT_DIRECT_AUTHORIZATION_ERROR,
        (
            "Break-glass management requires "
            "direct authorization"
        ),
        correlation_id=str(context.correlation_id),
    )
