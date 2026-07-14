from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.admin import Admin
from app.schemas.product import ProductDeploymentCreate, ProductDeploymentRead, ProductDeploymentUpdate, ProductHealthCheckRead
from app.services.product_service import create_product, get_product, list_products, run_product_health_check, update_product

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
    return {"success": True, "data": _serialize_product(product)}


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
