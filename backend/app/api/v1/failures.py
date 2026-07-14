from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.enums import FailureStatus
from app.models.admin import Admin
from app.services.sync_service import FailureFilters, list_failures

router = APIRouter(prefix="/failures", tags=["failures"])


@router.get("")
async def failures_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    product_deployment_id: UUID | None = None,
    organization_id: UUID | None = None,
    pending_change_id: UUID | None = None,
    action: str | None = None,
    failure_category: str | None = None,
    status: FailureStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    items, total = list_failures(
        db,
        FailureFilters(
            product_deployment_id=product_deployment_id,
            organization_id=organization_id,
            pending_change_id=pending_change_id,
            action=action,
            failure_category=failure_category,
            status=status,
            date_from=date_from,
            date_to=date_to,
        ),
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": {"items": items, "total": total, "limit": limit, "offset": offset}}
