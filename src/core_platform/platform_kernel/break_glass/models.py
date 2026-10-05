from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)


class BreakGlassGrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BreakGlassScopeKind(StrEnum):
    TENANT = "TENANT"
    RESOURCE_TYPE = "RESOURCE_TYPE"
    RESOURCE = "RESOURCE"


def _require_aware(
    value: datetime,
    *,
    field_name: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )


def _normalize_required(
    value: str,
    *,
    field_name: str,
) -> str:
    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must not be empty"
        )

    return normalized


def _normalize_string_set(
    values: frozenset[str],
    *,
    field_name: str,
) -> frozenset[str]:
    normalized = frozenset(
        value.strip()
        for value in values
        if value.strip()
    )

    if len(normalized) != len(values):
        raise ValueError(
            f"{field_name} must not contain empty values"
        )

    return normalized


@dataclass(frozen=True, slots=True)
class BreakGlassScope:
    kind: BreakGlassScopeKind
    resource_type: str | None = None
    resource_id: str | None = None

    def __post_init__(self) -> None:
        resource_type = (
            None
            if self.resource_type is None
            else self.resource_type.strip()
        )
        resource_id = (
            None
            if self.resource_id is None
            else self.resource_id.strip()
        )

        if resource_type == "":
            raise ValueError(
                "resource_type must not be empty"
            )

        if resource_id == "":
            raise ValueError(
                "resource_id must not be empty"
            )

        if self.kind is BreakGlassScopeKind.TENANT:
            if (
                resource_type is not None
                or resource_id is not None
            ):
                raise ValueError(
                    "TENANT scope must not define resource fields"
                )

        elif self.kind is BreakGlassScopeKind.RESOURCE_TYPE:
            if resource_type is None:
                raise ValueError(
                    "RESOURCE_TYPE scope requires resource_type"
                )
            if resource_id is not None:
                raise ValueError(
                    "RESOURCE_TYPE scope must not define resource_id"
                )

        elif (
            self.kind is BreakGlassScopeKind.RESOURCE
            and (resource_type is None or resource_id is None)
        ):
            raise ValueError(
                "RESOURCE scope requires resource_type and resource_id"
            )

        object.__setattr__(
            self,
            "resource_type",
            resource_type,
        )
        object.__setattr__(
            self,
            "resource_id",
            resource_id,
        )

    def matches(
        self,
        *,
        resource_type: str | None,
        resource_id: str | None,
    ) -> bool:
        if self.kind is BreakGlassScopeKind.TENANT:
            return True

        if self.kind is BreakGlassScopeKind.RESOURCE_TYPE:
            return resource_type == self.resource_type

        return (
            resource_type == self.resource_type
            and resource_id == self.resource_id
        )


@dataclass(frozen=True, slots=True)
class BreakGlassGrant:
    grant_id: BreakGlassGrantId
    tenant_id: TenantId
    actor_id: ActorId
    issued_by_actor_id: ActorId
    capabilities: tuple[str, ...]
    scope: BreakGlassScope
    reason: str
    valid_from: datetime
    valid_until: datetime
    status: BreakGlassGrantStatus
    accepted_acr_values: frozenset[str]
    required_amr: frozenset[str]

    def __post_init__(self) -> None:
        reason = _normalize_required(
            self.reason,
            field_name="reason",
        )

        capabilities = tuple(
            capability.strip()
            for capability in self.capabilities
        )

        if not capabilities:
            raise ValueError(
                "capabilities must not be empty"
            )

        if any(
            not capability
            for capability in capabilities
        ):
            raise ValueError(
                "capabilities must not contain empty values"
            )

        if len(set(capabilities)) != len(capabilities):
            raise ValueError(
                "capabilities must not contain duplicates"
            )

        accepted_acr_values = _normalize_string_set(
            self.accepted_acr_values,
            field_name="accepted_acr_values",
        )
        required_amr = _normalize_string_set(
            self.required_amr,
            field_name="required_amr",
        )

        if (
            not accepted_acr_values
            and not required_amr
        ):
            raise ValueError(
                "break-glass grant requires elevated authentication assurance"
            )

        _require_aware(
            self.valid_from,
            field_name="valid_from",
        )
        _require_aware(
            self.valid_until,
            field_name="valid_until",
        )

        if self.valid_until <= self.valid_from:
            raise ValueError(
                "valid_until must be after valid_from"
            )

        object.__setattr__(
            self,
            "reason",
            reason,
        )
        object.__setattr__(
            self,
            "capabilities",
            capabilities,
        )
        object.__setattr__(
            self,
            "accepted_acr_values",
            accepted_acr_values,
        )
        object.__setattr__(
            self,
            "required_amr",
            required_amr,
        )

    def is_active_at(
        self,
        instant: datetime,
    ) -> bool:
        _require_aware(
            instant,
            field_name="instant",
        )

        return (
            self.status is BreakGlassGrantStatus.ACTIVE
            and self.valid_from <= instant < self.valid_until
        )

    def permits_capability(
        self,
        capability: str,
    ) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class BreakGlassElevationContext:
    grant_id: BreakGlassGrantId
    issued_by_actor_id: ActorId
    capability: str
    scope: BreakGlassScope
    reason: str
    activated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        capability = _normalize_required(
            self.capability,
            field_name="capability",
        )
        reason = _normalize_required(
            self.reason,
            field_name="reason",
        )

        _require_aware(
            self.activated_at,
            field_name="activated_at",
        )
        _require_aware(
            self.valid_until,
            field_name="valid_until",
        )

        if self.activated_at >= self.valid_until:
            raise ValueError(
                "break-glass elevation must expire after activation"
            )

        object.__setattr__(
            self,
            "capability",
            capability,
        )
        object.__setattr__(
            self,
            "reason",
            reason,
        )