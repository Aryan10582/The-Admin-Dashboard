"""phase 9b.2 ai usage resolution review

Revision ID: 202607100012
Revises: 202607100011
Create Date: 2026-07-15 09:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202607100012"
down_revision = "202607100011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_usage_records", sa.Column("conflict_reviewed_by_admin_id", sa.Uuid(), nullable=True))
    op.add_column("ai_usage_records", sa.Column("conflict_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_usage_records", sa.Column("conflict_review_note", sa.Text(), nullable=True))
    op.create_index("ix_ai_usage_records_conflict_reviewed_by_admin_id", "ai_usage_records", ["conflict_reviewed_by_admin_id"])
    op.create_foreign_key(
        "fk_ai_usage_records_conflict_reviewed_by_admin_id",
        "ai_usage_records",
        "admins",
        ["conflict_reviewed_by_admin_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_ai_usage_records_conflict_reviewed_by_admin_id", "ai_usage_records", type_="foreignkey")
    op.drop_index("ix_ai_usage_records_conflict_reviewed_by_admin_id", table_name="ai_usage_records")
    op.drop_column("ai_usage_records", "conflict_review_note")
    op.drop_column("ai_usage_records", "conflict_reviewed_at")
    op.drop_column("ai_usage_records", "conflict_reviewed_by_admin_id")
