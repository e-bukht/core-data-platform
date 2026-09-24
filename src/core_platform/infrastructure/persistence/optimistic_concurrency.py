from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import Table, update
from sqlalchemy.ext.asyncio import AsyncConnection

from core_platform.transaction_kernel.errors import (
    ConcurrencyConflict,
)

_PROTECTED_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "version",
    }
)


async def compare_and_swap(
    connection: AsyncConnection,
    *,
    table: Table,
    tenant_id: UUID,
    resource_id: UUID,
    resource_type: str,
    expected_version: int,
    values: Mapping[str, object],
) -> int:
    """Atomically update one tenant-scoped versioned row.

    A zero-row update is deliberately ambiguous: stale version,
    unknown resource and cross-tenant access all produce the same
    ConcurrencyConflict.
    """

    if expected_version < 0:
        raise ValueError("expected_version must be >= 0")

    if not resource_type:
        raise ValueError("resource_type must not be empty")

    if not values:
        raise ValueError("CAS values must not be empty")

    table_columns = set(table.c.keys())

    missing_columns = _PROTECTED_COLUMNS - table_columns
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"CAS table is missing required columns: {missing}")

    unknown_columns = set(values) - table_columns
    if unknown_columns:
        unknown = ", ".join(sorted(unknown_columns))
        raise ValueError(f"CAS values contain unknown columns: {unknown}")

    protected_mutations = set(values) & _PROTECTED_COLUMNS
    if protected_mutations:
        protected = ", ".join(sorted(protected_mutations))
        raise ValueError(f"CAS cannot directly mutate protected columns: {protected}")

    update_values = dict(values)
    update_values["version"] = table.c.version + 1

    statement = (
        update(table)
        .where(
            table.c.tenant_id == tenant_id,
            table.c.id == resource_id,
            table.c.version == expected_version,
        )
        .values(update_values)
        .returning(table.c.version)
    )

    result = await connection.execute(statement)
    new_version = result.scalar_one_or_none()

    if new_version is None:
        raise ConcurrencyConflict(
            resource_type=resource_type,
            resource_id=str(resource_id),
            expected_version=expected_version,
        )

    return int(new_version)
