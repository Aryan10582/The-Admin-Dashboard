from uuid import UUID

from pydantic import BaseModel

from app.core.enums import OrganizationLifecycleStatus, SyncStatus


class OrganizationRead(BaseModel):
    id: UUID
    central_organization_id: str
    name: str
    lifecycle_status: OrganizationLifecycleStatus
    sync_status: SyncStatus

    model_config = {"from_attributes": True}
