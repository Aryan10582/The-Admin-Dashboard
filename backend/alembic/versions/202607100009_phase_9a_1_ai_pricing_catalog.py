"""phase 9a.1 ai pricing catalog

Revision ID: 202607100009
Revises: 202607100008
Create Date: 2026-07-14 21:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202607100009"
down_revision = "202607100008"
branch_labels = None
depends_on = None


source_type_enum = sa.Enum("manual", "provider_check", "system_import", name="aipricingsourcetype")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        source_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "ai_model_pricing_catalogs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_model_id", sa.String(length=150), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("pricing_scope_code", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_model_id", "pricing_scope_code", "currency", name="uq_ai_pricing_catalog_identity"),
    )
    op.create_index("ix_ai_pricing_catalog_active", "ai_model_pricing_catalogs", ["is_active"], unique=False)
    op.create_index("ix_ai_pricing_catalog_currency", "ai_model_pricing_catalogs", ["currency"], unique=False)
    op.create_index("ix_ai_pricing_catalog_model", "ai_model_pricing_catalogs", ["provider_model_id"], unique=False)
    op.create_index("ix_ai_pricing_catalog_provider", "ai_model_pricing_catalogs", ["provider"], unique=False)
    op.create_index("ix_ai_pricing_catalog_scope", "ai_model_pricing_catalogs", ["pricing_scope_code"], unique=False)

    op.add_column("ai_model_pricing_versions", sa.Column("pricing_catalog_id", sa.Uuid(), nullable=True))
    op.add_column("ai_model_pricing_versions", sa.Column("pricing_unit_tokens", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("ai_model_pricing_versions", sa.Column("currency_snapshot", sa.String(length=3), nullable=True))
    op.add_column("ai_model_pricing_versions", sa.Column("pricing_scope_snapshot", sa.String(length=120), nullable=True))
    op.add_column(
        "ai_model_pricing_versions",
        sa.Column("source_type", source_type_enum, nullable=False, server_default="manual"),
    )
    op.add_column("ai_model_pricing_versions", sa.Column("source_reference", sa.String(length=500), nullable=True))
    op.add_column("ai_model_pricing_versions", sa.Column("created_by_admin_id", sa.Uuid(), nullable=True))
    op.add_column("ai_model_pricing_versions", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("ai_model_pricing_versions", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE ai_model_pricing_versions SET currency_snapshot = currency WHERE currency_snapshot IS NULL")
    op.execute("UPDATE ai_model_pricing_versions SET pricing_scope_snapshot = 'legacy' WHERE pricing_scope_snapshot IS NULL")
    op.execute("UPDATE ai_model_pricing_versions SET created_at = effective_from WHERE created_at IS NULL")
    op.alter_column("ai_model_pricing_versions", "created_at", nullable=False)
    op.create_foreign_key(
        "fk_ai_pricing_versions_catalog_id",
        "ai_model_pricing_versions",
        "ai_model_pricing_catalogs",
        ["pricing_catalog_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_ai_pricing_versions_created_by_admin_id",
        "ai_model_pricing_versions",
        "admins",
        ["created_by_admin_id"],
        ["id"],
    )
    op.create_index("ix_ai_model_pricing_versions_pricing_catalog_id", "ai_model_pricing_versions", ["pricing_catalog_id"], unique=False)
    op.create_index("ix_ai_model_pricing_versions_created_by_admin_id", "ai_model_pricing_versions", ["created_by_admin_id"], unique=False)
    op.create_index("ix_ai_pricing_catalog_effective", "ai_model_pricing_versions", ["pricing_catalog_id", "effective_from", "effective_to"], unique=False)
    op.create_index("ix_ai_pricing_catalog_source", "ai_model_pricing_versions", ["pricing_catalog_id", "source_type"], unique=False)
    op.create_unique_constraint("uq_ai_pricing_versions_catalog_version", "ai_model_pricing_versions", ["pricing_catalog_id", "version_number"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_constraint("uq_ai_pricing_versions_catalog_version", "ai_model_pricing_versions", type_="unique")
    op.drop_index("ix_ai_pricing_catalog_source", table_name="ai_model_pricing_versions")
    op.drop_index("ix_ai_pricing_catalog_effective", table_name="ai_model_pricing_versions")
    op.drop_index("ix_ai_model_pricing_versions_created_by_admin_id", table_name="ai_model_pricing_versions")
    op.drop_index("ix_ai_model_pricing_versions_pricing_catalog_id", table_name="ai_model_pricing_versions")
    op.drop_constraint("fk_ai_pricing_versions_created_by_admin_id", "ai_model_pricing_versions", type_="foreignkey")
    op.drop_constraint("fk_ai_pricing_versions_catalog_id", "ai_model_pricing_versions", type_="foreignkey")
    op.drop_column("ai_model_pricing_versions", "created_at")
    op.drop_column("ai_model_pricing_versions", "note")
    op.drop_column("ai_model_pricing_versions", "created_by_admin_id")
    op.drop_column("ai_model_pricing_versions", "source_reference")
    op.drop_column("ai_model_pricing_versions", "source_type")
    op.drop_column("ai_model_pricing_versions", "pricing_scope_snapshot")
    op.drop_column("ai_model_pricing_versions", "currency_snapshot")
    op.drop_column("ai_model_pricing_versions", "pricing_unit_tokens")
    op.drop_column("ai_model_pricing_versions", "pricing_catalog_id")

    op.drop_index("ix_ai_pricing_catalog_scope", table_name="ai_model_pricing_catalogs")
    op.drop_index("ix_ai_pricing_catalog_provider", table_name="ai_model_pricing_catalogs")
    op.drop_index("ix_ai_pricing_catalog_model", table_name="ai_model_pricing_catalogs")
    op.drop_index("ix_ai_pricing_catalog_currency", table_name="ai_model_pricing_catalogs")
    op.drop_index("ix_ai_pricing_catalog_active", table_name="ai_model_pricing_catalogs")
    op.drop_table("ai_model_pricing_catalogs")

    if bind.dialect.name == "postgresql":
        source_type_enum.drop(bind, checkfirst=True)
