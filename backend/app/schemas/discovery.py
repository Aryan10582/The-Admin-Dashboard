from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import BillingCalculationStatus, BillingMode, CreditStatus, OrganizationDiscoveryStatus, OrganizationLifecycleStatus, ServiceStatus


class ProductOrganizationDiscoveryRead(BaseModel):
    id: UUID
    product_deployment_id: UUID
    product_organization_id: str
    organization_name: str
    lifecycle_status_snapshot: OrganizationLifecycleStatus | None
    billing_mode_snapshot: BillingMode | None
    billing_calculation_status_snapshot: BillingCalculationStatus | None
    currency_snapshot: str | None
    credit_status_snapshot: CreditStatus | None
    credit_balance_snapshot: Decimal | None
    outstanding_dues_snapshot: Decimal | None
    service_status_snapshot: ServiceStatus | None
    product_active_status: bool | None
    product_api_version: str | None
    product_request_id: str | None
    product_updated_at: datetime | None
    last_active_at: datetime | None
    last_seen_at: datetime | None
    discovery_status: OrganizationDiscoveryStatus
    central_organization_id: UUID | None
    safe_metadata: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiscoveryListResponse(BaseModel):
    items: list[ProductOrganizationDiscoveryRead]
    total: int
    limit: int
    offset: int


class DiscoverySummary(BaseModel):
    discovered_count: int
    newly_discovered_count: int
    already_mapped_count: int
    conflict_count: int
    invalid_count: int
    pages_fetched: int
    safe_failures: list[str]


class ImportOrganizationsRequest(BaseModel):
    discovery_ids: list[UUID] | None = None
    product_organization_ids: list[str] | None = None


class ImportAllOrganizationsRequest(BaseModel):
    confirm: str = Field(min_length=1)
    limit: int = Field(default=100, ge=1, le=500)


class ImportResultItem(BaseModel):
    product_organization_id: str
    status: str
    organization_id: UUID | None = None
    mapping_status: str | None = None
    message: str | None = None


class ImportResult(BaseModel):
    items: list[ImportResultItem]
