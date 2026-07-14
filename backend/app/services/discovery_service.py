from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    AuditResultStatus,
    BillingCalculationStatus,
    BillingMode,
    CreditStatus,
    FailureStatus,
    MappingStatus,
    OrganizationDiscoveryStatus,
    OrganizationLifecycleStatus,
    ServiceStatus,
    SyncStatus,
)
from app.core.product_secrets import decrypt_product_secret
from app.integrations.product_admin_client import ProductOrganizationListItem
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.discovery import ProductOrganizationDiscovery
from app.models.failure_log import FailureLog
from app.models.organization import Organization, OrganizationMapping
from app.models.product import ProductDeployment
from app.schemas.discovery import ImportResult, ImportResultItem
from app.services.organization_service import get_organization, verify_mapping
from app.services.product_client import build_product_client

MAX_DISCOVERY_PAGES = 5
DISCOVERY_PAGE_SIZE = 100


@dataclass(frozen=True)
class DiscoveryFilters:
    status: OrganizationDiscoveryStatus | None = None
    search: str | None = None
    product_organization_id: str | None = None
    product_active_status: bool | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(message: str | None) -> str:
    return " ".join((message or "Product organization discovery failed").split())[:500]


def _enum(enum_cls, value, default=None):
    if value is None:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _audit(db: Session, admin: Admin, action: str, product_id: UUID, payload: dict, result_status: AuditResultStatus = AuditResultStatus.success, failure_message: str | None = None) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id,
            action=action,
            product_deployment_id=product_id,
            new_value=payload,
            result_status=result_status,
            failure_message=_safe_error(failure_message) if failure_message else None,
            created_at=_now(),
        )
    )


def _failure(db: Session, admin: Admin, product: ProductDeployment, code: str, message: str) -> None:
    db.add(
        FailureLog(
            product_deployment_id=product.id,
            action_attempted="product.organizations.discover",
            error_message=_safe_error(message),
            error_code=code,
            retry_count=0,
            current_status=FailureStatus.open,
            admin_id=admin.id,
            product_api_version=product.admin_api_version,
            created_at=_now(),
        )
    )


def _mapping_for_external_id(db: Session, product_id: UUID, product_organization_id: str) -> OrganizationMapping | None:
    return db.scalar(
        select(OrganizationMapping).where(
            OrganizationMapping.product_deployment_id == product_id,
            OrganizationMapping.product_organization_id == product_organization_id,
        )
    )


def _status_for_item(db: Session, product_id: UUID, product_organization_id: str) -> tuple[OrganizationDiscoveryStatus, UUID | None]:
    mapping = _mapping_for_external_id(db, product_id, product_organization_id)
    if mapping is None:
        return OrganizationDiscoveryStatus.discovered, None
    if mapping.organization_id:
        return OrganizationDiscoveryStatus.already_mapped, mapping.organization_id
    return OrganizationDiscoveryStatus.conflict, None


def _upsert_discovery(db: Session, product: ProductDeployment, item: ProductOrganizationListItem) -> tuple[ProductOrganizationDiscovery, bool]:
    discovery = db.scalar(
        select(ProductOrganizationDiscovery).where(
            ProductOrganizationDiscovery.product_deployment_id == product.id,
            ProductOrganizationDiscovery.product_organization_id == item.product_organization_id,
        )
    )
    created = discovery is None
    status_value, org_id = _status_for_item(db, product.id, item.product_organization_id)
    if discovery is None:
        discovery = ProductOrganizationDiscovery(
            product_deployment_id=product.id,
            product_organization_id=item.product_organization_id,
            organization_name=item.organization_name,
        )
        db.add(discovery)
    discovery.organization_name = item.organization_name
    discovery.lifecycle_status_snapshot = _enum(OrganizationLifecycleStatus, item.lifecycle_status)
    discovery.billing_mode_snapshot = _enum(BillingMode, item.billing_mode)
    discovery.billing_calculation_status_snapshot = _enum(BillingCalculationStatus, item.billing_calculation_status)
    discovery.currency_snapshot = item.currency or product.currency
    discovery.credit_status_snapshot = _enum(CreditStatus, item.credit_status)
    discovery.credit_balance_snapshot = item.credit_balance
    discovery.outstanding_dues_snapshot = item.outstanding_dues
    discovery.service_status_snapshot = _enum(ServiceStatus, item.service_status)
    discovery.product_active_status = item.product_active_status
    discovery.product_api_version = item.product_api_version
    discovery.product_request_id = item.product_request_id
    discovery.last_active_at = _dt(item.last_active_at)
    discovery.product_updated_at = _dt(item.product_updated_at)
    discovery.last_seen_at = _now()
    discovery.discovery_status = status_value
    discovery.central_organization_id = org_id
    discovery.safe_metadata = item.safe_metadata
    return discovery, created


async def discover_product_organizations(db: Session, product_id: UUID, admin: Admin) -> dict:
    product = db.get(ProductDeployment, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    product.last_organization_discovery_attempt_at = _now()
    db.commit()

    discovered_count = newly_discovered_count = already_mapped_count = conflict_count = invalid_count = pages_fetched = 0
    safe_failures: list[str] = []
    seen: set[str] = set()
    cursor = None
    try:
        client = build_product_client(product, api_secret=decrypt_product_secret(product.admin_api_secret_encrypted))
        for _ in range(MAX_DISCOVERY_PAGES):
            result = await client.list_organizations(cursor=cursor, limit=DISCOVERY_PAGE_SIZE)
            pages_fetched += 1
            if not result.is_success:
                invalid_count += 1
                message = result.error_message or "Product organization discovery failed"
                safe_failures.append(_safe_error(message))
                product.last_organization_discovery_error = _safe_error(message)
                _failure(db, admin, product, result.error_category or "discovery_failed", message)
                break
            for item in result.organizations:
                seen.add(item.product_organization_id)
                discovery, created = _upsert_discovery(db, product, item)
                discovered_count += 1
                newly_discovered_count += 1 if created else 0
                already_mapped_count += 1 if discovery.discovery_status == OrganizationDiscoveryStatus.already_mapped else 0
                conflict_count += 1 if discovery.discovery_status == OrganizationDiscoveryStatus.conflict else 0
            if not result.has_more or not result.next_cursor:
                break
            cursor = result.next_cursor
        for discovery in db.scalars(select(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product.id)):
            if discovery.product_organization_id not in seen and discovery.discovery_status in {OrganizationDiscoveryStatus.discovered, OrganizationDiscoveryStatus.already_mapped}:
                discovery.discovery_status = OrganizationDiscoveryStatus.no_longer_returned
        if not safe_failures:
            product.last_successful_organization_discovery_at = _now()
            product.last_organization_discovery_error = None
        _audit(
            db,
            admin,
            "product.organizations.discovered",
            product.id,
            {
                "discovered_count": discovered_count,
                "newly_discovered_count": newly_discovered_count,
                "already_mapped_count": already_mapped_count,
                "conflict_count": conflict_count,
                "invalid_count": invalid_count,
                "pages_fetched": pages_fetched,
            },
            AuditResultStatus.failure if safe_failures else AuditResultStatus.success,
            "; ".join(safe_failures) if safe_failures else None,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        product = db.get(ProductDeployment, product_id)
        if product is not None:
            product.last_organization_discovery_error = _safe_error(str(exc))
            _failure(db, admin, product, "discovery_exception", str(exc))
            db.commit()
        safe_failures.append(_safe_error(str(exc)))
    return {
        "discovered_count": discovered_count,
        "newly_discovered_count": newly_discovered_count,
        "already_mapped_count": already_mapped_count,
        "conflict_count": conflict_count,
        "invalid_count": invalid_count,
        "pages_fetched": pages_fetched,
        "safe_failures": safe_failures,
    }


def list_discoveries(db: Session, product_id: UUID, filters: DiscoveryFilters, *, limit: int, offset: int) -> tuple[list[ProductOrganizationDiscovery], int]:
    stmt = select(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product_id)
    if filters.status:
        stmt = stmt.where(ProductOrganizationDiscovery.discovery_status == filters.status)
    if filters.product_organization_id:
        stmt = stmt.where(ProductOrganizationDiscovery.product_organization_id.ilike(f"%{filters.product_organization_id}%"))
    if filters.search:
        stmt = stmt.where(or_(ProductOrganizationDiscovery.organization_name.ilike(f"%{filters.search}%"), ProductOrganizationDiscovery.product_organization_id.ilike(f"%{filters.search}%")))
    if filters.product_active_status is not None:
        stmt = stmt.where(ProductOrganizationDiscovery.product_active_status == filters.product_active_status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return list(db.scalars(stmt.order_by(ProductOrganizationDiscovery.last_seen_at.desc().nullslast(), ProductOrganizationDiscovery.created_at.desc()).limit(limit).offset(offset))), total


def _organization_from_discovery(product: ProductDeployment, discovery: ProductOrganizationDiscovery) -> Organization:
    return Organization(
        central_organization_id=f"org_{uuid4()}",
        name=discovery.organization_name,
        product_deployment_id=product.id,
        currency=discovery.currency_snapshot or product.currency,
        lifecycle_status=discovery.lifecycle_status_snapshot or OrganizationLifecycleStatus.trial,
        billing_mode=discovery.billing_mode_snapshot or BillingMode.prepaid_credits,
        billing_calculation_status=discovery.billing_calculation_status_snapshot or BillingCalculationStatus.usage_tracking_only,
        credit_status=discovery.credit_status_snapshot or CreditStatus.not_applicable,
        service_status=discovery.service_status_snapshot or ServiceStatus.pending_sync,
        service_enforcement_status=discovery.service_status_snapshot or ServiceStatus.pending_sync,
        credit_balance=discovery.credit_balance_snapshot or Decimal("0.00"),
        outstanding_dues=discovery.outstanding_dues_snapshot or Decimal("0.00"),
        sync_status=SyncStatus.pending,
        last_active_at=discovery.last_active_at,
    )


async def import_discoveries(db: Session, product_id: UUID, admin: Admin, *, discovery_ids: list[UUID] | None = None, product_organization_ids: list[str] | None = None, limit: int = 100) -> dict:
    product = db.get(ProductDeployment, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    stmt = select(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product_id)
    if discovery_ids:
        stmt = stmt.where(ProductOrganizationDiscovery.id.in_(discovery_ids))
    if product_organization_ids:
        stmt = stmt.where(ProductOrganizationDiscovery.product_organization_id.in_(product_organization_ids))
    stmt = stmt.limit(limit)
    items: list[ImportResultItem] = []
    for discovery in list(db.scalars(stmt)):
        if discovery.discovery_status in {OrganizationDiscoveryStatus.imported, OrganizationDiscoveryStatus.already_mapped} or discovery.central_organization_id:
            items.append(ImportResultItem(product_organization_id=discovery.product_organization_id, status="skipped", message="Already mapped or imported"))
            continue
        if discovery.discovery_status in {OrganizationDiscoveryStatus.conflict, OrganizationDiscoveryStatus.missing_required_data}:
            items.append(ImportResultItem(product_organization_id=discovery.product_organization_id, status="skipped", message=f"Discovery status is {discovery.discovery_status.value}"))
            continue
        if _mapping_for_external_id(db, product_id, discovery.product_organization_id):
            discovery.discovery_status = OrganizationDiscoveryStatus.already_mapped
            items.append(ImportResultItem(product_organization_id=discovery.product_organization_id, status="skipped", message="External ID already mapped"))
            continue
        organization = _organization_from_discovery(product, discovery)
        db.add(organization)
        db.flush()
        mapping = OrganizationMapping(
            organization_id=organization.id,
            product_deployment_id=product.id,
            product_organization_id=discovery.product_organization_id,
            product_api_version=discovery.product_api_version or product.admin_api_version,
            mapping_status=MappingStatus.requires_manual_review,
        )
        db.add(mapping)
        discovery.discovery_status = OrganizationDiscoveryStatus.imported
        discovery.central_organization_id = organization.id
        _audit(
            db,
            admin,
            "product.organization.imported",
            product.id,
            {"product_organization_id": discovery.product_organization_id, "organization_id": str(organization.id)},
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            items.append(ImportResultItem(product_organization_id=discovery.product_organization_id, status="conflict", message="External ID is already mapped"))
            continue
        organization = get_organization(db, organization.id)
        if organization is not None:
            mapping, _success, _message = await verify_mapping(db, organization, admin)
            items.append(ImportResultItem(product_organization_id=discovery.product_organization_id, status="imported", organization_id=organization.id, mapping_status=mapping.mapping_status.value))
    return ImportResult(items=items).model_dump(mode="json")
