from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import AuditResultStatus, FailureStatus, ProductHealthStatus
from app.core.product_secrets import decrypt_product_secret, encrypt_product_secret
from app.integrations.product_admin_client import ProductHealthResult
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.failure_log import FailureLog
from app.models.product import ProductDeployment
from app.schemas.product import ProductDeploymentCreate, ProductDeploymentUpdate
from app.services.product_client import build_product_client


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.split())[:500]


def _safe_product_snapshot(product: ProductDeployment) -> dict:
    return {
        "id": str(product.id),
        "product_name": product.product_name,
        "region": product.region,
        "environment": product.environment.value,
        "currency": product.currency,
        "api_base_url": product.api_base_url,
        "health_check_url": product.health_check_url,
        "admin_api_version": product.admin_api_version,
        "is_active": product.is_active,
        "is_under_maintenance": product.is_under_maintenance,
        "health_status": product.health_status.value,
        "sync_status": product.sync_status.value,
        "secret_configured": product.secret_configured,
    }


def _add_audit_log(
    db: Session,
    *,
    admin_id: UUID,
    action: str,
    product_id: UUID,
    result_status: AuditResultStatus = AuditResultStatus.success,
    old_value: dict | None = None,
    new_value: dict | None = None,
    failure_message: str | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            product_deployment_id=product_id,
            old_value=old_value,
            new_value=new_value,
            result_status=result_status,
            failure_message=_safe_error(failure_message),
            created_at=datetime.now(timezone.utc),
        )
    )


def _add_failure_log(
    db: Session,
    *,
    admin_id: UUID,
    product: ProductDeployment,
    category: str,
    message: str,
) -> None:
    db.add(
        FailureLog(
            product_deployment_id=product.id,
            action_attempted="product.health_check",
            error_message=_safe_error(message) or "Product health check failed",
            error_code=category,
            retry_count=0,
            current_status=FailureStatus.open,
            admin_id=admin_id,
            product_api_version=product.admin_api_version,
            created_at=datetime.now(timezone.utc),
        )
    )


def list_products(db: Session) -> list[ProductDeployment]:
    return list(db.scalars(select(ProductDeployment).order_by(ProductDeployment.created_at.desc())))


def get_product(db: Session, product_id: UUID) -> ProductDeployment | None:
    return db.get(ProductDeployment, product_id)


def create_product(db: Session, payload: ProductDeploymentCreate, admin: Admin) -> ProductDeployment:
    product_data = payload.model_dump()
    secret = product_data.pop("admin_api_secret", None)
    product = ProductDeployment(**product_data)
    if secret is not None:
        product.admin_api_secret_encrypted = encrypt_product_secret(secret)
    if product.is_under_maintenance:
        product.health_status = ProductHealthStatus.under_maintenance

    db.add(product)
    db.flush()
    _add_audit_log(
        db,
        admin_id=admin.id,
        action="product.created",
        product_id=product.id,
        new_value=_safe_product_snapshot(product),
    )
    db.commit()
    db.refresh(product)
    return product


def update_product(db: Session, product: ProductDeployment, payload: ProductDeploymentUpdate, admin: Admin) -> ProductDeployment:
    old_value = _safe_product_snapshot(product)
    update_data = payload.model_dump(exclude_unset=True)
    secret = update_data.pop("admin_api_secret", None)
    for field, value in update_data.items():
        setattr(product, field, value)
    if secret is not None:
        product.admin_api_secret_encrypted = encrypt_product_secret(secret)

    if product.is_under_maintenance:
        product.health_status = ProductHealthStatus.under_maintenance

    db.flush()
    _add_audit_log(
        db,
        admin_id=admin.id,
        action="product.updated",
        product_id=product.id,
        old_value=old_value,
        new_value=_safe_product_snapshot(product),
    )
    db.commit()
    db.refresh(product)
    return product


def classify_health(product: ProductDeployment, result: ProductHealthResult) -> ProductHealthStatus:
    if product.is_under_maintenance:
        return ProductHealthStatus.under_maintenance
    if not result.is_success:
        if result.error_category == "timeout":
            return ProductHealthStatus.not_responding
        return ProductHealthStatus.down
    if result.response_time_ms is not None and result.response_time_ms >= settings.product_health_slow_threshold_ms:
        return ProductHealthStatus.slow
    return ProductHealthStatus.healthy


async def run_product_health_check(db: Session, product: ProductDeployment, admin: Admin) -> ProductDeployment:
    client = build_product_client(product, api_secret=decrypt_product_secret(product.admin_api_secret_encrypted))
    result = await client.health_check()
    checked_at = datetime.now(timezone.utc)
    status = classify_health(product, result)

    product.health_status = status
    product.last_checked_at = checked_at
    product.last_health_response_time_ms = result.response_time_ms

    if result.is_success:
        product.last_successful_health_check_at = checked_at
        product.last_error_message = None
    else:
        product.last_error_message = _safe_error(result.error_message)
        _add_failure_log(
            db,
            admin_id=admin.id,
            product=product,
            category=result.error_category or "unknown",
            message=result.error_message or "Product health check failed",
        )

    _add_audit_log(
        db,
        admin_id=admin.id,
        action="product.health_check",
        product_id=product.id,
        result_status=AuditResultStatus.success if result.is_success else AuditResultStatus.failure,
        new_value={
            "product_deployment_id": str(product.id),
            "health_status": status.value,
            "response_time_ms": result.response_time_ms,
            "success": result.is_success,
            "checked_at": checked_at.isoformat(),
        },
        failure_message=result.error_message if not result.is_success else None,
    )

    db.commit()
    db.refresh(product)
    return product
