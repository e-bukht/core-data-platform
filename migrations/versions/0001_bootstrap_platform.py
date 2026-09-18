"""Bootstrap platform schema.

Revision ID: 0001_bootstrap_platform
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001_bootstrap_platform"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")
    op.execute("COMMENT ON SCHEMA platform IS 'Core Data Model Platform application schema'")


def downgrade() -> None:
    # Intentionally conservative. Destructive production recovery must not depend on blind downgrade.
    pass
