from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    BillingCalculationStatus,
    BillingMode,
    CreditStatus,
    Environment,
    MappingStatus,
    OrganizationLifecycleStatus,
    ServiceStatus,
    SyncStatus,
)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    product_deployment_id: UUID
    currency: str = Field(min_length=3, max_length=3)
    lifecycle_status: OrganizationLifecycleStatus = OrganizationLifecycleStatus.trial
    billing_mode: BillingMode
    billing_calculation_status: BillingCalculationStatus = BillingCalculationStatus.usage_tracking_only
    last_active_at: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class ProductOrganizationLookupRequest(BaseModel):
    product_deployment_id: UUID
    product_organization_id: str = Field(min_length=1, max_length=150)


class ProductOrganizationLookupRead(BaseModel):
    product_deployment_id: UUID
    product_organization_id: str
    organization_name: str | None = None
    lifecycle_status: OrganizationLifecycleStatus | None = None
    billing_mode: BillingMode | None = None
    billing_calculation_status: BillingCalculationStatus | None = None
    currency: str | None = None
    credit_status: CreditStatus | None = None
    service_status: ServiceStatus | None = None
    credit_balance: Decimal | None = None
    outstanding_dues: Decimal | None = None
    last_active_at: datetime | None = None
    safe_metadata: dict | None = None


class OrganizationLinkFromProductRequest(ProductOrganizationLookupRequest):
    reason: str | None = Field(default=None, max_length=1000)
    manual_name: str | None = Field(default=None, min_length=1, max_length=255)
    manual_currency: str | None = Field(default=None, min_length=3, max_length=3)
    manual_lifecycle_status: OrganizationLifecycleStatus | None = None
    manual_billing_mode: BillingMode | None = None
    manual_billing_calculation_status: BillingCalculationStatus | None = None

    @field_validator("manual_currency")
    @classmethod
    def normalize_manual_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    product_deployment_id: UUID | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lifecycle_status: OrganizationLifecycleStatus | None = None
    billing_mode: BillingMode | None = None
    billing_calculation_status: BillingCalculationStatus | None = None
    last_active_at: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class ProductDeploymentSummary(BaseModel):
    id: UUID
    product_name: str
    region: str
    environment: Environment
    currency: str
    admin_api_version: str

    model_config = ConfigDict(from_attributes=True)


class OrganizationMappingRead(BaseModel):
    id: UUID
    organization_id: UUID
    product_deployment_id: UUID
    product_organization_id: str | None
    product_api_version: str
    external_billing_id: str | None
    external_customer_id: str | None
    external_plan_id: str | None
    external_subscription_id: str | None
    mapping_status: MappingStatus
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationMappingUpdate(BaseModel):
    product_deployment_id: UUID | None = None
    product_organization_id: str | None = Field(default=None, max_length=150)
    mapping_status: MappingStatus | None = None
    external_billing_id: str | None = Field(default=None, max_length=150)
    external_customer_id: str | None = Field(default=None, max_length=150)
    external_plan_id: str | None = Field(default=None, max_length=150)
    external_subscription_id: str | None = Field(default=None, max_length=150)

    @field_validator("product_organization_id")
    @classmethod
    def reject_empty_product_org_id(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("Product organization ID cannot be empty")
        return value


class OrganizationRead(BaseModel):
    id: UUID
    central_organization_id: str
    name: str
    product_deployment_id: UUID
    currency: str
    lifecycle_status: OrganizationLifecycleStatus
    billing_mode: BillingMode
    billing_calculation_status: BillingCalculationStatus
    credit_status: CreditStatus
    service_status: ServiceStatus
    service_enforcement_status: ServiceStatus
    credit_balance: Decimal
    outstanding_dues: Decimal
    sync_status: SyncStatus
    last_synced_at: datetime | None
    last_active_at: datetime | None
    created_at: datetime
    updated_at: datetime
    product_deployment: ProductDeploymentSummary
    mapping: OrganizationMappingRead | None = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationListResponse(BaseModel):
    items: list[OrganizationRead]
    total: int
    limit: int
    offset: int


class MappingVerificationRead(BaseModel):
    mapping: OrganizationMappingRead
    success: bool
    message: str | None = None
