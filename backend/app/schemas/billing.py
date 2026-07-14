from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import BillingMode, BillingTransactionType, CreditStatus, ProductConfirmationStatus, SyncStatus


class FinancialActionBase(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class AddCreditsRequest(FinancialActionBase):
    pass


class DeductCreditsRequest(FinancialActionBase):
    allow_negative_balance: bool = False


class ManualPaymentRequest(FinancialActionBase):
    payment_date: date | None = None
    payment_method: str | None = Field(default=None, max_length=100)
    payment_reference: str | None = Field(default=None, max_length=150)


class BillingLedgerEntryRead(BaseModel):
    id: UUID
    organization_id: UUID
    product_deployment_id: UUID
    currency: str
    amount: Decimal
    transaction_type: BillingTransactionType
    balance_before: Decimal
    balance_after: Decimal
    outstanding_dues_before: Decimal
    outstanding_dues_after: Decimal
    note: str | None
    admin_id: UUID | None
    idempotency_key: str
    related_original_transaction_id: UUID | None
    related_product_transaction_id: str | None
    product_sync_status: SyncStatus
    failure_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ManualPaymentRead(BaseModel):
    id: UUID
    organization_id: UUID
    product_deployment_id: UUID
    currency: str
    payment_amount: Decimal
    payment_date: date
    payment_method: str | None
    payment_reference: str | None
    admin_id: UUID | None
    note: str | None
    idempotency_key: str
    product_sync_status: SyncStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BillingSummaryRead(BaseModel):
    organization_id: UUID
    product_deployment_id: UUID
    currency: str
    billing_mode: BillingMode
    credit_status: CreditStatus
    credit_balance: Decimal
    outstanding_dues: Decimal


class FinancialActionResult(BaseModel):
    organization: BillingSummaryRead
    ledger_entry: BillingLedgerEntryRead
    pending_product_change_id: UUID | None = None
    manual_payment: ManualPaymentRead | None = None
    idempotency_key: str


class LedgerListResponse(BaseModel):
    items: list[BillingLedgerEntryRead]
    total: int
    limit: int
    offset: int


class BillingPlanCreate(BaseModel):
    plan_code: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    product_deployment_id: UUID
    currency: str = Field(min_length=3, max_length=3)
    is_active: bool = True

    @field_validator("plan_code")
    @classmethod
    def normalize_plan_code(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized or any(char for char in normalized if not (char.isalnum() or char in {"_", "-"})):
            raise ValueError("Plan code may contain only letters, numbers, underscores, and hyphens")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_plan_currency(cls, value: str) -> str:
        return value.upper()


class BillingPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class BillingPlanVersionCreate(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    billing_mode_compatibility: BillingMode
    base_price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    pricing_structure: dict = Field(default_factory=dict)
    limits: dict | None = None
    included_tokens: int = Field(default=0, ge=0)
    included_leads: int = Field(default=0, ge=0)
    overage_pricing: dict | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    is_active: bool = True
    external_product_plan_id: str | None = Field(default=None, max_length=150)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_version_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class BillingPlanVersionRead(BaseModel):
    id: UUID
    billing_plan_id: UUID
    version_number: int
    currency: str
    billing_mode_compatibility: BillingMode
    pricing_structure: dict
    price: Decimal
    limits: dict | None
    included_tokens: int
    included_leads: int
    overage_pricing: dict | None
    effective_from: datetime
    effective_to: datetime | None
    is_active: bool
    external_product_plan_id: str | None
    created_by_admin_id: UUID | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    immutable_terms: bool = True

    model_config = ConfigDict(from_attributes=True)


class BillingPlanRead(BaseModel):
    id: UUID
    plan_code: str
    name: str
    description: str | None
    product_deployment_id: UUID
    product_name: str | None
    region: str | None
    environment: str | None
    currency: str
    is_active: bool
    latest_version: BillingPlanVersionRead | None = None
    current_effective_version: BillingPlanVersionRead | None = None
    version_count: int = 0
    assignment_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BillingPlanListResponse(BaseModel):
    items: list[BillingPlanRead]
    total: int
    limit: int
    offset: int


class PlanAssignmentRequest(BaseModel):
    billing_plan_version_id: UUID
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def assignment_reason_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class PlanAssignmentRead(BaseModel):
    id: UUID
    organization_id: UUID
    billing_plan_id: UUID
    billing_plan_version_id: UUID
    plan_name: str
    plan_code: str
    version_number: int
    currency: str
    base_price: Decimal
    billing_mode_compatibility: BillingMode
    effective_from: datetime
    effective_to: datetime | None
    assigned_at: datetime
    replaced_at: datetime | None
    assigned_by_admin_id: UUID | None
    reason: str | None
    previous_assignment_id: UUID | None
    pending_product_change_id: UUID | None
    pending_product_change_status: str | None
    product_confirmation_status: ProductConfirmationStatus
    product_confirmed_at: datetime | None
    product_confirmed_plan_code: str | None
    product_confirmed_version_number: int | None


class OrganizationPlanAssignmentState(BaseModel):
    organization_id: UUID
    current_intended: PlanAssignmentRead | None
    last_product_confirmed: PlanAssignmentRead | None
    pending_change_id: UUID | None
    pending_change_status: str | None


class PlanAssignmentResult(BaseModel):
    assignment: PlanAssignmentRead
    pending_product_change_id: UUID
    idempotency_key: str
