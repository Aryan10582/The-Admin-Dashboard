from uuid import UUID

from pydantic import BaseModel

from app.core.enums import Environment, ProductHealthStatus, SyncStatus


class ProductDeploymentRead(BaseModel):
    id: UUID
    product_name: str
    region: str
    environment: Environment
    currency: str
    health_status: ProductHealthStatus
    sync_status: SyncStatus

    model_config = {"from_attributes": True}
