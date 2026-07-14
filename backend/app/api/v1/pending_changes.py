from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.enums import Environment, PendingChangeStatus
from app.core.idempotency import require_idempotency_key
from app.models.admin import Admin
from app.schemas.pending_change import PendingChangeActionRequest, PendingChangeListResponse
from app.services.service_enforcement import (
    PendingChangeFilters,
    cancel_pending_change,
    get_pending_change,
    list_pending_changes,
    mark_pending_change_manual_resolution,
)
from app.services.sync_service import deliver_pending_change

router = APIRouter(prefix="/pending-changes", tags=["pending-changes"])


@router.get("")
async def pending_changes_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: PendingChangeStatus | None = None,
    action: str | None = None,
    organization_id: UUID | None = None,
    product_deployment_id: UUID | None = None,
    product_name: str | None = None,
    region: str | None = None,
    environment: Environment | None = None,
    admin_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    items, total = list_pending_changes(
        db,
        PendingChangeFilters(
            status=status,
            action=action,
            organization_id=organization_id,
            product_deployment_id=product_deployment_id,
            product_name=product_name,
            region=region,
            environment=environment,
            admin_id=admin_id,
            date_from=date_from,
            date_to=date_to,
        ),
        limit=limit,
        offset=offset,
    )
    payload = PendingChangeListResponse(items=items, total=total, limit=limit, offset=offset)
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.get("/{pending_change_id}")
async def pending_changes_detail(
    pending_change_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_pending_change(db, pending_change_id).model_dump(mode="json")}


@router.post("/{pending_change_id}/cancel")
async def pending_changes_cancel(
    pending_change_id: UUID,
    payload: PendingChangeActionRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": cancel_pending_change(db, pending_change_id, reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


@router.post("/{pending_change_id}/mark-manual-resolution")
async def pending_changes_manual_resolution(
    pending_change_id: UUID,
    payload: PendingChangeActionRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": mark_pending_change_manual_resolution(db, pending_change_id, reason=payload.reason, idempotency_key=idempotency_key, admin=current_admin)}


@router.post("/{pending_change_id}/retry")
async def pending_changes_retry(
    pending_change_id: UUID,
    payload: PendingChangeActionRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {
        "success": True,
        "data": await deliver_pending_change(
            db,
            pending_change_id,
            current_admin,
            retry_reason=payload.reason,
            retry_request_idempotency_key=idempotency_key,
        ),
    }
