from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import AiUsageConflictStatus, AiUsageFinalizationStatus, AiUsageMappingResolutionStatus, AiUsagePricingResolutionStatus, AiUsageSyncRunStatus


class ProductAIModelPricingMappingCreate(BaseModel):
    product_provider: str = Field(min_length=1, max_length=100)
    product_model_id: str = Field(min_length=1, max_length=150)
    pricing_catalog_id: UUID
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("product_provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("product_model_id", "reason")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value is required")
        return stripped


class ProductAIModelPricingMappingUpdate(BaseModel):
    pricing_catalog_id: UUID | None = None
    is_active: bool | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class ProductAIModelPricingMappingRead(BaseModel):
    id: UUID
    product_deployment_id: UUID
    product_provider: str
    product_model_id: str
    pricing_catalog_id: UUID
    is_active: bool
    verified_at: datetime | None
    created_by_admin_id: UUID | None
    note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenUsageSyncRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=100, ge=1, le=250)
    max_pages: int = Field(default=5, ge=1, le=25)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AIUsageResolvePricingRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    pricing_version_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AIUsageBatchResolvePricingRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    product_deployment_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=250)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AIUsageBatchResolveMappingsRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    product_deployment_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=250)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AIUsageConflictReviewRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AIUsageRead(BaseModel):
    id: UUID
    product_deployment_id: UUID
    product_usage_id: str
    product_organization_id: str | None
    organization_id: UUID | None
    provider: str
    model_name: str
    product_model_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    usage_at: datetime | None
    usage_revision: str | None
    is_final: bool
    finalized_at: datetime | None
    pricing_mapping_id: UUID | None
    pricing_catalog_id: UUID | None
    pricing_version_id: UUID | None
    pricing_unit_tokens: int | None
    input_token_price: Decimal | None
    output_token_price: Decimal | None
    cost_currency: str | None
    input_cost: Decimal | None
    output_cost: Decimal | None
    total_cost: Decimal | None
    calculated_at: datetime | None
    finalization_status: AiUsageFinalizationStatus
    pricing_resolution_status: AiUsagePricingResolutionStatus
    mapping_resolution_status: AiUsageMappingResolutionStatus
    conflict_status: AiUsageConflictStatus
    conflict_reviewed_by_admin_id: UUID | None
    conflict_reviewed_at: datetime | None
    conflict_review_note: str | None
    invalid_reason: str | None
    campaign_reference: str | None
    conversation_reference: str | None
    lead_reference: str | None
    request_reference: str | None
    created_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AIUsageListResponse(BaseModel):
    items: list[AIUsageRead]
    total: int
    limit: int
    offset: int


class AIUsageSyncRunRead(BaseModel):
    id: UUID
    product_deployment_id: UUID
    started_at: datetime
    completed_at: datetime | None
    starting_cursor: str | None
    ending_cursor: str | None
    pages_fetched: int
    records_received: int
    imported_count: int
    unchanged_count: int
    finalized_cost_count: int
    unresolved_pricing_count: int
    unresolved_mapping_count: int
    conflict_count: int
    invalid_count: int
    safe_failure_count: int
    status: AiUsageSyncRunStatus
    safe_error: str | None
    requested_by_admin_id: UUID | None
    reason: str | None

    model_config = ConfigDict(from_attributes=True)


class AIUsageSyncStateRead(BaseModel):
    product_deployment_id: UUID
    last_committed_cursor: str | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    safe_last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIUsageSyncRunListResponse(BaseModel):
    items: list[AIUsageSyncRunRead]
    total: int
    limit: int
    offset: int


class AIUsageResolutionItemResult(BaseModel):
    usage_id: UUID
    product_usage_id: str
    outcome: str
    message: str | None = None
    usage: AIUsageRead | None = None


class AIUsageBatchResolutionResponse(BaseModel):
    items: list[AIUsageResolutionItemResult]
    processed: int
    resolved: int


class AIUsageConflictDetail(BaseModel):
    usage: AIUsageRead
    original: dict
    candidate: dict | None
    candidate_fingerprint: str | None
    detected_fields: list[str]
    reviewed: bool


class CurrencyCostSummary(BaseModel):
    currency: str
    total_cost: Decimal


class RankedCostSummary(BaseModel):
    id: UUID | None
    label: str
    currency: str
    total_cost: Decimal


class ProviderModelUsageSummary(BaseModel):
    provider: str
    product_model_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    record_count: int


class AIUsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    usage_record_count: int
    finalized_costs_by_currency: list[CurrencyCostSummary]
    unpriced_usage_count: int
    unmapped_usage_count: int
    non_final_usage_count: int
    invalid_usage_count: int
    conflict_count: int
    reviewed_conflict_count: int
    unreviewed_conflict_count: int
    highest_cost_organizations: list[RankedCostSummary]
    highest_cost_products: list[RankedCostSummary]
    provider_model_breakdown: list[ProviderModelUsageSummary]
    free_internal_testing_costs_by_currency: list[CurrencyCostSummary]
