from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.idempotency import require_idempotency_key
from app.core.database import get_db
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
from app.models.admin import Admin
from app.schemas.organization import (
    MappingVerificationRead,
    OrganizationCreate,
    OrganizationListResponse,
    OrganizationMappingRead,
    OrganizationMappingUpdate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.schemas.billing import AddCreditsRequest, DeductCreditsRequest, LedgerListResponse, ManualPaymentRequest, BillingLedgerEntryRead
from app.services.billing_service import (
    LedgerFilters,
    add_credits,
    deduct_credits,
    get_billing_summary,
    list_ledger,
    record_manual_payment,
)
from app.services.organization_service import (
    OrganizationFilters,
    create_organization,
    get_mapping,
    get_organization,
    list_organizations,
    update_organization,
    upsert_mapping,
    verify_mapping,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _serialize_organization(organization) -> dict:
    return OrganizationRead.model_validate(organization).model_dump(mode="json")


def _serialize_mapping(mapping) -> dict:
    return OrganizationMappingRead.model_validate(mapping).model_dump(mode="json")


@router.get("")
async def organizations_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    product_deployment_id: UUID | None = None,
    product_name: str | None = None,
    region: str | None = None,
    environment: Environment | None = None,
    currency: str | None = None,
    lifecycle_status: OrganizationLifecycleStatus | None = None,
    billing_mode: BillingMode | None = None,
    billing_calculation_status: BillingCalculationStatus | None = None,
    credit_status: CreditStatus | None = None,
    service_status: ServiceStatus | None = None,
    sync_status: SyncStatus | None = None,
    mapping_status: MappingStatus | None = None,
    search: str | None = None,
    last_active_from: datetime | None = None,
    last_active_to: datetime | None = None,
) -> dict:
    filters = OrganizationFilters(
        product_deployment_id=product_deployment_id,
        product_name=product_name,
        region=region,
        environment=environment,
        currency=currency,
        lifecycle_status=lifecycle_status,
        billing_mode=billing_mode,
        billing_calculation_status=billing_calculation_status,
        credit_status=credit_status,
        service_status=service_status,
        sync_status=sync_status,
        mapping_status=mapping_status,
        search=search,
        last_active_from=last_active_from,
        last_active_to=last_active_to,
    )
    organizations, total = list_organizations(db, filters, limit=limit, offset=offset)
    payload = OrganizationListResponse(
        items=[OrganizationRead.model_validate(organization) for organization in organizations],
        total=total,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.post("", status_code=status.HTTP_201_CREATED)
async def organizations_create(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization = create_organization(db, payload, current_admin)
    return {"success": True, "data": _serialize_organization(organization)}


@router.get("/{organization_id}")
async def organizations_detail(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization = get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return {"success": True, "data": _serialize_organization(organization)}


@router.get("/{organization_id}/billing")
async def organizations_billing(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_billing_summary(db, organization_id)}


@router.get("/{organization_id}/ledger")
async def organizations_ledger(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    if get_organization(db, organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    items, total = list_ledger(db, LedgerFilters(organization_id=organization_id), limit=limit, offset=offset)
    payload = LedgerListResponse(
        items=[BillingLedgerEntryRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.patch("/{organization_id}")
async def organizations_update(
    organization_id: UUID,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization = get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    organization = update_organization(db, organization, payload, current_admin)
    return {"success": True, "data": _serialize_organization(organization)}


@router.post("/{organization_id}/credits/add")
async def organizations_add_credits(
    organization_id: UUID,
    payload: AddCreditsRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": add_credits(db, organization_id, payload, idempotency_key, current_admin)}


@router.post("/{organization_id}/credits/deduct")
async def organizations_deduct_credits(
    organization_id: UUID,
    payload: DeductCreditsRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": deduct_credits(db, organization_id, payload, idempotency_key, current_admin)}


@router.post("/{organization_id}/manual-payment")
async def organizations_manual_payment(
    organization_id: UUID,
    payload: ManualPaymentRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": record_manual_payment(db, organization_id, payload, idempotency_key, current_admin)}


@router.get("/{organization_id}/mapping")
async def organizations_mapping_detail(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization = get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    mapping = get_mapping(db, organization)
    return {"success": True, "data": _serialize_mapping(mapping) if mapping is not None else None}


@router.patch("/{organization_id}/mapping")
async def organizations_mapping_update(
    organization_id: UUID,
    payload: OrganizationMappingUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization = get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    mapping = upsert_mapping(db, organization, payload, current_admin)
    return {"success": True, "data": _serialize_mapping(mapping)}


@router.post("/{organization_id}/verify-mapping")
async def organizations_verify_mapping(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization = get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    mapping, success, message = await verify_mapping(db, organization, current_admin)
    payload = MappingVerificationRead(
        mapping=OrganizationMappingRead.model_validate(mapping),
        success=success,
        message=message,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}
