from datetime import datetime
from uuid import UUID, uuid4

from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    BillingCalculationStatus,
    BillingMode,
    CreditStatus,
    MappingStatus,
    OrganizationLifecycleStatus,
    ServiceStatus,
    SyncStatus,
)
from app.models.base import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    central_organization_id: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), index=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    lifecycle_status: Mapped[OrganizationLifecycleStatus] = mapped_column(
        Enum(OrganizationLifecycleStatus),
        default=OrganizationLifecycleStatus.trial,
        nullable=False,
    )
    billing_mode: Mapped[BillingMode] = mapped_column(Enum(BillingMode), nullable=False)
    billing_calculation_status: Mapped[BillingCalculationStatus] = mapped_column(
        Enum(BillingCalculationStatus),
        default=BillingCalculationStatus.usage_tracking_only,
        nullable=False,
    )
    credit_status: Mapped[CreditStatus] = mapped_column(Enum(CreditStatus), default=CreditStatus.not_applicable, nullable=False)
    service_status: Mapped[ServiceStatus] = mapped_column(Enum(ServiceStatus), default=ServiceStatus.pending_sync, nullable=False)
    service_enforcement_status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus),
        default=ServiceStatus.pending_sync,
        nullable=False,
    )
    credit_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    outstanding_dues: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    selected_ai_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selected_ai_model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product_deployment = relationship("ProductDeployment")


class OrganizationMapping(Base, TimestampMixin):
    __tablename__ = "organization_mappings"
    __table_args__ = (
        Index(
            "uq_active_product_org_mapping",
            "product_deployment_id",
            "product_organization_id",
            unique=True,
            sqlite_where=text("mapping_status = 'active'"),
            postgresql_where=text("mapping_status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), index=True, nullable=False)
    product_organization_id: Mapped[str | None] = mapped_column(String(150), index=True, nullable=True)
    product_api_version: Mapped[str] = mapped_column(String(50), default="v1", nullable=False)
    external_billing_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    external_plan_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    external_subscription_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    mapping_status: Mapped[MappingStatus] = mapped_column(
        Enum(MappingStatus),
        default=MappingStatus.requires_manual_review,
        nullable=False,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization")
    product_deployment = relationship("ProductDeployment")
