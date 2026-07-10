from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ProductConfirmationStatus, ServiceStatus
from app.models.base import Base, TimestampMixin


class ServiceEnforcementRule(Base, TimestampMixin):
    __tablename__ = "service_enforcement_rules"
    __table_args__ = (
        Index("ix_service_rules_org_active", "organization_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    service_status: Mapped[ServiceStatus] = mapped_column(Enum(ServiceStatus), nullable=False)
    low_balance_warning_threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    hard_stop_threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    manual_continuation_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    product_confirmation_status: Mapped[ProductConfirmationStatus] = mapped_column(
        Enum(ProductConfirmationStatus),
        default=ProductConfirmationStatus.pending,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
