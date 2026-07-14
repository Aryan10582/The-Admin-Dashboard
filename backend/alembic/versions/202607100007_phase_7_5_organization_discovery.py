"""phase 7.5 organization discovery

Revision ID: 202607100007
Revises: 202607100006
Create Date: 2026-07-14 15:30:00.000000
"""

from collections import OrderedDict

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202607100007"
down_revision = "202607100006"
branch_labels = None
depends_on = None


organization_discovery_status = postgresql.ENUM(
    "discovered",
    "already_mapped",
    "imported",
    "ignored",
    "conflict",
    "missing_required_data",
    "requires_manual_review",
    "no_longer_returned",
    name="organizationdiscoverystatus",
    create_type=False,
)
organization_lifecycle_status = postgresql.ENUM(
    "active",
    "trial",
    "suspended",
    "churned",
    "internal_testing",
    "demo",
    name="organizationlifecyclestatus",
    create_type=False,
)
billing_mode = postgresql.ENUM(
    "prepaid_credits",
    "postpaid_manual_settlement",
    "free_internal_testing",
    name="billingmode",
    create_type=False,
)
billing_calculation_status = postgresql.ENUM(
    "active",
    "paused",
    "usage_tracking_only",
    "disabled",
    name="billingcalculationstatus",
    create_type=False,
)
credit_status = postgresql.ENUM(
    "healthy_balance",
    "low_balance",
    "zero_balance",
    "balance_exhausted",
    "outstanding_dues",
    "not_applicable",
    name="creditstatus",
    create_type=False,
)
service_status = postgresql.ENUM(
    "running",
    "paused",
    "disabled",
    "pending_sync",
    "product_mismatch",
    "failed_to_apply",
    name="servicestatus",
    create_type=False,
)


def _enum_types() -> list[postgresql.ENUM]:
    by_name = OrderedDict()
    for enum_type in (
        organization_discovery_status,
        organization_lifecycle_status,
        billing_mode,
        billing_calculation_status,
        credit_status,
        service_status,
    ):
        by_name[enum_type.name] = enum_type
    return list(by_name.values())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_type in _enum_types():
            enum_type.create(bind, checkfirst=True)

    op.add_column("product_deployments", sa.Column("organization_list_path", sa.String(length=300), nullable=True))
    op.add_column("product_deployments", sa.Column("organization_detail_path_template", sa.String(length=300), nullable=True))
    op.add_column("product_deployments", sa.Column("last_organization_discovery_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("product_deployments", sa.Column("last_successful_organization_discovery_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("product_deployments", sa.Column("last_organization_discovery_error", sa.Text(), nullable=True))

    op.create_table(
        "product_organization_discoveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("product_organization_id", sa.String(length=150), nullable=False),
        sa.Column("organization_name", sa.String(length=255), nullable=False),
        sa.Column("lifecycle_status_snapshot", organization_lifecycle_status, nullable=True),
        sa.Column("billing_mode_snapshot", billing_mode, nullable=True),
        sa.Column("billing_calculation_status_snapshot", billing_calculation_status, nullable=True),
        sa.Column("currency_snapshot", sa.String(length=3), nullable=True),
        sa.Column("credit_status_snapshot", credit_status, nullable=True),
        sa.Column("credit_balance_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("outstanding_dues_snapshot", sa.Numeric(14, 2), nullable=True),
        sa.Column("service_status_snapshot", service_status, nullable=True),
        sa.Column("product_active_status", sa.Boolean(), nullable=True),
        sa.Column("product_api_version", sa.String(length=50), nullable=True),
        sa.Column("product_request_id", sa.String(length=150), nullable=True),
        sa.Column("product_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovery_status", organization_discovery_status, nullable=False),
        sa.Column("central_organization_id", sa.Uuid(), nullable=True),
        sa.Column("safe_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["central_organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_org_discovery_central_org", "product_organization_discoveries", ["central_organization_id"])
    op.create_index("ix_product_org_discovery_deployment_external_id", "product_organization_discoveries", ["product_deployment_id", "product_organization_id"], unique=True)
    op.create_index("ix_product_org_discovery_last_seen", "product_organization_discoveries", ["last_seen_at"])
    op.create_index("ix_product_org_discovery_status", "product_organization_discoveries", ["discovery_status"])
    op.create_index("ix_product_organization_discoveries_product_deployment_id", "product_organization_discoveries", ["product_deployment_id"])

    op.create_index(
        "ix_organization_mappings_deployment_product_org_unique",
        "organization_mappings",
        ["product_deployment_id", "product_organization_id"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_organization_mappings_deployment_product_org_unique", table_name="organization_mappings")
    op.drop_index("ix_product_organization_discoveries_product_deployment_id", table_name="product_organization_discoveries")
    op.drop_index("ix_product_org_discovery_status", table_name="product_organization_discoveries")
    op.drop_index("ix_product_org_discovery_last_seen", table_name="product_organization_discoveries")
    op.drop_index("ix_product_org_discovery_deployment_external_id", table_name="product_organization_discoveries")
    op.drop_index("ix_product_org_discovery_central_org", table_name="product_organization_discoveries")
    op.drop_table("product_organization_discoveries")
    op.drop_column("product_deployments", "last_organization_discovery_error")
    op.drop_column("product_deployments", "last_successful_organization_discovery_at")
    op.drop_column("product_deployments", "last_organization_discovery_attempt_at")
    op.drop_column("product_deployments", "organization_detail_path_template")
    op.drop_column("product_deployments", "organization_list_path")
    if bind.dialect.name == "postgresql":
        organization_discovery_status.drop(bind, checkfirst=True)
