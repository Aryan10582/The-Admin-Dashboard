from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import CompatibilityStatus, Environment, ProductHealthStatus, SyncStatus


def normalize_admin_url(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        raise ValueError("URL cannot be empty")

    parsed = urlsplit(stripped)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("URL cannot contain embedded credentials")
    if not parsed.netloc:
        raise ValueError("URL must include a host")

    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def validate_relative_product_path(value: str | None, *, require_placeholder: bool = False) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    parsed = urlsplit(stripped)
    if parsed.scheme or parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Path must be relative to the product API base URL")
    if not stripped.startswith("/"):
        raise ValueError("Path must start with /")
    if ".." in parsed.path.split("/"):
        raise ValueError("Path cannot contain path traversal")
    if parsed.fragment:
        raise ValueError("Path cannot contain a fragment")
    if require_placeholder and "{organization_id}" not in stripped:
        raise ValueError("Path template must include {organization_id}")
    return stripped


class ProductDeploymentBase(BaseModel):
    product_name: str = Field(min_length=1, max_length=150)
    region: str = Field(min_length=1, max_length=80)
    environment: Environment
    currency: str = Field(min_length=3, max_length=3)
    api_base_url: str
    health_check_url: str | None = None
    admin_api_version: str = Field(default="v1", min_length=1, max_length=50)
    organization_list_path: str | None = None
    organization_detail_path_template: str | None = None
    is_active: bool = True
    is_under_maintenance: bool = False

    @field_validator("api_base_url", "health_check_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return normalize_admin_url(value)

    @field_validator("organization_list_path")
    @classmethod
    def validate_org_list_path(cls, value: str | None) -> str | None:
        return validate_relative_product_path(value)

    @field_validator("organization_detail_path_template")
    @classmethod
    def validate_org_detail_template(cls, value: str | None) -> str | None:
        return validate_relative_product_path(value, require_placeholder=True)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class ProductDeploymentCreate(ProductDeploymentBase):
    admin_api_secret: str | None = Field(default=None, max_length=4096)

    @field_validator("admin_api_secret")
    @classmethod
    def validate_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value == "":
            raise ValueError("Product admin secret cannot be empty")
        return value


class ProductDeploymentUpdate(BaseModel):
    product_name: str | None = Field(default=None, min_length=1, max_length=150)
    region: str | None = Field(default=None, min_length=1, max_length=80)
    environment: Environment | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    api_base_url: str | None = None
    health_check_url: str | None = None
    admin_api_version: str | None = Field(default=None, min_length=1, max_length=50)
    organization_list_path: str | None = None
    organization_detail_path_template: str | None = None
    is_active: bool | None = None
    is_under_maintenance: bool | None = None
    admin_api_secret: str | None = Field(default=None, max_length=4096)

    @field_validator("api_base_url", "health_check_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return normalize_admin_url(value)

    @field_validator("organization_list_path")
    @classmethod
    def validate_org_list_path(cls, value: str | None) -> str | None:
        return validate_relative_product_path(value)

    @field_validator("organization_detail_path_template")
    @classmethod
    def validate_org_detail_template(cls, value: str | None) -> str | None:
        return validate_relative_product_path(value, require_placeholder=True)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("admin_api_secret")
    @classmethod
    def validate_secret(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("Product admin secret cannot be empty")
        return value


class ProductDeploymentRead(BaseModel):
    id: UUID
    product_name: str
    region: str
    environment: Environment
    currency: str
    api_base_url: str
    health_check_url: str | None
    admin_api_version: str
    organization_list_path: str | None
    organization_detail_path_template: str | None
    supported_endpoints: dict[str, Any] | None
    compatibility_status: CompatibilityStatus
    is_active: bool
    is_under_maintenance: bool
    health_status: ProductHealthStatus
    sync_status: SyncStatus
    last_successful_sync_at: datetime | None
    last_failed_sync_at: datetime | None
    last_checked_at: datetime | None
    last_successful_health_check_at: datetime | None
    last_health_response_time_ms: int | None
    last_error_message: str | None
    last_organization_discovery_attempt_at: datetime | None
    last_successful_organization_discovery_at: datetime | None
    last_organization_discovery_error: str | None
    secret_configured: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductHealthCheckRead(BaseModel):
    product: ProductDeploymentRead
    health_status: ProductHealthStatus
    response_time_ms: int | None
    success: bool
    error_message: str | None = None
    checked_at: datetime


class ProductPurgeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    confirmation: str = Field(min_length=1, max_length=255)
