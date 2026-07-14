"""phase 7 delivery metadata

Revision ID: 202607100006
Revises: 202607100005
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607100006"
down_revision: str | None = "202607100005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pending_product_changes", sa.Column("delivery_attempt_id", sa.String(length=100), nullable=True))
    op.add_column("pending_product_changes", sa.Column("delivery_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pending_product_changes", sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pending_product_changes", sa.Column("product_request_id", sa.String(length=150), nullable=True))
    op.add_column("pending_product_changes", sa.Column("product_api_version", sa.String(length=50), nullable=True))
    op.add_column("pending_product_changes", sa.Column("safe_confirmation_summary", sa.JSON(), nullable=True))
    op.create_index("ix_pending_product_changes_delivery_attempt_id", "pending_product_changes", ["delivery_attempt_id"], unique=False)
    op.add_column("failure_logs", sa.Column("pending_change_id", sa.Uuid(), nullable=True))
    op.add_column("failure_logs", sa.Column("product_request_id", sa.String(length=150), nullable=True))
    op.create_index("ix_failure_logs_pending_change_id", "failure_logs", ["pending_change_id"], unique=False)
    op.create_foreign_key("fk_failure_logs_pending_change_id", "failure_logs", "pending_product_changes", ["pending_change_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_failure_logs_pending_change_id", "failure_logs", type_="foreignkey")
    op.drop_index("ix_failure_logs_pending_change_id", table_name="failure_logs")
    op.drop_column("failure_logs", "product_request_id")
    op.drop_column("failure_logs", "pending_change_id")
    op.drop_index("ix_pending_product_changes_delivery_attempt_id", table_name="pending_product_changes")
    op.drop_column("pending_product_changes", "safe_confirmation_summary")
    op.drop_column("pending_product_changes", "product_api_version")
    op.drop_column("pending_product_changes", "product_request_id")
    op.drop_column("pending_product_changes", "last_delivery_at")
    op.drop_column("pending_product_changes", "delivery_started_at")
    op.drop_column("pending_product_changes", "delivery_attempt_id")
