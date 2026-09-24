from core_platform.infrastructure.persistence.transaction_schema import (
    TRANSACTION_TENANT_SCOPED_TABLES,
    audit_record,
    idempotency_record,
    inbox_message,
    outbox_message,
)


def test_transaction_kernel_tenant_scoped_registry_is_explicit() -> None:
    assert set(TRANSACTION_TENANT_SCOPED_TABLES) == {
        "idempotency_record",
        "outbox_message",
        "inbox_message",
        "audit_record",
    }


def test_transaction_kernel_tables_match_registry() -> None:
    tables = {
        idempotency_record.name,
        outbox_message.name,
        inbox_message.name,
        audit_record.name,
    }

    assert tables == set(TRANSACTION_TENANT_SCOPED_TABLES)


def test_every_transaction_table_has_tenant_id() -> None:
    for table in (
        idempotency_record,
        outbox_message,
        inbox_message,
        audit_record,
    ):
        assert "tenant_id" in table.c
