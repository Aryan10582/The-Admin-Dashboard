from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AuditResultStatus, FailureStatus, IdempotencyRecordStatus, MappingStatus, PendingChangeStatus, ProductHealthStatus, SyncStatus
from app.core.product_secrets import ProductSecretEncryptionError, decrypt_product_secret
from app.integrations.product_admin_client import ProductDeliveryResult
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.failure_log import FailureLog
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization, OrganizationMapping
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.services.product_client import build_product_client
from app.services.product_service import run_product_health_check
from app.services.plan_service import confirm_assignment_from_product

ELIGIBLE_STATUSES = {PendingChangeStatus.saved, PendingChangeStatus.failed, PendingChangeStatus.pending_retry}
BLOCKING_STATUSES = {
    PendingChangeStatus.saved,
    PendingChangeStatus.failed,
    PendingChangeStatus.pending_retry,
    PendingChangeStatus.sent_to_product,
    PendingChangeStatus.accepted_by_product,
    PendingChangeStatus.requires_manual_resolution,
}
RETRYABLE_ERRORS = {"timeout", "connection_failure", "request_error", "http_failure", "product_down"}
STALE_ATTEMPT_AFTER = timedelta(minutes=15)


@dataclass(frozen=True)
class DeliveryResult:
    pending_change_id: UUID
    action: str
    status: PendingChangeStatus
    product_request_id: str | None
    safe_result: dict | None
    error: str | None = None


@dataclass(frozen=True)
class FailureFilters:
    product_deployment_id: UUID | None = None
    organization_id: UUID | None = None
    pending_change_id: UUID | None = None
    action: str | None = None
    failure_category: str | None = None
    status: FailureStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(message: str | None) -> str:
    return " ".join((message or "Product delivery failed").split())[:500]


def _safe_summary(result: ProductDeliveryResult) -> dict:
    return {
        "success": result.success,
        "product_organization_id": result.product_organization_id,
        "applied_change": result.applied_change,
        "current_product_value": result.current_product_value,
        "product_api_version": result.product_api_version,
        "sync_confirmed": result.sync_confirmed,
        "error_code": result.error_code,
        "safe_error_message": result.safe_error_message,
        "product_request_id": result.product_request_id,
        "idempotency_key": result.idempotency_key,
        "http_status": result.http_status,
        "plan_code": result.plan_code,
        "plan_version_number": result.plan_version_number,
    }


def _delivery_payload(final: DeliveryResult) -> dict:
    return {
        "pending_change_id": str(final.pending_change_id),
        "action": final.action,
        "status": final.status.value,
        "product_request_id": final.product_request_id,
        "safe_result": final.safe_result,
        "error": final.error,
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _is_stale_attempt(change: PendingProductChange) -> bool:
    started_at = _aware(change.delivery_started_at)
    return started_at is not None and _now() - started_at > STALE_ATTEMPT_AFTER


def _supported_flag(product: ProductDeployment, *keys: str) -> bool:
    supported = product.supported_endpoints or {}
    for key in keys:
        value = supported.get(key)
        if value is True:
            return True
        if isinstance(value, dict) and any(item is True for item in value.values()):
            return True
    pending_changes = supported.get("pending_changes")
    if isinstance(pending_changes, dict):
        return any(pending_changes.get(key) is True for key in keys)
    return False


def _product_guarantees_delivery_idempotency(product: ProductDeployment) -> bool:
    return _supported_flag(product, "idempotent_delivery", "delivery_idempotency_guaranteed", "idempotent_writes")


def _product_supports_status_lookup(product: ProductDeployment) -> bool:
    return _supported_flag(product, "pending_change_status_lookup", "status_lookup", "confirmation_lookup")


def _is_retryable_result(product: ProductDeployment, result: ProductDeliveryResult) -> bool:
    if result.error_code == "timeout":
        return _product_guarantees_delivery_idempotency(product)
    return result.error_code in {"connection_failure", "request_error", "http_failure", "product_down"}


def _audit(db: Session, *, admin: Admin, action: str, change: PendingProductChange | None, product_id: UUID | None, result_status: AuditResultStatus, payload: dict, failure_message: str | None = None) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id,
            action=action,
            organization_id=change.organization_id if change else None,
            product_deployment_id=product_id,
            new_value=payload,
            result_status=result_status,
            failure_message=_safe_error(failure_message) if failure_message else None,
            idempotency_key=change.idempotency_key if change else None,
            created_at=_now(),
        )
    )


def _failure(db: Session, *, admin: Admin, change: PendingProductChange | None, product: ProductDeployment | None, category: str, message: str, product_request_id: str | None = None) -> None:
    db.add(
        FailureLog(
            product_deployment_id=product.id if product else (change.product_deployment_id if change else None),
            organization_id=change.organization_id if change else None,
            pending_change_id=change.id if change else None,
            action_attempted=change.action if change else "sync",
            error_message=_safe_error(message),
            error_code=category,
            retry_count=change.retry_count if change else 0,
            current_status=FailureStatus.open,
            idempotency_key=change.idempotency_key if change else None,
            admin_id=admin.id,
            product_api_version=product.admin_api_version if product else None,
            product_request_id=product_request_id,
            created_at=_now(),
        )
    )


def _mapping(db: Session, change: PendingProductChange) -> OrganizationMapping:
    mapping = db.scalar(
        select(OrganizationMapping).where(
            OrganizationMapping.organization_id == change.organization_id,
            OrganizationMapping.product_deployment_id == change.product_deployment_id,
        )
    )
    if mapping is None or mapping.mapping_status != MappingStatus.active or not mapping.product_organization_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Verified mapping is required before delivery")
    return mapping


def _older_blocker(db: Session, change: PendingProductChange) -> PendingProductChange | None:
    if change.organization_id is None:
        return None
    return db.scalar(
        select(PendingProductChange)
        .where(
            PendingProductChange.organization_id == change.organization_id,
            PendingProductChange.product_deployment_id == change.product_deployment_id,
            PendingProductChange.id != change.id,
            PendingProductChange.created_at < change.created_at,
            PendingProductChange.status.in_(BLOCKING_STATUSES),
        )
        .order_by(PendingProductChange.created_at.asc())
        .limit(1)
    )


def _validate_product(product: ProductDeployment) -> None:
    if not product.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product deployment is inactive")
    if product.is_under_maintenance:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product deployment is under maintenance")
    if not product.admin_api_secret_encrypted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product API secret is not configured")


def _retry_action_type(pending_change_id: UUID) -> str:
    return f"pending_change.retry:{pending_change_id}"


def _get_retry_replay(db: Session, key: str, action_type: str, organization_id: UUID | None) -> dict | None:
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))
    if record is None:
        return None
    if record.action_type != action_type:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different action")
    if record.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different organization")
    if record.status == IdempotencyRecordStatus.completed and record.response_json is not None:
        return record.response_json
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress")


def _start_retry_idempotency(db: Session, key: str | None, change: PendingProductChange, admin: Admin) -> IdempotencyRecord | dict | None:
    if key is None:
        return None
    action_type = _retry_action_type(change.id)
    replay = _get_retry_replay(db, key, action_type, change.organization_id)
    if replay is not None:
        return replay
    record = IdempotencyRecord(
        idempotency_key=key,
        action_type=action_type,
        status=IdempotencyRecordStatus.started,
        created_at=_now(),
        admin_id=admin.id,
        organization_id=change.organization_id,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _get_retry_replay(db, key, action_type, change.organization_id)
        if replay is not None:
            return replay
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress") from exc
    return record


def _is_confirmed(change: PendingProductChange, mapping: OrganizationMapping, product: ProductDeployment, result: ProductDeliveryResult) -> bool:
    if not result.success or not result.sync_confirmed:
        return False
    if result.product_organization_id != mapping.product_organization_id:
        return False
    if result.idempotency_key != change.idempotency_key:
        return False
    if result.product_api_version != product.admin_api_version:
        return False
    if result.applied_change != change.action:
        return False
    requested = (change.payload or {}).get("requested_intended_service_status")
    if requested and result.current_product_value and result.current_product_value != requested:
        return False
    requested_plan_code = (change.payload or {}).get("plan_code")
    requested_plan_version = (change.payload or {}).get("plan_version_number")
    if requested_plan_code is not None and result.plan_code != requested_plan_code:
        return False
    if requested_plan_version is not None and result.plan_version_number != requested_plan_version:
        return False
    return True


def _manual_reason(change: PendingProductChange, mapping: OrganizationMapping, product: ProductDeployment, result: ProductDeliveryResult) -> str | None:
    if result.product_organization_id and result.product_organization_id != mapping.product_organization_id:
        return "organization_mismatch"
    if result.idempotency_key and result.idempotency_key != change.idempotency_key:
        return "idempotency_mismatch"
    if result.product_api_version and result.product_api_version != product.admin_api_version:
        return "incompatible_api_version"
    if result.applied_change and result.applied_change != change.action:
        return "contradictory_product_value"
    if result.success and result.sync_confirmed and (
        not result.product_organization_id
        or not result.idempotency_key
        or not result.product_api_version
        or not result.applied_change
    ):
        return "unclear_confirmation"
    requested = (change.payload or {}).get("requested_intended_service_status")
    if requested and result.current_product_value and result.current_product_value != requested:
        return "contradictory_product_value"
    requested_plan_code = (change.payload or {}).get("plan_code")
    requested_plan_version = (change.payload or {}).get("plan_version_number")
    if requested_plan_code is not None and result.plan_code != requested_plan_code:
        return "contradictory_product_value"
    if requested_plan_version is not None and result.plan_version_number != requested_plan_version:
        return "contradictory_product_value"
    if result.success and not result.sync_confirmed:
        return "unclear_confirmation"
    if not _is_retryable_result(product, result):
        if result.error_code == "timeout":
            return "ambiguous_timeout"
        return result.error_code or "unclear_confirmation"
    return None


def _mark_stale_attempt_manual_resolution(db: Session, change: PendingProductChange, product: ProductDeployment, admin: Admin) -> DeliveryResult:
    change.status = PendingChangeStatus.requires_manual_resolution
    change.last_delivery_at = _now()
    change.last_error = "Previous delivery attempt may have reached the product and requires manual confirmation"
    change.safe_confirmation_summary = {
        "success": False,
        "error_code": "stale_delivery_attempt",
        "safe_error_message": change.last_error,
        "delivery_attempt_id": change.delivery_attempt_id,
    }
    product.last_failed_sync_at = change.last_delivery_at
    product.sync_status = SyncStatus.failed
    _failure(
        db,
        admin=admin,
        change=change,
        product=product,
        category="stale_delivery_attempt",
        message=change.last_error,
        product_request_id=change.product_request_id,
    )
    _audit(
        db,
        admin=admin,
        action="pending_change.delivery.stale_manual_resolution",
        change=change,
        product_id=product.id,
        result_status=AuditResultStatus.failure,
        payload=change.safe_confirmation_summary,
        failure_message=change.last_error,
    )
    return DeliveryResult(change.id, change.action, change.status, change.product_request_id, change.safe_confirmation_summary, change.last_error)


def _claim_stale_status_lookup(db: Session, change: PendingProductChange, product: ProductDeployment, admin: Admin, retry_reason: str | None) -> tuple[PendingProductChange, ProductDeployment, OrganizationMapping, str]:
    mapping = _mapping(db, change)
    if _older_blocker(db, change) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Older unresolved pending change blocks delivery")
    attempt_id = str(uuid4())
    change.delivery_attempt_id = attempt_id
    change.delivery_started_at = _now()
    _audit(
        db,
        admin=admin,
        action="pending_change.delivery.status_lookup_claimed",
        change=change,
        product_id=product.id,
        result_status=AuditResultStatus.success,
        payload={"pending_change_id": str(change.id), "attempt_id": attempt_id, "retry_reason": retry_reason},
    )
    db.commit()
    return change, product, mapping, attempt_id


def _recover_or_claim_stale_attempt(db: Session, pending_change_id: UUID, admin: Admin, retry_reason: str | None = None) -> tuple[PendingProductChange, ProductDeployment, OrganizationMapping, str] | DeliveryResult | None:
    change = db.scalar(select(PendingProductChange).where(PendingProductChange.id == pending_change_id).with_for_update(of=PendingProductChange))
    if change is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    if change.status != PendingChangeStatus.sent_to_product:
        return None
    product = db.get(ProductDeployment, change.product_deployment_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    if not _is_stale_attempt(change):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending change delivery is already in progress")
    _validate_product(product)
    if _product_supports_status_lookup(product):
        return _claim_stale_status_lookup(db, change, product, admin, retry_reason)
    return _mark_stale_attempt_manual_resolution(db, change, product, admin)


def _claim(db: Session, pending_change_id: UUID, admin: Admin, retry_reason: str | None = None) -> tuple[PendingProductChange, ProductDeployment, OrganizationMapping, str, int]:
    change = db.get(PendingProductChange, pending_change_id)
    if change is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    change = db.scalar(select(PendingProductChange).where(PendingProductChange.id == pending_change_id).with_for_update(of=PendingProductChange))
    assert change is not None
    if change.status not in ELIGIBLE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending change is not eligible for delivery")
    product = db.get(ProductDeployment, change.product_deployment_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    _validate_product(product)
    mapping = _mapping(db, change)
    if _older_blocker(db, change) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Older unresolved pending change blocks delivery")
    attempt_id = str(uuid4())
    previous_attempts = 1 + change.retry_count if change.last_delivery_at else 0
    if change.last_delivery_at is not None:
        change.retry_count += 1
        change.last_retry_at = _now()
    change.delivery_attempt_id = attempt_id
    change.delivery_started_at = _now()
    change.status = PendingChangeStatus.sent_to_product
    _audit(
        db,
        admin=admin,
        action="pending_change.delivery.claimed",
        change=change,
        product_id=product.id,
        result_status=AuditResultStatus.success,
        payload={"pending_change_id": str(change.id), "attempt_id": attempt_id, "retry_reason": retry_reason},
    )
    db.commit()
    return change, product, mapping, attempt_id, previous_attempts


def _has_unresolved_product_changes(db: Session, product_id: UUID, exclude_change_id: UUID) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(PendingProductChange)
        .where(
            PendingProductChange.product_deployment_id == product_id,
            PendingProductChange.id != exclude_change_id,
            PendingProductChange.status.in_(BLOCKING_STATUSES),
        )
    ) or 0
    return count > 0


def _finalize(
    db: Session,
    pending_change_id: UUID,
    attempt_id: str,
    result: ProductDeliveryResult,
    admin: Admin,
    retry_record_id: UUID | None = None,
) -> DeliveryResult:
    change = db.scalar(select(PendingProductChange).where(PendingProductChange.id == pending_change_id).with_for_update(of=PendingProductChange))
    if change is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    if change.delivery_attempt_id != attempt_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delivery attempt no longer owns this pending change")
    product = db.get(ProductDeployment, change.product_deployment_id)
    assert product is not None
    mapping = _mapping(db, change)
    summary = _safe_summary(result)
    change.last_delivery_at = _now()
    change.product_request_id = result.product_request_id
    change.product_api_version = result.product_api_version or product.admin_api_version
    change.safe_confirmation_summary = summary
    change.last_error = result.safe_error_message

    if _is_confirmed(change, mapping, product, result):
        change.status = PendingChangeStatus.confirmed_and_synced
        change.last_error = None
        confirm_assignment_from_product(db, change, result)
        product.last_successful_sync_at = change.last_delivery_at
        product.sync_status = SyncStatus.pending if _has_unresolved_product_changes(db, product.id, change.id) else SyncStatus.synced
        _audit(db, admin=admin, action="pending_change.delivery.confirmed", change=change, product_id=product.id, result_status=AuditResultStatus.success, payload=summary)
    else:
        manual_reason = _manual_reason(change, mapping, product, result)
        if manual_reason is not None:
            change.status = PendingChangeStatus.requires_manual_resolution
            _failure(db, admin=admin, change=change, product=product, category=manual_reason, message=result.safe_error_message or manual_reason, product_request_id=result.product_request_id)
        elif _is_retryable_result(product, result):
            change.status = PendingChangeStatus.pending_retry
            _failure(db, admin=admin, change=change, product=product, category=result.error_code or "product_down", message=result.safe_error_message or "Temporary product delivery failure", product_request_id=result.product_request_id)
        elif result.success:
            change.status = PendingChangeStatus.accepted_by_product
        else:
            change.status = PendingChangeStatus.requires_manual_resolution
        product.last_failed_sync_at = change.last_delivery_at
        product.sync_status = SyncStatus.failed
        _audit(db, admin=admin, action="pending_change.delivery.failed", change=change, product_id=product.id, result_status=AuditResultStatus.failure, payload=summary, failure_message=change.last_error)
    final = DeliveryResult(change.id, change.action, change.status, change.product_request_id, change.safe_confirmation_summary, change.last_error)
    if retry_record_id is not None:
        record = db.get(IdempotencyRecord, retry_record_id)
        if record is not None:
            record.status = IdempotencyRecordStatus.completed
            record.response_json = _delivery_payload(final)
    db.commit()
    return final


async def deliver_pending_change(
    db: Session,
    pending_change_id: UUID,
    admin: Admin,
    retry_reason: str | None = None,
    retry_request_idempotency_key: str | None = None,
) -> dict:
    existing = db.get(PendingProductChange, pending_change_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    retry_record = _start_retry_idempotency(db, retry_request_idempotency_key, existing, admin)
    if isinstance(retry_record, dict):
        return retry_record
    retry_record_id = retry_record.id if retry_record is not None else None

    stale_lookup_claim = _recover_or_claim_stale_attempt(db, pending_change_id, admin, retry_reason=retry_reason)
    if stale_lookup_claim is not None:
        if isinstance(stale_lookup_claim, DeliveryResult):
            payload = _delivery_payload(stale_lookup_claim)
            if retry_record_id is not None:
                record = db.get(IdempotencyRecord, retry_record_id)
                if record is not None:
                    record.status = IdempotencyRecordStatus.completed
                    record.response_json = payload
            db.commit()
            return payload
        change, product, mapping, attempt_id = stale_lookup_claim
        try:
            secret = decrypt_product_secret(product.admin_api_secret_encrypted)
            client = build_product_client(product, api_secret=secret)
            result = await client.get_pending_change_status(change.idempotency_key or "")
        except ProductSecretEncryptionError:
            result = ProductDeliveryResult(
                success=False,
                error_code="secret_configuration_error",
                safe_error_message="Product API secret could not be used for delivery status lookup",
            )
        except Exception:
            result = ProductDeliveryResult(
                success=False,
                error_code="unexpected_product_client_failure",
                safe_error_message="Product delivery status lookup failed before confirmation",
            )
        final = _finalize(db, change.id, attempt_id, result, admin, retry_record_id=retry_record_id)
        return _delivery_payload(final)

    change, product, mapping, attempt_id, _previous_attempts = _claim(db, pending_change_id, admin, retry_reason=retry_reason)
    try:
        secret = decrypt_product_secret(product.admin_api_secret_encrypted)
        client = build_product_client(product, api_secret=secret)
        result = await client.deliver_pending_change(
            product_organization_id=mapping.product_organization_id or "",
            action=change.action,
            payload=change.payload,
            idempotency_key=change.idempotency_key or "",
            admin_id=str(admin.id),
            reason=change.reason,
        )
    except ProductSecretEncryptionError:
        result = ProductDeliveryResult(
            success=False,
            error_code="secret_configuration_error",
            safe_error_message="Product API secret could not be used for delivery",
        )
    except Exception:
        result = ProductDeliveryResult(
            success=False,
            error_code="unexpected_product_client_failure",
            safe_error_message="Product delivery failed before confirmation",
        )
    final = _finalize(db, change.id, attempt_id, result, admin, retry_record_id=retry_record_id)
    return _delivery_payload(final)


async def sync_organization(db: Session, organization_id: UUID, admin: Admin, *, limit: int = 25) -> dict:
    ids = list(
        db.scalars(
            select(PendingProductChange.id)
            .where(PendingProductChange.organization_id == organization_id, PendingProductChange.status.in_(ELIGIBLE_STATUSES))
            .order_by(PendingProductChange.created_at.asc())
            .limit(limit)
        )
    )
    results = []
    for change_id in ids:
        try:
            results.append(await deliver_pending_change(db, change_id, admin))
        except HTTPException as exc:
            results.append({"pending_change_id": str(change_id), "status": "blocked", "error": str(exc.detail)})
            break
    return {"organization_id": str(organization_id), "results": results}


async def sync_product(db: Session, product_id: UUID, admin: Admin, *, limit: int = 50, run_health: bool = True) -> dict:
    product = db.get(ProductDeployment, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    health = None
    if run_health:
        product = await run_product_health_check(db, product, admin)
        health = {"health_status": product.health_status.value, "last_checked_at": product.last_checked_at.isoformat() if product.last_checked_at else None}
        if product.health_status in {ProductHealthStatus.down, ProductHealthStatus.not_responding, ProductHealthStatus.under_maintenance}:
            return {"product_id": str(product.id), "health": health, "results": [], "examined_count": 0, "blocked_count": 1}
    ids = list(
        db.scalars(
            select(PendingProductChange.id)
            .where(PendingProductChange.product_deployment_id == product_id, PendingProductChange.status.in_(ELIGIBLE_STATUSES))
            .order_by(PendingProductChange.organization_id.asc(), PendingProductChange.created_at.asc())
            .limit(limit)
        )
    )
    results = []
    for change_id in ids:
        try:
            results.append(await deliver_pending_change(db, change_id, admin))
        except HTTPException as exc:
            results.append({"pending_change_id": str(change_id), "status": "blocked", "error": str(exc.detail)})
    return {
        "product_id": str(product_id),
        "health": health,
        "examined_count": len(ids),
        "confirmed_count": sum(1 for item in results if item.get("status") == PendingChangeStatus.confirmed_and_synced.value),
        "pending_retry_count": sum(1 for item in results if item.get("status") == PendingChangeStatus.pending_retry.value),
        "manual_resolution_count": sum(1 for item in results if item.get("status") == PendingChangeStatus.requires_manual_resolution.value),
        "blocked_count": sum(1 for item in results if item.get("status") == "blocked"),
        "results": results,
    }


async def reverify_product_mappings(db: Session, product_id: UUID, admin: Admin) -> dict:
    product = db.get(ProductDeployment, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    mappings = list(db.scalars(select(OrganizationMapping).where(OrganizationMapping.product_deployment_id == product_id)))
    checked = 0
    failed = 0
    secret = decrypt_product_secret(product.admin_api_secret_encrypted)
    client = build_product_client(product, api_secret=secret)
    for mapping in mappings:
        if not mapping.product_organization_id:
            failed += 1
            continue
        result = await client.get_organization_detail(mapping.product_organization_id)
        checked += 1
        if not result.is_success or result.product_organization_id != mapping.product_organization_id:
            failed += 1
    _audit(db, admin=admin, action="product.mapping_reverify", change=None, product_id=product.id, result_status=AuditResultStatus.success, payload={"checked": checked, "failed": failed})
    db.commit()
    return {"product_id": str(product_id), "checked": checked, "failed": failed}


def sync_status(db: Session) -> dict:
    items = []
    for product in db.scalars(select(ProductDeployment).order_by(ProductDeployment.product_name.asc())):
        counts = {
            status_value.value: db.scalar(
                select(func.count()).select_from(PendingProductChange).where(
                    PendingProductChange.product_deployment_id == product.id,
                    PendingProductChange.status == status_value,
                )
            )
            or 0
            for status_value in PendingChangeStatus
        }
        latest_failure = db.scalar(
            select(FailureLog)
            .where(FailureLog.product_deployment_id == product.id)
            .order_by(FailureLog.created_at.desc())
            .limit(1)
        )
        blocker = db.scalar(
            select(PendingProductChange)
            .where(PendingProductChange.product_deployment_id == product.id, PendingProductChange.status.in_(BLOCKING_STATUSES))
            .order_by(PendingProductChange.created_at.asc())
            .limit(1)
        )
        items.append(
            {
                "product_id": str(product.id),
                "product_name": product.product_name,
                "region": product.region,
                "environment": product.environment.value,
                "health_status": product.health_status.value,
                "compatibility_status": product.compatibility_status.value,
                "last_health_check": product.last_checked_at.isoformat() if product.last_checked_at else None,
                "last_confirmed_delivery": product.last_successful_sync_at.isoformat() if product.last_successful_sync_at else None,
                "counts": counts,
                "latest_failure": _safe_error(latest_failure.error_message) if latest_failure else None,
                "has_ordering_blocker": blocker is not None,
            }
        )
    return {"items": items}


def list_failures(db: Session, filters: FailureFilters, *, limit: int, offset: int) -> tuple[list[dict], int]:
    stmt: Select = select(FailureLog)
    if filters.product_deployment_id:
        stmt = stmt.where(FailureLog.product_deployment_id == filters.product_deployment_id)
    if filters.organization_id:
        stmt = stmt.where(FailureLog.organization_id == filters.organization_id)
    if filters.pending_change_id:
        stmt = stmt.where(FailureLog.pending_change_id == filters.pending_change_id)
    if filters.action:
        stmt = stmt.where(FailureLog.action_attempted == filters.action)
    if filters.failure_category:
        stmt = stmt.where(FailureLog.error_code == filters.failure_category)
    if filters.status:
        stmt = stmt.where(FailureLog.current_status == filters.status)
    if filters.date_from:
        stmt = stmt.where(FailureLog.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(FailureLog.created_at <= filters.date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(FailureLog.created_at.desc()).limit(limit).offset(offset)))
    return [
        {
            "id": str(row.id),
            "product_deployment_id": str(row.product_deployment_id) if row.product_deployment_id else None,
            "organization_id": str(row.organization_id) if row.organization_id else None,
            "pending_change_id": str(row.pending_change_id) if row.pending_change_id else None,
            "action_attempted": row.action_attempted,
            "error_code": row.error_code,
            "error_message": _safe_error(row.error_message),
            "retry_count": row.retry_count,
            "current_status": row.current_status.value,
            "product_request_id": row.product_request_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ], total
