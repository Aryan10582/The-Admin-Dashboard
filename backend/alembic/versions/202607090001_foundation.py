"""foundation

Revision ID: 202607090001
Revises:
Create Date: 2026-07-09 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607090001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admins_email"), "admins", ["email"], unique=True)
    op.create_index(op.f("ix_admins_username"), "admins", ["username"], unique=True)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("session_token_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_sessions_admin_id"), "admin_sessions", ["admin_id"], unique=False)

    op.create_table(
        "product_deployments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(length=150), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=False),
        sa.Column("environment", sa.Enum("production", "staging", "testing", "development", name="environment"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("api_base_url", sa.String(length=500), nullable=False),
        sa.Column("health_check_url", sa.String(length=500), nullable=True),
        sa.Column("admin_api_version", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_under_maintenance", sa.Boolean(), nullable=False),
        sa.Column(
            "health_status",
            sa.Enum("healthy", "down", "slow", "under_maintenance", "not_responding", name="producthealthstatus"),
            nullable=False,
        ),
        sa.Column(
            "sync_status",
            sa.Enum("synced", "pending", "failed", "retrying", "outdated", "mismatch", "requires_manual_resolution", name="syncstatus"),
            nullable=False,
        ),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_product_deployments_environment"), "product_deployments", ["environment"], unique=False)
    op.create_index(op.f("ix_product_deployments_product_name"), "product_deployments", ["product_name"], unique=False)
    op.create_index(op.f("ix_product_deployments_region"), "product_deployments", ["region"], unique=False)

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("central_organization_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "lifecycle_status",
            sa.Enum("active", "trial", "suspended", "churned", "internal_testing", "demo", name="organizationlifecyclestatus"),
            nullable=False,
        ),
        sa.Column(
            "billing_mode",
            sa.Enum("prepaid_credits", "postpaid_manual_settlement", "free_internal_testing", name="billingmode"),
            nullable=False,
        ),
        sa.Column(
            "billing_calculation_status",
            sa.Enum("active", "paused", "usage_tracking_only", "disabled", name="billingcalculationstatus"),
            nullable=False,
        ),
        sa.Column(
            "credit_status",
            sa.Enum("healthy_balance", "low_balance", "zero_balance", "balance_exhausted", "outstanding_dues", "not_applicable", name="creditstatus"),
            nullable=False,
        ),
        sa.Column(
            "service_status",
            sa.Enum("running", "paused", "disabled", "pending_sync", "product_mismatch", "failed_to_apply", name="servicestatus"),
            nullable=False,
        ),
        sa.Column("sync_status", sa.Enum("synced", "pending", "failed", "retrying", "outdated", "mismatch", "requires_manual_resolution", name="syncstatus"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_central_organization_id"), "organizations", ["central_organization_id"], unique=True)
    op.create_index(op.f("ix_organizations_name"), "organizations", ["name"], unique=False)
    op.create_index(op.f("ix_organizations_product_deployment_id"), "organizations", ["product_deployment_id"], unique=False)

    op.create_table(
        "organization_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column("product_organization_id", sa.String(length=150), nullable=True),
        sa.Column("product_api_version", sa.String(length=50), nullable=False),
        sa.Column("external_billing_id", sa.String(length=150), nullable=True),
        sa.Column("external_customer_id", sa.String(length=150), nullable=True),
        sa.Column("external_plan_id", sa.String(length=150), nullable=True),
        sa.Column("external_subscription_id", sa.String(length=150), nullable=True),
        sa.Column(
            "mapping_status",
            sa.Enum("active", "inactive", "missing_product_id", "product_mismatch", "verification_failed", "requires_manual_review", name="mappingstatus"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organization_mappings_organization_id"), "organization_mappings", ["organization_id"], unique=False)
    op.create_index(op.f("ix_organization_mappings_product_deployment_id"), "organization_mappings", ["product_deployment_id"], unique=False)
    op.create_index(op.f("ix_organization_mappings_product_organization_id"), "organization_mappings", ["product_organization_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=150), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("result_status", sa.Enum("success", "failure", name="auditresultstatus"), nullable=False),
        sa.Column("sync_status", sa.Enum("synced", "pending", "failed", "retrying", "outdated", "mismatch", "requires_manual_resolution", name="syncstatus"), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_admin_id"), "audit_logs", ["admin_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_idempotency_key"), "audit_logs", ["idempotency_key"], unique=False)
    op.create_index(op.f("ix_audit_logs_organization_id"), "audit_logs", ["organization_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_product_deployment_id"), "audit_logs", ["product_deployment_id"], unique=False)

    op.create_table(
        "pending_product_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=150), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("saved", "sent_to_product", "accepted_by_product", "confirmed_and_synced", "failed", "pending_retry", "cancelled", "requires_manual_resolution", name="pendingchangestatus"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_product_changes_action"), "pending_product_changes", ["action"], unique=False)
    op.create_index(op.f("ix_pending_product_changes_admin_id"), "pending_product_changes", ["admin_id"], unique=False)
    op.create_index(op.f("ix_pending_product_changes_idempotency_key"), "pending_product_changes", ["idempotency_key"], unique=False)
    op.create_index(op.f("ix_pending_product_changes_organization_id"), "pending_product_changes", ["organization_id"], unique=False)
    op.create_index(op.f("ix_pending_product_changes_product_deployment_id"), "pending_product_changes", ["product_deployment_id"], unique=False)

    op.create_table(
        "failure_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_deployment_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("action_attempted", sa.String(length=150), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("current_status", sa.Enum("open", "retrying", "resolved", "ignored", name="failurestatus"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("product_api_version", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_deployment_id"], ["product_deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_failure_logs_action_attempted"), "failure_logs", ["action_attempted"], unique=False)
    op.create_index(op.f("ix_failure_logs_admin_id"), "failure_logs", ["admin_id"], unique=False)
    op.create_index(op.f("ix_failure_logs_idempotency_key"), "failure_logs", ["idempotency_key"], unique=False)
    op.create_index(op.f("ix_failure_logs_organization_id"), "failure_logs", ["organization_id"], unique=False)
    op.create_index(op.f("ix_failure_logs_product_deployment_id"), "failure_logs", ["product_deployment_id"], unique=False)


def downgrade() -> None:
    op.drop_table("failure_logs")
    op.drop_table("pending_product_changes")
    op.drop_table("audit_logs")
    op.drop_table("organization_mappings")
    op.drop_table("organizations")
    op.drop_table("product_deployments")
    op.drop_table("admin_sessions")
    op.drop_table("admins")
