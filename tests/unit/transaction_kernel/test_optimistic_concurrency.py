from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
)
from sqlalchemy import Uuid as SqlUuid

from core_platform.infrastructure.persistence.optimistic_concurrency import (
    compare_and_swap,
)
from core_platform.transaction_kernel.errors import (
    ConcurrencyConflict,
)

metadata = MetaData()

versioned_table = Table(
    "versioned_resource",
    metadata,
    Column(
        "id",
        SqlUuid(as_uuid=True),
        primary_key=True,
    ),
    Column(
        "tenant_id",
        SqlUuid(as_uuid=True),
        nullable=False,
    ),
    Column(
        "value",
        String(100),
        nullable=False,
    ),
    Column(
        "version",
        BigInteger,
        nullable=False,
    ),
)


def test_concurrency_conflict_exposes_only_expected_version() -> None:
    conflict = ConcurrencyConflict(
        resource_type="Example",
        resource_id="resource-1",
        expected_version=7,
    )

    assert str(conflict) == ("Optimistic concurrency conflict")
    assert conflict.resource_type == "Example"
    assert conflict.resource_id == "resource-1"
    assert conflict.expected_version == 7
    assert not hasattr(
        conflict,
        "actual_version",
    )


def test_cas_rejects_negative_expected_version() -> None:
    with pytest.raises(
        ValueError,
        match="expected_version must be >= 0",
    ):
        asyncio.run(
            compare_and_swap(
                None,  # type: ignore[arg-type]
                table=versioned_table,
                tenant_id=UUID(int=1),
                resource_id=UUID(int=2),
                resource_type="Example",
                expected_version=-1,
                values={"value": "updated"},
            )
        )


def test_cas_rejects_protected_column_mutation() -> None:
    with pytest.raises(
        ValueError,
        match="protected columns",
    ):
        asyncio.run(
            compare_and_swap(
                None,  # type: ignore[arg-type]
                table=versioned_table,
                tenant_id=UUID(int=1),
                resource_id=UUID(int=2),
                resource_type="Example",
                expected_version=0,
                values={
                    "version": 99,
                },
            )
        )


def test_cas_rejects_unknown_column() -> None:
    with pytest.raises(
        ValueError,
        match="unknown columns",
    ):
        asyncio.run(
            compare_and_swap(
                None,  # type: ignore[arg-type]
                table=versioned_table,
                tenant_id=UUID(int=1),
                resource_id=UUID(int=2),
                resource_type="Example",
                expected_version=0,
                values={
                    "does_not_exist": "value",
                },
            )
        )
