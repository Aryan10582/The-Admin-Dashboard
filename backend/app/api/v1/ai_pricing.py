from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.idempotency import require_idempotency_key
from app.models.admin import Admin
from app.core.enums import AiPriceCheckStatus
from app.schemas.ai_pricing import (
    AiPriceCheckReviewRequest,
    AiPriceCheckRunListResponse,
    AiPricingCatalogCreate,
    AiPricingCatalogListResponse,
    AiPricingCatalogUpdate,
    AiPricingSyncCheckRequest,
    AiPricingVersionCreate,
)
from app.services.ai_pricing_check_service import CheckRunFilters, approve_check_run, get_check_run, list_check_runs, reject_check_run, run_pricing_sync_check
from app.services.ai_pricing_catalog_service import (
    AiPricingFilters,
    create_pricing_catalog,
    create_pricing_version,
    get_pricing_catalog,
    get_pricing_version,
    list_pricing_catalogs,
    list_pricing_versions,
    update_pricing_catalog,
)

router = APIRouter(prefix="/ai/pricing", tags=["ai-pricing"])


@router.get("")
async def pricing_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    provider: str | None = None,
    provider_model_id: str | None = None,
    pricing_scope_code: str | None = None,
    currency: str | None = None,
    is_active: bool | None = None,
    has_current_version: bool | None = None,
    has_future_version: bool | None = None,
) -> dict:
    items, total = list_pricing_catalogs(
        db,
        AiPricingFilters(
            search=search,
            provider=provider,
            provider_model_id=provider_model_id,
            pricing_scope_code=pricing_scope_code,
            currency=currency,
            is_active=is_active,
            has_current_version=has_current_version,
            has_future_version=has_future_version,
        ),
        limit=limit,
        offset=offset,
    )
    payload = AiPricingCatalogListResponse(items=items, total=total, limit=limit, offset=offset)
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.post("", status_code=status.HTTP_201_CREATED)
async def pricing_create(
    payload: AiPricingCatalogCreate,
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    result = create_pricing_catalog(db, payload, idempotency_key, current_admin)
    return {"success": True, "data": result if isinstance(result, dict) else result.model_dump(mode="json")}


@router.post("/sync-check")
async def pricing_sync_check(
    payload: AiPricingSyncCheckRequest,
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": run_pricing_sync_check(db, payload, idempotency_key, current_admin)}


@router.get("/check-runs")
async def pricing_check_runs(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    pricing_catalog_id: UUID | None = None,
    provider: str | None = None,
    status_filter: AiPriceCheckStatus | None = Query(default=None, alias="status"),
    reviewed: bool | None = None,
    source_fingerprint: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> dict:
    items, total = list_check_runs(
        db,
        CheckRunFilters(
            pricing_catalog_id=pricing_catalog_id,
            provider=provider,
            status=status_filter,
            reviewed=reviewed,
            source_fingerprint=source_fingerprint,
            started_from=started_from,
            started_to=started_to,
        ),
        limit=limit,
        offset=offset,
    )
    payload = AiPriceCheckRunListResponse(items=items, total=total, limit=limit, offset=offset)
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.get("/check-runs/{check_run_id}")
async def pricing_check_run_detail(
    check_run_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_check_run(db, check_run_id).model_dump(mode="json")}


@router.post("/check-runs/{check_run_id}/approve")
async def pricing_check_run_approve(
    check_run_id: UUID,
    payload: AiPriceCheckReviewRequest,
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": approve_check_run(db, check_run_id, payload, idempotency_key, current_admin)}


@router.post("/check-runs/{check_run_id}/reject")
async def pricing_check_run_reject(
    check_run_id: UUID,
    payload: AiPriceCheckReviewRequest,
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": reject_check_run(db, check_run_id, payload, idempotency_key, current_admin)}


@router.get("/{pricing_id}")
async def pricing_detail(
    pricing_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_pricing_catalog(db, pricing_id).model_dump(mode="json")}


@router.patch("/{pricing_id}")
async def pricing_update(
    pricing_id: UUID,
    payload: AiPricingCatalogUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": update_pricing_catalog(db, pricing_id, payload, current_admin).model_dump(mode="json")}


@router.get("/{pricing_id}/versions")
async def pricing_versions(
    pricing_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": [item.model_dump(mode="json") for item in list_pricing_versions(db, pricing_id)]}


@router.post("/{pricing_id}/versions", status_code=status.HTTP_201_CREATED)
async def pricing_versions_create(
    pricing_id: UUID,
    payload: AiPricingVersionCreate,
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    result = create_pricing_version(db, pricing_id, payload, idempotency_key, current_admin)
    return {"success": True, "data": result if isinstance(result, dict) else result.model_dump(mode="json")}


@router.get("/{pricing_id}/versions/{version_id}")
async def pricing_versions_detail(
    pricing_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_pricing_version(db, pricing_id, version_id).model_dump(mode="json")}
