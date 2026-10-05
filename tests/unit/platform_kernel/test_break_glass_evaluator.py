from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassRequest,
    BreakGlassScope,
    BreakGlassScopeKind,
    evaluate_break_glass,
)
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)

_NOW = datetime(
    2026,
    9,
    26,
    20,
    30,
    tzinfo=UTC,
)


def _authentication(
    *,
    acr: str | None = "urn:core-platform:acr:elevated",
    amr: tuple[str, ...] = ("pwd", "mfa"),
) -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example.test",
        subject="operator",
        audience=("core-data-api",),
        client_id="control-plane",
        scopes=frozenset(),
        acr=acr,
        amr=amr,
        authenticated_at=_NOW - timedelta(minutes=1),
        token_id="token-1",
        expires_at=_NOW + timedelta(minutes=15),
    )


def _grant(
    *,
    tenant_id: TenantId | None = None,
    actor_id: ActorId | None = None,
    capabilities: tuple[str, ...] = (
        "platform.outbox.retry",
    ),
    scope: BreakGlassScope | None = None,
    status: BreakGlassGrantStatus = (
        BreakGlassGrantStatus.ACTIVE
    ),
    accepted_acr_values: frozenset[str] = frozenset(
        {"urn:core-platform:acr:elevated"}
    ),
    required_amr: frozenset[str] = frozenset(
        {"mfa"}
    ),
) -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=BreakGlassGrantId.new(),
        tenant_id=tenant_id or TenantId.new(),
        actor_id=actor_id or ActorId.new(),
        issued_by_actor_id=ActorId.new(),
        capabilities=capabilities,
        scope=scope
        or BreakGlassScope(
            BreakGlassScopeKind.TENANT
        ),
        reason="Emergency operational recovery",
        valid_from=_NOW - timedelta(minutes=5),
        valid_until=_NOW + timedelta(minutes=25),
        status=status,
        accepted_acr_values=accepted_acr_values,
        required_amr=required_amr,
    )


def _request(
    grant: BreakGlassGrant,
    *,
    capability: str = "platform.outbox.retry",
    authentication: AuthenticationContext | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> BreakGlassRequest:
    return BreakGlassRequest(
        tenant_id=grant.tenant_id,
        actor_id=grant.actor_id,
        capability=capability,
        authentication_context=(
            authentication or _authentication()
        ),
        resource_type=resource_type,
        resource_id=resource_id,
    )


def test_valid_explicit_break_glass_grant_allows() -> None:
    grant = _grant()

    decision = evaluate_break_glass(
        _request(grant),
        grant,
        now=_NOW,
    )

    assert decision.allowed
    assert decision.reason_code == (
        "explicit_break_glass_grant"
    )
    assert decision.elevation is not None
    assert decision.elevation.grant_id == grant.grant_id
    assert decision.elevation.valid_until == grant.valid_until


def test_missing_grant_denies() -> None:
    grant = _grant()

    decision = evaluate_break_glass(
        _request(grant),
        None,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "grant_not_found"
    assert decision.elevation is None


def test_subject_mismatch_denies() -> None:
    grant = _grant()

    request = BreakGlassRequest(
        tenant_id=grant.tenant_id,
        actor_id=ActorId.new(),
        capability="platform.outbox.retry",
        authentication_context=_authentication(),
    )

    decision = evaluate_break_glass(
        request,
        grant,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "grant_subject_mismatch"


def test_expired_grant_denies() -> None:
    grant = _grant()

    decision = evaluate_break_glass(
        _request(grant),
        grant,
        now=grant.valid_until,
    )

    assert not decision.allowed
    assert decision.reason_code == "grant_not_active"


def test_unlisted_capability_denies() -> None:
    grant = _grant()

    decision = evaluate_break_glass(
        _request(
            grant,
            capability="platform.audit.delete",
        ),
        grant,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "capability_not_permitted"


def test_resource_scope_mismatch_denies() -> None:
    grant = _grant(
        scope=BreakGlassScope(
            BreakGlassScopeKind.RESOURCE,
            resource_type="outbox-message",
            resource_id="message-1",
        )
    )

    decision = evaluate_break_glass(
        _request(
            grant,
            resource_type="outbox-message",
            resource_id="message-2",
        ),
        grant,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "scope_mismatch"


def test_exact_resource_scope_allows() -> None:
    grant = _grant(
        scope=BreakGlassScope(
            BreakGlassScopeKind.RESOURCE,
            resource_type="outbox-message",
            resource_id="message-1",
        )
    )

    decision = evaluate_break_glass(
        _request(
            grant,
            resource_type="outbox-message",
            resource_id="message-1",
        ),
        grant,
        now=_NOW,
    )

    assert decision.allowed
    assert decision.elevation is not None


def test_missing_required_acr_denies() -> None:
    grant = _grant()

    decision = evaluate_break_glass(
        _request(
            grant,
            authentication=_authentication(
                acr="urn:core-platform:acr:standard"
            ),
        ),
        grant,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "acr_insufficient"


def test_missing_required_amr_denies() -> None:
    grant = _grant()

    decision = evaluate_break_glass(
        _request(
            grant,
            authentication=_authentication(
                amr=("pwd",)
            ),
        ),
        grant,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "amr_insufficient"


def test_all_required_amr_values_are_required() -> None:
    grant = _grant(
        required_amr=frozenset(
            {"pwd", "mfa", "hardware-key"}
        )
    )

    decision = evaluate_break_glass(
        _request(grant),
        grant,
        now=_NOW,
    )

    assert not decision.allowed
    assert decision.reason_code == "amr_insufficient"