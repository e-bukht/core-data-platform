from __future__ import annotations

import asyncio
import selectors
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from core_platform.application.break_glass import (
    BREAK_GLASS_ISSUE_EVIDENCE_TYPE,
    BREAK_GLASS_ISSUE_OPERATION,
    BREAK_GLASS_MANAGEMENT_CAPABILITY,
    BREAK_GLASS_RESUME_EVIDENCE_TYPE,
    BREAK_GLASS_RESUME_OPERATION,
    BREAK_GLASS_REVOKE_EVIDENCE_TYPE,
    BREAK_GLASS_REVOKE_OPERATION,
    BREAK_GLASS_SUSPEND_EVIDENCE_TYPE,
    BREAK_GLASS_SUSPEND_OPERATION,
    BreakGlassIssueCommand,
    BreakGlassLifecycleService,
)
from core_platform.application.evidence.factory import SignedEvidenceFactory
from core_platform.foundation.identifiers import CorrelationId
from core_platform.infrastructure.persistence.break_glass_lifecycle_persistence import (
    PostgresBreakGlassLifecyclePersistence,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWorkFactory,
)
from core_platform.infrastructure.security.evidence_crypto import (
    Ed25519EvidenceSigner,
)
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)
from core_platform.transaction_kernel.ids import (
    AuditRecordId,
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    AuditOutcome,
    AuditRecord,
    TransactionContext,
)
from tests.integration.db_support import (
    admin_url,
    provision_roles,
    run_alembic,
)

NOW = datetime(
    2026,
    10,
    6,
    9,
    0,
    tzinfo=UTC,
)

TENANT_ID = TenantId(
    UUID("00000000-0000-7e00-8000-000000001001")
)
ADMIN_ID = ActorId(
    UUID("00000000-0000-7e00-8000-000000001002")
)
SUBJECT_ID = ActorId(
    UUID("00000000-0000-7e00-8000-000000001003")
)
GRANT_ID = BreakGlassGrantId(
    UUID("00000000-0000-7e00-8000-000000001004")
)
CORRELATION_ID = CorrelationId(
    UUID("00000000-0000-7e00-8000-000000001005")
)


class _SequenceClock:
    def __init__(
        self,
        values: list[datetime],
    ) -> None:
        self._values = iter(values)

    def now(self) -> datetime:
        return next(self._values)


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(
        selectors.SelectSelector()
    )


def _run(
    coro: Coroutine[Any, Any, None],
) -> None:
    with asyncio.Runner(
        loop_factory=_selector_loop_factory
    ) as runner:
        runner.run(coro)


def _seed(
    migration_url: str,
) -> None:
    engine = create_engine(
        migration_url
    )

    try:
        with engine.begin() as connection:
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
                        'break-glass-lifecycle',
                        'Break-glass Lifecycle',
                        'ACTIVE'
                    )
                    """
                ),
                {
                    "tenant_id": str(
                        TENANT_ID.value
                    )
                },
            )

            connection.execute(
                text(
                    """
                    INSERT INTO platform.actor (
                        id,
                        actor_type,
                        status,
                        display_name
                    )
                    VALUES
                    (
                        CAST(:admin_id AS uuid),
                        'HUMAN',
                        'ACTIVE',
                        'Lifecycle Administrator'
                    ),
                    (
                        CAST(:subject_id AS uuid),
                        'HUMAN',
                        'ACTIVE',
                        'Lifecycle Subject'
                    )
                    """
                ),
                {
                    "admin_id": str(
                        ADMIN_ID.value
                    ),
                    "subject_id": str(
                        SUBJECT_ID.value
                    ),
                },
            )
    finally:
        engine.dispose()


def _authentication() -> AuthenticationContext:
    return AuthenticationContext(
        issuer="https://issuer.example.test",
        subject="lifecycle-admin",
        audience=("core-data-api",),
        client_id="control-plane",
        scopes=frozenset(),
        acr="urn:core-platform:acr:loa2",
        amr=("pwd", "mfa"),
        authenticated_at=NOW - timedelta(minutes=1),
        token_id="lifecycle-token",
        expires_at=NOW + timedelta(hours=1),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=ADMIN_ID,
        actor_type=ActorType.HUMAN,
        authentication=_authentication(),
        correlation_id=CORRELATION_ID,
        break_glass=None,
    )


def _grant() -> BreakGlassGrant:
    return BreakGlassGrant(
        grant_id=GRANT_ID,
        tenant_id=TENANT_ID,
        actor_id=SUBJECT_ID,
        issued_by_actor_id=ADMIN_ID,
        capabilities=(
            "platform.outbox.retry",
            "platform.audit.read",
        ),
        scope=BreakGlassScope(
            BreakGlassScopeKind.TENANT
        ),
        reason="Controlled emergency recovery",
        valid_from=NOW,
        valid_until=NOW + timedelta(minutes=30),
        status=BreakGlassGrantStatus.ACTIVE,
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


def _issue_command() -> BreakGlassIssueCommand:
    grant = _grant()

    return BreakGlassIssueCommand(
        actor_id=grant.actor_id,
        capabilities=grant.capabilities,
        scope=grant.scope,
        reason=grant.reason,
        valid_from=grant.valid_from,
        valid_until=grant.valid_until,
        accepted_acr_values=(
            grant.accepted_acr_values
        ),
        required_amr=grant.required_amr,
    )


async def _exercise(
    runtime_url: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()

    signer = Ed25519EvidenceSigner(
        private_key=private_key,
        key_id="break-glass-lifecycle-test-key",
    )

    clock = _SequenceClock(
        [
            NOW,
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=2),
            NOW + timedelta(minutes=3),
        ]
    )

    database = Database(
        runtime_url
    )

    persistence = (
        PostgresBreakGlassLifecyclePersistence(
            PostgresUnitOfWorkFactory(
                database
            )
        )
    )

    service = BreakGlassLifecycleService(
        persistence=persistence,
        signer=signer,
        clock=clock,
    )

    context = _context()

    issue_result = await service.issue(
        context=context,
        command=_issue_command(),
    )

    assert issue_result.version == 0

    grant_id = issue_result.grant_id

    suspend_version = await service.suspend(
        context=context,
        grant_id=grant_id,
        expected_version=issue_result.version,
        transition_reason=(
            "Temporarily suspend emergency access"
        ),
    )

    assert suspend_version == 1

    resume_version = await service.resume(
        context=context,
        grant_id=grant_id,
        expected_version=suspend_version,
        transition_reason=(
            "Emergency recovery requires restored access"
        ),
    )

    assert resume_version == 2

    revoke_version = await service.revoke(
        context=context,
        grant_id=grant_id,
        expected_version=resume_version,
        expected_current_status=(
            BreakGlassGrantStatus.ACTIVE
        ),
        transition_reason=(
            "Emergency recovery completed"
        ),
    )

    assert revoke_version == 3

    async with database.tenant_transaction(
        TENANT_ID.value
    ) as connection:
        grant_row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT
                            status,
                            version
                        FROM platform.break_glass_grant
                        WHERE tenant_id =
                            CAST(:tenant_id AS uuid)
                          AND id =
                            CAST(:grant_id AS uuid)
                        """
                    ),
                    {
                        "tenant_id": str(
                            TENANT_ID.value
                        ),
                        "grant_id": str(
                            grant_id.value
                        ),
                    },
                )
            )
            .mappings()
            .one()
        )

        lifecycle_rows = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT
                            a.action,
                            a.transaction_id
                                AS audit_transaction_id,
                            a.actor_id
                                AS audit_actor_id,
                            a.correlation_id
                                AS audit_correlation_id,
                            a.details,
                            e.audit_record_id,
                            e.transaction_id
                                AS evidence_transaction_id,
                            e.actor_id
                                AS evidence_actor_id,
                            e.correlation_id
                                AS evidence_correlation_id,
                            e.evidence_type,
                            e.signature_algorithm,
                            e.key_id,
                            e.payload_hash,
                            octet_length(e.signature)
                                AS signature_length
                        FROM platform.audit_record AS a
                        JOIN platform.evidence_record AS e
                          ON e.audit_record_id = a.id
                         AND e.tenant_id = a.tenant_id
                         AND e.transaction_id =
                             a.transaction_id
                         AND e.actor_id = a.actor_id
                         AND e.correlation_id =
                             a.correlation_id
                        WHERE a.tenant_id =
                            CAST(:tenant_id AS uuid)
                          AND a.resource_type =
                            'BreakGlassGrant'
                          AND a.resource_id = :grant_id
                        ORDER BY a.occurred_at
                        """
                    ),
                    {
                        "tenant_id": str(
                            TENANT_ID.value
                        ),
                        "grant_id": str(
                            grant_id.value
                        ),
                    },
                )
            )
            .mappings()
            .all()
        )

    assert grant_row["status"] == "REVOKED"
    assert grant_row["version"] == 3

    assert [
        row["action"]
        for row in lifecycle_rows
    ] == [
        BREAK_GLASS_ISSUE_OPERATION,
        BREAK_GLASS_SUSPEND_OPERATION,
        BREAK_GLASS_RESUME_OPERATION,
        BREAK_GLASS_REVOKE_OPERATION,
    ]

    assert [
        row["evidence_type"]
        for row in lifecycle_rows
    ] == [
        BREAK_GLASS_ISSUE_EVIDENCE_TYPE,
        BREAK_GLASS_SUSPEND_EVIDENCE_TYPE,
        BREAK_GLASS_RESUME_EVIDENCE_TYPE,
        BREAK_GLASS_REVOKE_EVIDENCE_TYPE,
    ]

    assert [
        row["details"]["event"]
        for row in lifecycle_rows
    ] == [
        "break-glass.issuance",
        "break-glass.suspension",
        "break-glass.resumption",
        "break-glass.revocation",
    ]

    for row in lifecycle_rows:
        assert (
            row["audit_transaction_id"]
            == row["evidence_transaction_id"]
        )
        assert (
            row["audit_actor_id"]
            == row["evidence_actor_id"]
            == ADMIN_ID.value
        )
        assert (
            row["audit_correlation_id"]
            == row["evidence_correlation_id"]
            == CORRELATION_ID.value
        )
        assert row["signature_algorithm"] == "Ed25519"
        assert row["key_id"] == (
            "break-glass-lifecycle-test-key"
        )
        assert row["payload_hash"].startswith(
            "sha256:"
        )
        assert row["signature_length"] == 64


@pytest.mark.integration
@pytest.mark.parametrize(
    "image",
    [
        "postgres:12.22",
        "postgres:18",
    ],
)
def test_break_glass_lifecycle_happy_path(
    image: str,
) -> None:
    with PostgresContainer(
        image
    ) as postgres:
        migration_url, runtime_url = (
            provision_roles(
                admin_url(postgres)
            )
        )

        run_alembic(
            migration_url,
            runtime_url,
        )

        _seed(
            migration_url
        )

        _run(
            _exercise(
                runtime_url
            )
        )

# === C-I4-12z3 REAL TRANSITION ROLLBACK ===


async def _exercise_transition_rollback(
    runtime_url: str,
) -> None:
    private_key = Ed25519PrivateKey.generate()

    signer = Ed25519EvidenceSigner(
        private_key=private_key,
        key_id="break-glass-lifecycle-rollback-key",
    )

    database = Database(
        runtime_url
    )

    persistence = (
        PostgresBreakGlassLifecyclePersistence(
            PostgresUnitOfWorkFactory(
                database
            )
        )
    )

    # First establish a real durable ACTIVE grant at version 0.
    issue_service = BreakGlassLifecycleService(
        persistence=persistence,
        signer=signer,
        clock=_SequenceClock(
            [
                NOW,
            ]
        ),
    )

    issue_result = await issue_service.issue(
        context=_context(),
        command=_issue_command(),
    )

    assert issue_result.version == 0

    grant_id = issue_result.grant_id

    changed_at = NOW + timedelta(minutes=1)
    transaction_id = TransactionId.new()
    audit_record_id = AuditRecordId.new()

    transaction_context = TransactionContext(
        transaction_id=transaction_id,
        tenant_id=TENANT_ID,
        actor_id=ADMIN_ID,
        correlation_id=CORRELATION_ID,
        operation=BREAK_GLASS_SUSPEND_OPERATION,
        capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
        started_at=changed_at,
    )

    payload = {
        "event": "break-glass.suspension",
        "outcome": "SUCCESS",
        "tenant_id": str(TENANT_ID.value),
        "grant_id": str(grant_id.value),
        "changed_by_actor_id": str(ADMIN_ID.value),
        "from_status": "ACTIVE",
        "to_status": "SUSPENDED",
        "expected_version": 0,
        "transition_reason": (
            "Forced rollback integration proof"
        ),
        "changed_at": changed_at.isoformat(),
    }

    audit_record = AuditRecord(
        record_id=audit_record_id,
        tenant_id=TENANT_ID,
        transaction_id=transaction_id,
        actor_id=ADMIN_ID,
        correlation_id=CORRELATION_ID,
        capability=BREAK_GLASS_MANAGEMENT_CAPABILITY,
        action=BREAK_GLASS_SUSPEND_OPERATION,
        resource_type="BreakGlassGrant",
        resource_id=str(grant_id.value),
        outcome=AuditOutcome.SUCCESS,
        occurred_at=changed_at,
        details=payload,
    )

    # Build a correctly signed Evidence linked to the Audit/transaction,
    # but bind it to the wrong actor. Persistence pre-linkage checks pass;
    # PostgresEvidenceRepository rejects it only after transition + Audit
    # have already executed inside the same UoW transaction.
    wrong_actor_context = ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=SUBJECT_ID,
        actor_type=ActorType.HUMAN,
        authentication=_authentication(),
        correlation_id=CORRELATION_ID,
        break_glass=None,
    )

    evidence_factory = SignedEvidenceFactory(
        signer=signer,
        clock=_SequenceClock(
            [
                changed_at,
            ]
        ),
    )

    evidence_record = await evidence_factory.create(
        context=wrong_actor_context,
        audit_record_id=audit_record_id.value,
        transaction_id=transaction_id.value,
        evidence_type=(
            BREAK_GLASS_SUSPEND_EVIDENCE_TYPE
        ),
        occurred_at=changed_at,
        payload=payload,
        signed_at=changed_at,
    )

    with pytest.raises(
        ValueError,
        match=(
            "Evidence actor does not match UnitOfWork"
        ),
    ):
        await persistence.persist_transition(
            transaction_context=transaction_context,
            grant_id=grant_id,
            expected_version=0,
            expected_current_status=(
                BreakGlassGrantStatus.ACTIVE
            ),
            target_status=(
                BreakGlassGrantStatus.SUSPENDED
            ),
            changed_at=changed_at,
            audit_record=audit_record,
            evidence_record=evidence_record,
        )

    # PostgreSQL must have rolled back BOTH the CAS and Audit append.
    async with database.tenant_transaction(
        TENANT_ID.value
    ) as connection:
        grant_row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT
                            status,
                            version
                        FROM platform.break_glass_grant
                        WHERE tenant_id =
                            CAST(:tenant_id AS uuid)
                          AND id =
                            CAST(:grant_id AS uuid)
                        """
                    ),
                    {
                        "tenant_id": str(
                            TENANT_ID.value
                        ),
                        "grant_id": str(
                            grant_id.value
                        ),
                    },
                )
            )
            .mappings()
            .one()
        )

        suspend_audit_count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM platform.audit_record
                    WHERE tenant_id =
                        CAST(:tenant_id AS uuid)
                      AND resource_type =
                        'BreakGlassGrant'
                      AND resource_id = :grant_id
                      AND action = :action
                    """
                ),
                {
                    "tenant_id": str(
                        TENANT_ID.value
                    ),
                    "grant_id": str(
                        grant_id.value
                    ),
                    "action": (
                        BREAK_GLASS_SUSPEND_OPERATION
                    ),
                },
            )
        ).scalar_one()

        suspend_evidence_count = (
            await connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM platform.evidence_record
                    WHERE tenant_id =
                        CAST(:tenant_id AS uuid)
                      AND evidence_type =
                        :evidence_type
                    """
                ),
                {
                    "tenant_id": str(
                        TENANT_ID.value
                    ),
                    "evidence_type": (
                        BREAK_GLASS_SUSPEND_EVIDENCE_TYPE
                    ),
                },
            )
        ).scalar_one()

    assert grant_row["status"] == "ACTIVE"
    assert grant_row["version"] == 0
    assert suspend_audit_count == 0
    assert suspend_evidence_count == 0


@pytest.mark.integration
def test_break_glass_transition_rolls_back_on_evidence_failure() -> None:
    with PostgresContainer(
        "postgres:18"
    ) as postgres:
        migration_url, runtime_url = (
            provision_roles(
                admin_url(postgres)
            )
        )

        run_alembic(
            migration_url,
            runtime_url,
        )

        _seed(
            migration_url
        )

        _run(
            _exercise_transition_rollback(
                runtime_url
            )
        )
