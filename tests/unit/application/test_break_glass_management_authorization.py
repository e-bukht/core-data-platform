from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from core_platform.application.break_glass import (
    BREAK_GLASS_MANAGEMENT_CAPABILITY,
    BREAK_GLASS_MANAGEMENT_DIRECT_AUTHORIZATION_ERROR,
    require_direct_break_glass_management,
)
from core_platform.foundation.errors import AuthorizationError
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)

NOW = datetime(
    2026,
    10,
    5,
    18,
    30,
    tzinfo=UTC,
)

TENANT_ID = TenantId(UUID("00000000-0000-7000-8000-000000000101"))
ACTOR_ID = ActorId(UUID("00000000-0000-7000-8000-000000000102"))
ISSUER_ID = ActorId(UUID("00000000-0000-7000-8000-000000000103"))
GRANT_ID = BreakGlassGrantId(UUID("00000000-0000-7000-8000-000000000104"))
CORRELATION_ID = CorrelationId(UUID("00000000-0000-7000-8000-000000000105"))


def _authentication() -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example.test",
        subject="operator",
        audience=("core-data-api",),
        client_id="control-plane",
        scopes=frozenset(),
        acr="urn:core-platform:acr:loa2",
        amr=("pwd", "mfa"),
        authenticated_at=NOW - timedelta(minutes=1),
        token_id="token-1",
        expires_at=NOW + timedelta(minutes=15),
    )


def _context(
    *,
    elevation_capability: str | None,
) -> ExecutionContext:
    elevation = None

    if elevation_capability is not None:
        elevation = BreakGlassElevationContext(
            grant_id=GRANT_ID,
            issued_by_actor_id=ISSUER_ID,
            capability=elevation_capability,
            scope=BreakGlassScope(BreakGlassScopeKind.TENANT),
            reason="Emergency recovery",
            activated_at=NOW,
            valid_until=NOW + timedelta(minutes=20),
        )

    return ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        actor_type=ActorType.HUMAN,
        authentication=_authentication(),
        correlation_id=CORRELATION_ID,
        break_glass=elevation,
    )


def test_direct_management_context_is_allowed() -> None:
    require_direct_break_glass_management(
        _context(
            elevation_capability=None,
        )
    )


@pytest.mark.parametrize(
    "elevation_capability",
    [
        BREAK_GLASS_MANAGEMENT_CAPABILITY,
        "platform.context.read",
    ],
)
def test_any_break_glass_elevation_is_rejected_for_management(
    elevation_capability: str,
) -> None:
    with pytest.raises(
        AuthorizationError,
    ) as exc:
        require_direct_break_glass_management(
            _context(
                elevation_capability=elevation_capability,
            )
        )

    assert exc.value.code == BREAK_GLASS_MANAGEMENT_DIRECT_AUTHORIZATION_ERROR
