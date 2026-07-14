"""phase 3 product connections

Revision ID: 202607100002
Revises: 202607100001
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607100002"
down_revision: str | None = "202607100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_deployments", sa.Column("admin_api_secret", sa.Text(), nullable=True))
    op.add_column("product_deployments", sa.Column("last_successful_health_check_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("product_deployments", sa.Column("last_health_response_time_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("product_deployments", "last_health_response_time_ms")
    op.drop_column("product_deployments", "last_successful_health_check_at")
    op.drop_column("product_deployments", "admin_api_secret")
