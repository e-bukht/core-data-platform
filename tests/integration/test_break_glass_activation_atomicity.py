from __future__ import annotations

import asyncio
import json
import selectors
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from testcontainers.community.postgres import PostgresContainer

from core_platform.application.break_glass import (
    DurableBreakGlassActivationRecorder,
)
from core_platform.application.context_trust import ContextTrustService
from core_platform.foundation.canonical_json import (
    canonical_json_bytes,
    canonical_json_sha256,
)
from core_platform.foundation.identifiers import CorrelationId
from core_platform.foundation.temporal import UtcClock
from core_platform.infrastructure.persistence.break_glass_activation_persistence import (
    PostgresBreakGlassActivationPersistence,
)
from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_uow import (
    PostgresUnitOfWorkFactory,
)
from core_platform.infrastructure.security.evidence_crypto import (
    Ed25519EvidenceSigner,
    Ed25519EvidenceVerifier,
)
from core_platform.platform_kernel.actor import Actor, ActorStatus, ActorType
from core_platform.platform_kernel.break_glass import (
    BreakGlassElevationContext,
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.context import ExecutionContext
from core_platform.platform_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceRecord,
    EvidenceRecordId,
)
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, BreakGlassGrantId, TenantId
from core_platform.platform_kernel.policy import CapabilityGrantPdp
from core_platform.platform_kernel.tenant import (
    MembershipStatus,
    Tenant,
    TenantMembership,
    TenantStatus,
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
    9,
    27,
    10,
    0,
    tzinfo=UTC,
)

TENANT_ID = TenantId(
    UUID(
        "00000000-0000-7d00-8000-000000001001"
    )
)
ACTOR_ID = ActorId(
    UUID(
        "00000000-0000-7d00-8000-000000001002"
    )
)
CORRELATION_ID = CorrelationId(
    UUID(
        "00000000-0000-7d00-8000-000000001003"
    )
)


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
                        'break-glass-atomicity',
                        'Break-glass Atomicity',
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
                    VALUES (
                        CAST(:actor_id AS uuid),
                        'HUMAN',
                        'ACTIVE',
                        'Break-glass Operator'
                    )
                    """
                ),
                {
                    "actor_id": str(
                        ACTOR_ID.value
                    )
                },
            )
    finally:
        engine.dispose()


def _context(
    transaction_id: TransactionId,
) -> TransactionContext:
    return TransactionContext(
        transaction_id=transaction_id,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        operation=(
            "security.break-glass.activate"
        ),
        capability="platform.outbox.retry",
        started_at=NOW,
    )


def _audit(
    *,
    audit_id: AuditRecordId,
    context: TransactionContext,
    grant_id: str,
) -> AuditRecord:
    return AuditRecord(
        record_id=audit_id,
        tenant_id=TENANT_ID,
        transaction_id=context.transaction_id,
        actor_id=ACTOR_ID,
        correlation_id=CORRELATION_ID,
        capability="platform.outbox.retry",
        action="security.break-glass.activate",
        resource_type="BreakGlassGrant",
        resource_id=grant_id,
        outcome=AuditOutcome.SUCCESS,
        occurred_at=NOW,
        details={
            "event": "break-glass.activation",
            "grant_id": grant_id,
        },
    )


def _evidence(
    *,
    evidence_id: EvidenceRecordId,
    audit: AuditRecord,
    context: TransactionContext,
) -> EvidenceRecord:
    payload = {
        "event": "break-glass.activation",
        "grant_id": audit.resource_id,
    }

    return EvidenceRecord(
        envelope=EvidenceEnvelope(
            envelope_version=1,
            record_id=evidence_id,
            tenant_id=TENANT_ID,
            audit_record_id=audit.record_id.value,
            transaction_id=(
                context.transaction_id.value
            ),
            actor_id=ACTOR_ID,
            correlation_id=CORRELATION_ID,
            evidence_type=(
                "security.break-glass.activation"
            ),
            occurred_at=NOW,
            signed_at=NOW,
            payload_hash=canonical_json_sha256(
                payload
            ),
            signature_algorithm="Ed25519",
            key_id=(
                "break-glass-atomicity-test-key"
            ),
        ),
        canonical_payload=canonical_json_bytes(
            payload
        ),
        signature=b"test-signature",
    )


async def _counts(
    database: Database,
    *,
    audit_id: AuditRecordId,
    evidence_id: EvidenceRecordId,
) -> tuple[int, int]:
    async with database.tenant_transaction(
        TENANT_ID.value
    ) as connection:
        audit_count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM platform.audit_record
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": str(
                    audit_id.value
                )
            },
        )

        evidence_count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM platform.evidence_record
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": str(
                    evidence_id.value
                )
            },
        )

    return (
        int(audit_count or 0),
        int(evidence_count or 0),
    )


async def _link_count(
    database: Database,
    *,
    audit_id: AuditRecordId,
    evidence_id: EvidenceRecordId,
) -> int:
    async with database.tenant_transaction(
        TENANT_ID.value
    ) as connection:
        count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM platform.evidence_record AS evidence
                JOIN platform.audit_record AS audit
                  ON audit.id =
                     evidence.audit_record_id
                 AND audit.tenant_id =
                     evidence.tenant_id
                 AND audit.transaction_id =
                     evidence.transaction_id
                 AND audit.actor_id =
                     evidence.actor_id
                 AND audit.correlation_id =
                     evidence.correlation_id
                WHERE audit.id =
                      CAST(:audit_id AS uuid)
                  AND evidence.id =
                      CAST(:evidence_id AS uuid)
                """
            ),
            {
                "audit_id": str(
                    audit_id.value
                ),
                "evidence_id": str(
                    evidence_id.value
                ),
            },
        )

    return int(
        count or 0
    )


async def _exercise(
    runtime_url: str,
) -> None:
    database = Database(
        runtime_url
    )
    factory = PostgresUnitOfWorkFactory(
        database
    )
    persistence = (
        PostgresBreakGlassActivationPersistence(
            factory
        )
    )

    try:
        # --------------------------------------------------
        # 1. Successful activation persists linked
        #    Audit + Evidence atomically.
        # --------------------------------------------------
        success_transaction = TransactionId(
            UUID(
                "00000000-0000-7d01-8000-000000001001"
            )
        )
        success_audit_id = AuditRecordId(
            UUID(
                "00000000-0000-7d02-8000-000000001001"
            )
        )
        success_evidence_id = EvidenceRecordId(
            UUID(
                "00000000-0000-7d03-8000-000000001001"
            )
        )

        success_context = _context(
            success_transaction
        )
        success_audit = _audit(
            audit_id=success_audit_id,
            context=success_context,
            grant_id=(
                "00000000-0000-7d04-8000-000000001001"
            ),
        )
        success_evidence = _evidence(
            evidence_id=success_evidence_id,
            audit=success_audit,
            context=success_context,
        )

        await persistence.persist(
            transaction_context=success_context,
            audit_record=success_audit,
            evidence_record=success_evidence,
        )

        assert await _counts(
            database,
            audit_id=success_audit_id,
            evidence_id=success_evidence_id,
        ) == (
            1,
            1,
        )

        assert (
            await _link_count(
                database,
                audit_id=success_audit_id,
                evidence_id=success_evidence_id,
            )
            == 1
        )

        # --------------------------------------------------
        # 2. Evidence failure happens after Audit append.
        #    The PostgreSQL transaction must roll back Audit.
        # --------------------------------------------------
        failure_transaction = TransactionId(
            UUID(
                "00000000-0000-7d01-8000-000000001002"
            )
        )
        failure_audit_id = AuditRecordId(
            UUID(
                "00000000-0000-7d02-8000-000000001002"
            )
        )
        failure_evidence_id = EvidenceRecordId(
            UUID(
                "00000000-0000-7d03-8000-000000001002"
            )
        )

        failure_context = _context(
            failure_transaction
        )
        failure_audit = _audit(
            audit_id=failure_audit_id,
            context=failure_context,
            grant_id=(
                "00000000-0000-7d04-8000-000000001002"
            ),
        )
        valid_failure_evidence = _evidence(
            evidence_id=failure_evidence_id,
            audit=failure_audit,
            context=failure_context,
        )

        broken_evidence = replace(
            valid_failure_evidence,
            envelope=replace(
                valid_failure_evidence.envelope,
                transaction_id=UUID(
                    "00000000-0000-7d01-8000-000000009999"
                ),
            ),
        )

        with pytest.raises(
            ValueError,
            match=(
                "Evidence transaction does not match UnitOfWork"
            ),
        ):
            await persistence.persist(
                transaction_context=failure_context,
                audit_record=failure_audit,
                evidence_record=broken_evidence,
            )

        assert await _counts(
            database,
            audit_id=failure_audit_id,
            evidence_id=failure_evidence_id,
        ) == (
            0,
            0,
        )

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
def test_break_glass_activation_audit_and_evidence_are_atomic(
    image: str,
) -> None:
    with PostgresContainer(
        image
    ) as postgres:
        migration_url, runtime_url = provision_roles(
            admin_url(
                postgres
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

async def _exercise_real_signing(runtime_url: str) -> None:
    """Real recorder -> PostgreSQL commit -> retrieval -> signature verification."""
    private_key = Ed25519PrivateKey.generate()
    key_id = "break-glass-integration-ed25519"
    signer = Ed25519EvidenceSigner(private_key=private_key, key_id=key_id)
    verifier = Ed25519EvidenceVerifier(
        public_keys={key_id: private_key.public_key()},
    )
    now = datetime.now(UTC)
    grant_id = BreakGlassGrantId(
        UUID("00000000-0000-7d04-8000-000000001009")
    )
    context = ExecutionContext(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        actor_type=ActorType.HUMAN,
        authentication=AuthenticationContext(
            issuer="https://issuer.example",
            subject="integration-operator",
            audience=("core-data-api",),
            client_id=None,
            scopes=frozenset(),
            acr="urn:core-platform:acr:elevated",
            amr=("pwd", "mfa"),
            authenticated_at=now - timedelta(minutes=1),
            token_id=None,
            expires_at=now + timedelta(minutes=10),
        ),
        correlation_id=CORRELATION_ID,
        break_glass=BreakGlassElevationContext(
            grant_id=grant_id,
            issued_by_actor_id=ActorId(
                UUID("00000000-0000-7d00-8000-000000001010")
            ),
            capability="platform.outbox.retry",
            scope=BreakGlassScope(
                BreakGlassScopeKind.RESOURCE,
                resource_type="outbox-message",
                resource_id="message-42",
            ),
            reason="Controlled recovery approval",
            activated_at=now - timedelta(seconds=2),
            valid_until=now + timedelta(minutes=10),
        ),
    )
    database = Database(runtime_url)
    recorder = DurableBreakGlassActivationRecorder(
        persistence=PostgresBreakGlassActivationPersistence(
            PostgresUnitOfWorkFactory(database),
        ),
        signer=signer,
        clock=UtcClock(),
    )
    try:
        await recorder.record(context)

        # Query through the non-owner runtime role with tenant-local RLS.
        async with database.tenant_transaction(TENANT_ID.value) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          a.id AS audit_id,
                          a.tenant_id AS audit_tenant_id,
                          a.transaction_id AS audit_transaction_id,
                          a.actor_id AS audit_actor_id,
                          a.correlation_id AS audit_correlation_id,
                          a.action AS audit_action,
                          a.capability AS audit_capability,
                          e.*
                        FROM platform.audit_record AS a
                        JOIN platform.evidence_record AS e
                          ON e.audit_record_id = a.id
                         AND e.tenant_id = a.tenant_id
                         AND e.transaction_id = a.transaction_id
                         AND e.actor_id = a.actor_id
                         AND e.correlation_id = a.correlation_id
                        WHERE a.tenant_id = CAST(:tenant_id AS uuid)
                          AND a.resource_id = :grant_id
                          AND a.action = 'security.break-glass.activate'
                        """
                    ),
                    {
                        "tenant_id": str(TENANT_ID.value),
                        "grant_id": str(grant_id.value),
                    },
                )
            ).mappings().all()
        assert len(rows) == 1
        row = rows[0]
        assert row["audit_id"] == row["audit_record_id"]
        assert row["tenant_id"] == row["audit_tenant_id"] == TENANT_ID.value
        assert row["transaction_id"] == row["audit_transaction_id"]
        assert row["actor_id"] == row["audit_actor_id"] == ACTOR_ID.value
        assert row["correlation_id"] == row["audit_correlation_id"] == CORRELATION_ID.value
        assert row["audit_action"] == "security.break-glass.activate"
        assert row["audit_capability"] == "platform.outbox.retry"
        assert row["evidence_type"] == "security.break-glass.activation"
        assert row["signature_algorithm"] == "Ed25519"
        assert row["key_id"] == key_id

        stored = EvidenceRecord(
            envelope=EvidenceEnvelope(
                envelope_version=row["envelope_version"],
                record_id=EvidenceRecordId(row["id"]),
                tenant_id=TenantId(row["tenant_id"]),
                audit_record_id=row["audit_record_id"],
                transaction_id=row["transaction_id"],
                actor_id=ActorId(row["actor_id"]),
                correlation_id=CorrelationId(row["correlation_id"]),
                evidence_type=row["evidence_type"],
                occurred_at=row["occurred_at"],
                signed_at=row["signed_at"],
                payload_hash=row["payload_hash"],
                signature_algorithm=row["signature_algorithm"],
                key_id=row["key_id"],
            ),
            canonical_payload=bytes(row["canonical_payload"]),
            signature=bytes(row["signature"]),
        )
        assert stored.payload_hash_matches()
        assert await verifier.verify(
            stored.envelope.signing_bytes(),
            signature=stored.signature,
            algorithm=stored.envelope.signature_algorithm,
            key_id=stored.envelope.key_id,
        )
        assert not await verifier.verify(
            replace(
                stored.envelope,
                payload_hash="sha256:" + "0" * 64,
            ).signing_bytes(),
            signature=stored.signature,
            algorithm=stored.envelope.signature_algorithm,
            key_id=stored.envelope.key_id,
        )
        assert not replace(
            stored, canonical_payload=stored.canonical_payload + b" "
        ).payload_hash_matches()

        # A different tenant must not read this activation via FORCE RLS.
        async with database.tenant_transaction(
            UUID("00000000-0000-7d00-8000-000000009999")
        ) as connection:
            visible = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM platform.evidence_record
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": str(stored.envelope.record_id.value)},
            )
        assert visible == 0
    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize("image", ["postgres:12.22", "postgres:18"])
def test_break_glass_real_signing_pg_matrix(image: str) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))
        run_alembic(migration_url, runtime_url)
        _seed(migration_url)
        _run(_exercise_real_signing(runtime_url))


async def _exercise_authorization_durable_gate(
    runtime_url: str,
    migration_url: str,
) -> None:
    """Actual authorization -> signed Audit/Evidence commit, then fail closed."""
    now = datetime.now(UTC)
    private_key = Ed25519PrivateKey.generate()
    key_id = "break-glass-service-integration"
    grant_id = BreakGlassGrantId(
        UUID("00000000-0000-7d04-8000-000000002001")
    )
    capability = "platform.outbox.retry"
    authentication = AuthenticationContext(
        issuer="https://issuer.example",
        subject="operator",
        audience=("core-data-api",),
        client_id=None,
        scopes=frozenset(),
        acr="urn:core-platform:acr:elevated",
        amr=("pwd", "mfa"),
        authenticated_at=now - timedelta(minutes=1),
        token_id=None,
        expires_at=now + timedelta(minutes=10),
    )
    actor = Actor(
        ACTOR_ID, ActorType.HUMAN, ActorStatus.ACTIVE, "Operator", now, now
    )
    tenant = Tenant(
        TENANT_ID, "service-evidence", "Service evidence", TenantStatus.ACTIVE,
        now, now,
    )
    membership = TenantMembership(
        TENANT_ID, ACTOR_ID, MembershipStatus.ACTIVE,
        now - timedelta(minutes=1), None, 0,
    )
    grant = BreakGlassGrant(
        grant_id=grant_id,
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        issued_by_actor_id=ActorId(
            UUID("00000000-0000-7d00-8000-000000002010")
        ),
        capabilities=(capability,),
        scope=BreakGlassScope(BreakGlassScopeKind.TENANT),
        reason="Controlled recovery approval",
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=10),
        status=BreakGlassGrantStatus.ACTIVE,
        accepted_acr_values=frozenset({authentication.acr}),
        required_amr=frozenset({"mfa"}),
    )

    class Authenticator:
        async def authenticate(self, token: str) -> AuthenticationContext:
            assert token == "operator-token"
            return authentication

    class TrustRepository:
        async def resolve_actor(self, issuer: str, subject: str) -> Actor | None:
            assert (issuer, subject) == (authentication.issuer, authentication.subject)
            return actor

        async def get_tenant(self, tenant_id: TenantId) -> Tenant | None:
            assert tenant_id == TENANT_ID
            return tenant

        async def get_membership(
            self, tenant_id: TenantId, actor_id: ActorId
        ) -> TenantMembership | None:
            assert (tenant_id, actor_id) == (TENANT_ID, ACTOR_ID)
            return membership

        async def get_capability_grant(
            self, tenant_id: TenantId, actor_id: ActorId, capability_code: str
        ) -> None:
            assert (tenant_id, actor_id, capability_code) == (
                TENANT_ID, ACTOR_ID, capability
            )
            return None  # Normal PDP must DENY before break-glass fallback.

        async def list_active_capability_codes(
            self, tenant_id: TenantId, actor_id: ActorId
        ) -> tuple[str, ...]:
            return ()

    class BreakGlassRepository:
        async def list_candidate_grants(
            self,
            tenant_id: TenantId,
            actor_id: ActorId,
            requested_capability: str,
            *,
            now: datetime,
        ) -> tuple[BreakGlassGrant, ...]:
            assert (tenant_id, actor_id, requested_capability) == (
                TENANT_ID, ACTOR_ID, capability
            )
            return (grant,)

    database = Database(runtime_url)
    signer = Ed25519EvidenceSigner(private_key=private_key, key_id=key_id)
    verifier = Ed25519EvidenceVerifier(
        public_keys={key_id: private_key.public_key()}
    )
    recorder = DurableBreakGlassActivationRecorder(
        persistence=PostgresBreakGlassActivationPersistence(
            PostgresUnitOfWorkFactory(database)
        ),
        signer=signer,
        clock=UtcClock(),
    )
    service = ContextTrustService(
        authenticator=Authenticator(),
        repository=TrustRepository(),
        break_glass_repository=BreakGlassRepository(),
        pdp=CapabilityGrantPdp(),
        environment="test",
        break_glass_activation_recorder=recorder,
    )

    async def records() -> list[Any]:
        async with database.tenant_transaction(TENANT_ID.value) as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT a.id AS audit_id, a.action AS audit_action,
                           a.correlation_id AS audit_correlation_id, e.*
                    FROM platform.audit_record AS a
                    JOIN platform.evidence_record AS e
                      ON e.audit_record_id = a.id
                     AND e.transaction_id = a.transaction_id
                     AND e.tenant_id = a.tenant_id
                    WHERE a.resource_id = :grant_id
                      AND a.action = 'security.break-glass.activate'
                    """
                ),
                {"grant_id": str(grant_id.value)},
            )
            return list(result.mappings().all())

    try:
        elevated = await service.authorize(
            token="operator-token",
            tenant_selector=str(TENANT_ID.value),
            capability_code=capability,
            correlation_id=CORRELATION_ID,
        )
        assert elevated.break_glass is not None
        assert elevated.break_glass.grant_id == grant_id
        saved = await records()
        assert len(saved) == 1
        row = saved[0]
        assert row["audit_id"] == row["audit_record_id"]
        assert row["audit_action"] == "security.break-glass.activate"
        assert row["audit_correlation_id"] == row["correlation_id"]
        assert row["correlation_id"] == CORRELATION_ID.value
        stored = EvidenceRecord(
            envelope=EvidenceEnvelope(
                envelope_version=row["envelope_version"],
                record_id=EvidenceRecordId(row["id"]),
                tenant_id=TenantId(row["tenant_id"]),
                audit_record_id=row["audit_record_id"],
                transaction_id=row["transaction_id"],
                actor_id=ActorId(row["actor_id"]),
                correlation_id=CorrelationId(row["correlation_id"]),
                evidence_type=row["evidence_type"],
                occurred_at=row["occurred_at"],
                signed_at=row["signed_at"],
                payload_hash=row["payload_hash"],
                signature_algorithm=row["signature_algorithm"],
                key_id=row["key_id"],
            ),
            canonical_payload=bytes(row["canonical_payload"]),
            signature=bytes(row["signature"]),
        )
        assert stored.payload_hash_matches()
        assert await verifier.verify(
            stored.envelope.signing_bytes(),
            signature=stored.signature,
            algorithm=stored.envelope.signature_algorithm,
            key_id=stored.envelope.key_id,
        )
        payload = json.loads(stored.canonical_payload)
        assert payload["grant_id"] == str(grant_id.value)
        assert payload["reason"] == "Controlled recovery approval"

        # A real database failure AFTER the Audit insert must not yield
        # an elevated context or leave an additional partial Audit row.
        migration_engine = create_engine(migration_url)
        try:
            with migration_engine.begin() as connection:
                connection.execute(
                    text(
                        "REVOKE INSERT ON platform.evidence_record "
                        "FROM coredata_runtime"
                    )
                )
        finally:
            migration_engine.dispose()

        with pytest.raises(ProgrammingError, match="permission denied"):
            await service.authorize(
                token="operator-token",
                tenant_selector=str(TENANT_ID.value),
                capability_code=capability,
                correlation_id=CORRELATION_ID,
            )
        assert len(await records()) == 1
    finally:
        await database.close()


@pytest.mark.integration
@pytest.mark.compatibility
@pytest.mark.parametrize("image", ["postgres:12.22", "postgres:18"])
def test_authorize_commits_evidence_before_elevation_pg_matrix(image: str) -> None:
    with PostgresContainer(image) as postgres:
        migration_url, runtime_url = provision_roles(admin_url(postgres))
        run_alembic(migration_url, runtime_url)
        _seed(migration_url)
        _run(_exercise_authorization_durable_gate(runtime_url, migration_url))
