from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from core_platform.infrastructure.persistence.break_glass_repository import (
    SqlBreakGlassRepository,
    _grant_from_row,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrantStatus,
    BreakGlassRepository,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.ids import ActorId, TenantId

TENANT_ID = TenantId(
    UUID(
        "00000000-0000-7800-8000-000000001001"
    )
)

ACTOR_ID = ActorId(
    UUID(
        "00000000-0000-7800-8000-000000001002"
    )
)

GRANT_ID = UUID(
    "00000000-0000-7800-8000-000000001003"
)

ISSUER_ID = UUID(
    "00000000-0000-7800-8000-000000001004"
)

NOW = datetime(
    2026,
    9,
    26,
    23,
    30,
    tzinfo=UTC,
)


def _row() -> RowMapping:
    return cast(
        RowMapping,
        {
            "id": GRANT_ID,
            "tenant_id": TENANT_ID.value,
            "actor_id": ACTOR_ID.value,
            "issued_by_actor_id": ISSUER_ID,
            "capabilities": [
                "platform.outbox.retry",
                "platform.audit.read",
            ],
            "scope_kind": "RESOURCE",
            "resource_type": "outbox-message",
            "resource_id": "message-1",
            "reason": "Emergency recovery",
            "valid_from": NOW - timedelta(minutes=5),
            "valid_until": NOW + timedelta(minutes=20),
            "status": "ACTIVE",
            "accepted_acr_values": [
                "urn:core-platform:acr:elevated"
            ],
            "required_amr": [
                "mfa"
            ],
            "version": 0,
            "created_at": NOW,
            "updated_at": NOW,
        },
    )


class _Result:
    def __init__(
        self,
        rows: list[RowMapping],
    ) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[RowMapping]:
        return self._rows


class _Connection:
    def __init__(
        self,
        rows: list[RowMapping],
    ) -> None:
        self._rows = rows
        self.statement: object | None = None

    async def execute(
        self,
        statement: object,
    ) -> _Result:
        self.statement = statement
        return _Result(self._rows)


class _Database:
    def __init__(
        self,
        rows: list[RowMapping],
    ) -> None:
        self.connection = _Connection(rows)
        self.tenant_id: UUID | None = None

    @asynccontextmanager
    async def tenant_transaction(
        self,
        tenant_id: UUID,
    ) -> AsyncIterator[_Connection]:
        self.tenant_id = tenant_id
        yield self.connection


def test_row_maps_to_domain_grant() -> None:
    grant = _grant_from_row(
        _row()
    )

    assert grant.tenant_id == TENANT_ID
    assert grant.actor_id == ACTOR_ID
    assert grant.status is (
        BreakGlassGrantStatus.ACTIVE
    )
    assert grant.scope.kind is (
        BreakGlassScopeKind.RESOURCE
    )
    assert grant.scope.resource_type == (
        "outbox-message"
    )
    assert grant.scope.resource_id == "message-1"
    assert grant.capabilities == (
        "platform.outbox.retry",
        "platform.audit.read",
    )


def test_repository_is_structural_port() -> None:
    database = _Database(
        []
    )

    repository: BreakGlassRepository = (
        SqlBreakGlassRepository(
            cast(
                Database,
                database,
            )
        )
    )

    assert repository is not None


def test_repository_uses_tenant_transaction_and_candidate_filters() -> None:
    database = _Database(
        [_row()]
    )

    repository = SqlBreakGlassRepository(
        cast(
            Database,
            database,
        )
    )

    grants = asyncio.run(
        repository.list_candidate_grants(
            TENANT_ID,
            ACTOR_ID,
            "platform.outbox.retry",
            now=NOW,
        )
    )

    assert len(grants) == 1
    assert grants[0].grant_id.value == GRANT_ID
    assert database.tenant_id == TENANT_ID.value

    statement = database.connection.statement
    assert statement is not None

    sql = str(statement)

    assert "break_glass_grant.tenant_id" in sql
    assert "break_glass_grant.actor_id" in sql
    assert "break_glass_grant.status" in sql
    assert "break_glass_grant.valid_from" in sql
    assert "break_glass_grant.valid_until" in sql
    assert "ANY" in sql
    assert "ORDER BY" in sql


def test_repository_returns_all_candidates_in_database_order() -> None:
    first = dict(
        _row()
    )
    second = dict(
        _row()
    )

    first["id"] = UUID(
        "00000000-0000-7800-8000-000000001010"
    )
    second["id"] = UUID(
        "00000000-0000-7800-8000-000000001011"
    )

    database = _Database(
        [
            cast(RowMapping, first),
            cast(RowMapping, second),
        ]
    )

    repository = SqlBreakGlassRepository(
        cast(
            Database,
            database,
        )
    )

    grants = asyncio.run(
        repository.list_candidate_grants(
            TENANT_ID,
            ACTOR_ID,
            "platform.outbox.retry",
            now=NOW,
        )
    )

    assert tuple(
        grant.grant_id.value
        for grant in grants
    ) == (
        first["id"],
        second["id"],
    )


def test_repository_rejects_naive_instant() -> None:
    database = _Database(
        []
    )

    repository = SqlBreakGlassRepository(
        cast(
            Database,
            database,
        )
    )

    naive = datetime(
        2026,
        9,
        26,
        23,
        30,
    )

    try:
        asyncio.run(
            repository.list_candidate_grants(
                TENANT_ID,
                ACTOR_ID,
                "platform.outbox.retry",
                now=naive,
            )
        )
    except ValueError as exc:
        assert str(exc) == (
            "now must be timezone-aware"
        )
    else:
        raise AssertionError(
            "Expected timezone validation failure"
        )


def test_repository_rejects_blank_capability() -> None:
    database = _Database(
        []
    )

    repository = SqlBreakGlassRepository(
        cast(
            Database,
            database,
        )
    )

    try:
        asyncio.run(
            repository.list_candidate_grants(
                TENANT_ID,
                ACTOR_ID,
                "   ",
                now=NOW,
            )
        )
    except ValueError as exc:
        assert str(exc) == (
            "capability must not be empty"
        )
    else:
        raise AssertionError(
            "Expected capability validation failure"
        )