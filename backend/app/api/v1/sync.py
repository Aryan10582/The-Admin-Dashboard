from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.admin import Admin
from app.services.sync_service import sync_status

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
async def sync_status_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": sync_status(db)}
