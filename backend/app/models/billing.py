from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import BillingMode, BillingTransactionType, FailureStatus, ProductConfirmationStatus, SyncStatus
from app.models.base import Base, TimestampMixin


class BillingPlan(Base, TimestampMixin):
    __tablename__ = "billing_plans"
    __table_args__ = (
        Index("ix_billing_plans_product_currency_active", "product_deployment_id", "currency", "is_active"),
        UniqueConstraint("product_deployment_id", "plan_code", name="uq_billing_plans_deployment_plan_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_deployment_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_deployments.id"), nullable=True, index=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product_deployment = relationship("ProductDeployment")


class BillingPlanVersion(Base, TimestampMixin):
    __tablename__ = "billing_plan_versions"
    __table_args__ = (
        Index("ix_billing_plan_versions_plan_active", "billing_plan_id", "is_active"),
        Index("ix_billing_plan_versions_effective", "effective_from", "effective_to"),
        UniqueConstraint("billing_plan_id", "version_number", name="uq_billing_plan_versions_plan_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    billing_plan_id: Mapped[UUID] = mapped_column(ForeignKey("billing_plans.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billing_mode_compatibility: Mapped[BillingMode] = mapped_column(Enum(BillingMode), nullable=False)
    pricing_structure: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    included_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    included_leads: Mapped[int] = mapped_column(default=0, nullable=False)
    overage_pricing: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    external_product_plan_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    billing_plan = relationship("BillingPlan")


class OrganizationPlanAssignment(Base, TimestampMixin):
    __tablename__ = "organization_plan_assignments"
    __table_args__ = (
        Index("ix_org_plan_assignments_org_active", "organization_id", "is_active"),
        Index("ix_org_plan_assignments_confirmation", "product_confirmation_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    billing_plan_id: Mapped[UUID] = mapped_column(ForeignKey("billing_plans.id"), nullable=False, index=True)
    billing_plan_version_id: Mapped[UUID] = mapped_column(ForeignKey("billing_plan_versions.id"), nullable=False, index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    previous_assignment_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization_plan_assignments.id"), nullable=True, index=True)
    pending_product_change_id: Mapped[UUID | None] = mapped_column(ForeignKey("pending_product_changes.id"), nullable=True, index=True)
    product_confirmation_status: Mapped[ProductConfirmationStatus] = mapped_column(
        Enum(ProductConfirmationStatus),
        default=ProductConfirmationStatus.pending,
        nullable=False,
    )
    product_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    product_confirmed_plan_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_confirmed_version_number: Mapped[int | None] = mapped_column(nullable=True)

    billing_plan = relationship("BillingPlan")
    billing_plan_version = relationship("BillingPlanVersion")


class BillingLedgerEntry(Base):
    """Append-only financial record. Future services should create corrections instead of updating rows."""

    __tablename__ = "billing_ledger_entries"
    __table_args__ = (
        Index("ix_billing_ledger_org_created", "organization_id", "created_at"),
        Index("ix_billing_ledger_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    transaction_type: Mapped[BillingTransactionType] = mapped_column(Enum(BillingTransactionType), nullable=False, index=True)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    outstanding_dues_before: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    outstanding_dues_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    related_original_transaction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("billing_ledger_entries.id"),
        nullable=True,
        index=True,
    )
    billing_plan_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("billing_plan_versions.id"), nullable=True, index=True)
    organization_plan_assignment_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization_plan_assignments.id"), nullable=True, index=True)
    related_product_transaction_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    product_sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)
    failure_status: Mapped[FailureStatus | None] = mapped_column(Enum(FailureStatus), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManualPayment(Base, TimestampMixin):
    __tablename__ = "manual_payments"
    __table_args__ = (
        Index("ix_manual_payments_idempotency_key", "idempotency_key", unique=True),
        Index("ix_manual_payments_org_date", "organization_id", "payment_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    product_sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)
