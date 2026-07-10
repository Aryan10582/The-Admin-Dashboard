from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PricingCreatedBy, SyncStatus
from app.models.base import Base


class AiModelPricingVersion(Base):
    __tablename__ = "ai_model_pricing_versions"
    __table_args__ = (
        Index("ix_ai_pricing_provider_model_active", "provider", "model_name", "is_active"),
        Index("ix_ai_pricing_effective", "effective_from", "effective_to"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(150), nullable=False)
    input_token_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    output_token_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    pricing_source: Mapped[str] = mapped_column(String(255), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[PricingCreatedBy] = mapped_column(Enum(PricingCreatedBy), nullable=False)
    audit_log_id: Mapped[UUID | None] = mapped_column(ForeignKey("audit_logs.id"), nullable=True, index=True)


class AiUsageRecord(Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        Index("ix_ai_usage_date_provider_model", "usage_date", "provider", "model_name"),
        Index("ix_ai_usage_org_date", "organization_id", "usage_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(150), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pricing_version_id: Mapped[UUID] = mapped_column(ForeignKey("ai_model_pricing_versions.id"), nullable=False, index=True)
    calculated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    product_usage_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    campaign_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    conversation_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    lead_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)
