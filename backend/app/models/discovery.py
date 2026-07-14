from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import BillingCalculationStatus, BillingMode, CreditStatus, OrganizationDiscoveryStatus, OrganizationLifecycleStatus, ServiceStatus
from app.models.base import Base, TimestampMixin


class ProductOrganizationDiscovery(Base, TimestampMixin):
    __tablename__ = "product_organization_discoveries"
    __table_args__ = (
        Index(
            "ix_product_org_discovery_deployment_external_id",
            "product_deployment_id",
            "product_organization_id",
            unique=True,
        ),
        Index("ix_product_org_discovery_status", "discovery_status"),
        Index("ix_product_org_discovery_last_seen", "last_seen_at"),
        Index("ix_product_org_discovery_central_org", "central_organization_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    product_organization_id: Mapped[str] = mapped_column(String(150), nullable=False)
    organization_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_status_snapshot: Mapped[OrganizationLifecycleStatus | None] = mapped_column(Enum(OrganizationLifecycleStatus), nullable=True)
    billing_mode_snapshot: Mapped[BillingMode | None] = mapped_column(Enum(BillingMode), nullable=True)
    billing_calculation_status_snapshot: Mapped[BillingCalculationStatus | None] = mapped_column(Enum(BillingCalculationStatus), nullable=True)
    currency_snapshot: Mapped[str | None] = mapped_column(String(3), nullable=True)
    credit_status_snapshot: Mapped[CreditStatus | None] = mapped_column(Enum(CreditStatus), nullable=True)
    credit_balance_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    outstanding_dues_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    service_status_snapshot: Mapped[ServiceStatus | None] = mapped_column(Enum(ServiceStatus), nullable=True)
    product_active_status: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    product_api_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    product_request_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    product_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_status: Mapped[OrganizationDiscoveryStatus] = mapped_column(
        Enum(OrganizationDiscoveryStatus),
        default=OrganizationDiscoveryStatus.discovered,
        nullable=False,
    )
    central_organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    safe_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
