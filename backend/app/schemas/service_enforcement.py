from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import BillingMode, CreditStatus, ServiceStatus, SyncStatus


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class ServiceEnforcementUpdate(ReasonRequest):
    pass


class PendingChangeSummary(BaseModel):
    id: UUID
    action: str
    status: str
    created_at: datetime
    reason: str | None

    model_config = ConfigDict(from_attributes=True)


class ServiceEnforcementRead(BaseModel):
    organization_id: UUID
    product_deployment_id: UUID
    intended_service_status: ServiceStatus
    evaluated_service_status: ServiceStatus
    product_confirmation_status: SyncStatus
    billing_mode: BillingMode
    credit_balance: Decimal
    outstanding_dues: Decimal
    credit_status: CreditStatus
    manual_continuation_enabled: bool
    manual_continuation_reason: str | None
    latest_pending_change: PendingChangeSummary | None = None


class ServiceActionResult(BaseModel):
    organization_id: UUID
    intended_service_status: ServiceStatus
    product_confirmation_status: SyncStatus
    manual_continuation_enabled: bool
    pending_product_change_id: UUID
    idempotency_key: str
