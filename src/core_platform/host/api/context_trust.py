from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core_platform.application.context_trust import ContextTrustService
from core_platform.host.security import require_capability
from core_platform.platform_kernel.context import ExecutionContext

router = APIRouter(prefix="/platform", tags=["context-trust"])


class ContextResponse(BaseModel):
    tenant_id: str
    actor_id: str
    actor_type: str
    issuer: str
    subject: str
    correlation_id: str


class TenantResponse(BaseModel):
    tenant_id: str


class ActorResponse(BaseModel):
    actor_id: str
    actor_type: str


class CapabilitiesResponse(BaseModel):
    capabilities: tuple[str, ...]


@router.get("/context", response_model=ContextResponse)
async def context_endpoint(
    context: Annotated[
        ExecutionContext,
        Depends(require_capability("platform.context.read")),
    ],
) -> ContextResponse:
    return ContextResponse(
        tenant_id=str(context.tenant_id),
        actor_id=str(context.actor_id),
        actor_type=context.actor_type.value,
        issuer=context.authentication.issuer,
        subject=context.authentication.subject,
        correlation_id=str(context.correlation_id),
    )


@router.get("/tenant", response_model=TenantResponse)
async def tenant_endpoint(
    context: Annotated[
        ExecutionContext,
        Depends(require_capability("platform.tenant.read")),
    ],
) -> TenantResponse:
    return TenantResponse(tenant_id=str(context.tenant_id))


@router.get("/actor/me", response_model=ActorResponse)
async def actor_endpoint(
    context: Annotated[
        ExecutionContext,
        Depends(require_capability("platform.actor.read.self")),
    ],
) -> ActorResponse:
    return ActorResponse(
        actor_id=str(context.actor_id),
        actor_type=context.actor_type.value,
    )


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities_endpoint(
    request: Request,
    context: Annotated[
        ExecutionContext,
        Depends(require_capability("platform.capability.read.self")),
    ],
) -> CapabilitiesResponse:
    service: ContextTrustService = request.app.state.context_trust
    capabilities = await service.list_effective_capabilities(context)
    return CapabilitiesResponse(capabilities=capabilities)
