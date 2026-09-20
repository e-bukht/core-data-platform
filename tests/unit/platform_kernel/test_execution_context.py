import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from core_platform.foundation.identifiers import CorrelationId
from core_platform.platform_kernel.actor import ActorType
from core_platform.platform_kernel.context import (
    ExecutionContext,
    bind_execution_context,
    get_execution_context,
    require_execution_context,
)
from core_platform.platform_kernel.identity import AuthenticationContext
from core_platform.platform_kernel.ids import ActorId, TenantId


def _context(index: int) -> ExecutionContext:
    now = datetime.now(UTC)
    return ExecutionContext(
        tenant_id=TenantId(UUID(int=index + 1)),
        actor_id=ActorId(UUID(int=index + 1001)),
        actor_type=ActorType.HUMAN,
        authentication=AuthenticationContext(
            issuer="https://issuer.example",
            subject=f"subject-{index}",
            audience=("core-data-api",),
            client_id="client",
            scopes=frozenset(),
            acr=None,
            amr=(),
            authenticated_at=now,
            token_id=None,
            expires_at=now + timedelta(minutes=5),
        ),
        correlation_id=CorrelationId(UUID(int=index + 2001)),
    )


def test_execution_context_is_reset() -> None:
    context = _context(1)
    assert get_execution_context() is None
    with bind_execution_context(context):
        assert require_execution_context() == context
    assert get_execution_context() is None


def test_execution_context_isolated_across_100_async_tasks() -> None:
    async def worker(index: int) -> None:
        context = _context(index)
        with bind_execution_context(context):
            await asyncio.sleep(0)
            assert require_execution_context() == context
        assert get_execution_context() is None

    async def run() -> None:
        await asyncio.gather(*(worker(index) for index in range(100)))

    asyncio.run(run())
    assert get_execution_context() is None
