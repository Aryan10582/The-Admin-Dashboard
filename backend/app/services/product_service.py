from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.enums import AuditResultStatus, FailureStatus, IdempotencyRecordStatus, ProductHealthStatus
from app.core.product_secrets import decrypt_product_secret, encrypt_product_secret
from app.integrations.product_admin_client import ProductHealthResult
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingLedgerEntry, BillingPlan, BillingPlanVersion, ManualPayment, OrganizationPlanAssignment
from app.models.discovery import ProductOrganizationDiscovery
from app.models.failure_log import FailureLog
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization, OrganizationMapping
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.models.service_enforcement import ServiceEnforcementRule
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
        "organization_list_path": product.organization_list_path,
        "organization_detail_path_template_configured": bool(product.organization_detail_path_template),
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


def product_dependency_summary(db: Session, product_id: UUID) -> dict:
    org_ids = list(db.scalars(select(Organization.id).where(Organization.product_deployment_id == product_id)))
    return {
        "organizations": len(org_ids),
        "mappings": db.scalar(select(func.count()).select_from(OrganizationMapping).where(OrganizationMapping.product_deployment_id == product_id)) or 0,
        "discovered_organizations": db.scalar(select(func.count()).select_from(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product_id)) or 0,
        "ledger_entries": db.scalar(select(func.count()).select_from(BillingLedgerEntry).where(BillingLedgerEntry.product_deployment_id == product_id)) or 0,
        "manual_payments": db.scalar(select(func.count()).select_from(ManualPayment).where(ManualPayment.product_deployment_id == product_id)) or 0,
        "billing_plans": db.scalar(select(func.count()).select_from(BillingPlan).where(BillingPlan.product_deployment_id == product_id)) or 0,
        "billing_plan_versions": db.scalar(
            select(func.count())
            .select_from(BillingPlanVersion)
            .join(BillingPlan, BillingPlan.id == BillingPlanVersion.billing_plan_id)
            .where(BillingPlan.product_deployment_id == product_id)
        )
        or 0,
        "plan_assignments": db.scalar(select(func.count()).select_from(OrganizationPlanAssignment).where(OrganizationPlanAssignment.organization_id.in_(org_ids))) if org_ids else 0,
        "pending_changes": db.scalar(select(func.count()).select_from(PendingProductChange).where(PendingProductChange.product_deployment_id == product_id)) or 0,
        "failure_logs": db.scalar(select(func.count()).select_from(FailureLog).where(FailureLog.product_deployment_id == product_id)) or 0,
        "audit_logs": db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.product_deployment_id == product_id)) or 0,
        "idempotency_records": db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.organization_id.in_(org_ids))) if org_ids else 0,
        "service_rules": db.scalar(select(func.count()).select_from(ServiceEnforcementRule).where(ServiceEnforcementRule.organization_id.in_(org_ids))) if org_ids else 0,
    }


def test_purge_preview(db: Session, product: ProductDeployment) -> dict:
    return {
        "enabled": settings.environment != "production" and settings.allow_destructive_test_purge,
        "environment": settings.environment,
        "remote_product_deleted": False,
        "dependency_summary": product_dependency_summary(db, product.id),
        "confirmation_required": [product.product_name, str(product.id)],
    }


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


def delete_product_if_unused(db: Session, product: ProductDeployment, admin: Admin) -> dict:
    summary = product_dependency_summary(db, product.id)
    if any(summary.values()):
        _add_audit_log(
            db,
            admin_id=admin.id,
            action="product.delete_blocked",
            product_id=product.id,
            result_status=AuditResultStatus.failure,
            new_value={"dependency_summary": summary},
            failure_message="Product deployment has dependent Admin Dashboard records",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Product deployment has dependencies; archive/deactivate instead", "dependency_summary": summary},
        )
    deleted_product_snapshot = _safe_product_snapshot(product)
    db.delete(product)
    db.flush()
    db.add(
        AuditLog(
            admin_id=admin.id,
            action="product.deleted",
            product_deployment_id=None,
            new_value=deleted_product_snapshot,
            result_status=AuditResultStatus.success,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return {"deleted": True, "dependency_summary": summary}


def purge_test_product_data(db: Session, product: ProductDeployment, *, reason: str, confirmation: str, idempotency_key: str, admin: Admin) -> dict:
    if settings.environment == "production" or not settings.allow_destructive_test_purge:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Destructive test purge is disabled")
    if "prod" in settings.database_url.lower() or "production" in settings.database_url.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Destructive test purge refuses production-looking database configuration")
    if confirmation not in {product.product_name, str(product.id)}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Confirmation must match product name or deployment ID")
    if not reason.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reason is required")
    replay = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == idempotency_key))
    if replay is not None and replay.response_json is not None:
        return replay.response_json

    summary = product_dependency_summary(db, product.id)
    org_ids = list(db.scalars(select(Organization.id).where(Organization.product_deployment_id == product.id)))
    record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        action_type=f"product.purge_test_data:{product.id}",
        response_json=None,
        status=IdempotencyRecordStatus.started,
        created_at=datetime.now(timezone.utc),
        admin_id=admin.id,
        organization_id=None,
    )
    db.add(record)
    for model, condition in (
        (ServiceEnforcementRule, ServiceEnforcementRule.organization_id.in_(org_ids) if org_ids else None),
        (BillingLedgerEntry, BillingLedgerEntry.product_deployment_id == product.id),
        (ManualPayment, ManualPayment.product_deployment_id == product.id),
        (PendingProductChange, PendingProductChange.product_deployment_id == product.id),
        (ProductOrganizationDiscovery, ProductOrganizationDiscovery.product_deployment_id == product.id),
        (OrganizationPlanAssignment, OrganizationPlanAssignment.organization_id.in_(org_ids) if org_ids else None),
        (OrganizationMapping, OrganizationMapping.product_deployment_id == product.id),
        (FailureLog, FailureLog.product_deployment_id == product.id),
        (AuditLog, AuditLog.product_deployment_id == product.id),
        (IdempotencyRecord, IdempotencyRecord.organization_id.in_(org_ids) if org_ids else None),
        (Organization, Organization.product_deployment_id == product.id),
        (BillingPlanVersion, BillingPlanVersion.billing_plan_id.in_(select(BillingPlan.id).where(BillingPlan.product_deployment_id == product.id))),
        (BillingPlan, BillingPlan.product_deployment_id == product.id),
    ):
        if condition is not None:
            for row in list(db.scalars(select(model).where(condition))):
                db.delete(row)
    payload = {"purged": True, "dependency_summary": summary, "remote_product_deleted": False}
    record.status = IdempotencyRecordStatus.completed
    record.response_json = payload
    db.delete(product)
    db.commit()
    return payload


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
