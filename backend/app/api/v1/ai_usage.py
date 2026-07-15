from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.enums import AiUsageConflictStatus, AiUsageFinalizationStatus, AiUsageMappingResolutionStatus, AiUsagePricingResolutionStatus
from app.core.idempotency import require_idempotency_key
from app.models.admin import Admin
from app.schemas.ai_usage import AIUsageBatchResolveMappingsRequest, AIUsageBatchResolvePricingRequest, AIUsageConflictReviewRequest, AIUsageResolvePricingRequest
from app.services.ai_usage_service import (
    UsageFilters,
    get_conflict_detail,
    get_usage,
    list_usage,
    mark_conflict_reviewed,
    resolve_missing_mappings,
    resolve_missing_pricing,
    resolve_usage_pricing,
    summarize_usage,
)

router = APIRouter(prefix="/ai/usage", tags=["ai-usage"])


def _filters(
    product_deployment_id: UUID | None,
    organization_id: UUID | None,
    product_organization_id: str | None,
    provider: str | None,
    product_model_id: str | None,
    usage_from: datetime | None,
    usage_to: datetime | None,
    pricing_catalog_id: UUID | None = None,
    pricing_version_id: UUID | None = None,
    cost_currency: str | None = None,
    pricing_resolution_status: AiUsagePricingResolutionStatus | None = None,
    mapping_resolution_status: AiUsageMappingResolutionStatus | None = None,
    conflict_status: AiUsageConflictStatus | None = None,
    finalization_status: AiUsageFinalizationStatus | None = None,
    product_usage_id: str | None = None,
) -> UsageFilters:
    return UsageFilters(
        product_deployment_id=product_deployment_id,
        organization_id=organization_id,
        product_organization_id=product_organization_id,
        provider=provider,
        product_model_id=product_model_id,
        usage_from=usage_from,
        usage_to=usage_to,
        pricing_catalog_id=pricing_catalog_id,
        pricing_version_id=pricing_version_id,
        cost_currency=cost_currency,
        pricing_resolution_status=pricing_resolution_status,
        mapping_resolution_status=mapping_resolution_status,
        conflict_status=conflict_status,
        finalization_status=finalization_status,
        product_usage_id=product_usage_id,
    )


@router.get("")
async def ai_usage_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    product_deployment_id: UUID | None = None,
    organization_id: UUID | None = None,
    product_organization_id: str | None = None,
    provider: str | None = None,
    product_model_id: str | None = None,
    usage_from: datetime | None = None,
    usage_to: datetime | None = None,
    pricing_catalog_id: UUID | None = None,
    pricing_version_id: UUID | None = None,
    cost_currency: str | None = None,
    pricing_resolution_status: AiUsagePricingResolutionStatus | None = None,
    mapping_resolution_status: AiUsageMappingResolutionStatus | None = None,
    conflict_status: AiUsageConflictStatus | None = None,
    finalization_status: AiUsageFinalizationStatus | None = None,
    product_usage_id: str | None = None,
) -> dict:
    payload = list_usage(
        db,
        _filters(product_deployment_id, organization_id, product_organization_id, provider, product_model_id, usage_from, usage_to, pricing_catalog_id, pricing_version_id, cost_currency, pricing_resolution_status, mapping_resolution_status, conflict_status, finalization_status, product_usage_id),
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.get("/summary")
async def ai_usage_summary(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    product_deployment_id: UUID | None = None,
    organization_id: UUID | None = None,
    product_organization_id: str | None = None,
    provider: str | None = None,
    product_model_id: str | None = None,
    usage_from: datetime | None = None,
    usage_to: datetime | None = None,
) -> dict:
    payload = summarize_usage(db, _filters(product_deployment_id, organization_id, product_organization_id, provider, product_model_id, usage_from, usage_to))
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.post("/resolve-missing-pricing")
async def ai_usage_resolve_missing_pricing(
    payload: AIUsageBatchResolvePricingRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": resolve_missing_pricing(db, payload, idempotency_key, current_admin)}


@router.post("/resolve-mappings")
async def ai_usage_resolve_mappings(
    payload: AIUsageBatchResolveMappingsRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": resolve_missing_mappings(db, payload, idempotency_key, current_admin)}


@router.get("/{usage_id}")
async def ai_usage_detail(
    usage_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_usage(db, usage_id).model_dump(mode="json")}


@router.post("/{usage_id}/resolve-pricing")
async def ai_usage_resolve_pricing(
    usage_id: UUID,
    payload: AIUsageResolvePricingRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": resolve_usage_pricing(db, usage_id, payload, idempotency_key, current_admin)}


@router.get("/{usage_id}/conflict")
async def ai_usage_conflict_detail(
    usage_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_conflict_detail(db, usage_id).model_dump(mode="json")}


@router.post("/{usage_id}/conflict/mark-reviewed")
async def ai_usage_conflict_mark_reviewed(
    usage_id: UUID,
    payload: AIUsageConflictReviewRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": mark_conflict_reviewed(db, usage_id, payload, idempotency_key, current_admin)}
