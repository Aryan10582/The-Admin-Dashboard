from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.enums import OrganizationDiscoveryStatus
from app.core.idempotency import require_idempotency_key
from app.models.admin import Admin
from app.models.idempotency import IdempotencyRecord
from app.schemas.discovery import DiscoveryListResponse, ImportAllOrganizationsRequest, ImportOrganizationsRequest, ProductOrganizationDiscoveryRead
from app.schemas.ai_usage import ProductAIModelPricingMappingCreate, ProductAIModelPricingMappingUpdate, TokenUsageSyncRequest
from app.schemas.product import ProductDeploymentCreate, ProductDeploymentRead, ProductDeploymentUpdate, ProductHealthCheckRead, ProductPurgeRequest
from app.services.ai_usage_service import UsageFilters, create_model_mapping, get_model_mapping, get_sync_state, list_model_mappings, list_sync_runs, list_usage, sync_token_usage, update_model_mapping
from app.services.discovery_service import DiscoveryFilters, discover_product_organizations, import_discoveries, list_discoveries
from app.services.product_service import create_product, delete_product_if_unused, get_product, list_products, purge_test_product_data, run_product_health_check, test_purge_preview, update_product
from app.services.sync_service import reverify_product_mappings, sync_product

router = APIRouter(prefix="/products", tags=["products"])


def _serialize_product(product) -> dict:
    return ProductDeploymentRead.model_validate(product).model_dump(mode="json")


@router.get("")
async def products_index(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": [_serialize_product(product) for product in list_products(db)]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def products_create(
    payload: ProductDeploymentCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = create_product(db, payload, current_admin)
    discovery = await discover_product_organizations(db, product.id, current_admin) if product.organization_list_path else None
    return {"success": True, "data": _serialize_product(product), "meta": {"organization_discovery": discovery}}


@router.get("/{product_id}")
async def products_detail(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    return {"success": True, "data": _serialize_product(product)}


@router.patch("/{product_id}")
async def products_update(
    product_id: UUID,
    payload: ProductDeploymentUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    product = update_product(db, product, payload, current_admin)
    return {"success": True, "data": _serialize_product(product)}


@router.delete("/{product_id}")
async def products_delete(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    return {"success": True, "data": delete_product_if_unused(db, product, current_admin)}


@router.post("/{product_id}/purge-test-data")
async def products_purge_test_data(
    product_id: UUID,
    payload: ProductPurgeRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    replay = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == idempotency_key,
            IdempotencyRecord.action_type == f"product.purge_test_data:{product_id}",
        )
    )
    if replay is not None and replay.response_json is not None:
        return {"success": True, "data": replay.response_json}
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    return {"success": True, "data": purge_test_product_data(db, product, reason=payload.reason, confirmation=payload.confirmation, idempotency_key=idempotency_key, admin=current_admin)}


@router.get("/{product_id}/purge-test-data/preview")
async def products_purge_test_data_preview(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    return {"success": True, "data": test_purge_preview(db, product)}


@router.post("/{product_id}/health-check")
async def products_health_check(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")

    product = await run_product_health_check(db, product, current_admin)
    payload = ProductHealthCheckRead(
        product=ProductDeploymentRead.model_validate(product),
        health_status=product.health_status,
        response_time_ms=product.last_health_response_time_ms,
        success=product.last_error_message is None,
        error_message=product.last_error_message,
        checked_at=product.last_checked_at,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.post("/{product_id}/sync")
async def products_sync(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": await sync_product(db, product_id, current_admin)}


@router.post("/{product_id}/sync/token-usage")
async def products_sync_token_usage(
    product_id: UUID,
    payload: TokenUsageSyncRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    return {"success": True, "data": await sync_token_usage(db, product_id, payload, idempotency_key, current_admin)}


@router.get("/{product_id}/ai-usage")
async def products_ai_usage(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return {"success": True, "data": list_usage(db, UsageFilters(product_deployment_id=product_id), limit=limit, offset=offset).model_dump(mode="json")}


@router.get("/{product_id}/ai-usage-sync-state")
async def products_ai_usage_sync_state(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    state = get_sync_state(db, product_id)
    return {"success": True, "data": state.model_dump(mode="json") if state is not None else None}


@router.get("/{product_id}/ai-usage-sync-runs")
async def products_ai_usage_sync_runs(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    return {"success": True, "data": list_sync_runs(db, product_id, limit=limit, offset=offset).model_dump(mode="json")}


@router.get("/{product_id}/ai-model-mappings")
async def products_ai_model_mappings(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": [item.model_dump(mode="json") for item in list_model_mappings(db, product_id)]}


@router.post("/{product_id}/ai-model-mappings")
async def products_ai_model_mapping_create(
    product_id: UUID,
    payload: ProductAIModelPricingMappingCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    result = create_model_mapping(db, product_id, payload, idempotency_key, current_admin)
    return {"success": True, "data": result if isinstance(result, dict) else result.model_dump(mode="json")}


@router.get("/{product_id}/ai-model-mappings/{mapping_id}")
async def products_ai_model_mapping_detail(
    product_id: UUID,
    mapping_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": get_model_mapping(db, product_id, mapping_id).model_dump(mode="json")}


@router.patch("/{product_id}/ai-model-mappings/{mapping_id}")
async def products_ai_model_mapping_update(
    product_id: UUID,
    mapping_id: UUID,
    payload: ProductAIModelPricingMappingUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    result = update_model_mapping(db, product_id, mapping_id, payload, idempotency_key, current_admin)
    return {"success": True, "data": result if isinstance(result, dict) else result.model_dump(mode="json")}


@router.post("/{product_id}/sync/health")
async def products_sync_health(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    product = await run_product_health_check(db, product, current_admin)
    return {"success": True, "data": _serialize_product(product)}


@router.post("/{product_id}/sync/organizations")
async def products_sync_organizations(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": await reverify_product_mappings(db, product_id, current_admin)}


@router.post("/{product_id}/organizations/discover")
async def products_discover_organizations(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {"success": True, "data": await discover_product_organizations(db, product_id, current_admin)}


@router.get("/{product_id}/organizations/discovered")
async def products_discovered_organizations(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: OrganizationDiscoveryStatus | None = Query(default=None, alias="status"),
    search: str | None = None,
    product_organization_id: str | None = None,
    product_active_status: bool | None = None,
) -> dict:
    items, total = list_discoveries(
        db,
        product_id,
        DiscoveryFilters(
            status=status_filter,
            search=search,
            product_organization_id=product_organization_id,
            product_active_status=product_active_status,
        ),
        limit=limit,
        offset=offset,
    )
    payload = DiscoveryListResponse(
        items=[ProductOrganizationDiscoveryRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": payload.model_dump(mode="json")}


@router.post("/{product_id}/organizations/import")
async def products_import_organizations(
    product_id: UUID,
    payload: ImportOrganizationsRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    return {
        "success": True,
        "data": await import_discoveries(
            db,
            product_id,
            current_admin,
            discovery_ids=payload.discovery_ids,
            product_organization_ids=payload.product_organization_ids,
        ),
    }


@router.post("/{product_id}/organizations/import-all")
async def products_import_all_organizations(
    product_id: UUID,
    payload: ImportAllOrganizationsRequest,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> dict:
    product = get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    if payload.confirm != product.product_name and payload.confirm != str(product.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Confirmation must match product name or deployment ID")
    return {"success": True, "data": await import_discoveries(db, product_id, current_admin, limit=payload.limit)}
