"""encrypt product secrets

Revision ID: 202607100003
Revises: 202607100002
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607100003"
down_revision: str | None = "202607100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_deployments", sa.Column("admin_api_secret_encrypted", sa.Text(), nullable=True))
    op.drop_column("product_deployments", "admin_api_secret")


def downgrade() -> None:
    op.add_column("product_deployments", sa.Column("admin_api_secret", sa.Text(), nullable=True))
    op.drop_column("product_deployments", "admin_api_secret_encrypted")
