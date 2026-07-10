"""phase 2 core schema

Revision ID: 202607100001
Revises: 202607090001
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607100001"
down_revision: str | None = "202607090001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def jsonb_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


environment_enum = postgresql.ENUM("production", "staging", "testing", "development", name="environment", create_type=False)
sync_status_enum = postgresql.ENUM(
    "synced",
    "pending",
    "failed",
    "retrying",
    "outdated",
    "mismatch",
    "requires_manual_resolution",
    name="syncstatus",
    create_type=False,
)
service_status_enum = postgresql.ENUM(
    "running",
    "paused",
    "disabled",
    "pending_sync",
    "product_mismatch",
    "failed_to_apply",
    name="servicestatus",
    create_type=False,
)
billing_mode_enum = postgresql.ENUM(
    "prepaid_credits",
    "postpaid_manual_settlement",
    "free_internal_testing",
    name="billingmode",
    create_type=False,
)
compatibility_status_enum = postgresql.ENUM(
    "compatible",
    "incompatible",
    "unknown",
    "requires_upgrade",
    name="compatibilitystatus",
    create_type=False,
)
billing_transaction_type_enum = postgresql.ENUM(
    "credit_grant",
    "credit_deduction",
    "manual_payment",
    "usage_charge",
    "adjustment",
    "correction",
    "reversal",
    name="billingtransactiontype",
    create_type=False,
)
failure_status_enum = postgresql.ENUM("open", "retrying", "resolved", "ignored", name="failurestatus", create_type=False)
product_confirmation_status_enum = postgresql.ENUM(
    "pending",
    "confirmed",
    "failed",
    "not_required",
    name="productconfirmationstatus",
    create_type=False,
)
pricing_created_by_enum = postgresql.ENUM("system", "admin", name="pricingcreatedby", create_type=False)
revenue_type_enum = postgresql.ENUM(
    "recognized",
    "collected",
    "outstanding",
    "adjustment",
    name="revenuetype",
    create_type=False,
)
revenue_source_enum = postgresql.ENUM(
    "billing_ledger",
    "manual_payment",
    "product_sync",
    "admin_adjustment",
    name="revenuesource",
    create_type=False,
)
mismatch_status_enum = postgresql.ENUM("matched", "mismatch", "pending_review", name="mismatchstatus", create_type=False)
idempotency_status_enum = postgresql.ENUM(
    "started",
    "completed",
    "failed",
    "expired",
    name="idempotencyrecordstatus",
    create_type=False,
)


PHASE_2_REQUIRED_ENUM_TYPES = (
    sync_status_enum,
    service_status_enum,
    billing_mode_enum,
    compatibility_status_enum,
    billing_transaction_type_enum,
    failure_status_enum,
    product_confirmation_status_enum,
    pricing_created_by_enum,
    revenue_type_enum,
    revenue_source_enum,
    mismatch_status_enum,
    idempotency_status_enum,
)

PHASE_2_OWNED_ENUM_TYPES = (
    compatibility_status_enum,
    billing_transaction_type_enum,
    product_confirmation_status_enum,
    pricing_created_by_enum,
    revenue_type_enum,
    revenue_source_enum,
    mismatch_status_enum,
    idempotency_status_enum,
)


def _dedupe_enums_by_name(enum_types):
    seen_names = set()
    unique_enum_types = []
    for enum_type in enum_types:
        if enum_type.name in seen_names:
            continue
        seen_names.add(enum_type.name)
        unique_enum_types.append(enum_type)
    return tuple(unique_enum_types)


PHASE_2_REQUIRED_ENUM_TYPES_BY_NAME = _dedupe_enums_by_name(PHASE_2_REQUIRED_ENUM_TYPES)
PHASE_2_OWNED_ENUM_TYPES_BY_NAME = _dedupe_enums_by_name(PHASE_2_OWNED_ENUM_TYPES)


def _create_postgresql_enums(bind) -> None:
    if bind.dialect.name != "postgresql":
        return

    for enum_type in PHASE_2_REQUIRED_ENUM_TYPES_BY_NAME:
        enum_type.create(bind, checkfirst=True)


def _drop_postgresql_enums(bind) -> None:
    if bind.dialect.name != "postgresql":
        return

    for enum_type in reversed(PHASE_2_OWNED_ENUM_TYPES_BY_NAME):
        enum_type.drop(bind, checkfirst=True)


def upgrade() -> None:
    bind = op.get_bind()
    _create_postgresql_enums(bind)

    op.add_column("product_deployments", sa.Column("supported_endpoints", jsonb_type(), nullable=True))
    op.add_column(
        "product_deployments",
        sa.Column("compatibility_status", compatibility_status_enum, server_default="unknown", nullable=False),
    )
    op.create_index("ix_product_deployments_health_status", "product_deployments", ["health_status"], unique=False)
    op.create_index("ix_product_deployments_sync_status", "product_deployments", ["sync_status"], unique=False)
    op.create_index("ix_product_deployments_active_status", "product_deployments", ["is_active"], unique=False)

    op.add_column(
        "organizations",
        sa.Column("service_enforcement_status", service_status_enum, server_default="pending_sync", nullable=False),
    )
    op.add_column("organizations", sa.Column("credit_balance", sa.Numeric(14, 2), server_default="0", nullable=False))
    op.add_column("organizations", sa.Column("outstanding_dues", sa.Numeric(14, 2), server_default="0", nullable=False))
    op.add_column("organizations", sa.Column("selected_ai_provider", sa.String(length=100), nullable=True))
    op.add_column("organizations", sa.Column("selected_ai_model", sa.String(length=150), nullable=True))
    op.create_index("ix_organizations_lifecycle_status", "organizations", ["lifecycle_status"], unique=False)
    op.create_index("ix_organizations_sync_status", "organizations", ["sync_status"], unique=False)
    op.create_index("ix_organizations_service_status", "organizations", ["service_status"], unique=False)
    op.create_index("ix_organizations_credit_status", "organizations", ["credit_status"], unique=False)

    op.create_index(
        "uq_active_product_org_mapping",
        "organization_mappings",
        ["product_deployment_id", "product_organization_id"],
        unique=True,
        postgresql_where=sa.text("mapping_status = 'active'"),
        sqlite_where=sa.text("mapping_status = 'active'"),
    )

    op.add_column("pending_product_changes", sa.Column("payload", jsonb_type(), nullable=True))
    op.create_index("ix_pending_changes_status_created", "pending_product_changes", ["status", "created_at"], unique=False)

    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"], unique=False)
    op.create_index("ix_failure_logs_status_created", "failure_logs", ["current_status", "created_at"], unique=False)

    op.create_table(
        "billing_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=True),
        sa.Column("product_name", sa.String(length=150), nullable=True),
        sa.Column("region", sa.String(length=80), nullable=True),
        sa.Column("environment", sa.String(length=50), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_plans_name", "billing_plans", ["name"], unique=False)
    op.create_index("ix_billing_plans_currency", "billing_plans", ["currency"], unique=False)
    op.create_index("ix_billing_plans_product_deployment_id", "billing_plans", ["product_deployment_id"], unique=False)
    op.create_index("ix_billing_plans_product_currency_active", "billing_plans", ["product_deployment_id", "currency", "is_active"], unique=False)

    op.create_table(
        "billing_plan_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("billing_plan_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("billing_mode_compatibility", billing_mode_enum, nullable=False),
        sa.Column("pricing_structure", jsonb_type(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("limits", jsonb_type(), nullable=True),
        sa.Column("included_tokens", sa.Integer(), nullable=False),
        sa.Column("included_leads", sa.Integer(), nullable=False),
        sa.Column("overage_pricing", jsonb_type(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("external_product_plan_id", sa.String(length=150), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["billing_plan_id"], ["billing_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_plan_versions_billing_plan_id", "billing_plan_versions", ["billing_plan_id"], unique=False)
    op.create_index("ix_billing_plan_versions_plan_active", "billing_plan_versions", ["billing_plan_id", "is_active"], unique=False)
    op.create_index("ix_billing_plan_versions_effective", "billing_plan_versions", ["effective_from", "effective_to"], unique=False)

    op.create_table(
        "organization_plan_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("billing_plan_id", sa.Uuid(), nullable=False),
        sa.Column("billing_plan_version_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["billing_plan_id"], ["billing_plans.id"]),
        sa.ForeignKeyConstraint(["billing_plan_version_id"], ["billing_plan_versions.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_plan_assignments_organization_id", "organization_plan_assignments", ["organization_id"], unique=False)
    op.create_index("ix_organization_plan_assignments_billing_plan_id", "organization_plan_assignments", ["billing_plan_id"], unique=False)
    op.create_index("ix_organization_plan_assignments_billing_plan_version_id", "organization_plan_assignments", ["billing_plan_version_id"], unique=False)
    op.create_index("ix_organization_plan_assignments_admin_id", "organization_plan_assignments", ["admin_id"], unique=False)
    op.create_index("ix_org_plan_assignments_org_active", "organization_plan_assignments", ["organization_id", "is_active"], unique=False)

    op.create_table(
        "billing_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("transaction_type", billing_transaction_type_enum, nullable=False),
        sa.Column("balance_before", sa.Numeric(14, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("outstanding_dues_before", sa.Numeric(14, 2), nullable=False),
        sa.Column("outstanding_dues_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("related_original_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("related_product_transaction_id", sa.String(length=150), nullable=True),
        sa.Column("product_sync_status", sync_status_enum, nullable=False),
        sa.Column("failure_status", failure_status_enum, nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.ForeignKeyConstraint(["related_original_transaction_id"], ["billing_ledger_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_ledger_entries_organization_id", "billing_ledger_entries", ["organization_id"], unique=False)
    op.create_index("ix_billing_ledger_entries_product_deployment_id", "billing_ledger_entries", ["product_deployment_id"], unique=False)
    op.create_index("ix_billing_ledger_entries_transaction_type", "billing_ledger_entries", ["transaction_type"], unique=False)
    op.create_index("ix_billing_ledger_entries_admin_id", "billing_ledger_entries", ["admin_id"], unique=False)
    op.create_index("ix_billing_ledger_entries_related_original_transaction_id", "billing_ledger_entries", ["related_original_transaction_id"], unique=False)
    op.create_index("ix_billing_ledger_org_created", "billing_ledger_entries", ["organization_id", "created_at"], unique=False)
    op.create_index("ix_billing_ledger_idempotency_key", "billing_ledger_entries", ["idempotency_key"], unique=True)

    op.create_table(
        "manual_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=100), nullable=True),
        sa.Column("payment_reference", sa.String(length=150), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("product_sync_status", sync_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_payments_organization_id", "manual_payments", ["organization_id"], unique=False)
    op.create_index("ix_manual_payments_product_deployment_id", "manual_payments", ["product_deployment_id"], unique=False)
    op.create_index("ix_manual_payments_admin_id", "manual_payments", ["admin_id"], unique=False)
    op.create_index("ix_manual_payments_idempotency_key", "manual_payments", ["idempotency_key"], unique=True)
    op.create_index("ix_manual_payments_org_date", "manual_payments", ["organization_id", "payment_date"], unique=False)

    op.create_table(
        "service_enforcement_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("service_status", service_status_enum, nullable=False),
        sa.Column("low_balance_warning_threshold", sa.Numeric(14, 2), nullable=True),
        sa.Column("hard_stop_threshold", sa.Numeric(14, 2), nullable=True),
        sa.Column("manual_continuation_override", sa.Boolean(), nullable=False),
        sa.Column("manual_override_reason", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("product_confirmation_status", product_confirmation_status_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_enforcement_rules_organization_id", "service_enforcement_rules", ["organization_id"], unique=False)
    op.create_index("ix_service_rules_org_active", "service_enforcement_rules", ["organization_id", "is_active"], unique=False)

    op.create_table(
        "ai_model_pricing_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=150), nullable=False),
        sa.Column("input_token_cost", sa.Numeric(18, 8), nullable=False),
        sa.Column("output_token_cost", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("pricing_source", sa.String(length=255), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", pricing_created_by_enum, nullable=False),
        sa.Column("audit_log_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["audit_log_id"], ["audit_logs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_model_pricing_versions_audit_log_id", "ai_model_pricing_versions", ["audit_log_id"], unique=False)
    op.create_index("ix_ai_pricing_provider_model_active", "ai_model_pricing_versions", ["provider", "model_name", "is_active"], unique=False)
    op.create_index("ix_ai_pricing_effective", "ai_model_pricing_versions", ["effective_from", "effective_to"], unique=False)

    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=150), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("pricing_version_id", sa.Uuid(), nullable=False),
        sa.Column("calculated_cost", sa.Numeric(14, 6), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("product_usage_id", sa.String(length=150), nullable=True),
        sa.Column("campaign_reference", sa.String(length=150), nullable=True),
        sa.Column("conversation_reference", sa.String(length=150), nullable=True),
        sa.Column("lead_reference", sa.String(length=150), nullable=True),
        sa.Column("sync_status", sync_status_enum, nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["pricing_version_id"], ["ai_model_pricing_versions.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_records_organization_id", "ai_usage_records", ["organization_id"], unique=False)
    op.create_index("ix_ai_usage_records_product_deployment_id", "ai_usage_records", ["product_deployment_id"], unique=False)
    op.create_index("ix_ai_usage_records_pricing_version_id", "ai_usage_records", ["pricing_version_id"], unique=False)
    op.create_index("ix_ai_usage_date_provider_model", "ai_usage_records", ["usage_date", "provider", "model_name"], unique=False)
    op.create_index("ix_ai_usage_org_date", "ai_usage_records", ["organization_id", "usage_date"], unique=False)

    op.create_table(
        "revenue_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("revenue_type", revenue_type_enum, nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("source", revenue_source_enum, nullable=False),
        sa.Column("revenue_date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(length=30), nullable=True),
        sa.Column("related_ledger_entry_id", sa.Uuid(), nullable=True),
        sa.Column("sync_status", sync_status_enum, nullable=False),
        sa.Column("mismatch_status", mismatch_status_enum, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.ForeignKeyConstraint(["related_ledger_entry_id"], ["billing_ledger_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revenue_records_organization_id", "revenue_records", ["organization_id"], unique=False)
    op.create_index("ix_revenue_records_product_deployment_id", "revenue_records", ["product_deployment_id"], unique=False)
    op.create_index("ix_revenue_records_related_ledger_entry_id", "revenue_records", ["related_ledger_entry_id"], unique=False)
    op.create_index("ix_revenue_date_currency", "revenue_records", ["revenue_date", "currency"], unique=False)
    op.create_index("ix_revenue_product_date", "revenue_records", ["product_deployment_id", "revenue_date"], unique=False)

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=150), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=True),
        sa.Column("response_json", jsonb_type(), nullable=True),
        sa.Column("status", idempotency_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_idempotency_records_admin_id", "idempotency_records", ["admin_id"], unique=False)
    op.create_index("ix_idempotency_records_organization_id", "idempotency_records", ["organization_id"], unique=False)
    op.create_index("ix_idempotency_records_key", "idempotency_records", ["idempotency_key"], unique=True)
    op.create_index("ix_idempotency_records_action_status", "idempotency_records", ["action_type", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("revenue_records")
    op.drop_table("ai_usage_records")
    op.drop_table("ai_model_pricing_versions")
    op.drop_table("service_enforcement_rules")
    op.drop_table("manual_payments")
    op.drop_table("billing_ledger_entries")
    op.drop_table("organization_plan_assignments")
    op.drop_table("billing_plan_versions")
    op.drop_table("billing_plans")

    op.drop_index("ix_failure_logs_status_created", table_name="failure_logs")
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_pending_changes_status_created", table_name="pending_product_changes")
    op.drop_column("pending_product_changes", "payload")
    op.drop_index("uq_active_product_org_mapping", table_name="organization_mappings")
    op.drop_index("ix_organizations_credit_status", table_name="organizations")
    op.drop_index("ix_organizations_service_status", table_name="organizations")
    op.drop_index("ix_organizations_sync_status", table_name="organizations")
    op.drop_index("ix_organizations_lifecycle_status", table_name="organizations")
    op.drop_column("organizations", "selected_ai_model")
    op.drop_column("organizations", "selected_ai_provider")
    op.drop_column("organizations", "outstanding_dues")
    op.drop_column("organizations", "credit_balance")
    op.drop_column("organizations", "service_enforcement_status")
    op.drop_index("ix_product_deployments_active_status", table_name="product_deployments")
    op.drop_index("ix_product_deployments_sync_status", table_name="product_deployments")
    op.drop_index("ix_product_deployments_health_status", table_name="product_deployments")
    op.drop_column("product_deployments", "compatibility_status")
    op.drop_column("product_deployments", "supported_endpoints")

    bind = op.get_bind()
    _drop_postgresql_enums(bind)
