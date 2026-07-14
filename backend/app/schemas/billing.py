from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import BillingMode, BillingTransactionType, CreditStatus, SyncStatus


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
