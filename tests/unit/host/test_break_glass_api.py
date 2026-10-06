from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from core_platform.application.break_glass import (
    BreakGlassIssueCommand,
    BreakGlassIssueResult,
)
from core_platform.foundation.errors import (
    ValidationError,
)
from core_platform.foundation.identifiers import (
    CorrelationId,
)
from core_platform.host.api.break_glass import (
    BreakGlassIssueRequest,
    BreakGlassRevokeRequest,
    BreakGlassScopeRequest,
    BreakGlassTransitionRequest,
    issue_break_glass_grant,
    resume_break_glass_grant,
    revoke_break_glass_grant,
    suspend_break_glass_grant,
)
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrantStatus,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.ids import (
    BreakGlassGrantId,
)

NOW = datetime(
    2026,
    10,
    6,
    14,
    0,
    tzinfo=UTC,
)

CORRELATION_ID = CorrelationId(
    UUID(
        "00000000-0000-7f00-8000-000000001001"
    )
)

GRANT_ID = BreakGlassGrantId(
    UUID(
        "00000000-0000-7f00-8000-000000001002"
    )
)


class _Lifecycle:
    def __init__(self) -> None:
        self.calls = 0
        self.context: object | None = None
        self.command: BreakGlassIssueCommand | None = None

    async def issue(
        self,
        *,
        context: object,
        command: BreakGlassIssueCommand,
    ) -> BreakGlassIssueResult:
        self.calls += 1
        self.context = context
        self.command = command

        return BreakGlassIssueResult(
            grant_id=GRANT_ID,
            version=0,
        )


def _payload(
    *,
    actor_id: str = (
        "00000000-0000-7f00-8000-000000001003"
    ),
) -> BreakGlassIssueRequest:
    return BreakGlassIssueRequest(
        actor_id=actor_id,
        capabilities=(
            "platform.outbox.retry",
        ),
        scope=BreakGlassScopeRequest(
            kind=BreakGlassScopeKind.TENANT,
        ),
        reason="Controlled emergency recovery",
        valid_from=NOW,
        valid_until=NOW + timedelta(minutes=30),
        accepted_acr_values=frozenset(
            {
                "urn:core-platform:acr:loa2",
            }
        ),
        required_amr=frozenset(
            {
                "mfa",
            }
        ),
    )


def test_issue_route_maps_only_admin_controlled_fields() -> None:
    async def scenario() -> None:
        lifecycle = _Lifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        response = await issue_break_glass_grant(
            payload=_payload(),
            request=request,  # type: ignore[arg-type]
            context=context,  # type: ignore[arg-type]
        )

        assert response.grant_id == str(
            GRANT_ID
        )
        assert response.version == 0
        assert lifecycle.calls == 1
        assert lifecycle.context is context
        assert lifecycle.command is not None

        command = lifecycle.command

        assert str(command.actor_id) == (
            "00000000-0000-7f00-8000-000000001003"
        )
        assert command.capabilities == (
            "platform.outbox.retry",
        )
        assert command.scope.kind is (
            BreakGlassScopeKind.TENANT
        )

    asyncio.run(
        scenario()
    )


def test_issue_request_forbids_server_controlled_fields() -> None:
    payload = _payload().model_dump(
        mode="python"
    )

    payload["tenant_id"] = (
        "00000000-0000-7f00-8000-000000009999"
    )
    payload["status"] = "ACTIVE"

    with pytest.raises(
        PydanticValidationError
    ):
        BreakGlassIssueRequest.model_validate(
            payload
        )


def test_issue_route_rejects_invalid_actor_id_before_service() -> None:
    async def scenario() -> None:
        lifecycle = _Lifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        with pytest.raises(
            ValidationError
        ) as caught:
            await issue_break_glass_grant(
                payload=_payload(
                    actor_id="not-a-uuid"
                ),
                request=request,  # type: ignore[arg-type]
                context=context,  # type: ignore[arg-type]
            )

        assert caught.value.code == (
            "BREAK_GLASS.ISSUE.INVALID"
        )
        assert caught.value.correlation_id == str(
            CORRELATION_ID
        )
        assert lifecycle.calls == 0

    asyncio.run(
        scenario()
    )


class _SuspendLifecycle:
    def __init__(self) -> None:
        self.calls = 0
        self.context: object | None = None
        self.grant_id: BreakGlassGrantId | None = None
        self.expected_version: int | None = None
        self.transition_reason: str | None = None

    async def suspend(
        self,
        *,
        context: object,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        transition_reason: str,
    ) -> int:
        self.calls += 1
        self.context = context
        self.grant_id = grant_id
        self.expected_version = expected_version
        self.transition_reason = transition_reason

        return expected_version + 1


def test_suspend_route_maps_transition_intent() -> None:
    async def scenario() -> None:
        lifecycle = _SuspendLifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        response = await suspend_break_glass_grant(
            grant_id=str(GRANT_ID),
            payload=BreakGlassTransitionRequest(
                expected_version=7,
                transition_reason=(
                    "Emergency condition contained"
                ),
            ),
            request=request,  # type: ignore[arg-type]
            context=context,  # type: ignore[arg-type]
        )

        assert response.grant_id == str(
            GRANT_ID
        )
        assert response.version == 8

        assert lifecycle.calls == 1
        assert lifecycle.context is context
        assert lifecycle.grant_id == GRANT_ID
        assert lifecycle.expected_version == 7
        assert lifecycle.transition_reason == (
            "Emergency condition contained"
        )

    asyncio.run(
        scenario()
    )


def test_suspend_route_rejects_invalid_grant_id_before_service() -> None:
    async def scenario() -> None:
        lifecycle = _SuspendLifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        with pytest.raises(
            ValidationError
        ) as caught:
            await suspend_break_glass_grant(
                grant_id="not-a-uuid",
                payload=BreakGlassTransitionRequest(
                    expected_version=7,
                    transition_reason=(
                        "Emergency suspension"
                    ),
                ),
                request=request,  # type: ignore[arg-type]
                context=context,  # type: ignore[arg-type]
            )

        assert caught.value.code == (
            "BREAK_GLASS.TRANSITION.INVALID"
        )
        assert caught.value.correlation_id == str(
            CORRELATION_ID
        )
        assert lifecycle.calls == 0

    asyncio.run(
        scenario()
    )


def test_suspend_request_forbids_unknown_fields() -> None:
    with pytest.raises(
        PydanticValidationError
    ):
        BreakGlassTransitionRequest.model_validate(
            {
                "expected_version": 7,
                "transition_reason": (
                    "Emergency suspension"
                ),
                "status": "SUSPENDED",
            }
        )


class _ResumeLifecycle:
    def __init__(self) -> None:
        self.calls = 0
        self.context: object | None = None
        self.grant_id: BreakGlassGrantId | None = None
        self.expected_version: int | None = None
        self.transition_reason: str | None = None

    async def resume(
        self,
        *,
        context: object,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        transition_reason: str,
    ) -> int:
        self.calls += 1
        self.context = context
        self.grant_id = grant_id
        self.expected_version = expected_version
        self.transition_reason = transition_reason

        return expected_version + 1


def test_resume_route_maps_transition_intent() -> None:
    async def scenario() -> None:
        lifecycle = _ResumeLifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        response = await resume_break_glass_grant(
            grant_id=str(GRANT_ID),
            payload=BreakGlassTransitionRequest(
                expected_version=8,
                transition_reason=(
                    "Emergency recovery still active"
                ),
            ),
            request=request,  # type: ignore[arg-type]
            context=context,  # type: ignore[arg-type]
        )

        assert response.grant_id == str(
            GRANT_ID
        )
        assert response.version == 9

        assert lifecycle.calls == 1
        assert lifecycle.context is context
        assert lifecycle.grant_id == GRANT_ID
        assert lifecycle.expected_version == 8
        assert lifecycle.transition_reason == (
            "Emergency recovery still active"
        )

    asyncio.run(
        scenario()
    )


def test_resume_route_rejects_invalid_grant_id_before_service() -> None:
    async def scenario() -> None:
        lifecycle = _ResumeLifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        with pytest.raises(
            ValidationError
        ) as caught:
            await resume_break_glass_grant(
                grant_id="not-a-uuid",
                payload=BreakGlassTransitionRequest(
                    expected_version=8,
                    transition_reason=(
                        "Emergency recovery"
                    ),
                ),
                request=request,  # type: ignore[arg-type]
                context=context,  # type: ignore[arg-type]
            )

        assert caught.value.code == (
            "BREAK_GLASS.TRANSITION.INVALID"
        )
        assert caught.value.correlation_id == str(
            CORRELATION_ID
        )
        assert lifecycle.calls == 0

    asyncio.run(
        scenario()
    )


class _RevokeLifecycle:
    def __init__(self) -> None:
        self.calls = 0
        self.context: object | None = None
        self.grant_id: BreakGlassGrantId | None = None
        self.expected_version: int | None = None
        self.expected_current_status: (
            BreakGlassGrantStatus | None
        ) = None
        self.transition_reason: str | None = None

    async def revoke(
        self,
        *,
        context: object,
        grant_id: BreakGlassGrantId,
        expected_version: int,
        expected_current_status: BreakGlassGrantStatus,
        transition_reason: str,
    ) -> int:
        self.calls += 1
        self.context = context
        self.grant_id = grant_id
        self.expected_version = expected_version
        self.expected_current_status = (
            expected_current_status
        )
        self.transition_reason = transition_reason

        return expected_version + 1


@pytest.mark.parametrize(
    "source_status",
    [
        BreakGlassGrantStatus.ACTIVE,
        BreakGlassGrantStatus.SUSPENDED,
    ],
)
def test_revoke_route_maps_source_precondition(
    source_status: BreakGlassGrantStatus,
) -> None:
    async def scenario() -> None:
        lifecycle = _RevokeLifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        response = await revoke_break_glass_grant(
            grant_id=str(GRANT_ID),
            payload=BreakGlassRevokeRequest(
                expected_version=9,
                expected_current_status=source_status,
                transition_reason=(
                    "Emergency access no longer required"
                ),
            ),
            request=request,  # type: ignore[arg-type]
            context=context,  # type: ignore[arg-type]
        )

        assert response.grant_id == str(
            GRANT_ID
        )
        assert response.version == 10

        assert lifecycle.calls == 1
        assert lifecycle.context is context
        assert lifecycle.grant_id == GRANT_ID
        assert lifecycle.expected_version == 9
        assert (
            lifecycle.expected_current_status
            is source_status
        )
        assert lifecycle.transition_reason == (
            "Emergency access no longer required"
        )

    asyncio.run(
        scenario()
    )


def test_revoke_route_rejects_invalid_grant_id_before_service() -> None:
    async def scenario() -> None:
        lifecycle = _RevokeLifecycle()

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    break_glass_lifecycle=lifecycle
                )
            )
        )

        context = SimpleNamespace(
            correlation_id=CORRELATION_ID
        )

        with pytest.raises(
            ValidationError
        ) as caught:
            await revoke_break_glass_grant(
                grant_id="not-a-uuid",
                payload=BreakGlassRevokeRequest(
                    expected_version=9,
                    expected_current_status=(
                        BreakGlassGrantStatus.ACTIVE
                    ),
                    transition_reason=(
                        "Emergency access no longer required"
                    ),
                ),
                request=request,  # type: ignore[arg-type]
                context=context,  # type: ignore[arg-type]
            )

        assert caught.value.code == (
            "BREAK_GLASS.TRANSITION.INVALID"
        )
        assert caught.value.correlation_id == str(
            CORRELATION_ID
        )
        assert lifecycle.calls == 0

    asyncio.run(
        scenario()
    )


def test_revoke_request_forbids_unknown_fields() -> None:
    with pytest.raises(
        PydanticValidationError
    ):
        BreakGlassRevokeRequest.model_validate(
            {
                "expected_version": 9,
                "expected_current_status": "ACTIVE",
                "transition_reason": (
                    "Emergency access no longer required"
                ),
                "target_status": "REVOKED",
            }
        )
