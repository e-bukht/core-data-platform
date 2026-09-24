from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar, Token
from types import TracebackType

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncTransaction

from core_platform.infrastructure.persistence.database import Database
from core_platform.infrastructure.persistence.transaction_stores import (
    PostgresAuditStore,
    PostgresIdempotencyStore,
    PostgresInboxStore,
    PostgresOutboxStore,
)
from core_platform.transaction_kernel.models import TransactionContext
from core_platform.transaction_kernel.ports import (
    AuditStore,
    IdempotencyStore,
    InboxStore,
    OutboxStore,
    UnitOfWork,
)

_ACTIVE_ROOT_UOW: ContextVar[bool] = ContextVar(
    "core_platform_active_root_uow",
    default=False,
)


class PostgresUnitOfWork:
    def __init__(
        self,
        database: Database,
        context: TransactionContext,
    ) -> None:
        self._database = database
        self._context = context

        self._connection_context: AbstractAsyncContextManager[AsyncConnection] | None = None
        self._connection: AsyncConnection | None = None
        self._transaction: AsyncTransaction | None = None
        self._root_token: Token[bool] | None = None
        self._used = False

        self._idempotency = PostgresIdempotencyStore(
            self._require_connection,
            context,
        )
        self._outbox = PostgresOutboxStore(
            self._require_connection,
            context,
        )
        self._inbox = PostgresInboxStore(
            self._require_connection,
            context,
        )
        self._audit = PostgresAuditStore(
            self._require_connection,
            context,
        )

    @property
    def context(self) -> TransactionContext:
        return self._context

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    @property
    def outbox(self) -> OutboxStore:
        return self._outbox

    @property
    def inbox(self) -> InboxStore:
        return self._inbox

    @property
    def audit(self) -> AuditStore:
        return self._audit

    async def __aenter__(self) -> PostgresUnitOfWork:
        if self._used:
            raise RuntimeError("UnitOfWork instances are single-use")
        if _ACTIVE_ROOT_UOW.get():
            raise RuntimeError("Nested root UnitOfWork is not allowed")

        self._used = True
        self._root_token = _ACTIVE_ROOT_UOW.set(True)

        try:
            connection_context = self._database.open_connection()
            self._connection_context = connection_context
            self._connection = await connection_context.__aenter__()
            self._transaction = await self._connection.begin()

            await self._connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(self._context.tenant_id.value)},
            )
            await self._connection.execute(
                text("SELECT set_config('app.current_actor_id', :actor_id, true)"),
                {"actor_id": str(self._context.actor_id.value)},
            )
            await self._connection.execute(
                text("SELECT set_config('app.current_correlation_id', :correlation_id, true)"),
                {"correlation_id": str(self._context.correlation_id.value)},
            )

            return self
        except BaseException:
            await self._abort_failed_enter()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            transaction = self._transaction
            if transaction is not None and transaction.is_active:
                await transaction.rollback()
        finally:
            self._transaction = None
            self._connection = None

            connection_context = self._connection_context
            self._connection_context = None

            try:
                if connection_context is not None:
                    await connection_context.__aexit__(
                        exc_type,
                        exc_value,
                        traceback,
                    )
            finally:
                self._reset_root_token()

    async def commit(self) -> None:
        transaction = self._require_transaction()
        await transaction.commit()
        self._transaction = None

    async def rollback(self) -> None:
        transaction = self._require_transaction()
        await transaction.rollback()
        self._transaction = None

    def _require_connection(self) -> AsyncConnection:
        connection = self._connection
        transaction = self._transaction

        if connection is None or transaction is None or not transaction.is_active:
            raise RuntimeError("UnitOfWork has no active transaction")

        return connection

    def _require_transaction(self) -> AsyncTransaction:
        transaction = self._transaction

        if transaction is None or not transaction.is_active:
            raise RuntimeError("UnitOfWork has no active transaction")

        return transaction

    async def _abort_failed_enter(self) -> None:
        transaction = self._transaction
        if transaction is not None and transaction.is_active:
            await transaction.rollback()

        self._transaction = None
        self._connection = None

        connection_context = self._connection_context
        self._connection_context = None

        try:
            if connection_context is not None:
                await connection_context.__aexit__(
                    None,
                    None,
                    None,
                )
        finally:
            self._reset_root_token()

    def _reset_root_token(self) -> None:
        token = self._root_token
        if token is not None:
            _ACTIVE_ROOT_UOW.reset(token)
            self._root_token = None


class PostgresUnitOfWorkFactory:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self,
        context: TransactionContext,
    ) -> UnitOfWork:
        return PostgresUnitOfWork(
            self._database,
            context,
        )
