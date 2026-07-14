from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
import hashlib
import json

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.enums import AuditResultStatus, IdempotencyRecordStatus, PendingChangeStatus, ProductConfirmationStatus, SyncStatus
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingPlan, BillingPlanVersion, OrganizationPlanAssignment
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.schemas.billing import (
    BillingPlanCreate,
    BillingPlanRead,
    BillingPlanUpdate,
    BillingPlanVersionCreate,
    BillingPlanVersionRead,
    OrganizationPlanAssignmentState,
    PlanAssignmentRead,
    PlanAssignmentRequest,
    PlanAssignmentResult,
)
from app.services.organization_service import require_verified_mapping

BLOCKING_ASSIGNMENT_STATUSES = {
    PendingChangeStatus.saved,
    PendingChangeStatus.failed,
    PendingChangeStatus.pending_retry,
    PendingChangeStatus.sent_to_product,
    PendingChangeStatus.accepted_by_product,
    PendingChangeStatus.requires_manual_resolution,
}


@dataclass(frozen=True)
class PlanFilters:
    search: str | None = None
    product_deployment_id: UUID | None = None
    currency: str | None = None
    is_active: bool | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.split())[:500]


def _request_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _audit(
    db: Session,
    *,
    admin: Admin,
    action: str,
    product_deployment_id: UUID | None,
    organization_id: UUID | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    result_status: AuditResultStatus = AuditResultStatus.success,
    idempotency_key: str | None = None,
    failure_message: str | None = None,
) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id,
            action=action,
            organization_id=organization_id,
            product_deployment_id=product_deployment_id,
            old_value=old_value,
            new_value=new_value,
            result_status=result_status,
            idempotency_key=idempotency_key,
            failure_message=_safe_error(failure_message),
            created_at=_now(),
        )
    )


def _plan_snapshot(plan: BillingPlan) -> dict:
    return {
        "billing_plan_id": str(plan.id),
        "plan_code": plan.plan_code,
        "name": plan.name,
        "description": plan.description,
        "product_deployment_id": str(plan.product_deployment_id) if plan.product_deployment_id else None,
        "currency": plan.currency,
        "is_active": plan.is_active,
    }


def _version_snapshot(plan: BillingPlan, version: BillingPlanVersion) -> dict:
    return {
        **_plan_snapshot(plan),
        "billing_plan_version_id": str(version.id),
        "version_number": version.version_number,
        "version_currency": version.currency,
        "billing_mode_compatibility": version.billing_mode_compatibility.value,
        "base_price": str(version.price),
        "included_tokens": version.included_tokens,
        "included_leads": version.included_leads,
        "effective_from": version.effective_from.isoformat(),
        "effective_to": version.effective_to.isoformat() if version.effective_to else None,
        "is_version_active": version.is_active,
    }


def _version_read(version: BillingPlanVersion | None) -> BillingPlanVersionRead | None:
    return BillingPlanVersionRead.model_validate(version) if version is not None else None


def _plan_read(db: Session, plan: BillingPlan) -> BillingPlanRead:
    versions = list(
        db.scalars(
            select(BillingPlanVersion)
            .where(BillingPlanVersion.billing_plan_id == plan.id)
            .order_by(BillingPlanVersion.version_number.desc())
        )
    )
    now = _now()
    current = next(
        (
            version
            for version in versions
            if version.is_active and _aware(version.effective_from) <= now and (version.effective_to is None or _aware(version.effective_to) > now)
        ),
        None,
    )
    return BillingPlanRead(
        id=plan.id,
        plan_code=plan.plan_code,
        name=plan.name,
        description=plan.description,
        product_deployment_id=plan.product_deployment_id,
        product_name=plan.product_name,
        region=plan.region,
        environment=plan.environment,
        currency=plan.currency,
        is_active=plan.is_active,
        latest_version=_version_read(versions[0] if versions else None),
        current_effective_version=_version_read(current),
        version_count=len(versions),
        assignment_count=db.scalar(select(func.count()).select_from(OrganizationPlanAssignment).where(OrganizationPlanAssignment.billing_plan_id == plan.id)) or 0,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _assignment_read(db: Session, assignment: OrganizationPlanAssignment) -> PlanAssignmentRead:
    plan = assignment.billing_plan or db.get(BillingPlan, assignment.billing_plan_id)
    version = assignment.billing_plan_version or db.get(BillingPlanVersion, assignment.billing_plan_version_id)
    pending = db.get(PendingProductChange, assignment.pending_product_change_id) if assignment.pending_product_change_id else None
    assert plan is not None and version is not None
    return PlanAssignmentRead(
        id=assignment.id,
        organization_id=assignment.organization_id,
        billing_plan_id=assignment.billing_plan_id,
        billing_plan_version_id=assignment.billing_plan_version_id,
        plan_name=plan.name,
        plan_code=plan.plan_code,
        version_number=version.version_number,
        currency=version.currency,
        base_price=version.price,
        billing_mode_compatibility=version.billing_mode_compatibility,
        effective_from=assignment.effective_from,
        effective_to=assignment.effective_to,
        assigned_at=assignment.created_at,
        replaced_at=assignment.effective_to,
        assigned_by_admin_id=assignment.admin_id,
        reason=assignment.note,
        previous_assignment_id=assignment.previous_assignment_id,
        pending_product_change_id=assignment.pending_product_change_id,
        pending_product_change_status=pending.status.value if pending else None,
        product_confirmation_status=assignment.product_confirmation_status,
        product_confirmed_at=assignment.product_confirmed_at,
        product_confirmed_plan_code=assignment.product_confirmed_plan_code,
        product_confirmed_version_number=assignment.product_confirmed_version_number,
    )


def list_plans(db: Session, filters: PlanFilters, *, limit: int, offset: int) -> tuple[list[BillingPlanRead], int]:
    stmt: Select = select(BillingPlan).join(ProductDeployment, ProductDeployment.id == BillingPlan.product_deployment_id)
    if filters.search:
        term = f"%{filters.search.lower()}%"
        stmt = stmt.where(or_(func.lower(BillingPlan.name).like(term), func.lower(BillingPlan.plan_code).like(term)))
    if filters.product_deployment_id:
        stmt = stmt.where(BillingPlan.product_deployment_id == filters.product_deployment_id)
    if filters.currency:
        stmt = stmt.where(BillingPlan.currency == filters.currency.upper())
    if filters.is_active is not None:
        stmt = stmt.where(BillingPlan.is_active == filters.is_active)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    plans = list(db.scalars(stmt.order_by(BillingPlan.created_at.desc()).limit(limit).offset(offset)))
    return [_plan_read(db, plan) for plan in plans], total


def get_plan(db: Session, plan_id: UUID) -> BillingPlanRead:
    plan = db.get(BillingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan not found")
    return _plan_read(db, plan)


def create_plan(db: Session, payload: BillingPlanCreate, admin: Admin) -> BillingPlanRead:
    product = db.get(ProductDeployment, payload.product_deployment_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
    if payload.currency != product.currency:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan currency must match product deployment currency")
    plan = BillingPlan(
        plan_code=payload.plan_code,
        name=payload.name.strip(),
        description=payload.description,
        product_deployment_id=product.id,
        product_name=product.product_name,
        region=product.region,
        environment=product.environment.value,
        currency=payload.currency,
        is_active=payload.is_active,
    )
    db.add(plan)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan code already exists for this product deployment") from exc
    _audit(db, admin=admin, action="billing_plan.created", product_deployment_id=product.id, new_value=_plan_snapshot(plan))
    db.commit()
    db.refresh(plan)
    return _plan_read(db, plan)


def update_plan(db: Session, plan_id: UUID, payload: BillingPlanUpdate, admin: Admin) -> BillingPlanRead:
    plan = db.get(BillingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan not found")
    old_value = _plan_snapshot(plan)
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "description", "is_active"):
        if field in data:
            setattr(plan, field, data[field].strip() if isinstance(data[field], str) else data[field])
    db.flush()
    _audit(db, admin=admin, action="billing_plan.updated", product_deployment_id=plan.product_deployment_id, old_value=old_value, new_value=_plan_snapshot(plan))
    db.commit()
    db.refresh(plan)
    return _plan_read(db, plan)


def _validate_version_payload(payload: BillingPlanVersionCreate) -> None:
    if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="effective_to must be later than effective_from")
    for field_name in ("pricing_structure", "limits", "overage_pricing"):
        value = getattr(payload, field_name)
        if value is not None and not isinstance(value, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} must be a JSON object")


def _overlaps(existing: BillingPlanVersion, start: datetime, end: datetime | None) -> bool:
    existing_end = _aware(existing.effective_to)
    existing_start = _aware(existing.effective_from)
    return _aware(start) < (existing_end or datetime.max.replace(tzinfo=timezone.utc)) and existing_start < (_aware(end) or datetime.max.replace(tzinfo=timezone.utc))


def create_plan_version(db: Session, plan_id: UUID, payload: BillingPlanVersionCreate, admin: Admin) -> BillingPlanVersionRead:
    _validate_version_payload(payload)
    plan = db.scalar(select(BillingPlan).where(BillingPlan.id == plan_id).with_for_update(of=BillingPlan))
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan not found")
    if not plan.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot create a version for an inactive plan")
    if payload.currency != plan.currency:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version currency must match plan currency")
    existing_versions = list(db.scalars(select(BillingPlanVersion).where(BillingPlanVersion.billing_plan_id == plan.id)))
    if any(_overlaps(version, payload.effective_from, payload.effective_to) for version in existing_versions):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan version effective period overlaps an existing version")
    next_version = (max((version.version_number for version in existing_versions), default=0) + 1)
    version = BillingPlanVersion(
        billing_plan_id=plan.id,
        version_number=next_version,
        currency=payload.currency,
        billing_mode_compatibility=payload.billing_mode_compatibility,
        pricing_structure=payload.pricing_structure,
        price=payload.base_price,
        limits=payload.limits,
        included_tokens=payload.included_tokens,
        included_leads=payload.included_leads,
        overage_pricing=payload.overage_pricing,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        is_active=payload.is_active,
        external_product_plan_id=payload.external_product_plan_id,
        created_by_admin_id=admin.id,
        note=payload.reason,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Concurrent plan version creation conflicted; retry the request") from exc
    _audit(db, admin=admin, action="billing_plan_version.created", product_deployment_id=plan.product_deployment_id, new_value=_version_snapshot(plan, version))
    db.commit()
    db.refresh(version)
    return BillingPlanVersionRead.model_validate(version)


def list_plan_versions(db: Session, plan_id: UUID) -> list[BillingPlanVersionRead]:
    if db.get(BillingPlan, plan_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan not found")
    versions = list(db.scalars(select(BillingPlanVersion).where(BillingPlanVersion.billing_plan_id == plan_id).order_by(BillingPlanVersion.version_number.desc())))
    return [BillingPlanVersionRead.model_validate(version) for version in versions]


def get_plan_version(db: Session, plan_id: UUID, version_id: UUID) -> BillingPlanVersionRead:
    version = db.get(BillingPlanVersion, version_id)
    if version is None or version.billing_plan_id != plan_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan version not found")
    return BillingPlanVersionRead.model_validate(version)


def _get_assignment_replay(db: Session, key: str, organization_id: UUID, request_hash: str) -> dict | None:
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))
    if record is None:
        return None
    if record.action_type != "plan.assign":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different action")
    if record.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different organization")
    if record.request_hash and record.request_hash != request_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different plan assignment request")
    if record.status == IdempotencyRecordStatus.completed and record.response_json is not None:
        return record.response_json
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress")


def _start_assignment_idempotency(db: Session, key: str, organization: Organization, admin: Admin, request_hash: str) -> IdempotencyRecord | dict:
    replay = _get_assignment_replay(db, key, organization.id, request_hash)
    if replay is not None:
        return replay
    record = IdempotencyRecord(
        idempotency_key=key,
        action_type="plan.assign",
        request_hash=request_hash,
        status=IdempotencyRecordStatus.started,
        response_json=None,
        created_at=_now(),
        admin_id=admin.id,
        organization_id=organization.id,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _get_assignment_replay(db, key, organization.id, request_hash)
        if replay is not None:
            return replay
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress") from exc
    return record


def _current_assignment(db: Session, organization_id: UUID) -> OrganizationPlanAssignment | None:
    return db.scalar(
        select(OrganizationPlanAssignment)
        .where(OrganizationPlanAssignment.organization_id == organization_id, OrganizationPlanAssignment.is_active.is_(True))
        .options(joinedload(OrganizationPlanAssignment.billing_plan), joinedload(OrganizationPlanAssignment.billing_plan_version))
        .order_by(OrganizationPlanAssignment.created_at.desc())
        .limit(1)
    )


def _unresolved_plan_change(db: Session, organization_id: UUID, product_deployment_id: UUID) -> PendingProductChange | None:
    return db.scalar(
        select(PendingProductChange)
        .where(
            PendingProductChange.organization_id == organization_id,
            PendingProductChange.product_deployment_id == product_deployment_id,
            PendingProductChange.action.in_(("assign_plan_version", "change_plan_version")),
            PendingProductChange.status.in_(BLOCKING_ASSIGNMENT_STATUSES),
        )
        .order_by(PendingProductChange.created_at.asc())
        .limit(1)
    )


def _validate_assignment(organization: Organization, plan: BillingPlan, version: BillingPlanVersion) -> None:
    now = _now()
    if plan.product_deployment_id != organization.product_deployment_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan is not applicable to this organization deployment")
    if organization.currency != version.currency:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan version currency does not match organization currency")
    if organization.billing_mode != version.billing_mode_compatibility:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan version is not compatible with organization billing mode")
    if not plan.is_active or not version.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan and version must be active")
    effective_from = _aware(version.effective_from)
    effective_to = _aware(version.effective_to)
    if effective_from > now or (effective_to is not None and effective_to <= now):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan version is not currently effective")


def _assignment_payload(organization: Organization, mapping_product_org_id: str, plan: BillingPlan, version: BillingPlanVersion, assignment: OrganizationPlanAssignment) -> dict:
    return {
        "product_organization_id": mapping_product_org_id,
        "plan_code": plan.plan_code,
        "plan_version_number": version.version_number,
        "currency": version.currency,
        "compatible_billing_mode": version.billing_mode_compatibility.value,
        "base_price": str(version.price),
        "limits": version.limits or {},
        "included_tokens": version.included_tokens,
        "included_leads": version.included_leads,
        "overage_pricing": version.overage_pricing or {},
        "pricing_structure": version.pricing_structure or {},
        "effective_from": assignment.effective_from.isoformat(),
        "central_assignment_id": str(assignment.id),
        "organization_id": str(organization.id),
    }


def assign_plan_version(db: Session, organization_id: UUID, payload: PlanAssignmentRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash({"organization_id": str(organization_id), **payload.model_dump(mode="json")})
    try:
        organization = db.scalar(select(Organization).where(Organization.id == organization_id).with_for_update(of=Organization))
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        record = _start_assignment_idempotency(db, idempotency_key, organization, admin, request_hash)
        if isinstance(record, dict):
            return record
        mapping = require_verified_mapping(db, organization.id, organization.product_deployment_id)
        version = db.get(BillingPlanVersion, payload.billing_plan_version_id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan version not found")
        plan = db.get(BillingPlan, version.billing_plan_id)
        assert plan is not None
        _validate_assignment(organization, plan, version)
        if _unresolved_plan_change(db, organization.id, organization.product_deployment_id) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unresolved plan assignment change already exists")
        previous = _current_assignment(db, organization.id)
        if previous and previous.billing_plan_version_id == version.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization is already assigned to this plan version")
        now = _now()
        if previous is not None:
            previous.is_active = False
            previous.effective_to = now
        assignment = OrganizationPlanAssignment(
            organization_id=organization.id,
            billing_plan_id=plan.id,
            billing_plan_version_id=version.id,
            effective_from=now,
            effective_to=None,
            is_active=True,
            note=payload.reason,
            admin_id=admin.id,
            previous_assignment_id=previous.id if previous else None,
            product_confirmation_status=ProductConfirmationStatus.pending,
        )
        db.add(assignment)
        db.flush()
        change = PendingProductChange(
            action="assign_plan_version" if previous is None else "change_plan_version",
            payload=_assignment_payload(organization, mapping.product_organization_id or "", plan, version, assignment),
            organization_id=organization.id,
            product_deployment_id=organization.product_deployment_id,
            status=PendingChangeStatus.saved,
            idempotency_key=idempotency_key,
            retry_count=0,
            reason=payload.reason,
            admin_id=admin.id,
        )
        db.add(change)
        db.flush()
        assignment.pending_product_change_id = change.id
        organization.sync_status = SyncStatus.pending
        _audit(
            db,
            admin=admin,
            action="organization.plan_assigned",
            organization_id=organization.id,
            product_deployment_id=organization.product_deployment_id,
            old_value=_version_snapshot(previous.billing_plan, previous.billing_plan_version) if previous else None,
            new_value={**_version_snapshot(plan, version), "pending_product_change_id": str(change.id), "reason": payload.reason},
            idempotency_key=idempotency_key,
        )
        db.flush()
        response = PlanAssignmentResult(
            assignment=_assignment_read(db, assignment),
            pending_product_change_id=change.id,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def get_organization_plan_assignment(db: Session, organization_id: UUID) -> OrganizationPlanAssignmentState:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    current = _current_assignment(db, organization_id)
    confirmed = db.scalar(
        select(OrganizationPlanAssignment)
        .where(
            OrganizationPlanAssignment.organization_id == organization_id,
            OrganizationPlanAssignment.product_confirmation_status == ProductConfirmationStatus.confirmed,
        )
        .options(joinedload(OrganizationPlanAssignment.billing_plan), joinedload(OrganizationPlanAssignment.billing_plan_version))
        .order_by(OrganizationPlanAssignment.product_confirmed_at.desc())
        .limit(1)
    )
    pending = db.get(PendingProductChange, current.pending_product_change_id) if current and current.pending_product_change_id else None
    return OrganizationPlanAssignmentState(
        organization_id=organization_id,
        current_intended=_assignment_read(db, current) if current else None,
        last_product_confirmed=_assignment_read(db, confirmed) if confirmed else None,
        pending_change_id=pending.id if pending else None,
        pending_change_status=pending.status.value if pending else None,
    )


def list_organization_plan_history(db: Session, organization_id: UUID) -> list[PlanAssignmentRead]:
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    rows = list(
        db.scalars(
            select(OrganizationPlanAssignment)
            .where(OrganizationPlanAssignment.organization_id == organization_id)
            .options(joinedload(OrganizationPlanAssignment.billing_plan), joinedload(OrganizationPlanAssignment.billing_plan_version))
            .order_by(OrganizationPlanAssignment.created_at.desc())
        )
    )
    return [_assignment_read(db, row) for row in rows]


def confirm_assignment_from_product(db: Session, change: PendingProductChange, result) -> None:
    if change.action not in {"assign_plan_version", "change_plan_version"}:
        return
    assignment_id = (change.payload or {}).get("central_assignment_id")
    if not assignment_id:
        return
    assignment = db.get(OrganizationPlanAssignment, UUID(str(assignment_id)))
    if assignment is None:
        return
    assignment.product_confirmation_status = ProductConfirmationStatus.confirmed
    assignment.product_confirmed_at = _now()
    assignment.product_confirmed_plan_code = result.plan_code
    assignment.product_confirmed_version_number = result.plan_version_number
