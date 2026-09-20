from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from core_platform.platform_kernel.ids import ActorId, IdentityId


class ExternalIdentityProviderType(StrEnum):
    OIDC = "OIDC"


class ExternalIdentityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    identity_id: IdentityId
    provider_type: ExternalIdentityProviderType
    issuer: str
    subject: str
    actor_id: ActorId
    status: ExternalIdentityStatus
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AuthenticationContext:
    issuer: str
    subject: str
    audience: tuple[str, ...]
    client_id: str | None
    scopes: frozenset[str]
    acr: str | None
    amr: tuple[str, ...]
    authenticated_at: datetime | None
    token_id: str | None
    expires_at: datetime
