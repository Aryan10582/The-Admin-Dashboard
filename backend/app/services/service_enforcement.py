from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    AuditResultStatus,
    BillingMode,
    IdempotencyRecordStatus,
    PendingChangeStatus,
    ProductConfirmationStatus,
    ServiceStatus,
    SyncStatus,
)
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.models.service_enforcement import ServiceEnforcementRule
from app.schemas.pending_change import PendingChangeRead
from app.schemas.service_enforcement import PendingChangeSummary, ServiceActionResult, ServiceEnforcementRead
from app.services.organization_service import require_verified_mapping


SERVICE_ACTIONS = {
    "service.pause",
    "service.resume",
    "service.disable",
    "service.manual_continuation.apply",
    "service.manual_continuation.remove",
    "service.auto_pause_zero_balance",
}


@dataclass(frozen=True)
class PendingChangeFilters:
    status: PendingChangeStatus | None = None
    action: str | None = None
    organization_id: UUID | None = None
    product_deployment_id: UUID | None = None
    product_name: str | None = None
    region: str | None = None
    environment: object | None = None
    admin_id: UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_service_status(organization: Organization) -> ServiceStatus:
    if organization.service_enforcement_status == ServiceStatus.disabled:
        return ServiceStatus.disabled
    rule = getattr(organization, "_service_rule", None)
    manual_continuation_enabled = bool(rule.manual_continuation_override) if rule is not None else False
    if (
        organization.billing_mode == BillingMode.prepaid_credits
        and organization.credit_balance <= 0
        and not manual_continuation_enabled
    ):
        return ServiceStatus.paused
    return organization.service_enforcement_status


def _safe_org_payload(organization: Organization, rule: ServiceEnforcementRule | None = None) -> dict:
    return {
        "organization_id": str(organization.id),
        "product_deployment_id": str(organization.product_deployment_id),
        "intended_service_status": organization.service_enforcement_status.value,
        "product_confirmation_status": organization.sync_status.value,
        "manual_continuation_enabled": bool(rule.manual_continuation_override) if rule is not None else False,
        "credit_balance": str(organization.credit_balance),
        "outstanding_dues": str(organization.outstanding_dues),
        "billing_mode": organization.billing_mode.value,
    }


def _audit(
    db: Session,
    *,
    admin: Admin,
    action: str,
    organization: Organization,
    old_value: dict | None,
    new_value: dict | None,
    reason: str,
    idempotency_key: str,
) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id,
            action=action,
            organization_id=organization.id,
            product_deployment_id=organization.product_deployment_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            result_status=AuditResultStatus.success,
            sync_status=SyncStatus.pending,
            idempotency_key=idempotency_key,
            created_at=_now(),
        )
    )


def _get_org(db: Session, organization_id: UUID, *, lock: bool = False) -> Organization:
    stmt = select(Organization).where(Organization.id == organization_id)
    if lock:
        stmt = stmt.with_for_update(of=Organization)
    organization = db.scalar(stmt)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


def _get_rule(db: Session, organization: Organization, *, lock: bool = False, create: bool = False) -> ServiceEnforcementRule | None:
    stmt = select(ServiceEnforcementRule).where(
        ServiceEnforcementRule.organization_id == organization.id,
        ServiceEnforcementRule.is_active.is_(True),
    )
    if lock:
        stmt = stmt.with_for_update(of=ServiceEnforcementRule)
    rule = db.scalar(stmt)
    if rule is None and create:
        rule = ServiceEnforcementRule(
            organization_id=organization.id,
            service_status=organization.service_enforcement_status,
            manual_continuation_override=False,
            product_confirmation_status=ProductConfirmationStatus.pending,
            is_active=True,
        )
        db.add(rule)
        db.flush()
    return rule


def _get_replay(db: Session, key: str, action_type: str, organization_id: UUID) -> dict | None:
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


def _start_idempotency(db: Session, key: str, action_type: str, admin: Admin, organization: Organization) -> IdempotencyRecord | dict:
    record = IdempotencyRecord(
        idempotency_key=key,
        action_type=action_type,
        status=IdempotencyRecordStatus.started,
        created_at=_now(),
        admin_id=admin.id,
        organization_id=organization.id,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _get_replay(db, key, action_type, organization.id)
        if replay is not None:
            return replay
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress") from exc
    return record


def _begin_action(db: Session, *, organization_id: UUID, idempotency_key: str, action_type: str, admin: Admin) -> tuple[Organization | None, IdempotencyRecord | None, dict | None]:
    replay = _get_replay(db, idempotency_key, action_type, organization_id)
    if replay is not None:
        return None, None, replay
    organization_for_record = _get_org(db, organization_id)
    record = _start_idempotency(db, idempotency_key, action_type, admin, organization_for_record)
    if isinstance(record, dict):
        return None, None, record
    organization = _get_org(db, organization_id, lock=True)
    _get_rule(db, organization, lock=True, create=True)
    require_verified_mapping(db, organization.id, organization.product_deployment_id)
    return organization, record, None


def _latest_saved_service_change(db: Session, organization: Organization) -> PendingProductChange | None:
    return db.scalar(
        select(PendingProductChange)
        .where(
            PendingProductChange.organization_id == organization.id,
            PendingProductChange.product_deployment_id == organization.product_deployment_id,
            PendingProductChange.status == PendingChangeStatus.saved,
            PendingProductChange.action.in_(SERVICE_ACTIONS),
        )
        .order_by(PendingProductChange.created_at.desc())
        .limit(1)
    )


def _ensure_no_conflicting_saved_service_change(db: Session, organization: Organization) -> None:
    if _latest_saved_service_change(db, organization) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A saved service pending change already exists for this organization",
        )


def _pending_payload(
    *,
    organization: Organization,
    product_organization_id: str,
    previous_status: ServiceStatus,
    requested_status: ServiceStatus,
    previous_override: bool,
    requested_override: bool,
    previous_override_reason: str | None,
    reason: str,
) -> dict:
    return {
        "organization_id": str(organization.id),
        "product_deployment_id": str(organization.product_deployment_id),
        "product_organization_id": product_organization_id,
        "previous_intended_service_status": previous_status.value,
        "requested_intended_service_status": requested_status.value,
        "previous_manual_continuation_enabled": previous_override,
        "previous_manual_continuation_reason": previous_override_reason,
        "requested_manual_continuation_enabled": requested_override,
        "reason": reason,
    }


def _create_pending_change(
    db: Session,
    *,
    organization: Organization,
    action: str,
    reason: str,
    admin: Admin,
    idempotency_key: str,
    previous_status: ServiceStatus,
    previous_override: bool,
    previous_override_reason: str | None,
) -> PendingProductChange:
    mapping = require_verified_mapping(db, organization.id, organization.product_deployment_id)
    _ensure_no_conflicting_saved_service_change(db, organization)
    rule = _get_rule(db, organization, create=True)
    assert rule is not None
    change = PendingProductChange(
        action=action,
        payload=_pending_payload(
            organization=organization,
            product_organization_id=mapping.product_organization_id or "",
            previous_status=previous_status,
            requested_status=organization.service_enforcement_status,
            previous_override=previous_override,
            requested_override=rule.manual_continuation_override,
            previous_override_reason=previous_override_reason,
            reason=reason,
        ),
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        status=PendingChangeStatus.saved,
        idempotency_key=idempotency_key,
        retry_count=0,
        reason=reason,
        admin_id=admin.id,
    )
    db.add(change)
    db.flush()
    return change


def _result(organization: Organization, rule: ServiceEnforcementRule, change: PendingProductChange, idempotency_key: str) -> dict:
    return ServiceActionResult(
        organization_id=organization.id,
        intended_service_status=organization.service_enforcement_status,
        product_confirmation_status=organization.sync_status,
        manual_continuation_enabled=rule.manual_continuation_override,
        pending_product_change_id=change.id,
        idempotency_key=idempotency_key,
    ).model_dump(mode="json")


def _latest_pending_change(db: Session, organization_id: UUID) -> PendingProductChange | None:
    return db.scalar(
        select(PendingProductChange)
        .where(PendingProductChange.organization_id == organization_id)
        .order_by(PendingProductChange.created_at.desc())
        .limit(1)
    )


def get_service_enforcement(db: Session, organization_id: UUID) -> dict:
    organization = _get_org(db, organization_id)
    rule = _get_rule(db, organization)
    setattr(organization, "_service_rule", rule)
    latest = _latest_pending_change(db, organization_id)
    payload = ServiceEnforcementRead(
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        intended_service_status=organization.service_enforcement_status,
        evaluated_service_status=evaluate_service_status(organization),
        product_confirmation_status=organization.sync_status,
        billing_mode=organization.billing_mode,
        credit_balance=organization.credit_balance,
        outstanding_dues=organization.outstanding_dues,
        credit_status=organization.credit_status,
        manual_continuation_enabled=bool(rule.manual_continuation_override) if rule is not None else False,
        manual_continuation_reason=rule.manual_override_reason if rule is not None else None,
        latest_pending_change=PendingChangeSummary.model_validate(latest) if latest is not None else None,
    )
    return payload.model_dump(mode="json")


def apply_service_action(
    db: Session,
    *,
    organization_id: UUID,
    action: str,
    reason: str,
    idempotency_key: str,
    admin: Admin,
) -> dict:
    try:
        organization, record, replay = _begin_action(
            db,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            action_type=action,
            admin=admin,
        )
        if replay is not None:
            return replay
        assert organization is not None and record is not None
        rule = _get_rule(db, organization, lock=True, create=True)
        assert rule is not None
        old_value = _safe_org_payload(organization, rule)
        previous_status = organization.service_enforcement_status
        previous_override = rule.manual_continuation_override
        previous_override_reason = rule.manual_override_reason

        if action == "service.pause":
            organization.service_enforcement_status = ServiceStatus.paused
        elif action == "service.resume":
            if organization.billing_mode == BillingMode.prepaid_credits and organization.credit_balance <= 0 and not rule.manual_continuation_override:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot resume prepaid service with exhausted credits")
            organization.service_enforcement_status = ServiceStatus.running
        elif action == "service.disable":
            organization.service_enforcement_status = ServiceStatus.disabled
        elif action == "service.manual_continuation.apply":
            if organization.billing_mode != BillingMode.prepaid_credits:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Manual continuation applies only to prepaid organizations")
            if organization.credit_balance > 0:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Manual continuation requires exhausted credits")
            rule.manual_continuation_override = True
            rule.manual_override_reason = reason
            if organization.service_enforcement_status != ServiceStatus.disabled:
                organization.service_enforcement_status = ServiceStatus.running
        elif action == "service.manual_continuation.remove":
            rule.manual_continuation_override = False
            rule.manual_override_reason = None
            if organization.billing_mode == BillingMode.prepaid_credits and organization.credit_balance <= 0 and organization.service_enforcement_status != ServiceStatus.disabled:
                organization.service_enforcement_status = ServiceStatus.paused
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported service action")

        organization.sync_status = SyncStatus.pending
        change = _create_pending_change(
            db,
            organization=organization,
            action=action,
            reason=reason,
            admin=admin,
            idempotency_key=idempotency_key,
            previous_status=previous_status,
            previous_override=previous_override,
            previous_override_reason=previous_override_reason,
        )
        _audit(
            db,
            admin=admin,
            action=action,
            organization=organization,
            old_value=old_value,
            new_value=_safe_org_payload(organization, rule) | {"pending_product_change_id": str(change.id)},
            reason=reason,
            idempotency_key=idempotency_key,
        )
        response = _result(organization, rule, change, idempotency_key)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def maybe_auto_pause_for_zero_balance(
    db: Session,
    *,
    organization: Organization,
    reason: str,
    admin: Admin,
    idempotency_key: str,
) -> PendingProductChange | None:
    if organization.billing_mode != BillingMode.prepaid_credits:
        return None
    rule = _get_rule(db, organization, create=True)
    assert rule is not None
    if organization.credit_balance > 0 or rule.manual_continuation_override:
        return None
    if organization.service_enforcement_status != ServiceStatus.running:
        return None

    old_value = _safe_org_payload(organization, rule)
    previous_status = organization.service_enforcement_status
    previous_override = rule.manual_continuation_override
    previous_override_reason = rule.manual_override_reason
    organization.service_enforcement_status = ServiceStatus.paused
    organization.sync_status = SyncStatus.pending
    change = _create_pending_change(
        db,
        organization=organization,
        action="service.auto_pause_zero_balance",
        reason=reason,
        admin=admin,
        idempotency_key=idempotency_key,
        previous_status=previous_status,
        previous_override=previous_override,
        previous_override_reason=previous_override_reason,
    )
    _audit(
        db,
        admin=admin,
        action="service.auto_pause_zero_balance",
        organization=organization,
        old_value=old_value,
        new_value=_safe_org_payload(organization, rule) | {"pending_product_change_id": str(change.id)},
        reason=reason,
        idempotency_key=idempotency_key,
    )
    return change


def update_service_enforcement_config(db: Session, organization_id: UUID) -> dict:
    return get_service_enforcement(db, organization_id)


def _pending_query(filters: PendingChangeFilters) -> Select:
    stmt = select(PendingProductChange, ProductDeployment).join(
        ProductDeployment,
        ProductDeployment.id == PendingProductChange.product_deployment_id,
    )
    if filters.status:
        stmt = stmt.where(PendingProductChange.status == filters.status)
    if filters.action:
        stmt = stmt.where(PendingProductChange.action == filters.action)
    if filters.organization_id:
        stmt = stmt.where(PendingProductChange.organization_id == filters.organization_id)
    if filters.product_deployment_id:
        stmt = stmt.where(PendingProductChange.product_deployment_id == filters.product_deployment_id)
    if filters.product_name:
        stmt = stmt.where(ProductDeployment.product_name == filters.product_name)
    if filters.region:
        stmt = stmt.where(ProductDeployment.region == filters.region)
    if filters.environment:
        stmt = stmt.where(ProductDeployment.environment == filters.environment)
    if filters.admin_id:
        stmt = stmt.where(PendingProductChange.admin_id == filters.admin_id)
    if filters.date_from:
        stmt = stmt.where(PendingProductChange.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(PendingProductChange.created_at <= filters.date_to)
    return stmt


def _can_cancel(change: PendingProductChange) -> bool:
    return (
        change.status == PendingChangeStatus.saved
        and change.action in SERVICE_ACTIONS
        and change.payload is not None
        and "previous_intended_service_status" in change.payload
    )


def _change_matches_current_intended_state(change: PendingProductChange, organization: Organization, rule: ServiceEnforcementRule | None) -> bool:
    if change.payload is None:
        return False
    requested_status = change.payload.get("requested_intended_service_status")
    requested_override = bool(change.payload.get("requested_manual_continuation_enabled", False))
    current_override = bool(rule.manual_continuation_override) if rule is not None else False
    return requested_status == organization.service_enforcement_status.value and requested_override == current_override


def _serialize_change(change: PendingProductChange, product: ProductDeployment) -> PendingChangeRead:
    can_retry = change.status in {
        PendingChangeStatus.saved,
        PendingChangeStatus.failed,
        PendingChangeStatus.pending_retry,
    }
    return PendingChangeRead(
        id=change.id,
        action=change.action,
        organization_id=change.organization_id,
        product_deployment_id=change.product_deployment_id,
        product_name=product.product_name,
        region=product.region,
        environment=product.environment,
        status=change.status,
        retry_count=change.retry_count,
        last_retry_at=change.last_retry_at,
        last_error=change.last_error,
        admin_id=change.admin_id,
        idempotency_key=change.idempotency_key,
        reason=change.reason,
        payload=change.payload,
        delivery_attempt_id=change.delivery_attempt_id,
        delivery_started_at=change.delivery_started_at,
        last_delivery_at=change.last_delivery_at,
        product_request_id=change.product_request_id,
        product_api_version=change.product_api_version,
        safe_confirmation_summary=change.safe_confirmation_summary,
        created_at=change.created_at,
        updated_at=change.updated_at,
        can_cancel=_can_cancel(change),
        can_retry=can_retry,
    )


def list_pending_changes(db: Session, filters: PendingChangeFilters, *, limit: int, offset: int) -> tuple[list[PendingChangeRead], int]:
    stmt = _pending_query(filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(PendingProductChange.created_at.desc()).limit(limit).offset(offset)).all()
    return [_serialize_change(change, product) for change, product in rows], total


def get_pending_change(db: Session, pending_change_id: UUID) -> PendingChangeRead:
    row = db.execute(
        select(PendingProductChange, ProductDeployment)
        .join(ProductDeployment, ProductDeployment.id == PendingProductChange.product_deployment_id)
        .where(PendingProductChange.id == pending_change_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    change, product = row
    return _serialize_change(change, product)


def _pending_action_replay(db: Session, key: str, action_type: str, organization_id: UUID) -> dict | None:
    return _get_replay(db, key, action_type, organization_id)


def cancel_pending_change(db: Session, pending_change_id: UUID, *, reason: str, idempotency_key: str, admin: Admin) -> dict:
    change = db.get(PendingProductChange, pending_change_id)
    if change is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    if change.organization_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending change cannot be cancelled automatically")

    action_type = f"pending_change.cancel.{pending_change_id}"
    try:
        replay = _pending_action_replay(db, idempotency_key, action_type, change.organization_id)
        if replay is not None:
            return replay
        organization = _get_org(db, change.organization_id)
        record = _start_idempotency(db, idempotency_key, action_type, admin, organization)
        if isinstance(record, dict):
            return record
        organization = _get_org(db, change.organization_id, lock=True)
        rule = _get_rule(db, organization, lock=True, create=True)
        change = db.get(PendingProductChange, pending_change_id)
        assert change is not None
        if not _can_cancel(change):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending change is not safely cancellable")
        latest_change = _latest_saved_service_change(db, organization)
        if latest_change is None or latest_change.id != change.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only the latest saved service change can be cancelled")
        if not _change_matches_current_intended_state(change, organization, rule):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending change no longer matches current intended state")
        assert rule is not None
        old_value = _safe_org_payload(organization, rule) | {"pending_change_status": change.status.value}
        organization.service_enforcement_status = ServiceStatus(change.payload["previous_intended_service_status"])
        rule.manual_continuation_override = bool(change.payload.get("previous_manual_continuation_enabled", False))
        rule.manual_override_reason = change.payload.get("previous_manual_continuation_reason") if rule.manual_continuation_override else None
        change.status = PendingChangeStatus.cancelled
        change.last_error = None
        _audit(
            db,
            admin=admin,
            action="pending_change.cancel",
            organization=organization,
            old_value=old_value,
            new_value=_safe_org_payload(organization, rule) | {"pending_change_status": change.status.value, "pending_change_id": str(change.id)},
            reason=reason,
            idempotency_key=idempotency_key,
        )
        response = get_pending_change(db, pending_change_id).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def mark_pending_change_manual_resolution(db: Session, pending_change_id: UUID, *, reason: str, idempotency_key: str, admin: Admin) -> dict:
    change = db.get(PendingProductChange, pending_change_id)
    if change is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending change not found")
    if change.organization_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending change requires an organization")
    action_type = f"pending_change.manual_resolution.{pending_change_id}"
    try:
        replay = _pending_action_replay(db, idempotency_key, action_type, change.organization_id)
        if replay is not None:
            return replay
        organization = _get_org(db, change.organization_id)
        record = _start_idempotency(db, idempotency_key, action_type, admin, organization)
        if isinstance(record, dict):
            return record
        old_status = change.status
        change.status = PendingChangeStatus.requires_manual_resolution
        change.last_error = reason
        _audit(
            db,
            admin=admin,
            action="pending_change.manual_resolution",
            organization=organization,
            old_value={"pending_change_id": str(change.id), "status": old_status.value},
            new_value={"pending_change_id": str(change.id), "status": change.status.value},
            reason=reason,
            idempotency_key=idempotency_key,
        )
        response = get_pending_change(db, pending_change_id).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
