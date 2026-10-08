from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated

import structlog
from fastapi import Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from structlog.contextvars import bind_contextvars, clear_contextvars

from core_platform.application.context_trust import ContextTrustService
from core_platform.foundation.errors import AuthenticationError, PlatformError, ValidationError
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.context import ExecutionContext, bind_execution_context

_bearer = HTTPBearer(auto_error=False)
logger = structlog.get_logger(__name__)


def _break_glass_log_fields(
    context: ExecutionContext,
) -> dict[str, str | bool]:
    elevation = context.break_glass

    if elevation is None:
        return {}

    return {
        "break_glass": True,
        "break_glass_grant_id": str(elevation.grant_id.value),
        "break_glass_scope_kind": (elevation.scope.kind.value),
    }


def _correlation_id(request: Request) -> CorrelationId:
    header_name = request.app.state.settings.correlation_header
    raw = request.headers.get(header_name)
    if raw is None or not raw.strip():
        correlation_id = CorrelationId.new()
    else:
        try:
            correlation_id = CorrelationId.parse(raw.strip())
        except ValueError as exc:
            raise ValidationError(
                "CORRELATION.ID.INVALID", "Correlation identifier is invalid"
            ) from exc
    request.state.correlation_id = correlation_id
    return correlation_id


def require_capability(
    capability_code: str,
) -> Callable[..., AsyncIterator[ExecutionContext]]:
    async def dependency(
        request: Request,
        response: Response,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_bearer),
        ],
    ) -> AsyncIterator[ExecutionContext]:
        correlation_id = _correlation_id(request)
        settings = request.app.state.settings
        response.headers[settings.correlation_header] = str(correlation_id)
        tenant_selector = request.headers.get(settings.tenant_header)
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise AuthenticationError(
                "AUTH.TOKEN.REQUIRED",
                "Bearer access token is required",
                correlation_id=str(correlation_id),
            )
        service: ContextTrustService = request.app.state.context_trust
        try:
            context = await service.authorize(
                token=credentials.credentials,
                tenant_selector=tenant_selector,
                capability_code=capability_code,
                correlation_id=correlation_id,
            )
        except PlatformError as exc:
            await logger.awarn(
                "authorization_decision",
                effect="DENY",
                capability=capability_code,
                correlation_id=str(correlation_id),
                code=exc.code,
            )
            raise

        break_glass_log_fields = _break_glass_log_fields(context)

        bind_contextvars(
            correlation_id=str(context.correlation_id),
            tenant_id=str(context.tenant_id),
            actor_id=str(context.actor_id),
            **break_glass_log_fields,
        )
        await logger.ainfo(
            "authorization_decision",
            effect="ALLOW",
            capability=capability_code,
            correlation_id=str(context.correlation_id),
            tenant_id=str(context.tenant_id),
            actor_id=str(context.actor_id),
            **break_glass_log_fields,
        )
        try:
            with bind_execution_context(context):
                yield context
        finally:
            clear_contextvars()

    return dependency
