from __future__ import annotations

import asyncio
import selectors
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from testcontainers.community.postgres import PostgresContainer

from core_platform.infrastructure.persistence.break_glass_repository import (
    SqlBreakGlassRepository,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.platform_kernel.ids import ActorId, TenantId
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

TENANT_A = "00000000-0000-7900-8000-000000001001"
TENANT_B = "00000000-0000-7900-8000-000000001002"

ACTOR_A = "00000000-0000-7900-8000-000000001011"
ACTOR_OTHER = "00000000-0000-7900-8000-000000001012"
ACTOR_B = "00000000-0000-7900-8000-000000001013"

ISSUER = "00000000-0000-7900-8000-000000001021"

CANDIDATE_1 = "00000000-0000-7900-8000-000000001031"
CANDIDATE_2 = "00000000-0000-7900-8000-000000001032"
CANDIDATE_3 = "00000000-0000-7900-8000-000000001033"

NOW = datetime(
    2026,
    9,
    26,
    23,
    30,
    tzinfo=UTC,
)


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def _set_tenant(
    connection: Connection,
    tenant_id: str,
) -> None:
    connection.execute(
        text(
            """
            SELECT set_config(
                'app.current_tenant_id',
                :tenant_id,
                true
            )
            """
        ),
        {"tenant_id": tenant_id},
    )


def _seed_identity(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        for tenant_id, code in (
            (TENANT_A, "repository-a"),
            (TENANT_B, "repository-b"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO platform.tenant (
                        id,
                        code,
                        display_name,
                        status
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        :code,
                        :code,
                        'ACTIVE'
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "code": code,
                },
            )

        for actor_id, display_name in (
            (ACTOR_A, "Candidate Actor"),
            (ACTOR_OTHER, "Other Actor"),
            (ACTOR_B, "Tenant B Actor"),
            (ISSUER, "Break Glass Issuer"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO platform.actor (
                        id,
                        actor_type,
                        status,
                        display_name
                    )
                    VALUES (
                        CAST(:actor_id AS uuid),
                        'HUMAN',
                        'ACTIVE',
                        :display_name
                    )
                    """
                ),
                {
                    "actor_id": actor_id,
                    "display_name": display_name,
                },
            )


def _insert_grant(
    connection: Connection,
    *,
    grant_id: str,
    tenant_id: str,
    actor_id: str,
    capability: str,
    status: str = "ACTIVE",
    valid_from: datetime,
    valid_until: datetime,
    scope_kind: str = "TENANT",
    resource_type: str | None = None,
    resource_id: str | None = None,
    acr: str = "urn:core-platform:acr:elevated",
    amr: str = "mfa",
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO platform.break_glass_grant (
                id,
                tenant_id,
                actor_id,
                issued_by_actor_id,
                capabilities,
                scope_kind,
                resource_type,
                resource_id,
                reason,
                valid_from,
                valid_until,
                status,
                accepted_acr_values,
                required_amr
            )
            VALUES (
                CAST(:grant_id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:actor_id AS uuid),
                CAST(:issuer_id AS uuid),
                ARRAY[:capability]::varchar(160)[],
                :scope_kind,
                :resource_type,
                :resource_id,
                'Repository integration probe',
                :valid_from,
                :valid_until,
                :status,
                ARRAY[:acr]::varchar(255)[],
                ARRAY[:amr]::varchar(128)[]
            )
            """
        ),
        {
            "grant_id": grant_id,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "issuer_id": ISSUER,
            "capability": capability,
            "scope_kind": scope_kind,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": status,
            "acr": acr,
            "amr": amr,
        },
    )


def _seed_grants(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        _set_tenant(
            connection,
            TENANT_A,
        )

        # Candidate 1: exact operational grant.
        _insert_grant(
            connection,
            grant_id=CANDIDATE_1,
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.outbox.retry",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=10),
        )

        # Candidate 2: scope deliberately different.
        # Repository must still return it.
        _insert_grant(
            connection,
            grant_id=CANDIDATE_2,
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.outbox.retry",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=20),
            scope_kind="RESOURCE",
            resource_type="outbox-message",
            resource_id="different-message",
        )

        # Candidate 3: assurance deliberately incompatible.
        # Repository must still return it.
        _insert_grant(
            connection,
            grant_id=CANDIDATE_3,
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.outbox.retry",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=20),
            acr="urn:core-platform:acr:hardware-only",
            amr="hardware-key",
        )

        # Suspended: excluded.
        _insert_grant(
            connection,
            grant_id="00000000-0000-7900-8000-000000001041",
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.outbox.retry",
            status="SUSPENDED",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=30),
        )

        # Expired: excluded.
        _insert_grant(
            connection,
            grant_id="00000000-0000-7900-8000-000000001042",
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.outbox.retry",
            valid_from=NOW - timedelta(minutes=30),
            valid_until=NOW,
        )

        # Future: excluded.
        _insert_grant(
            connection,
            grant_id="00000000-0000-7900-8000-000000001043",
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.outbox.retry",
            valid_from=NOW + timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=30),
        )

        # Different capability: excluded.
        _insert_grant(
            connection,
            grant_id="00000000-0000-7900-8000-000000001044",
            tenant_id=TENANT_A,
            actor_id=ACTOR_A,
            capability="platform.audit.read",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=30),
        )

        # Different actor in same tenant: excluded.
        _insert_grant(
            connection,
            grant_id="00000000-0000-7900-8000-000000001045",
            tenant_id=TENANT_A,
            actor_id=ACTOR_OTHER,
            capability="platform.outbox.retry",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=30),
        )

    with engine.begin() as connection:
        _set_tenant(
            connection,
            TENANT_B,
        )

        # Same capability but another tenant: excluded by
        # query subject and independently by RLS.
        _insert_grant(
            connection,
            grant_id="00000000-0000-7900-8000-000000001046",
            tenant_id=TENANT_B,
            actor_id=ACTOR_B,
            capability="platform.outbox.retry",
            valid_from=NOW - timedelta(minutes=10),
            valid_until=NOW + timedelta(minutes=30),
        )


async def _assert_repository(
    runtime_url: str,
) -> None:
    database = Database(runtime_url)

    try:
        repository = SqlBreakGlassRepository(database)

        grants = await repository.list_candidate_grants(
            TenantId.parse(TENANT_A),
            ActorId.parse(ACTOR_A),
            "platform.outbox.retry",
            now=NOW,
        )

        ids = tuple(str(grant.grant_id) for grant in grants)

        assert ids == (
            CANDIDATE_1,
            CANDIDATE_2,
            CANDIDATE_3,
        )

        # Prove that SQL did not perform domain scope
        # or authentication-assurance decisions.
        assert grants[1].scope.resource_id == ("different-message")
        assert grants[2].accepted_acr_values == frozenset(
            {
                "urn:core-platform:acr:hardware-only",
            }
        )
        assert grants[2].required_amr == frozenset(
            {
                "hardware-key",
            }
        )

        tenant_b = await repository.list_candidate_grants(
            TenantId.parse(TENANT_B),
            ActorId.parse(ACTOR_B),
            "platform.outbox.retry",
            now=NOW,
        )

        assert len(tenant_b) == 1

    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_break_glass_repository_returns_all_and_only_sql_candidates(
    image: str,
) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))

        run_alembic(
            migration_url,
            runtime_url,
        )

        migration_engine = create_engine(migration_url)

        try:
            _seed_identity(migration_engine)
            _seed_grants(migration_engine)
        finally:
            migration_engine.dispose()

        with asyncio.Runner(loop_factory=_selector_loop_factory) as runner:
            runner.run(_assert_repository(runtime_url))
