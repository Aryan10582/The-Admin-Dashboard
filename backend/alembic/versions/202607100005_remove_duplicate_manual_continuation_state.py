"""remove duplicate manual continuation state

Revision ID: 202607100005
Revises: 202607100004
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607100005"
down_revision: str | None = "202607100004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("organizations", "manual_continuation_reason")
    op.drop_column("organizations", "manual_continuation_enabled")


def downgrade() -> None:
    op.add_column("organizations", sa.Column("manual_continuation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("organizations", sa.Column("manual_continuation_reason", sa.Text(), nullable=True))
    op.alter_column("organizations", "manual_continuation_enabled", server_default=None)
