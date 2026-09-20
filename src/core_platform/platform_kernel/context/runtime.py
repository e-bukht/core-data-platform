from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from core_platform.foundation.errors import InternalError
from core_platform.platform_kernel.context.models import ExecutionContext

_execution_context: ContextVar[ExecutionContext | None] = ContextVar(
    "execution_context", default=None
)


@contextmanager
def bind_execution_context(context: ExecutionContext) -> Iterator[ExecutionContext]:
    token = _execution_context.set(context)
    try:
        yield context
    finally:
        _execution_context.reset(token)


def get_execution_context() -> ExecutionContext | None:
    return _execution_context.get()


def require_execution_context() -> ExecutionContext:
    context = get_execution_context()
    if context is None:
        raise InternalError("CONTEXT.NOT.BOUND", "Execution context is not bound")
    return context
