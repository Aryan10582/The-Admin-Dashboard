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
    OrganizationLinkFromProductRequest,
    OrganizationListResponse,
    OrganizationMappingRead,
    OrganizationMappingUpdate,
    ProductOrganizationLookupRead,
    ProductOrganizationLookupRequest,
    OrganizationRead,
    OrganizationUpdate,
)
from app.schemas.billing import AddCreditsRequest, DeductCreditsRequest, LedgerListResponse, ManualPaymentRequest, BillingLedgerEntryRead
from app.schemas.billing import PlanAssignmentRequest
from app.schemas.service_enforcement import ReasonRequest, ServiceEnforcementUpdate
from app.services.billing_service import (
    LedgerFilters,
    add_credits,
    deduct_credits,
    get_billing_summary,
    list_ledger,
    record_manual_payment,
)
from app.services.ai_usage_service import UsageFilters, list_usage
from app.services.organization_service import (
    OrganizationFilters,
    create_organization,
    get_mapping,
    get_organization,
    fetch_product_organization_for_link,
    link_organization_from_product,
    list_organizations,
    update_organization,
    upsert_mapping,
    verify_mapping,
)
from app.services.plan_service import assign_plan_version, get_organization_plan_assignment, list_organization_plan_history
from app.services.service_enforcement import apply_service_action, get_service_enforcement, update_service_enforcement_config
from app.services.sync_service import sync_organization

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


@router.post("/product-lookup")
async def organizations_product_lookup(
    payload: ProductOrganizationLookupRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    lookup = await fetch_product_organization_for_link(db, payload, current_admin)
    return {"success": True, "data": ProductOrganizationLookupRead.model_validate(lookup).model_dump(mode="json")}


@router.post("/link-from-product", status_code=status.HTTP_201_CREATED)
async def organizations_link_from_product(
    payload: OrganizationLinkFromProductRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    organization, verification_success, verification_message = await link_organization_from_product(db, payload, current_admin)
    return {
        "success": True,
        "data": _serialize_organization(organization),
        "meta": {"verification_success": verification_success, "verification_message": verification_message},
    }


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


@router.get("/{organization_id}/ai-usage")
async def organizations_ai_usage(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return {"success": True, "data": list_usage(db, UsageFilters(organization_id=organization_id), limit=limit, offset=offset).model_dump(mode="json")}


@router.get("/{organization_id}/plan-assignment")
async def organizations_plan_assignment(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_organization_plan_assignment(db, organization_id).model_dump(mode="json")}


@router.post("/{organization_id}/plan-assignment")
async def organizations_plan_assignment_create(
    organization_id: UUID,
    payload: PlanAssignmentRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": assign_plan_version(db, organization_id, payload, idempotency_key, current_admin)}


@router.get("/{organization_id}/plan-assignment-history")
async def organizations_plan_assignment_history(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": [item.model_dump(mode="json") for item in list_organization_plan_history(db, organization_id)]}


@router.post("/{organization_id}/sync")
async def organizations_sync(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": await sync_organization(db, organization_id, current_admin)}


@router.get("/{organization_id}/service-enforcement")
async def organizations_service_enforcement(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_service_enforcement(db, organization_id)}


@router.patch("/{organization_id}/service-enforcement")
async def organizations_service_enforcement_update(
    organization_id: UUID,
    payload: ServiceEnforcementUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": update_service_enforcement_config(db, organization_id)}


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


@router.post("/{organization_id}/service/pause")
async def organizations_service_pause(
    organization_id: UUID,
    payload: ReasonRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": apply_service_action(db, organization_id=organization_id, action="service.pause", reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


@router.post("/{organization_id}/service/resume")
async def organizations_service_resume(
    organization_id: UUID,
    payload: ReasonRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": apply_service_action(db, organization_id=organization_id, action="service.resume", reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


@router.post("/{organization_id}/service/disable")
async def organizations_service_disable(
    organization_id: UUID,
    payload: ReasonRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": apply_service_action(db, organization_id=organization_id, action="service.disable", reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


@router.post("/{organization_id}/manual-continuation/apply")
async def organizations_manual_continuation_apply(
    organization_id: UUID,
    payload: ReasonRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": apply_service_action(db, organization_id=organization_id, action="service.manual_continuation.apply", reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


@router.post("/{organization_id}/manual-continuation/remove")
async def organizations_manual_continuation_remove(
    organization_id: UUID,
    payload: ReasonRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": apply_service_action(db, organization_id=organization_id, action="service.manual_continuation.remove", reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


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
