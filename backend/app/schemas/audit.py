from uuid import UUID

from pydantic import BaseModel

from app.core.enums import AuditResultStatus, SyncStatus


class AuditLogCreate(BaseModel):
    admin_id: UUID | None = None
    action: str
    organization_id: UUID | None = None
    product_deployment_id: UUID | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    reason: str | None = None
    result_status: AuditResultStatus = AuditResultStatus.success
    sync_status: SyncStatus | None = None
    idempotency_key: str | None = None
    failure_message: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
