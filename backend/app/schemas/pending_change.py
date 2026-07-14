from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import Environment, PendingChangeStatus


class PendingChangeActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason is required")
        return stripped


class PendingChangeRead(BaseModel):
    id: UUID
    action: str
    organization_id: UUID | None
    product_deployment_id: UUID
    product_name: str | None = None
    region: str | None = None
    environment: Environment | None = None
    status: PendingChangeStatus
    retry_count: int
    last_retry_at: datetime | None
    last_error: str | None
    admin_id: UUID | None
    idempotency_key: str | None
    reason: str | None
    payload: dict | None
    delivery_attempt_id: str | None
    delivery_started_at: datetime | None
    last_delivery_at: datetime | None
    product_request_id: str | None
    product_api_version: str | None
    safe_confirmation_summary: dict | None
    created_at: datetime
    updated_at: datetime
    can_cancel: bool
    can_retry: bool

    model_config = ConfigDict(from_attributes=True)


class PendingChangeListResponse(BaseModel):
    items: list[PendingChangeRead]
    total: int
    limit: int
    offset: int
