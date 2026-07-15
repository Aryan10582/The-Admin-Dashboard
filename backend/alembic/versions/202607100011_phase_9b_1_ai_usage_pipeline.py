"""phase 9b.1 ai usage pipeline

Revision ID: 202607100011
Revises: 202607100010
Create Date: 2026-07-14 23:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202607100011"
down_revision = "202607100010"
branch_labels = None
depends_on = None


finalization_enum = sa.Enum("finalized", "non_final", "invalid", name="aiusagefinalizationstatus")
pricing_resolution_enum = sa.Enum("resolved", "requires_pricing_resolution", "unsupported_dimensions", name="aiusagepricingresolutionstatus")
mapping_resolution_enum = sa.Enum("resolved", "requires_mapping_resolution", name="aiusagemappingresolutionstatus")
conflict_enum = sa.Enum("none", "conflict", name="aiusageconflictstatus")
sync_run_enum = sa.Enum("success", "partial_success", "failed", name="aiusagesyncrunstatus")

FINALIZATION_VALUES = ("finalized", "non_final", "invalid")
PRICING_RESOLUTION_VALUES = ("resolved", "requires_pricing_resolution", "unsupported_dimensions")
MAPPING_RESOLUTION_VALUES = ("resolved", "requires_mapping_resolution")
CONFLICT_VALUES = ("none", "conflict")
SYNC_RUN_VALUES = ("success", "partial_success", "failed")


def _create_enums(bind) -> None:
    if bind.dialect.name == "postgresql":
        for enum in (finalization_enum, pricing_resolution_enum, mapping_resolution_enum, conflict_enum, sync_run_enum):
            enum.create(bind, checkfirst=True)


def _drop_enums(bind) -> None:
    if bind.dialect.name == "postgresql":
        for enum in (sync_run_enum, conflict_enum, mapping_resolution_enum, pricing_resolution_enum, finalization_enum):
            enum.drop(bind, checkfirst=True)


def _enum_for_column(bind, values: tuple[str, ...], name: str):
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    _create_enums(bind)
    finalization_column_enum = _enum_for_column(bind, FINALIZATION_VALUES, "aiusagefinalizationstatus")
    pricing_resolution_column_enum = _enum_for_column(bind, PRICING_RESOLUTION_VALUES, "aiusagepricingresolutionstatus")
    mapping_resolution_column_enum = _enum_for_column(bind, MAPPING_RESOLUTION_VALUES, "aiusagemappingresolutionstatus")
    conflict_column_enum = _enum_for_column(bind, CONFLICT_VALUES, "aiusageconflictstatus")
    sync_run_column_enum = _enum_for_column(bind, SYNC_RUN_VALUES, "aiusagesyncrunstatus")

    op.add_column("product_deployments", sa.Column("token_usage_list_path", sa.String(length=300), nullable=True))
    op.add_column("product_deployments", sa.Column("last_usage_sync_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("product_deployments", sa.Column("last_successful_usage_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("product_deployments", sa.Column("last_usage_sync_error", sa.Text(), nullable=True))

    op.create_table(
        "product_ai_model_pricing_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("product_provider", sa.String(length=100), nullable=False),
        sa.Column("product_model_id", sa.String(length=150), nullable=False),
        sa.Column("pricing_catalog_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["pricing_catalog_id"], ["ai_model_pricing_catalogs.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_deployment_id", "product_provider", "product_model_id", name="uq_product_ai_model_pricing_mapping_identity"),
    )
    op.create_index("ix_product_ai_model_pricing_mappings_active", "product_ai_model_pricing_mappings", ["is_active"])
    op.create_index("ix_product_ai_model_pricing_mappings_catalog", "product_ai_model_pricing_mappings", ["pricing_catalog_id"])
    op.create_index("ix_product_ai_model_pricing_mappings_product", "product_ai_model_pricing_mappings", ["product_deployment_id"])
    op.create_index("ix_product_ai_model_pricing_mappings_created_by_admin_id", "product_ai_model_pricing_mappings", ["created_by_admin_id"])

    for column_name in ("organization_id", "pricing_version_id", "calculated_cost"):
        op.alter_column("ai_usage_records", column_name, existing_type=sa.Uuid() if column_name != "calculated_cost" else sa.Numeric(14, 6), nullable=True)
    op.add_column("ai_usage_records", sa.Column("product_organization_id", sa.String(length=150), nullable=True))
    op.add_column("ai_usage_records", sa.Column("product_model_id", sa.String(length=150), nullable=True))
    op.add_column("ai_usage_records", sa.Column("pricing_mapping_id", sa.Uuid(), nullable=True))
    op.add_column("ai_usage_records", sa.Column("pricing_catalog_id", sa.Uuid(), nullable=True))
    op.add_column("ai_usage_records", sa.Column("pricing_unit_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_usage_records", sa.Column("input_token_price", sa.Numeric(18, 8), nullable=True))
    op.add_column("ai_usage_records", sa.Column("output_token_price", sa.Numeric(18, 8), nullable=True))
    op.add_column("ai_usage_records", sa.Column("cost_currency", sa.String(length=3), nullable=True))
    op.add_column("ai_usage_records", sa.Column("input_cost", sa.Numeric(20, 10), nullable=True))
    op.add_column("ai_usage_records", sa.Column("output_cost", sa.Numeric(20, 10), nullable=True))
    op.add_column("ai_usage_records", sa.Column("total_cost", sa.Numeric(20, 10), nullable=True))
    op.add_column("ai_usage_records", sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_usage_records", sa.Column("usage_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_usage_records", sa.Column("usage_revision", sa.String(length=80), nullable=True))
    op.add_column("ai_usage_records", sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("ai_usage_records", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_usage_records", sa.Column("finalization_status", finalization_column_enum, nullable=False, server_default="finalized"))
    op.add_column("ai_usage_records", sa.Column("pricing_resolution_status", pricing_resolution_column_enum, nullable=False, server_default="requires_pricing_resolution"))
    op.add_column("ai_usage_records", sa.Column("mapping_resolution_status", mapping_resolution_column_enum, nullable=False, server_default="requires_mapping_resolution"))
    op.add_column("ai_usage_records", sa.Column("conflict_status", conflict_column_enum, nullable=False, server_default="none"))
    op.add_column("ai_usage_records", sa.Column("invalid_reason", sa.Text(), nullable=True))
    op.add_column("ai_usage_records", sa.Column("conflict_snapshot", sa.JSON(), nullable=True))
    op.add_column("ai_usage_records", sa.Column("request_reference", sa.String(length=150), nullable=True))
    op.create_foreign_key("fk_ai_usage_records_pricing_mapping_id", "ai_usage_records", "product_ai_model_pricing_mappings", ["pricing_mapping_id"], ["id"])
    op.create_foreign_key("fk_ai_usage_records_pricing_catalog_id", "ai_usage_records", "ai_model_pricing_catalogs", ["pricing_catalog_id"], ["id"])
    op.create_index("ix_ai_usage_deployment_usage_id", "ai_usage_records", ["product_deployment_id", "product_usage_id"], unique=True)
    op.create_index("ix_ai_usage_usage_at", "ai_usage_records", ["usage_at"])
    op.create_index("ix_ai_usage_product_org_id", "ai_usage_records", ["product_organization_id"])
    op.create_index("ix_ai_usage_pricing_catalog", "ai_usage_records", ["pricing_catalog_id"])
    op.create_index("ix_ai_usage_resolution_statuses", "ai_usage_records", ["pricing_resolution_status", "mapping_resolution_status", "conflict_status"])

    op.create_table(
        "ai_usage_sync_states",
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("last_committed_cursor", sa.String(length=500), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("product_deployment_id"),
    )
    op.create_table(
        "ai_usage_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("starting_cursor", sa.String(length=500), nullable=True),
        sa.Column("ending_cursor", sa.String(length=500), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("finalized_cost_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_pricing_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_mapping_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("safe_failure_count", sa.Integer(), nullable=False),
        sa.Column("status", sync_run_column_enum, nullable=False),
        sa.Column("safe_error", sa.Text(), nullable=True),
        sa.Column("requested_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.ForeignKeyConstraint(["requested_by_admin_id"], ["admins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_sync_runs_product", "ai_usage_sync_runs", ["product_deployment_id", "started_at"])
    op.create_index("ix_ai_usage_sync_runs_status", "ai_usage_sync_runs", ["status"])
    op.create_index("ix_ai_usage_sync_runs_requested_by_admin_id", "ai_usage_sync_runs", ["requested_by_admin_id"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_ai_usage_sync_runs_requested_by_admin_id", table_name="ai_usage_sync_runs")
    op.drop_index("ix_ai_usage_sync_runs_status", table_name="ai_usage_sync_runs")
    op.drop_index("ix_ai_usage_sync_runs_product", table_name="ai_usage_sync_runs")
    op.drop_table("ai_usage_sync_runs")
    op.drop_table("ai_usage_sync_states")
    op.drop_index("ix_ai_usage_resolution_statuses", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_pricing_catalog", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_product_org_id", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_usage_at", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_deployment_usage_id", table_name="ai_usage_records")
    op.drop_constraint("fk_ai_usage_records_pricing_catalog_id", "ai_usage_records", type_="foreignkey")
    op.drop_constraint("fk_ai_usage_records_pricing_mapping_id", "ai_usage_records", type_="foreignkey")
    for column in (
        "request_reference",
        "conflict_snapshot",
        "invalid_reason",
        "conflict_status",
        "mapping_resolution_status",
        "pricing_resolution_status",
        "finalization_status",
        "finalized_at",
        "is_final",
        "usage_revision",
        "usage_at",
        "calculated_at",
        "total_cost",
        "output_cost",
        "input_cost",
        "cost_currency",
        "output_token_price",
        "input_token_price",
        "pricing_unit_tokens",
        "pricing_catalog_id",
        "pricing_mapping_id",
        "product_model_id",
        "product_organization_id",
    ):
        op.drop_column("ai_usage_records", column)
    op.drop_index("ix_product_ai_model_pricing_mappings_created_by_admin_id", table_name="product_ai_model_pricing_mappings")
    op.drop_index("ix_product_ai_model_pricing_mappings_product", table_name="product_ai_model_pricing_mappings")
    op.drop_index("ix_product_ai_model_pricing_mappings_catalog", table_name="product_ai_model_pricing_mappings")
    op.drop_index("ix_product_ai_model_pricing_mappings_active", table_name="product_ai_model_pricing_mappings")
    op.drop_table("product_ai_model_pricing_mappings")
    for column in ("last_usage_sync_error", "last_successful_usage_sync_at", "last_usage_sync_attempt_at", "token_usage_list_path"):
        op.drop_column("product_deployments", column)
    _drop_enums(bind)
