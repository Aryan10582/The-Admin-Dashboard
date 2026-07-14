"""phase 8 billing plans

Revision ID: 202607100008
Revises: 202607100007
Create Date: 2026-07-14 18:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202607100008"
down_revision = "202607100007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_plans", sa.Column("plan_code", sa.String(length=120), nullable=True))
    op.add_column("billing_plans", sa.Column("description", sa.Text(), nullable=True))
    op.execute("UPDATE billing_plans SET plan_code = 'legacy_' || replace(CAST(id AS VARCHAR), '-', '_') WHERE plan_code IS NULL")
    op.create_index("ix_billing_plans_plan_code", "billing_plans", ["plan_code"], unique=False)
    op.create_unique_constraint("uq_billing_plans_deployment_plan_code", "billing_plans", ["product_deployment_id", "plan_code"])

    op.add_column("billing_plan_versions", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column("billing_plan_versions", sa.Column("created_by_admin_id", sa.Uuid(), nullable=True))
    op.add_column("billing_plan_versions", sa.Column("note", sa.Text(), nullable=True))
    op.execute(
        "UPDATE billing_plan_versions SET currency = "
        "(SELECT currency FROM billing_plans WHERE billing_plans.id = billing_plan_versions.billing_plan_id) "
        "WHERE currency IS NULL"
    )
    op.create_foreign_key("fk_billing_plan_versions_created_by_admin_id", "billing_plan_versions", "admins", ["created_by_admin_id"], ["id"])
    op.create_index("ix_billing_plan_versions_created_by_admin_id", "billing_plan_versions", ["created_by_admin_id"], unique=False)
    op.create_unique_constraint("uq_billing_plan_versions_plan_version", "billing_plan_versions", ["billing_plan_id", "version_number"])

    op.add_column("organization_plan_assignments", sa.Column("previous_assignment_id", sa.Uuid(), nullable=True))
    op.add_column("organization_plan_assignments", sa.Column("pending_product_change_id", sa.Uuid(), nullable=True))
    op.add_column(
        "organization_plan_assignments",
        sa.Column("product_confirmation_status", sa.Enum("pending", "confirmed", "failed", "not_required", name="productconfirmationstatus"), server_default="pending", nullable=False),
    )
    op.add_column("organization_plan_assignments", sa.Column("product_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organization_plan_assignments", sa.Column("product_confirmed_plan_code", sa.String(length=120), nullable=True))
    op.add_column("organization_plan_assignments", sa.Column("product_confirmed_version_number", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_org_plan_assignments_previous_assignment_id",
        "organization_plan_assignments",
        "organization_plan_assignments",
        ["previous_assignment_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_org_plan_assignments_pending_product_change_id",
        "organization_plan_assignments",
        "pending_product_changes",
        ["pending_product_change_id"],
        ["id"],
    )
    op.create_index("ix_organization_plan_assignments_previous_assignment_id", "organization_plan_assignments", ["previous_assignment_id"], unique=False)
    op.create_index("ix_organization_plan_assignments_pending_product_change_id", "organization_plan_assignments", ["pending_product_change_id"], unique=False)
    op.create_index("ix_org_plan_assignments_confirmation", "organization_plan_assignments", ["product_confirmation_status"], unique=False)
    op.create_index(
        "ix_org_plan_assignments_one_current",
        "organization_plan_assignments",
        ["organization_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = true"),
    )

    op.add_column("billing_ledger_entries", sa.Column("billing_plan_version_id", sa.Uuid(), nullable=True))
    op.add_column("billing_ledger_entries", sa.Column("organization_plan_assignment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_billing_ledger_entries_plan_version", "billing_ledger_entries", "billing_plan_versions", ["billing_plan_version_id"], ["id"])
    op.create_foreign_key(
        "fk_billing_ledger_entries_plan_assignment",
        "billing_ledger_entries",
        "organization_plan_assignments",
        ["organization_plan_assignment_id"],
        ["id"],
    )
    op.create_index("ix_billing_ledger_entries_billing_plan_version_id", "billing_ledger_entries", ["billing_plan_version_id"], unique=False)
    op.create_index("ix_billing_ledger_entries_organization_plan_assignment_id", "billing_ledger_entries", ["organization_plan_assignment_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_billing_ledger_entries_organization_plan_assignment_id", table_name="billing_ledger_entries")
    op.drop_index("ix_billing_ledger_entries_billing_plan_version_id", table_name="billing_ledger_entries")
    op.drop_constraint("fk_billing_ledger_entries_plan_assignment", "billing_ledger_entries", type_="foreignkey")
    op.drop_constraint("fk_billing_ledger_entries_plan_version", "billing_ledger_entries", type_="foreignkey")
    op.drop_column("billing_ledger_entries", "organization_plan_assignment_id")
    op.drop_column("billing_ledger_entries", "billing_plan_version_id")

    op.drop_index("ix_org_plan_assignments_one_current", table_name="organization_plan_assignments")
    op.drop_index("ix_org_plan_assignments_confirmation", table_name="organization_plan_assignments")
    op.drop_index("ix_organization_plan_assignments_pending_product_change_id", table_name="organization_plan_assignments")
    op.drop_index("ix_organization_plan_assignments_previous_assignment_id", table_name="organization_plan_assignments")
    op.drop_constraint("fk_org_plan_assignments_pending_product_change_id", "organization_plan_assignments", type_="foreignkey")
    op.drop_constraint("fk_org_plan_assignments_previous_assignment_id", "organization_plan_assignments", type_="foreignkey")
    op.drop_column("organization_plan_assignments", "product_confirmed_version_number")
    op.drop_column("organization_plan_assignments", "product_confirmed_plan_code")
    op.drop_column("organization_plan_assignments", "product_confirmed_at")
    op.drop_column("organization_plan_assignments", "product_confirmation_status")
    op.drop_column("organization_plan_assignments", "pending_product_change_id")
    op.drop_column("organization_plan_assignments", "previous_assignment_id")

    op.drop_constraint("uq_billing_plan_versions_plan_version", "billing_plan_versions", type_="unique")
    op.drop_index("ix_billing_plan_versions_created_by_admin_id", table_name="billing_plan_versions")
    op.drop_constraint("fk_billing_plan_versions_created_by_admin_id", "billing_plan_versions", type_="foreignkey")
    op.drop_column("billing_plan_versions", "note")
    op.drop_column("billing_plan_versions", "created_by_admin_id")
    op.drop_column("billing_plan_versions", "currency")

    op.drop_constraint("uq_billing_plans_deployment_plan_code", "billing_plans", type_="unique")
    op.drop_index("ix_billing_plans_plan_code", table_name="billing_plans")
    op.drop_column("billing_plans", "description")
    op.drop_column("billing_plans", "plan_code")
