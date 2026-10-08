from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)


def _grant(
    *,
    status: BreakGlassGrantStatus = (BreakGlassGrantStatus.ACTIVE),
    capabilities: tuple[str, ...] = ("platform.outbox.retry",),
    scope: BreakGlassScope | None = None,
    accepted_acr_values: frozenset[str] = frozenset({"urn:core-platform:acr:elevated"}),
    required_amr: frozenset[str] = frozenset({"mfa"}),
) -> BreakGlassGrant:
    start = datetime(
        2026,
        9,
        26,
        20,
        0,
        tzinfo=UTC,
    )

    return BreakGlassGrant(
        grant_id=BreakGlassGrantId.new(),
        tenant_id=TenantId.new(),
        actor_id=ActorId.new(),
        issued_by_actor_id=ActorId.new(),
        capabilities=capabilities,
        scope=scope or BreakGlassScope(BreakGlassScopeKind.TENANT),
        reason="Emergency operational recovery",
        valid_from=start,
        valid_until=start + timedelta(minutes=30),
        status=status,
        accepted_acr_values=accepted_acr_values,
        required_amr=required_amr,
    )


def test_active_grant_is_temporally_bounded() -> None:
    grant = _grant()

    assert grant.is_active_at(grant.valid_from)
    assert grant.is_active_at(grant.valid_until - timedelta(microseconds=1))
    assert not grant.is_active_at(grant.valid_until)


@pytest.mark.parametrize(
    "status",
    [
        BreakGlassGrantStatus.SUSPENDED,
        BreakGlassGrantStatus.REVOKED,
    ],
)
def test_non_active_status_never_activates(
    status: BreakGlassGrantStatus,
) -> None:
    grant = _grant(status=status)

    assert not grant.is_active_at(grant.valid_from)


def test_grant_requires_strict_expiration() -> None:
    start = datetime(
        2026,
        9,
        26,
        20,
        0,
        tzinfo=UTC,
    )

    with pytest.raises(
        ValueError,
        match="valid_until must be after valid_from",
    ):
        BreakGlassGrant(
            grant_id=BreakGlassGrantId.new(),
            tenant_id=TenantId.new(),
            actor_id=ActorId.new(),
            issued_by_actor_id=ActorId.new(),
            capabilities=("platform.outbox.retry",),
            scope=BreakGlassScope(BreakGlassScopeKind.TENANT),
            reason="Emergency recovery",
            valid_from=start,
            valid_until=start,
            status=BreakGlassGrantStatus.ACTIVE,
            accepted_acr_values=frozenset({"elevated"}),
            required_amr=frozenset(),
        )


def test_grant_requires_explicit_capabilities() -> None:
    with pytest.raises(
        ValueError,
        match="capabilities must not be empty",
    ):
        _grant(capabilities=())


def test_grant_rejects_duplicate_capabilities() -> None:
    with pytest.raises(
        ValueError,
        match="capabilities must not contain duplicates",
    ):
        _grant(
            capabilities=(
                "platform.outbox.retry",
                "platform.outbox.retry",
            )
        )


def test_grant_requires_elevated_authentication_assurance() -> None:
    with pytest.raises(
        ValueError,
        match="requires elevated authentication assurance",
    ):
        _grant(
            accepted_acr_values=frozenset(),
            required_amr=frozenset(),
        )


def test_tenant_scope_matches_any_resource() -> None:
    scope = BreakGlassScope(BreakGlassScopeKind.TENANT)

    assert scope.matches(
        resource_type=None,
        resource_id=None,
    )
    assert scope.matches(
        resource_type="outbox-message",
        resource_id="message-1",
    )


def test_resource_type_scope_is_exact() -> None:
    scope = BreakGlassScope(
        BreakGlassScopeKind.RESOURCE_TYPE,
        resource_type="outbox-message",
    )

    assert scope.matches(
        resource_type="outbox-message",
        resource_id="message-1",
    )
    assert not scope.matches(
        resource_type="tenant",
        resource_id="message-1",
    )


def test_resource_scope_is_exact() -> None:
    scope = BreakGlassScope(
        BreakGlassScopeKind.RESOURCE,
        resource_type="outbox-message",
        resource_id="message-1",
    )

    assert scope.matches(
        resource_type="outbox-message",
        resource_id="message-1",
    )
    assert not scope.matches(
        resource_type="outbox-message",
        resource_id="message-2",
    )


def test_resource_scope_requires_complete_identity() -> None:
    with pytest.raises(
        ValueError,
        match=("RESOURCE scope requires resource_type and resource_id"),
    ):
        BreakGlassScope(
            BreakGlassScopeKind.RESOURCE,
            resource_type="outbox-message",
        )


def test_elevation_context_is_explicit_and_bounded() -> None:
    grant = _grant()
    activated_at = grant.valid_from

    elevation = BreakGlassElevationContext(
        grant_id=grant.grant_id,
        issued_by_actor_id=grant.issued_by_actor_id,
        capability="platform.outbox.retry",
        scope=grant.scope,
        reason=grant.reason,
        activated_at=activated_at,
        valid_until=grant.valid_until,
    )

    assert elevation.grant_id == grant.grant_id
    assert elevation.capability == "platform.outbox.retry"
    assert elevation.valid_until == grant.valid_until


def test_grant_capability_check_is_explicit() -> None:
    grant = _grant()

    assert grant.permits_capability("platform.outbox.retry")
    assert not grant.permits_capability("platform.audit.delete")
