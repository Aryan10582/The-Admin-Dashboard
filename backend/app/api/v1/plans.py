from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.admin import Admin
from app.schemas.billing import BillingPlanCreate, BillingPlanListResponse, BillingPlanUpdate, BillingPlanVersionCreate
from app.services.plan_service import PlanFilters, create_plan, create_plan_version, get_plan, get_plan_version, list_plan_versions, list_plans, update_plan

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("")
async def plans_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    product_deployment_id: UUID | None = None,
    currency: str | None = None,
    is_active: bool | None = None,
) -> dict:
    items, total = list_plans(
        db,
        PlanFilters(search=search, product_deployment_id=product_deployment_id, currency=currency, is_active=is_active),
        limit=limit,
        offset=offset,
    )
    payload = BillingPlanListResponse(items=items, total=total, limit=limit, offset=offset)
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.post("", status_code=status.HTTP_201_CREATED)
async def plans_create(
    payload: BillingPlanCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": create_plan(db, payload, current_admin).model_dump(mode="json")}


@router.get("/{plan_id}")
async def plans_detail(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_plan(db, plan_id).model_dump(mode="json")}


@router.patch("/{plan_id}")
async def plans_update(
    plan_id: UUID,
    payload: BillingPlanUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": update_plan(db, plan_id, payload, current_admin).model_dump(mode="json")}


@router.get("/{plan_id}/versions")
async def plans_versions(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": [item.model_dump(mode="json") for item in list_plan_versions(db, plan_id)]}


@router.post("/{plan_id}/versions", status_code=status.HTTP_201_CREATED)
async def plans_versions_create(
    plan_id: UUID,
    payload: BillingPlanVersionCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": create_plan_version(db, plan_id, payload, current_admin).model_dump(mode="json")}


@router.get("/{plan_id}/versions/{version_id}")
async def plans_versions_detail(
    plan_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_plan_version(db, plan_id, version_id).model_dump(mode="json")}
