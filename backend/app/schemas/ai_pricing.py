from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import AiPriceCheckStatus, AiPriceReviewDecision, AiPricingSourceType, PricingCreatedBy


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")
    return value.astimezone(timezone.utc)


def _normalize_code(value: str, field_name: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if any(char for char in normalized if not (char.isalnum() or char in {"_", "-"})):
        raise ValueError(f"{field_name} may contain only letters, numbers, underscores, and hyphens")
    return normalized


class AiPricingCatalogCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    provider_model_id: str = Field(min_length=1, max_length=150)
    display_name: str = Field(min_length=1, max_length=150)
    pricing_scope_code: str = Field(min_length=1, max_length=120)
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("provider_model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider_model_id is required")
        return stripped

    @field_validator("pricing_scope_code")
    @classmethod
    def normalize_scope(cls, value: str) -> str:
        return _normalize_code(value, "pricing_scope_code")

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("display_name", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value is required")
        return stripped


class AiPricingCatalogUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("display_name", "reason")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value is required")
        return stripped


class AiPricingVersionCreate(BaseModel):
    input_token_price: Decimal = Field(ge=0, max_digits=18, decimal_places=8)
    output_token_price: Decimal = Field(ge=0, max_digits=18, decimal_places=8)
    pricing_unit_tokens: int = Field(gt=0)
    effective_from: datetime
    effective_to: datetime | None = None
    source_reference: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _normalize_utc(value)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AiPricingVersionRead(BaseModel):
    id: UUID
    pricing_catalog_id: UUID | None
    version_number: int
    input_token_price: Decimal
    output_token_price: Decimal
    pricing_unit_tokens: int
    currency_snapshot: str | None
    pricing_scope_snapshot: str | None
    effective_from: datetime
    effective_to: datetime | None
    source_type: AiPricingSourceType
    source_reference: str | None
    created_by_type: PricingCreatedBy
    created_by_admin_id: UUID | None
    note: str | None
    created_at: datetime
    is_active: bool
    effective_state: str


class AiPricingCatalogRead(BaseModel):
    id: UUID
    provider: str
    provider_model_id: str
    display_name: str
    pricing_scope_code: str
    currency: str
    description: str | None
    is_active: bool
    latest_version: AiPricingVersionRead | None = None
    current_effective_version: AiPricingVersionRead | None = None
    version_count: int = 0
    has_future_version: bool = False
    last_check_status: AiPriceCheckStatus | None = None
    last_checked_at: datetime | None = None
    unresolved_review_count: int = 0
    source_state: str = "source_unsupported"
    safe_last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiPricingCatalogListResponse(BaseModel):
    items: list[AiPricingCatalogRead]
    total: int
    limit: int
    offset: int


class AiPricingSyncCheckRequest(BaseModel):
    pricing_catalog_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=100)
    pricing_scope_code: str | None = Field(default=None, max_length=120)
    adapter_code: str | None = Field(default=None, max_length=100)
    mock_scenario: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider")
    @classmethod
    def normalize_optional_provider(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("pricing_scope_code")
    @classmethod
    def normalize_optional_scope(cls, value: str | None) -> str | None:
        return _normalize_code(value, "pricing_scope_code") if value else None

    @field_validator("reason")
    @classmethod
    def strip_sync_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class AiPriceCheckRunRead(BaseModel):
    id: UUID
    pricing_catalog_id: UUID | None
    provider: str
    pricing_scope_code: str
    started_at: datetime
    completed_at: datetime | None
    requested_by_admin_id: UUID | None
    reason: str | None
    request_idempotency_key: str | None
    source_reference: str | None
    source_fingerprint: str | None
    source_effective_at: datetime | None
    status: AiPriceCheckStatus
    candidate_input_price: Decimal | None
    candidate_output_price: Decimal | None
    candidate_currency: str | None
    candidate_pricing_unit_tokens: int | None
    candidate_provider_model_id: str | None
    safe_error: str | None
    reviewed_by_admin_id: UUID | None
    reviewed_at: datetime | None
    review_decision: AiPriceReviewDecision | None
    review_note: str | None
    created_version_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiPriceCheckRunListResponse(BaseModel):
    items: list[AiPriceCheckRunRead]
    total: int
    limit: int
    offset: int


class AiPriceCheckReviewRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def strip_review_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped
