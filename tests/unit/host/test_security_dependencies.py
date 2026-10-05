from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from structlog.contextvars import get_contextvars

from core_platform.foundation.identifiers import CorrelationId
from core_platform.host.security import dependencies
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
    9,
    27,
    8,
    30,
    tzinfo=UTC,
)

TENANT_ID = TenantId(
    UUID(
        "00000000-0000-7a00-8000-000000001001"
    )
)
ACTOR_ID = ActorId(
    UUID(
        "00000000-0000-7a00-8000-000000001002"
    )
)
ISSUER_ID = ActorId(
    UUID(
        "00000000-0000-7a00-8000-000000001003"
    )
)
GRANT_ID = BreakGlassGrantId(
    UUID(
        "00000000-0000-7a00-8000-000000001004"
    )
)
CORRELATION_ID = CorrelationId(
    UUID(
        "00000000-0000-7a00-8000-000000001005"
    )
)


class _FakeService:
    def __init__(
        self,
        context: ExecutionContext,
    ) -> None:
        self._context = context

    async def authorize(
        self,
        **kwargs: object,
    ) -> ExecutionContext:
        return self._context


class _FakeLogger:
    def __init__(self) -> None:
        self.entries: list[
            tuple[str, dict[str, object]]
        ] = []

    async def ainfo(
        self,
        event: str,
        **kwargs: object,
    ) -> None:
        self.entries.append(
            (
                event,
                kwargs,
            )
        )

    async def awarn(
        self,
        event: str,
        **kwargs: object,
    ) -> None:
        self.entries.append(
            (
                event,
                kwargs,
            )
        )


def _authentication() -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example",
        subject="subject",
        audience=("core-data-api",),
        client_id=None,
        scopes=frozenset(),
        acr="urn:core-platform:acr:elevated",
        amr=("pwd", "mfa"),
        authenticated_at=NOW,
        token_id=None,
        expires_at=NOW + timedelta(minutes=5),
    )


def _context(
    *,
    elevated: bool,
) -> ExecutionContext:
    elevation = None

    if elevated:
        elevation = BreakGlassElevationContext(
            grant_id=GRANT_ID,
            issued_by_actor_id=ISSUER_ID,
            capability="platform.context.read",
            scope=BreakGlassScope(
                BreakGlassScopeKind.TENANT
            ),
            reason=(
                "Sensitive emergency operational reason"
            ),
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


def _request(
    context: ExecutionContext,
) -> Request:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(
                correlation_header="X-Correlation-Id",
                tenant_header="X-Tenant-Id",
            ),
            context_trust=_FakeService(
                context
            ),
        )
    )

    scope = {
        "type": "http",
        "asgi": {
            "version": "3.0",
            "spec_version": "2.3",
        },
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/probe",
        "raw_path": b"/probe",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (
                b"x-tenant-id",
                str(TENANT_ID).encode(),
            ),
            (
                b"x-correlation-id",
                str(CORRELATION_ID).encode(),
            ),
        ],
        "client": (
            "test-client",
            12345,
        ),
        "server": (
            "test-server",
            80,
        ),
        "state": {},
        "app": app,
    }

    return Request(
        scope=scope
    )


async def _exercise_dependency(
    context: ExecutionContext,
) -> tuple[
    _FakeLogger,
    dict[str, Any],
    dict[str, Any],
]:
    fake_logger = _FakeLogger()
    dependencies.logger = fake_logger

    dependency = dependencies.require_capability(
        "platform.context.read"
    )

    generator = dependency(
        _request(context),
        Response(),
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="token",
        ),
    )

    resolved = await anext(generator)
    assert resolved == context

    bound_during = dict(
        get_contextvars()
    )

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    bound_after = dict(
        get_contextvars()
    )

    return (
        fake_logger,
        bound_during,
        bound_after,
    )


def test_normal_allow_logging_remains_unchanged() -> None:
    logger, bound_during, bound_after = asyncio.run(
        _exercise_dependency(
            _context(
                elevated=False
            )
        )
    )

    assert len(logger.entries) == 1

    event, fields = logger.entries[0]

    assert event == "authorization_decision"
    assert fields["effect"] == "ALLOW"

    assert "break_glass" not in fields
    assert "break_glass_grant_id" not in fields
    assert "break_glass_scope_kind" not in fields

    assert "break_glass" not in bound_during
    assert "break_glass_grant_id" not in bound_during
    assert "break_glass_scope_kind" not in bound_during

    assert bound_after == {}


def test_break_glass_allow_logs_only_safe_elevation_metadata() -> None:
    logger, bound_during, bound_after = asyncio.run(
        _exercise_dependency(
            _context(
                elevated=True
            )
        )
    )

    assert len(logger.entries) == 1

    event, fields = logger.entries[0]

    assert event == "authorization_decision"
    assert fields["effect"] == "ALLOW"

    assert fields["break_glass"] is True
    assert fields["break_glass_grant_id"] == str(
        GRANT_ID.value
    )
    assert fields["break_glass_scope_kind"] == "TENANT"

    assert bound_during["break_glass"] is True
    assert bound_during["break_glass_grant_id"] == str(
        GRANT_ID.value
    )
    assert (
        bound_during["break_glass_scope_kind"]
        == "TENANT"
    )

    serialized = repr(
        {
            "log": fields,
            "context": bound_during,
        }
    )

    assert (
        "Sensitive emergency operational reason"
        not in serialized
    )
    assert "reason" not in fields
    assert "issued_by_actor_id" not in fields

    assert bound_after == {}