from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import ClauseElement

from core_platform.foundation.errors import BusinessRuleViolation
from core_platform.foundation.identifiers import (
    CorrelationId,
)
from core_platform.infrastructure.persistence import (
    break_glass_lifecycle_store as module,
)
from core_platform.infrastructure.persistence.break_glass_lifecycle_store import (
    PostgresBreakGlassLifecycleStore,
)
from core_platform.platform_kernel.break_glass import (
    BreakGlassGrant,
    BreakGlassGrantStatus,
    BreakGlassScope,
    BreakGlassScopeKind,
)
from core_platform.platform_kernel.ids import (
    ActorId,
    BreakGlassGrantId,
    TenantId,
)
from core_platform.transaction_kernel.errors import (
    ConcurrencyConflict,
)
from core_platform.transaction_kernel.ids import (
    TransactionId,
)
from core_platform.transaction_kernel.models import (
    TransactionContext,
)

TENANT_ID = TenantId(
    UUID("00000000-0000-7000-8000-000000000001")
)
ACTOR_ID = ActorId(
    UUID("00000000-0000-7000-8000-000000000002")
)


def _async_test(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper


GRANT_ID = BreakGlassGrantId(
    UUID("00000000-0000-7000-8000-000000000003")
)


def _connection_provider(
    connection: object,
) -> Callable[[], AsyncConnection]:
    return lambda: cast(
        AsyncConnection,
        connection,
    )


def _context() -> TransactionContext:
    return TransactionContext(
        transaction_id=TransactionId(
            UUID("00000000-0000-7000-8000-000000000004")
        ),
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId(
            UUID("00000000-0000-7000-8000-000000000005")
        ),
        operation="security.break-glass.suspend",
        capability="platform.break-glass.manage",
        started_at=datetime(
            2026,
            10,
            5,
            16,
            30,
            tzinfo=UTC,
        ),
        idempotency_key=None,
    )


class _CurrentGrantRow:
    def __init__(
        self,
        *,
        status: str,
        valid_from: datetime,
        valid_until: datetime,
    ) -> None:
        self.status = status
        self.valid_from = valid_from
        self.valid_until = valid_until


class _Result:
    def __init__(
        self,
        value: _CurrentGrantRow | None,
    ) -> None:
        self._value = value

    def one_or_none(
        self,
    ) -> _CurrentGrantRow | None:
        return self._value


class _Connection:
    def __init__(
        self,
        current_status: str | None,
        *,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> None:
        if current_status is None:
            self.current = None
        else:
            self.current = _CurrentGrantRow(
                status=current_status,
                valid_from=valid_from
                or datetime(
                    2026,
                    10,
                    5,
                    16,
                    0,
                    tzinfo=UTC,
                ),
                valid_until=valid_until
                or datetime(
                    2026,
                    10,
                    5,
                    17,
                    0,
                    tzinfo=UTC,
                ),
            )

        self.executions = 0

    async def execute(
        self,
        statement: ClauseElement,
    ) -> _Result:
        del statement
        self.executions += 1
        return _Result(self.current)


@_async_test
async def test_transition_status_uses_existing_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection("ACTIVE")

    observed: dict[str, object] = {}

    async def fake_compare_and_swap(
        actual_connection: object,
        *,
        table: object,
        tenant_id: UUID,
        resource_id: UUID,
        resource_type: str,
        expected_version: int,
        values: dict[str, object],
    ) -> int:
        observed.update(
            {
                "connection": actual_connection,
                "table": table,
                "tenant_id": tenant_id,
                "resource_id": resource_id,
                "resource_type": resource_type,
                "expected_version": expected_version,
                "values": values,
            }
        )
        return 8

    monkeypatch.setattr(
        module,
        "compare_and_swap",
        fake_compare_and_swap,
    )

    store = PostgresBreakGlassLifecycleStore(
        _connection_provider(connection),
        _context(),
    )

    changed_at = datetime(
        2026,
        10,
        5,
        16,
        31,
        tzinfo=UTC,
    )

    new_version = await store.transition_status(
        grant_id=GRANT_ID,
        expected_version=7,
        expected_current_status=BreakGlassGrantStatus.ACTIVE,
        target_status=BreakGlassGrantStatus.SUSPENDED,
        changed_at=changed_at,
    )

    assert new_version == 8
    assert connection.executions == 1
    assert observed["connection"] is connection
    assert observed["tenant_id"] == TENANT_ID.value
    assert observed["resource_id"] == GRANT_ID.value
    assert observed["resource_type"] == "BreakGlassGrant"
    assert observed["expected_version"] == 7
    assert observed["values"] == {
        "status": "SUSPENDED",
        "updated_at": changed_at,
    }


@_async_test
async def test_missing_or_stale_grant_is_concurrency_conflict() -> None:
    connection = _Connection(None)

    store = PostgresBreakGlassLifecycleStore(
        _connection_provider(connection),
        _context(),
    )

    with pytest.raises(
        ConcurrencyConflict,
        match="Optimistic concurrency conflict",
    ) as exc:
        await store.transition_status(
            grant_id=GRANT_ID,
            expected_version=4,
            expected_current_status=BreakGlassGrantStatus.ACTIVE,
            target_status=BreakGlassGrantStatus.REVOKED,
            changed_at=datetime(
                2026,
                10,
                5,
                16,
                31,
                tzinfo=UTC,
            ),
        )

    assert exc.value.resource_type == "BreakGlassGrant"
    assert exc.value.resource_id == str(GRANT_ID.value)
    assert exc.value.expected_version == 4


@_async_test
async def test_illegal_transition_never_calls_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection("REVOKED")

    async def forbidden_cas(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise AssertionError(
            "CAS must not run for illegal transition"
        )

    monkeypatch.setattr(
        module,
        "compare_and_swap",
        forbidden_cas,
    )

    store = PostgresBreakGlassLifecycleStore(
        _connection_provider(connection),
        _context(),
    )

    with pytest.raises(
        ValueError,
        match="REVOKED -> ACTIVE is not allowed",
    ):
        await store.transition_status(
            grant_id=GRANT_ID,
            expected_version=2,
            expected_current_status=BreakGlassGrantStatus.REVOKED,
            target_status=BreakGlassGrantStatus.ACTIVE,
            changed_at=datetime(
                2026,
                10,
                5,
                16,
                31,
                tzinfo=UTC,
            ),
        )


@_async_test
async def test_naive_changed_at_is_rejected() -> None:
    connection = _Connection("ACTIVE")

    store = PostgresBreakGlassLifecycleStore(
        _connection_provider(connection),
        _context(),
    )

    with pytest.raises(
        ValueError,
        match="changed_at must be timezone-aware",
    ):
        await store.transition_status(
            grant_id=GRANT_ID,
            expected_version=0,
            expected_current_status=BreakGlassGrantStatus.ACTIVE,
            target_status=BreakGlassGrantStatus.SUSPENDED,
            changed_at=datetime(2026, 10, 5, 16, 31),
        )

    assert connection.executions == 0

# === C-I4-12k2 ISSUE STORE PROOFS ===

GRANT_ACTOR_ID = ActorId(
    UUID("00000000-0000-7000-8000-000000000006")
)


def _issue_grant(
    *,
    tenant_id: TenantId = TENANT_ID,
    issued_by_actor_id: ActorId = ACTOR_ID,
    status: BreakGlassGrantStatus = BreakGlassGrantStatus.ACTIVE,
) -> BreakGlassGrant:
    valid_from = datetime(
        2026,
        10,
        5,
        16,
        31,
        tzinfo=UTC,
    )

    return BreakGlassGrant(
        grant_id=GRANT_ID,
        tenant_id=tenant_id,
        actor_id=GRANT_ACTOR_ID,
        issued_by_actor_id=issued_by_actor_id,
        capabilities=(
            "platform.outbox.retry",
            "platform.audit.read",
        ),
        scope=BreakGlassScope(
            kind=BreakGlassScopeKind.RESOURCE,
            resource_type="OutboxMessage",
            resource_id="message-42",
        ),
        reason="Emergency recovery",
        valid_from=valid_from,
        valid_until=valid_from + timedelta(minutes=30),
        status=status,
        accepted_acr_values=frozenset(
            {
                "urn:core-platform:acr:elevated",
                "urn:core-platform:acr:loa2",
            }
        ),
        required_amr=frozenset(
            {
                "mfa",
                "pwd",
            }
        ),
    )


class _IssueResult:
    def __init__(self, version: int) -> None:
        self._version = version

    def scalar_one(self) -> int:
        return self._version


class _IssueConnection:
    def __init__(self) -> None:
        self.executions = 0
        self.statement: ClauseElement | None = None

    async def execute(
        self,
        statement: ClauseElement,
    ) -> _IssueResult:
        self.executions += 1
        self.statement = statement
        return _IssueResult(0)


def test_issue_inserts_complete_active_grant_at_version_zero() -> None:
    async def scenario() -> None:
        connection = _IssueConnection()

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        issued_at = datetime(
            2026,
            10,
            5,
            16,
            30,
            tzinfo=UTC,
        )

        version = await store.issue(
            grant=_issue_grant(),
            issued_at=issued_at,
        )

        assert version == 0
        assert connection.executions == 1
        assert connection.statement is not None

        compiled = connection.statement.compile()
        params = compiled.params

        assert params["id"] == GRANT_ID.value
        assert params["tenant_id"] == TENANT_ID.value
        assert params["actor_id"] == GRANT_ACTOR_ID.value
        assert params["issued_by_actor_id"] == ACTOR_ID.value
        assert params["capabilities"] == [
            "platform.outbox.retry",
            "platform.audit.read",
        ]
        assert params["scope_kind"] == "RESOURCE"
        assert params["resource_type"] == "OutboxMessage"
        assert params["resource_id"] == "message-42"
        assert params["reason"] == "Emergency recovery"
        assert params["status"] == "ACTIVE"
        assert params["accepted_acr_values"] == [
            "urn:core-platform:acr:elevated",
            "urn:core-platform:acr:loa2",
        ]
        assert params["required_amr"] == [
            "mfa",
            "pwd",
        ]
        assert params["version"] == 0
        assert params["created_at"] == issued_at
        assert params["updated_at"] == issued_at

    asyncio.run(scenario())


def test_issue_rejects_cross_tenant_grant_before_sql() -> None:
    async def scenario() -> None:
        connection = _IssueConnection()

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        foreign_tenant = TenantId(
            UUID("00000000-0000-7000-8000-000000000007")
        )

        with pytest.raises(
            ValueError,
            match=(
                "Break-glass grant tenant "
                "does not match UnitOfWork"
            ),
        ):
            await store.issue(
                grant=_issue_grant(
                    tenant_id=foreign_tenant,
                ),
                issued_at=datetime(
                    2026,
                    10,
                    5,
                    16,
                    30,
                    tzinfo=UTC,
                ),
            )

        assert connection.executions == 0

    asyncio.run(scenario())


def test_issue_rejects_foreign_issuer_before_sql() -> None:
    async def scenario() -> None:
        connection = _IssueConnection()

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        foreign_issuer = ActorId(
            UUID("00000000-0000-7000-8000-000000000008")
        )

        with pytest.raises(
            ValueError,
            match=(
                "Break-glass grant issuer "
                "does not match UnitOfWork actor"
            ),
        ):
            await store.issue(
                grant=_issue_grant(
                    issued_by_actor_id=foreign_issuer,
                ),
                issued_at=datetime(
                    2026,
                    10,
                    5,
                    16,
                    30,
                    tzinfo=UTC,
                ),
            )

        assert connection.executions == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status",
    [
        BreakGlassGrantStatus.SUSPENDED,
        BreakGlassGrantStatus.REVOKED,
    ],
)
def test_issue_rejects_non_active_initial_status_before_sql(
    status: BreakGlassGrantStatus,
) -> None:
    async def scenario() -> None:
        connection = _IssueConnection()

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        with pytest.raises(
            ValueError,
            match="New break-glass grant must be ACTIVE",
        ):
            await store.issue(
                grant=_issue_grant(
                    status=status,
                ),
                issued_at=datetime(
                    2026,
                    10,
                    5,
                    16,
                    30,
                    tzinfo=UTC,
                ),
            )

        assert connection.executions == 0

    asyncio.run(scenario())

# === C-I4-12u RESUME TEMPORAL SAFETY ===


@pytest.mark.parametrize(
    "changed_at",
    [
        datetime(
            2026,
            10,
            5,
            15,
            59,
            59,
            tzinfo=UTC,
        ),
        datetime(
            2026,
            10,
            5,
            17,
            0,
            tzinfo=UTC,
        ),
        datetime(
            2026,
            10,
            5,
            17,
            1,
            tzinfo=UTC,
        ),
    ],
)
def test_resume_rejects_outside_validity_window(
    changed_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        connection = _Connection(
            "SUSPENDED",
            valid_from=datetime(
                2026,
                10,
                5,
                16,
                0,
                tzinfo=UTC,
            ),
            valid_until=datetime(
                2026,
                10,
                5,
                17,
                0,
                tzinfo=UTC,
            ),
        )

        async def forbidden_cas(
            *args: object,
            **kwargs: object,
        ) -> int:
            del args, kwargs
            raise AssertionError(
                "CAS must not run outside validity window"
            )

        monkeypatch.setattr(
            module,
            "compare_and_swap",
            forbidden_cas,
        )

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        with pytest.raises(
            BusinessRuleViolation
        ) as caught:
            await store.transition_status(
                grant_id=GRANT_ID,
                expected_version=7,
                expected_current_status=BreakGlassGrantStatus.SUSPENDED,
                target_status=BreakGlassGrantStatus.ACTIVE,
                changed_at=changed_at,
            )

        assert caught.value.code == (
            "BREAK_GLASS.RESUME.OUTSIDE_VALIDITY_WINDOW"
        )
        assert caught.value.correlation_id == str(
            _context().correlation_id
        )

    asyncio.run(scenario())


def test_resume_inside_validity_window_uses_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        connection = _Connection(
            "SUSPENDED",
            valid_from=datetime(
                2026,
                10,
                5,
                16,
                0,
                tzinfo=UTC,
            ),
            valid_until=datetime(
                2026,
                10,
                5,
                17,
                0,
                tzinfo=UTC,
            ),
        )

        calls = 0

        async def fake_cas(
            *args: object,
            **kwargs: object,
        ) -> int:
            nonlocal calls
            del args, kwargs
            calls += 1
            return 8

        monkeypatch.setattr(
            module,
            "compare_and_swap",
            fake_cas,
        )

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        version = await store.transition_status(
            grant_id=GRANT_ID,
            expected_version=7,
            expected_current_status=BreakGlassGrantStatus.SUSPENDED,
            target_status=BreakGlassGrantStatus.ACTIVE,
            changed_at=datetime(
                2026,
                10,
                5,
                16,
                30,
                tzinfo=UTC,
            ),
        )

        assert version == 8
        assert calls == 1

    asyncio.run(scenario())

# === C-I4-12w EXPECTED SOURCE STATUS ===


def test_source_status_mismatch_is_concurrency_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        connection = _Connection(
            "SUSPENDED",
        )

        async def forbidden_cas(
            *args: object,
            **kwargs: object,
        ) -> int:
            del args, kwargs
            raise AssertionError(
                "CAS must not run after source-status mismatch"
            )

        monkeypatch.setattr(
            module,
            "compare_and_swap",
            forbidden_cas,
        )

        store = PostgresBreakGlassLifecycleStore(
            _connection_provider(connection),
            _context(),
        )

        with pytest.raises(
            ConcurrencyConflict,
            match="Optimistic concurrency conflict",
        ):
            await store.transition_status(
                grant_id=GRANT_ID,
                expected_version=7,
                expected_current_status=(
                    BreakGlassGrantStatus.ACTIVE
                ),
                target_status=BreakGlassGrantStatus.REVOKED,
                changed_at=datetime(
                    2026,
                    10,
                    5,
                    16,
                    31,
                    tzinfo=UTC,
                ),
            )

    asyncio.run(scenario())
