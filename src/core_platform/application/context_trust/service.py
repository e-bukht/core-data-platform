from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from core_platform.application.break_glass import BreakGlassActivationRecorder
from core_platform.foundation.errors import (
    AuthenticationError,
    AuthorizationError,
    ValidationError,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorStatus
from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
    BreakGlassRepository,
    BreakGlassRequest,
    evaluate_break_glass,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.context_trust import (
    ContextTrustRepository,
)
from core_platform.platform_kernel.identity import TokenAuthenticator
from core_platform.platform_kernel.ids import TenantId
from core_platform.platform_kernel.policy import (
    CapabilityGrantPdp,
    PolicyRequest,
)
from core_platform.platform_kernel.tenant import TenantStatus


class ContextTrustService:
    def __init__(
        self,
        authenticator: TokenAuthenticator,
        repository: ContextTrustRepository,
        break_glass_repository: BreakGlassRepository,
        pdp: CapabilityGrantPdp,
        *,
        environment: str,
        break_glass_activation_recorder: BreakGlassActivationRecorder | None = None,
    ) -> None:
        self._authenticator = authenticator
        self._repository = repository
        self._break_glass_repository = break_glass_repository
        self._pdp = pdp
        self._environment = environment
        self._break_glass_activation_recorder = break_glass_activation_recorder

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
        if not token:
            raise AuthenticationError(
                "AUTH.TOKEN.REQUIRED",
                "Bearer access token is required",
                correlation_id=str(correlation_id),
            )

        authentication = await self._authenticator.authenticate(
            token
        )

        actor = await self._repository.resolve_actor(
            authentication.issuer,
            authentication.subject,
        )

        if actor is None:
            raise AuthorizationError(
                "ACTOR.IDENTITY.NOT_REGISTERED",
                "Authenticated identity is not registered",
                correlation_id=str(correlation_id),
            )

        if actor.status is not ActorStatus.ACTIVE:
            raise AuthorizationError(
                "ACTOR.NOT.ACTIVE",
                "Actor is not active",
                correlation_id=str(correlation_id),
            )

        tenant_id = self._parse_tenant_selector(
            tenant_selector,
            correlation_id,
        )

        tenant = await self._repository.get_tenant(
            tenant_id
        )

        if tenant is None:
            raise AuthorizationError(
                "TENANT.ACCESS.DENIED",
                "Tenant access denied",
                correlation_id=str(correlation_id),
            )

        if tenant.status is not TenantStatus.ACTIVE:
            raise AuthorizationError(
                "TENANT.NOT.ACTIVE",
                "Tenant is not active",
                correlation_id=str(correlation_id),
            )

        instant = datetime.now(UTC)

        membership = await self._repository.get_membership(
            tenant_id,
            actor.actor_id,
        )

        if (
            membership is None
            or not membership.is_active_at(instant)
        ):
            raise AuthorizationError(
                "TENANT.ACCESS.DENIED",
                "Tenant access denied",
                correlation_id=str(correlation_id),
            )

        request = PolicyRequest(
            tenant_id=tenant_id,
            actor_id=actor.actor_id,
            capability=capability_code,
            environment=self._environment,
            authentication_context=authentication,
            resource_type=resource_type,
            resource_id=resource_id,
        )

        grant = await self._repository.get_capability_grant(
            tenant_id,
            actor.actor_id,
            capability_code,
        )

        decision = self._pdp.decide(
            request,
            grant,
            now=instant,
        )

        break_glass: BreakGlassElevationContext | None = None

        if not decision.allowed:
            candidates = (
                await self._break_glass_repository.list_candidate_grants(
                    tenant_id,
                    actor.actor_id,
                    capability_code,
                    now=instant,
                )
            )

            break_glass_request = BreakGlassRequest(
                tenant_id=tenant_id,
                actor_id=actor.actor_id,
                capability=capability_code,
                authentication_context=authentication,
                resource_type=resource_type,
                resource_id=resource_id,
            )

            for candidate in candidates:
                break_glass_decision = evaluate_break_glass(
                    break_glass_request,
                    candidate,
                    now=instant,
                )

                if break_glass_decision.allowed:
                    break_glass = (
                        break_glass_decision.elevation
                    )
                    break

            if break_glass is None:
                raise AuthorizationError(
                    "AUTHZ.CAPABILITY.DENIED",
                    "Capability denied",
                    details={
                        "capability": capability_code,
                        "reason": decision.reason_code,
                    },
                    correlation_id=str(correlation_id),
                )

        context = ExecutionContext(
            tenant_id=tenant_id,
            actor_id=actor.actor_id,
            actor_type=actor.actor_type,
            authentication=authentication,
            correlation_id=correlation_id,
            break_glass=break_glass,
        )

        if break_glass is not None:
            if self._break_glass_activation_recorder is None:
                raise RuntimeError(
                    "Break-glass activation recorder is not configured"
                )
            await self._break_glass_activation_recorder.record(context)

        return context

    async def list_effective_capabilities(
        self,
        context: ExecutionContext,
    ) -> tuple[str, ...]:
        return await self._repository.list_active_capability_codes(
            context.tenant_id,
            context.actor_id,
        )

    @staticmethod
    def _parse_tenant_selector(
        selector: str | None,
        correlation_id: CorrelationId,
    ) -> TenantId:
        if selector is None or not selector.strip():
            raise ValidationError(
                "TENANT.CONTEXT.REQUIRED",
                "Tenant context is required",
                correlation_id=str(correlation_id),
            )

        try:
            return TenantId(
                UUID(selector)
            )
        except ValueError as exc:
            raise ValidationError(
                "TENANT.ID.INVALID",
                "Tenant identifier is invalid",
                correlation_id=str(correlation_id),
            ) from exc