from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

from core_platform.application.break_glass import (
    BREAK_GLASS_MANAGEMENT_CAPABILITY,
    BreakGlassLifecycleService,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.host.main import create_app
from core_platform.host.settings import get_settings
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
    BreakGlassGrant,
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
    6,
    17,
    0,
    tzinfo=UTC,
)

TENANT_ID = TenantId(UUID("00000000-0000-7f00-8000-000000001001"))

ADMIN_ID = ActorId(UUID("00000000-0000-7f00-8000-000000001002"))

SUBJECT_ID = ActorId(UUID("00000000-0000-7f00-8000-000000001003"))

CORRELATION_ID = CorrelationId(UUID("00000000-0000-7f00-8000-000000001004"))


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


class _Signer:
    algorithm = "Ed25519"
    key_id = "asgi-test-key"

    def __init__(self) -> None:
        self.calls = 0

    async def sign(
        self,
        payload: bytes,
    ) -> bytes:
        assert payload
        self.calls += 1
        return b"signature"


class _Persistence:
    def __init__(self) -> None:
        self.issue_calls = 0
        self.issue_kwargs: dict[str, object] | None = None

    async def persist_issue(
        self,
        **kwargs: object,
    ) -> int:
        self.issue_calls += 1
        self.issue_kwargs = kwargs
        return 0

    async def persist_transition(
        self,
        **kwargs: object,
    ) -> int:
        del kwargs
        raise AssertionError("Transition persistence is not expected")


def _authentication() -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example.test",
        subject="lifecycle-admin",
        audience=("core-data-api",),
        client_id="control-plane",
        scopes=frozenset(),
        acr="urn:core-platform:acr:loa2",
        amr=("pwd", "mfa"),
        authenticated_at=NOW - timedelta(minutes=1),
        token_id="asgi-management-token",
        expires_at=NOW + timedelta(minutes=15),
    )


def _context(
    *,
    elevated: bool,
) -> ExecutionContext:
    elevation = None

    if elevated:
        elevation = BreakGlassElevationContext(
            grant_id=BreakGlassGrantId(UUID("00000000-0000-7f00-8000-000000001005")),
            issued_by_actor_id=ActorId(UUID("00000000-0000-7f00-8000-000000001006")),
            capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
            scope=BreakGlassScope(BreakGlassScopeKind.TENANT),
            reason="Controlled emergency elevation",
            activated_at=NOW,
            valid_until=NOW + timedelta(minutes=10),
        )

    return ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=ADMIN_ID,
        actor_type=ActorType.HUMAN,
        authentication=_authentication(),
        correlation_id=CORRELATION_ID,
        break_glass=elevation,
    )


class _Authorizer:
    def __init__(
        self,
        context: ExecutionContext,
    ) -> None:
        self.context = context
        self.calls = 0
        self.token: str | None = None
        self.tenant_selector: str | None = None
        self.capability_code: str | None = None
        self.correlation_id: CorrelationId | None = None

    async def authorize(
        self,
        *,
        token: str,
        tenant_selector: str | None,
        capability_code: str,
        correlation_id: CorrelationId,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> ExecutionContext:
        assert resource_type is None
        assert resource_id is None

        self.calls += 1
        self.token = token
        self.tenant_selector = tenant_selector
        self.capability_code = capability_code
        self.correlation_id = correlation_id

        return self.context


def _payload() -> dict[str, object]:
    return {
        "actor_id": str(SUBJECT_ID.value),
        "capabilities": [
            "platform.outbox.retry",
        ],
        "scope": {
            "kind": "TENANT",
        },
        "reason": "Controlled emergency recovery",
        "valid_from": NOW.isoformat(),
        "valid_until": (NOW + timedelta(minutes=30)).isoformat(),
        "accepted_acr_values": [
            "urn:core-platform:acr:loa2",
        ],
        "required_amr": [
            "mfa",
        ],
    }


async def _exercise_issue(
    *,
    elevated: bool,
) -> tuple[
    httpx.Response,
    _Authorizer,
    _Clock,
    _Signer,
    _Persistence,
]:
    settings = get_settings()

    app = create_app(
        settings=settings,
    )

    authorizer = _Authorizer(
        _context(
            elevated=elevated,
        )
    )

    clock = _Clock()
    signer = _Signer()
    persistence = _Persistence()

    app.state.context_trust = authorizer
    app.state.break_glass_lifecycle = BreakGlassLifecycleService(
        persistence=persistence,
        signer=signer,
        clock=clock,
    )

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/platform/break-glass/grants",
            headers={
                settings.tenant_header: str(TENANT_ID.value),
                settings.correlation_header: str(CORRELATION_ID),
                "Authorization": ("Bearer management-token"),
            },
            json=_payload(),
        )

    return (
        response,
        authorizer,
        clock,
        signer,
        persistence,
    )


def test_direct_management_authorization_reaches_real_lifecycle_service() -> None:
    (
        response,
        authorizer,
        clock,
        signer,
        persistence,
    ) = asyncio.run(
        _exercise_issue(
            elevated=False,
        )
    )

    assert response.status_code == 201

    body = response.json()

    assert body["version"] == 0
    assert UUID(body["grant_id"])

    assert authorizer.calls == 1
    assert authorizer.token == "management-token"
    assert authorizer.tenant_selector == str(TENANT_ID.value)
    assert authorizer.capability_code == (BREAK_GLASS_MANAGEMENT_CAPABILITY)
    assert authorizer.correlation_id == (CORRELATION_ID)

    assert clock.calls == 1
    assert signer.calls == 1
    assert persistence.issue_calls == 1
    assert persistence.issue_kwargs is not None

    grant = persistence.issue_kwargs["grant"]

    assert isinstance(
        grant,
        BreakGlassGrant,
    )
    assert grant.tenant_id == TENANT_ID
    assert grant.actor_id == SUBJECT_ID
    assert grant.issued_by_actor_id == ADMIN_ID

    assert response.headers[get_settings().correlation_header] == str(CORRELATION_ID)


def test_break_glass_elevated_management_is_rejected_through_real_asgi_route() -> None:
    (
        response,
        authorizer,
        clock,
        signer,
        persistence,
    ) = asyncio.run(
        _exercise_issue(
            elevated=True,
        )
    )

    assert response.status_code == 403

    body = response.json()

    assert body["code"] == ("BREAK_GLASS.MANAGEMENT.REQUIRES.DIRECT.AUTHORIZATION")
    assert body["correlation_id"] == str(CORRELATION_ID)

    assert authorizer.calls == 1
    assert authorizer.capability_code == (BREAK_GLASS_MANAGEMENT_CAPABILITY)

    assert clock.calls == 0
    assert signer.calls == 0
    assert persistence.issue_calls == 0
    assert persistence.issue_kwargs is None
