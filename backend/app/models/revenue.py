from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, Enum, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import MismatchStatus, RevenueSource, RevenueType, SyncStatus
from app.models.base import Base, TimestampMixin


class RevenueRecord(Base, TimestampMixin):
    __tablename__ = "revenue_records"
    __table_args__ = (
        Index("ix_revenue_date_currency", "revenue_date", "currency"),
        Index("ix_revenue_product_date", "product_deployment_id", "revenue_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    revenue_type: Mapped[RevenueType] = mapped_column(Enum(RevenueType), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source: Mapped[RevenueSource] = mapped_column(Enum(RevenueSource), nullable=False)
    revenue_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str | None] = mapped_column(String(30), nullable=True)
    related_ledger_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("billing_ledger_entries.id"), nullable=True, index=True)
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)
    mismatch_status: Mapped[MismatchStatus | None] = mapped_column(Enum(MismatchStatus), nullable=True)
