from core_platform.infrastructure.persistence.context_trust_schema import TENANT_SCOPED_TABLES


def test_tenant_scoped_table_registry_is_explicit() -> None:
    assert set(TENANT_SCOPED_TABLES) == {"tenant_membership", "capability_grant"}
