from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    AiPriceCheckStatus,
    AiPriceReviewDecision,
    AiPricingSourceType,
    AiUsageConflictStatus,
    AiUsageFinalizationStatus,
    AiUsageMappingResolutionStatus,
    AiUsagePricingResolutionStatus,
    AiUsageSyncRunStatus,
    PricingCreatedBy,
    SyncStatus,
)
from app.models.base import Base, TimestampMixin


class AiModelPricingCatalog(TimestampMixin, Base):
    __tablename__ = "ai_model_pricing_catalogs"
    __table_args__ = (
        UniqueConstraint("provider", "provider_model_id", "pricing_scope_code", "currency", name="uq_ai_pricing_catalog_identity"),
        Index("ix_ai_pricing_catalog_provider", "provider"),
        Index("ix_ai_pricing_catalog_model", "provider_model_id"),
        Index("ix_ai_pricing_catalog_scope", "pricing_scope_code"),
        Index("ix_ai_pricing_catalog_currency", "currency"),
        Index("ix_ai_pricing_catalog_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(150), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    pricing_scope_code: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AiModelPricingVersion(Base):
    __tablename__ = "ai_model_pricing_versions"
    __table_args__ = (
        Index("ix_ai_pricing_provider_model_active", "provider", "model_name", "is_active"),
        Index("ix_ai_pricing_effective", "effective_from", "effective_to"),
        Index("ix_ai_pricing_catalog_effective", "pricing_catalog_id", "effective_from", "effective_to"),
        Index("ix_ai_pricing_catalog_source", "pricing_catalog_id", "source_type"),
        Index("ix_ai_pricing_source_fingerprint", "pricing_catalog_id", "source_fingerprint", unique=True),
        UniqueConstraint("pricing_catalog_id", "version_number", name="uq_ai_pricing_versions_catalog_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    pricing_catalog_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_model_pricing_catalogs.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(150), nullable=False)
    input_token_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    output_token_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    pricing_unit_tokens: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    currency_snapshot: Mapped[str | None] = mapped_column(String(3), nullable=True)
    pricing_scope_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pricing_source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[AiPricingSourceType] = mapped_column(Enum(AiPricingSourceType), default=AiPricingSourceType.manual, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[PricingCreatedBy] = mapped_column(Enum(PricingCreatedBy), nullable=False)
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    audit_log_id: Mapped[UUID | None] = mapped_column(ForeignKey("audit_logs.id"), nullable=True, index=True)


class AIPriceCheckRun(TimestampMixin, Base):
    __tablename__ = "ai_price_check_runs"
    __table_args__ = (
        Index("ix_ai_price_check_runs_catalog_status", "pricing_catalog_id", "status"),
        Index("ix_ai_price_check_runs_provider_scope", "provider", "pricing_scope_code"),
        Index("ix_ai_price_check_runs_source_fingerprint", "source_fingerprint"),
        Index("ix_ai_price_check_runs_review", "review_decision", "reviewed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    pricing_catalog_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_model_pricing_catalogs.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    pricing_scope_code: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AiPriceCheckStatus] = mapped_column(Enum(AiPriceCheckStatus), nullable=False)
    candidate_input_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    candidate_output_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    candidate_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    candidate_pricing_unit_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_provider_model_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    safe_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_decision: Mapped[AiPriceReviewDecision | None] = mapped_column(Enum(AiPriceReviewDecision), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_model_pricing_versions.id"), nullable=True, index=True)


class ProductAIModelPricingMapping(TimestampMixin, Base):
    __tablename__ = "product_ai_model_pricing_mappings"
    __table_args__ = (
        UniqueConstraint("product_deployment_id", "product_provider", "product_model_id", name="uq_product_ai_model_pricing_mapping_identity"),
        Index("ix_product_ai_model_pricing_mappings_product", "product_deployment_id"),
        Index("ix_product_ai_model_pricing_mappings_catalog", "pricing_catalog_id"),
        Index("ix_product_ai_model_pricing_mappings_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    product_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    product_model_id: Mapped[str] = mapped_column(String(150), nullable=False)
    pricing_catalog_id: Mapped[UUID] = mapped_column(ForeignKey("ai_model_pricing_catalogs.id"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiUsageRecord(Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        Index("ix_ai_usage_date_provider_model", "usage_date", "provider", "model_name"),
        Index("ix_ai_usage_org_date", "organization_id", "usage_date"),
        Index("ix_ai_usage_deployment_usage_id", "product_deployment_id", "product_usage_id", unique=True),
        Index("ix_ai_usage_usage_at", "usage_at"),
        Index("ix_ai_usage_product_org_id", "product_organization_id"),
        Index("ix_ai_usage_pricing_catalog", "pricing_catalog_id"),
        Index("ix_ai_usage_resolution_statuses", "pricing_resolution_status", "mapping_resolution_status", "conflict_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    product_organization_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(150), nullable=False)
    product_model_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pricing_mapping_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_ai_model_pricing_mappings.id"), nullable=True, index=True)
    pricing_catalog_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_model_pricing_catalogs.id"), nullable=True, index=True)
    pricing_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_model_pricing_versions.id"), nullable=True, index=True)
    pricing_unit_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_token_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    output_token_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    input_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    output_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    calculated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    usage_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    product_usage_id: Mapped[str] = mapped_column(String(150), nullable=False)
    usage_revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalization_status: Mapped[AiUsageFinalizationStatus] = mapped_column(Enum(AiUsageFinalizationStatus), default=AiUsageFinalizationStatus.finalized, nullable=False)
    pricing_resolution_status: Mapped[AiUsagePricingResolutionStatus] = mapped_column(Enum(AiUsagePricingResolutionStatus), default=AiUsagePricingResolutionStatus.requires_pricing_resolution, nullable=False)
    mapping_resolution_status: Mapped[AiUsageMappingResolutionStatus] = mapped_column(Enum(AiUsageMappingResolutionStatus), default=AiUsageMappingResolutionStatus.requires_mapping_resolution, nullable=False)
    conflict_status: Mapped[AiUsageConflictStatus] = mapped_column(Enum(AiUsageConflictStatus), default=AiUsageConflictStatus.none, nullable=False)
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    conflict_reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    conflict_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conflict_review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    conversation_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    lead_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    request_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sync_status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.pending, nullable=False)


class AIUsageSyncState(TimestampMixin, Base):
    __tablename__ = "ai_usage_sync_states"

    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), primary_key=True)
    last_committed_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    safe_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIUsageSyncRun(Base):
    __tablename__ = "ai_usage_sync_runs"
    __table_args__ = (
        Index("ix_ai_usage_sync_runs_product", "product_deployment_id", "started_at"),
        Index("ix_ai_usage_sync_runs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_deployment_id: Mapped[UUID] = mapped_column(ForeignKey("product_deployments.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    starting_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ending_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    finalized_cost_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unresolved_pricing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unresolved_mapping_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safe_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[AiUsageSyncRunStatus] = mapped_column(Enum(AiUsageSyncRunStatus), nullable=False)
    safe_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
