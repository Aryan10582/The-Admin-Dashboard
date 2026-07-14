from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.core.enums import AuditResultStatus, FailureStatus, MappingStatus
from app.core.product_secrets import decrypt_product_secret
from app.integrations.product_admin_client import ProductOrganizationLookupResult
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.failure_log import FailureLog
from app.models.organization import Organization, OrganizationMapping
from app.models.product import ProductDeployment
from app.schemas.organization import OrganizationCreate, OrganizationMappingUpdate, OrganizationUpdate
from app.services.product_client import build_product_client


@dataclass(frozen=True)
class OrganizationFilters:
    product_deployment_id: UUID | None = None
    product_name: str | None = None
    region: str | None = None
    environment: object | None = None
    currency: str | None = None
    lifecycle_status: object | None = None
    billing_mode: object | None = None
    billing_calculation_status: object | None = None
    credit_status: object | None = None
    service_status: object | None = None
    sync_status: object | None = None
    mapping_status: object | None = None
    search: str | None = None
    last_active_from: datetime | None = None
    last_active_to: datetime | None = None


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.split())[:500]


def _safe_org_snapshot(organization: Organization, mapping: OrganizationMapping | None = None) -> dict:
    payload = {
        "organization_id": str(organization.id),
        "central_organization_id": organization.central_organization_id,
        "name": organization.name,
        "product_deployment_id": str(organization.product_deployment_id),
        "currency": organization.currency,
        "lifecycle_status": organization.lifecycle_status.value,
        "billing_mode": organization.billing_mode.value,
        "billing_calculation_status": organization.billing_calculation_status.value,
        "credit_status": organization.credit_status.value,
        "service_status": organization.service_status.value,
        "sync_status": organization.sync_status.value,
    }
    if mapping is not None:
        payload["mapping_id"] = str(mapping.id)
        payload["mapping_status"] = mapping.mapping_status.value
        payload["product_organization_id_configured"] = bool(mapping.product_organization_id)
    return payload


def _add_audit(
    db: Session,
    *,
    admin_id: UUID,
    action: str,
    organization_id: UUID | None,
    product_deployment_id: UUID | None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    result_status: AuditResultStatus = AuditResultStatus.success,
    failure_message: str | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            organization_id=organization_id,
            product_deployment_id=product_deployment_id,
            old_value=old_value,
            new_value=new_value,
            result_status=result_status,
            failure_message=_safe_error(failure_message),
            created_at=datetime.now(timezone.utc),
        )
    )


def _add_failure(
    db: Session,
    *,
    admin_id: UUID,
    organization_id: UUID,
    product_deployment_id: UUID,
    action: str,
    code: str,
    message: str,
    product_api_version: str | None = None,
) -> None:
    db.add(
        FailureLog(
            product_deployment_id=product_deployment_id,
            organization_id=organization_id,
            action_attempted=action,
            error_message=_safe_error(message) or "Organization mapping verification failed",
            error_code=code,
            retry_count=0,
            current_status=FailureStatus.open,
            admin_id=admin_id,
            product_api_version=product_api_version,
            created_at=datetime.now(timezone.utc),
        )
    )


def _base_query() -> Select:
    return (
        select(Organization)
        .join(Organization.product_deployment)
        .outerjoin(
            OrganizationMapping,
            (OrganizationMapping.organization_id == Organization.id)
            & (OrganizationMapping.product_deployment_id == Organization.product_deployment_id),
        )
        .options(contains_eager(Organization.product_deployment))
    )


def _apply_filters(stmt: Select, filters: OrganizationFilters) -> Select:
    if filters.product_deployment_id:
        stmt = stmt.where(Organization.product_deployment_id == filters.product_deployment_id)
    if filters.product_name:
        stmt = stmt.where(ProductDeployment.product_name == filters.product_name)
    if filters.region:
        stmt = stmt.where(ProductDeployment.region == filters.region)
    if filters.environment:
        stmt = stmt.where(ProductDeployment.environment == filters.environment)
    if filters.currency:
        stmt = stmt.where(Organization.currency == filters.currency.upper())
    if filters.lifecycle_status:
        stmt = stmt.where(Organization.lifecycle_status == filters.lifecycle_status)
    if filters.billing_mode:
        stmt = stmt.where(Organization.billing_mode == filters.billing_mode)
    if filters.billing_calculation_status:
        stmt = stmt.where(Organization.billing_calculation_status == filters.billing_calculation_status)
    if filters.credit_status:
        stmt = stmt.where(Organization.credit_status == filters.credit_status)
    if filters.service_status:
        stmt = stmt.where(Organization.service_status == filters.service_status)
    if filters.sync_status:
        stmt = stmt.where(Organization.sync_status == filters.sync_status)
    if filters.mapping_status:
        stmt = stmt.where(OrganizationMapping.mapping_status == filters.mapping_status)
    if filters.search:
        term = f"%{filters.search.lower()}%"
        stmt = stmt.where(func.lower(Organization.name).like(term))
    if filters.last_active_from:
        stmt = stmt.where(Organization.last_active_at >= filters.last_active_from)
    if filters.last_active_to:
        stmt = stmt.where(Organization.last_active_at <= filters.last_active_to)
    return stmt


def _mapping_lookup(db: Session, organization: Organization) -> OrganizationMapping | None:
    return db.scalar(
        select(OrganizationMapping).where(
            OrganizationMapping.organization_id == organization.id,
            OrganizationMapping.product_deployment_id == organization.product_deployment_id,
        )
    )


def attach_mapping(db: Session, organization: Organization) -> Organization:
    setattr(organization, "mapping", _mapping_lookup(db, organization))
    return organization


def list_organizations(db: Session, filters: OrganizationFilters, *, limit: int, offset: int) -> tuple[list[Organization], int]:
    filtered = _apply_filters(_base_query(), filters)
    total = db.scalar(select(func.count()).select_from(filtered.subquery())) or 0
    organizations = list(db.scalars(filtered.order_by(Organization.created_at.desc()).limit(limit).offset(offset)).unique())
    for organization in organizations:
        attach_mapping(db, organization)
    return organizations, total


def get_organization(db: Session, organization_id: UUID) -> Organization | None:
    organization = db.scalar(
        select(Organization).where(Organization.id == organization_id).options(joinedload(Organization.product_deployment))
    )
    if organization is not None:
        attach_mapping(db, organization)
    return organization


def create_organization(db: Session, payload: OrganizationCreate, admin: Admin) -> Organization:
    deployment = db.get(ProductDeployment, payload.product_deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    organization = Organization(**payload.model_dump())
    organization.service_enforcement_status = organization.service_status
    db.add(organization)
    db.flush()
    _add_audit(
        db,
        admin_id=admin.id,
        action="organization.created",
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        new_value=_safe_org_snapshot(organization),
    )
    db.commit()
    db.refresh(organization)
    organization.product_deployment = deployment
    return attach_mapping(db, organization)


def update_organization(db: Session, organization: Organization, payload: OrganizationUpdate, admin: Admin) -> Organization:
    old_deployment_id = organization.product_deployment_id
    old_value = _safe_org_snapshot(organization, getattr(organization, "mapping", None))
    update_data = payload.model_dump(exclude_unset=True)
    if "product_deployment_id" in update_data and db.get(ProductDeployment, update_data["product_deployment_id"]) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    for field, value in update_data.items():
        setattr(organization, field, value)
    if "service_status" in update_data:
        organization.service_enforcement_status = organization.service_status
    if old_deployment_id != organization.product_deployment_id:
        mapping = _mapping_lookup(db, organization)
        if mapping is not None:
            mapping.product_deployment_id = organization.product_deployment_id
            mapping.mapping_status = MappingStatus.requires_manual_review
            mapping.last_verified_at = None
    db.flush()
    attach_mapping(db, organization)
    _add_audit(
        db,
        admin_id=admin.id,
        action="organization.updated",
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        old_value=old_value,
        new_value=_safe_org_snapshot(organization, getattr(organization, "mapping", None)),
    )
    db.commit()
    db.refresh(organization)
    return get_organization(db, organization.id) or organization


def get_mapping(db: Session, organization: Organization) -> OrganizationMapping | None:
    return _mapping_lookup(db, organization)


def upsert_mapping(db: Session, organization: Organization, payload: OrganizationMappingUpdate, admin: Admin) -> OrganizationMapping:
    target_deployment_id = payload.product_deployment_id or organization.product_deployment_id
    if target_deployment_id != organization.product_deployment_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mapping deployment must match organization deployment")
    if db.get(ProductDeployment, target_deployment_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")

    mapping = _mapping_lookup(db, organization)
    created = mapping is None
    if mapping is None:
        mapping = OrganizationMapping(
            organization_id=organization.id,
            product_deployment_id=target_deployment_id,
            product_api_version=organization.product_deployment.admin_api_version,
            mapping_status=MappingStatus.requires_manual_review,
        )
        db.add(mapping)

    old_value = _safe_org_snapshot(organization, mapping)
    update_data = payload.model_dump(exclude_unset=True)
    previous_product_org_id = mapping.product_organization_id
    for field, value in update_data.items():
        if field == "product_deployment_id":
            continue
        setattr(mapping, field, value)

    if previous_product_org_id != mapping.product_organization_id:
        mapping.mapping_status = MappingStatus.requires_manual_review if mapping.product_organization_id else MappingStatus.missing_product_id
        mapping.last_verified_at = None

    db.flush()
    _add_audit(
        db,
        admin_id=admin.id,
        action="organization.mapping.created" if created else "organization.mapping.updated",
        organization_id=organization.id,
        product_deployment_id=mapping.product_deployment_id,
        old_value=None if created else old_value,
        new_value=_safe_org_snapshot(organization, mapping),
    )
    db.commit()
    db.refresh(mapping)
    return mapping


def _mark_verification_failure(
    db: Session,
    *,
    mapping: OrganizationMapping,
    organization: Organization,
    admin: Admin,
    status_value: MappingStatus,
    code: str,
    message: str,
) -> OrganizationMapping:
    mapping.mapping_status = status_value
    if status_value != MappingStatus.active:
        mapping.last_verified_at = None
    _add_failure(
        db,
        admin_id=admin.id,
        organization_id=organization.id,
        product_deployment_id=mapping.product_deployment_id,
        action="organization.mapping.verify",
        code=code,
        message=message,
        product_api_version=mapping.product_api_version,
    )
    return mapping


async def verify_mapping(db: Session, organization: Organization, admin: Admin) -> tuple[OrganizationMapping, bool, str | None]:
    mapping = _mapping_lookup(db, organization)
    if mapping is None:
        mapping = OrganizationMapping(
            organization_id=organization.id,
            product_deployment_id=organization.product_deployment_id,
            product_api_version=organization.product_deployment.admin_api_version,
            mapping_status=MappingStatus.missing_product_id,
        )
        db.add(mapping)

    old_value = _safe_org_snapshot(organization, mapping)
    if not mapping.product_organization_id:
        mapping.mapping_status = MappingStatus.missing_product_id
        mapping.last_verified_at = None
        success = False
        message = "Product-side organization ID is missing"
    else:
        client = build_product_client(
            organization.product_deployment,
            api_secret=decrypt_product_secret(organization.product_deployment.admin_api_secret_encrypted),
        )
        result = await client.get_organization_detail(mapping.product_organization_id)
        mapping, success, message = _apply_verification_result(db, organization, mapping, admin, result)

    _add_audit(
        db,
        admin_id=admin.id,
        action="organization.mapping.verify",
        organization_id=organization.id,
        product_deployment_id=mapping.product_deployment_id,
        old_value=old_value,
        new_value=_safe_org_snapshot(organization, mapping),
        result_status=AuditResultStatus.success if success else AuditResultStatus.failure,
        failure_message=message if not success else None,
    )
    db.commit()
    db.refresh(mapping)
    return mapping, success, message


def _apply_verification_result(
    db: Session,
    organization: Organization,
    mapping: OrganizationMapping,
    admin: Admin,
    result: ProductOrganizationLookupResult,
) -> tuple[OrganizationMapping, bool, str | None]:
    if result.is_success:
        if result.product_organization_id != mapping.product_organization_id:
            _mark_verification_failure(
                db,
                mapping=mapping,
                organization=organization,
                admin=admin,
                status_value=MappingStatus.product_mismatch,
                code="product_mismatch",
                message="Product organization ID did not match the configured mapping",
            )
            return mapping, False, "Product organization ID mismatch"
        if result.product_deployment_id and result.product_deployment_id != str(mapping.product_deployment_id):
            _mark_verification_failure(
                db,
                mapping=mapping,
                organization=organization,
                admin=admin,
                status_value=MappingStatus.product_mismatch,
                code="deployment_mismatch",
                message="Product deployment identity did not match the configured mapping",
            )
            return mapping, False, "Product deployment mismatch"
        mapping.mapping_status = MappingStatus.active
        mapping.last_verified_at = datetime.now(timezone.utc)
        return mapping, True, None

    status_value = MappingStatus.verification_failed
    if result.error_category in {"timeout", "connection_error", "request_error", "invalid_response", "http_error"}:
        status_value = MappingStatus.requires_manual_review
    if result.error_category == "not_found":
        status_value = MappingStatus.verification_failed
    _mark_verification_failure(
        db,
        mapping=mapping,
        organization=organization,
        admin=admin,
        status_value=status_value,
        code=result.error_category or "verification_failed",
        message=result.error_message or "Product organization verification failed",
    )
    return mapping, False, result.error_message


def require_verified_mapping(db: Session, organization_id: UUID, product_deployment_id: UUID) -> OrganizationMapping:
    mapping = db.scalar(
        select(OrganizationMapping).where(
            OrganizationMapping.organization_id == organization_id,
            OrganizationMapping.product_deployment_id == product_deployment_id,
        )
    )
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Verified organization mapping is required")
    if not mapping.product_organization_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product-side organization ID is required")
    if mapping.mapping_status != MappingStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization mapping is not verified")
    organization = db.get(Organization, organization_id)
    if organization is None or organization.product_deployment_id != product_deployment_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization mapping deployment mismatch")
    return mapping
