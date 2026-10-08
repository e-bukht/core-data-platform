"""Register the break-glass management capability.

Revision ID: 0006_bg_manage_capability
Revises: 0005_break_glass
"""

from __future__ import annotations

from alembic import op

revision = "0006_bg_manage_capability"
down_revision = "0005_break_glass"
branch_labels = None
depends_on = None

BREAK_GLASS_MANAGEMENT_CAPABILITY_ID = "00000000-0000-7000-8000-000000000105"
BREAK_GLASS_MANAGEMENT_CAPABILITY = "platform.break-glass.manage"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO platform.capability (
            id,
            code,
            description,
            risk_class,
            status
        )
        VALUES (
            '{BREAK_GLASS_MANAGEMENT_CAPABILITY_ID}'::uuid,
            '{BREAK_GLASS_MANAGEMENT_CAPABILITY}',
            'Manage tenant-scoped break-glass grants',
            'CRITICAL',
            'ACTIVE'
        )
        ON CONFLICT (code) DO UPDATE
        SET
            description = EXCLUDED.description,
            risk_class = EXCLUDED.risk_class,
            status = EXCLUDED.status
        """
    )


def downgrade() -> None:
    # P0 follows expand/migrate/contract.
    # Destructive downgrade is intentionally not automated.
    pass
