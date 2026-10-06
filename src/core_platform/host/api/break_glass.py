from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from core_platform.application.break_glass import (
    BREAK_GLASS_MANAGEMENT_CAPABILITY,
    BreakGlassIssueCommand,
    BreakGlassLifecycleService,
)
from core_platform.foundation.errors import ValidationError
from core_platform.host.security import require_capability
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
)

router = APIRouter(
    prefix="/platform/break-glass",
    tags=["break-glass"],
)


class BreakGlassScopeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    kind: BreakGlassScopeKind
    resource_type: str | None = None
    resource_id: str | None = None


class BreakGlassIssueRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    actor_id: str
    capabilities: tuple[str, ...] = Field(
        min_length=1
    )
    scope: BreakGlassScopeRequest
    reason: str = Field(
        min_length=1
    )
    valid_from: datetime
    valid_until: datetime
    accepted_acr_values: frozenset[str] = (
        frozenset()
    )
    required_amr: frozenset[str] = frozenset()


class BreakGlassIssueResponse(BaseModel):
    grant_id: str
    version: int


def _issue_command(
    payload: BreakGlassIssueRequest,
    *,
    correlation_id: str,
) -> BreakGlassIssueCommand:
    try:
        actor_id = ActorId.parse(
            payload.actor_id
        )

        scope = BreakGlassScope(
            kind=payload.scope.kind,
            resource_type=(
                payload.scope.resource_type
            ),
            resource_id=(
                payload.scope.resource_id
            ),
        )
    except ValueError as exc:
        raise ValidationError(
            "BREAK_GLASS.ISSUE.INVALID",
            "Break-glass issuance request is invalid",
            correlation_id=correlation_id,
        ) from exc

    return BreakGlassIssueCommand(
        actor_id=actor_id,
        capabilities=payload.capabilities,
        scope=scope,
        reason=payload.reason,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        accepted_acr_values=(
            payload.accepted_acr_values
        ),
        required_amr=payload.required_amr,
    )


@router.post(
    "/grants",
    response_model=BreakGlassIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_break_glass_grant(
    payload: BreakGlassIssueRequest,
    request: Request,
    context: Annotated[
        ExecutionContext,
        Depends(
            require_capability(
                BREAK_GLASS_MANAGEMENT_CAPABILITY
            )
        ),
    ],
) -> BreakGlassIssueResponse:
    service: BreakGlassLifecycleService = (
        request.app.state.break_glass_lifecycle
    )

    command = _issue_command(
        payload,
        correlation_id=str(
            context.correlation_id
        ),
    )

    result = await service.issue(
        context=context,
        command=command,
    )

    return BreakGlassIssueResponse(
        grant_id=str(
            result.grant_id
        ),
        version=result.version,
    )


class BreakGlassTransitionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    expected_version: int
    transition_reason: str


class BreakGlassTransitionResponse(BaseModel):
    grant_id: str
    version: int


def _parse_grant_id(
    raw: str,
    *,
    correlation_id: str,
) -> BreakGlassGrantId:
    try:
        return BreakGlassGrantId(
            UUID(raw)
        )
    except ValueError as exc:
        raise ValidationError(
            "BREAK_GLASS.TRANSITION.INVALID",
            "Break-glass transition request is invalid",
            correlation_id=correlation_id,
        ) from exc


@router.post(
    "/grants/{grant_id}/suspend",
    response_model=BreakGlassTransitionResponse,
)
async def suspend_break_glass_grant(
    grant_id: str,
    payload: BreakGlassTransitionRequest,
    request: Request,
    context: Annotated[
        ExecutionContext,
        Depends(
            require_capability(
                BREAK_GLASS_MANAGEMENT_CAPABILITY
            )
        ),
    ],
) -> BreakGlassTransitionResponse:
    service: BreakGlassLifecycleService = (
        request.app.state.break_glass_lifecycle
    )

    parsed_grant_id = _parse_grant_id(
        grant_id,
        correlation_id=str(
            context.correlation_id
        ),
    )

    version = await service.suspend(
        context=context,
        grant_id=parsed_grant_id,
        expected_version=payload.expected_version,
        transition_reason=payload.transition_reason,
    )

    return BreakGlassTransitionResponse(
        grant_id=str(
            parsed_grant_id
        ),
        version=version,
    )


@router.post(
    "/grants/{grant_id}/resume",
    response_model=BreakGlassTransitionResponse,
)
async def resume_break_glass_grant(
    grant_id: str,
    payload: BreakGlassTransitionRequest,
    request: Request,
    context: Annotated[
        ExecutionContext,
        Depends(
            require_capability(
                BREAK_GLASS_MANAGEMENT_CAPABILITY
            )
        ),
    ],
) -> BreakGlassTransitionResponse:
    service: BreakGlassLifecycleService = (
        request.app.state.break_glass_lifecycle
    )

    parsed_grant_id = _parse_grant_id(
        grant_id,
        correlation_id=str(
            context.correlation_id
        ),
    )

    version = await service.resume(
        context=context,
        grant_id=parsed_grant_id,
        expected_version=payload.expected_version,
        transition_reason=payload.transition_reason,
    )

    return BreakGlassTransitionResponse(
        grant_id=str(
            parsed_grant_id
        ),
        version=version,
    )


class BreakGlassRevokeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    expected_version: int
    expected_current_status: BreakGlassGrantStatus
    transition_reason: str


@router.post(
    "/grants/{grant_id}/revoke",
    response_model=BreakGlassTransitionResponse,
)
async def revoke_break_glass_grant(
    grant_id: str,
    payload: BreakGlassRevokeRequest,
    request: Request,
    context: Annotated[
        ExecutionContext,
        Depends(
            require_capability(
                BREAK_GLASS_MANAGEMENT_CAPABILITY
            )
        ),
    ],
) -> BreakGlassTransitionResponse:
    service: BreakGlassLifecycleService = (
        request.app.state.break_glass_lifecycle
    )

    parsed_grant_id = _parse_grant_id(
        grant_id,
        correlation_id=str(
            context.correlation_id
        ),
    )

    version = await service.revoke(
        context=context,
        grant_id=parsed_grant_id,
        expected_version=payload.expected_version,
        expected_current_status=(
            payload.expected_current_status
        ),
        transition_reason=payload.transition_reason,
    )

    return BreakGlassTransitionResponse(
        grant_id=str(
            parsed_grant_id
        ),
        version=version,
    )
