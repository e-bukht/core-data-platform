from __future__ import annotations

from dataclasses import dataclass

from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, TenantId


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    tenant_id: TenantId
    actor_id: ActorId
    actor_type: ActorType
    authentication: AuthenticationContext
    correlation_id: CorrelationId
    trace_id: str | None = None
    locale: str = "en"
    timezone: str = "UTC"
    delegated_by: ActorId | None = None
