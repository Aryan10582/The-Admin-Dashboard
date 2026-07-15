"""phase 9a.2 pricing checks

Revision ID: 202607100010
Revises: 202607100009
Create Date: 2026-07-14 22:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202607100010"
down_revision = "202607100009"
branch_labels = None
depends_on = None


check_status_values = (
    "running",
    "unchanged",
    "version_created",
    "requires_manual_review",
    "unsupported",
    "source_unavailable",
    "invalid_response",
    "failed",
    "approved",
    "rejected",
)
review_decision_values = ("approved", "rejected")

check_status_enum = sa.Enum(*check_status_values, name="aipricecheckstatus")
review_decision_enum = sa.Enum(*review_decision_values, name="aipricereviewdecision")


def _column_enum(bind, values: tuple[str, ...], name: str) -> sa.Enum:
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        check_status_enum.create(bind, checkfirst=True)
        review_decision_enum.create(bind, checkfirst=True)
    check_status_column_enum = _column_enum(bind, check_status_values, "aipricecheckstatus")
    review_decision_column_enum = _column_enum(bind, review_decision_values, "aipricereviewdecision")

    op.add_column("ai_model_pricing_versions", sa.Column("source_fingerprint", sa.String(length=128), nullable=True))
    op.create_index("ix_ai_pricing_source_fingerprint", "ai_model_pricing_versions", ["pricing_catalog_id", "source_fingerprint"], unique=True)

    op.create_table(
        "ai_price_check_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pricing_catalog_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("pricing_scope_code", sa.String(length=120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("source_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", check_status_column_enum, nullable=False),
        sa.Column("candidate_input_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("candidate_output_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("candidate_currency", sa.String(length=3), nullable=True),
        sa.Column("candidate_pricing_unit_tokens", sa.Integer(), nullable=True),
        sa.Column("candidate_provider_model_id", sa.String(length=150), nullable=True),
        sa.Column("safe_error", sa.Text(), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_decision", review_decision_column_enum, nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_version_id"], ["ai_model_pricing_versions.id"]),
        sa.ForeignKeyConstraint(["pricing_catalog_id"], ["ai_model_pricing_catalogs.id"]),
        sa.ForeignKeyConstraint(["requested_by_admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_admin_id"], ["admins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_price_check_runs_catalog_status", "ai_price_check_runs", ["pricing_catalog_id", "status"], unique=False)
    op.create_index("ix_ai_price_check_runs_created_version_id", "ai_price_check_runs", ["created_version_id"], unique=False)
    op.create_index("ix_ai_price_check_runs_pricing_catalog_id", "ai_price_check_runs", ["pricing_catalog_id"], unique=False)
    op.create_index("ix_ai_price_check_runs_provider_scope", "ai_price_check_runs", ["provider", "pricing_scope_code"], unique=False)
    op.create_index("ix_ai_price_check_runs_request_idempotency_key", "ai_price_check_runs", ["request_idempotency_key"], unique=False)
    op.create_index("ix_ai_price_check_runs_requested_by_admin_id", "ai_price_check_runs", ["requested_by_admin_id"], unique=False)
    op.create_index("ix_ai_price_check_runs_review", "ai_price_check_runs", ["review_decision", "reviewed_at"], unique=False)
    op.create_index("ix_ai_price_check_runs_reviewed_by_admin_id", "ai_price_check_runs", ["reviewed_by_admin_id"], unique=False)
    op.create_index("ix_ai_price_check_runs_source_fingerprint", "ai_price_check_runs", ["source_fingerprint"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_ai_price_check_runs_source_fingerprint", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_reviewed_by_admin_id", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_review", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_requested_by_admin_id", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_request_idempotency_key", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_provider_scope", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_pricing_catalog_id", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_created_version_id", table_name="ai_price_check_runs")
    op.drop_index("ix_ai_price_check_runs_catalog_status", table_name="ai_price_check_runs")
    op.drop_table("ai_price_check_runs")
    op.drop_index("ix_ai_pricing_source_fingerprint", table_name="ai_model_pricing_versions")
    op.drop_column("ai_model_pricing_versions", "source_fingerprint")
    if bind.dialect.name == "postgresql":
        review_decision_enum.drop(bind, checkfirst=True)
        check_status_enum.drop(bind, checkfirst=True)
