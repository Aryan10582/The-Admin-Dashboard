from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.enums import BillingTransactionType, Environment
from app.models.admin import Admin
from app.schemas.billing import BillingLedgerEntryRead, LedgerListResponse
from app.services.billing_service import LedgerFilters, list_ledger

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/ledger")
async def billing_ledger(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    organization_id: UUID | None = None,
    product_deployment_id: UUID | None = None,
    product_name: str | None = None,
    region: str | None = None,
    environment: Environment | None = None,
    currency: str | None = None,
    transaction_type: BillingTransactionType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    items, total = list_ledger(
        db,
        LedgerFilters(
            organization_id=organization_id,
            product_deployment_id=product_deployment_id,
            product_name=product_name,
            region=region,
            environment=environment,
            currency=currency,
            transaction_type=transaction_type,
            date_from=date_from,
            date_to=date_to,
        ),
        limit=limit,
        offset=offset,
    )
    payload = LedgerListResponse(
        items=[BillingLedgerEntryRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}
