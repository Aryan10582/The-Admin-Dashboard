from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID
import hashlib
import json

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AiPriceCheckStatus, AiPricingSourceType, AuditResultStatus, IdempotencyRecordStatus, PricingCreatedBy
from app.models.admin import Admin
from app.models.ai import AIPriceCheckRun, AiModelPricingCatalog, AiModelPricingVersion
from app.models.audit import AuditLog
from app.models.idempotency import IdempotencyRecord
from app.schemas.ai_pricing import (
    AiPricingCatalogCreate,
    AiPricingCatalogRead,
    AiPricingCatalogUpdate,
    AiPricingVersionCreate,
    AiPricingVersionRead,
)


@dataclass(frozen=True)
class AiPricingFilters:
    search: str | None = None
    provider: str | None = None
    provider_model_id: str | None = None
    pricing_scope_code: str | None = None
    currency: str | None = None
    is_active: bool | None = None
    has_current_version: bool | None = None
    has_future_version: bool | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.split())[:500]


def _request_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _snapshot_catalog(catalog: AiModelPricingCatalog) -> dict:
    return {
        "pricing_catalog_id": str(catalog.id),
        "provider": catalog.provider,
        "provider_model_id": catalog.provider_model_id,
        "pricing_scope_code": catalog.pricing_scope_code,
        "currency": catalog.currency,
        "display_name": catalog.display_name,
        "description": catalog.description,
        "is_active": catalog.is_active,
    }


def _snapshot_version(catalog: AiModelPricingCatalog, version: AiModelPricingVersion) -> dict:
    return {
        **_snapshot_catalog(catalog),
        "pricing_version_id": str(version.id),
        "version_number": version.version_number,
        "input_token_price": str(version.input_token_cost),
        "output_token_price": str(version.output_token_cost),
        "pricing_unit_tokens": version.pricing_unit_tokens,
        "currency_snapshot": version.currency_snapshot,
        "pricing_scope_snapshot": version.pricing_scope_snapshot,
        "effective_from": version.effective_from.isoformat(),
        "effective_to": version.effective_to.isoformat() if version.effective_to else None,
        "source_type": version.source_type.value,
    }


def _audit(
    db: Session,
    *,
    admin: Admin,
    action: str,
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
            old_value=old_value,
            new_value=new_value,
            result_status=result_status,
            idempotency_key=idempotency_key,
            failure_message=_safe_error(failure_message),
            created_at=_now(),
        )
    )


def _effective_state(version: AiModelPricingVersion, now: datetime | None = None) -> str:
    now = now or _now()
    start = _utc(version.effective_from)
    end = _utc(version.effective_to) if version.effective_to else None
    if start > now:
        return "future"
    if end is not None and end <= now:
        return "expired"
    return "current"


def _version_read(version: AiModelPricingVersion | None, now: datetime | None = None) -> AiPricingVersionRead | None:
    if version is None:
        return None
    return AiPricingVersionRead(
        id=version.id,
        pricing_catalog_id=version.pricing_catalog_id,
        version_number=version.version_number,
        input_token_price=version.input_token_cost,
        output_token_price=version.output_token_cost,
        pricing_unit_tokens=version.pricing_unit_tokens,
        currency_snapshot=version.currency_snapshot,
        pricing_scope_snapshot=version.pricing_scope_snapshot,
        effective_from=_utc(version.effective_from),
        effective_to=_utc(version.effective_to) if version.effective_to else None,
        source_type=version.source_type,
        source_reference=version.source_reference,
        created_by_type=version.created_by,
        created_by_admin_id=version.created_by_admin_id,
        note=version.note,
        created_at=_utc(version.created_at),
        is_active=version.is_active,
        effective_state=_effective_state(version, now),
    )


def _catalog_read(db: Session, catalog: AiModelPricingCatalog) -> AiPricingCatalogRead:
    versions = list(
        db.scalars(
            select(AiModelPricingVersion)
            .where(AiModelPricingVersion.pricing_catalog_id == catalog.id)
            .order_by(AiModelPricingVersion.version_number.desc())
        )
    )
    now = _now()
    current = next((version for version in versions if version.is_active and _effective_state(version, now) == "current"), None)
    latest_check = db.scalar(
        select(AIPriceCheckRun)
        .where(AIPriceCheckRun.pricing_catalog_id == catalog.id)
        .order_by(AIPriceCheckRun.started_at.desc())
        .limit(1)
    )
    unresolved_reviews = db.scalar(
        select(func.count())
        .select_from(AIPriceCheckRun)
        .where(AIPriceCheckRun.pricing_catalog_id == catalog.id, AIPriceCheckRun.status == AiPriceCheckStatus.requires_manual_review, AIPriceCheckRun.reviewed_at.is_(None))
    ) or 0
    source_state = "inactive" if not catalog.is_active else "source_unsupported"
    if latest_check is not None:
        if unresolved_reviews:
            source_state = "requires_manual_review"
        elif latest_check.status == AiPriceCheckStatus.version_created:
            source_state = "current"
        elif latest_check.status == AiPriceCheckStatus.unchanged:
            source_state = "current"
        elif latest_check.status == AiPriceCheckStatus.requires_manual_review:
            source_state = "requires_manual_review"
        elif latest_check.status == AiPriceCheckStatus.source_unavailable:
            source_state = "source_unavailable"
        elif latest_check.status == AiPriceCheckStatus.unsupported:
            source_state = "source_unsupported"
        elif latest_check.status == AiPriceCheckStatus.invalid_response:
            source_state = "requires_manual_review"
    return AiPricingCatalogRead(
        id=catalog.id,
        provider=catalog.provider,
        provider_model_id=catalog.provider_model_id,
        display_name=catalog.display_name,
        pricing_scope_code=catalog.pricing_scope_code,
        currency=catalog.currency,
        description=catalog.description,
        is_active=catalog.is_active,
        latest_version=_version_read(versions[0], now) if versions else None,
        current_effective_version=_version_read(current, now),
        version_count=len(versions),
        has_future_version=any(_effective_state(version, now) == "future" for version in versions),
        last_check_status=latest_check.status if latest_check else None,
        last_checked_at=latest_check.completed_at or latest_check.started_at if latest_check else None,
        unresolved_review_count=unresolved_reviews,
        source_state=source_state,
        safe_last_error=latest_check.safe_error if latest_check else None,
        created_at=catalog.created_at,
        updated_at=catalog.updated_at,
    )


def _get_replay(db: Session, key: str, action_type: str, request_hash: str) -> dict | None:
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))
    if record is None:
        return None
    if record.action_type != action_type:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different action")
    if record.request_hash and record.request_hash != request_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different pricing request")
    if record.status == IdempotencyRecordStatus.completed and record.response_json is not None:
        return record.response_json
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress")


def _start_idempotency(db: Session, *, key: str, action_type: str, admin: Admin, request_hash: str) -> IdempotencyRecord | dict:
    replay = _get_replay(db, key, action_type, request_hash)
    if replay is not None:
        return replay
    record = IdempotencyRecord(
        idempotency_key=key,
        action_type=action_type,
        request_hash=request_hash,
        response_json=None,
        status=IdempotencyRecordStatus.started,
        created_at=_now(),
        admin_id=admin.id,
        organization_id=None,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay = _get_replay(db, key, action_type, request_hash)
        if replay is not None:
            return replay
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress") from exc
    return record


def _validate_version_payload(payload: AiPricingVersionCreate) -> None:
    if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="effective_to must be later than effective_from")


def _overlaps(existing: AiModelPricingVersion, start: datetime, end: datetime | None) -> bool:
    existing_start = _utc(existing.effective_from)
    existing_end = _utc(existing.effective_to) if existing.effective_to else datetime.max.replace(tzinfo=timezone.utc)
    new_start = _utc(start)
    new_end = _utc(end) if end else datetime.max.replace(tzinfo=timezone.utc)
    return new_start < existing_end and existing_start < new_end


def _current_open_ended(versions: list[AiModelPricingVersion], start: datetime) -> AiModelPricingVersion | None:
    start = _utc(start)
    return next(
        (
            version
            for version in versions
            if version.effective_to is None and _utc(version.effective_from) < start
        ),
        None,
    )


def list_pricing_catalogs(db: Session, filters: AiPricingFilters, *, limit: int, offset: int) -> tuple[list[AiPricingCatalogRead], int]:
    stmt: Select = select(AiModelPricingCatalog)
    if filters.search:
        term = f"%{filters.search.lower()}%"
        stmt = stmt.where(or_(func.lower(AiModelPricingCatalog.display_name).like(term), func.lower(AiModelPricingCatalog.provider_model_id).like(term)))
    if filters.provider:
        stmt = stmt.where(AiModelPricingCatalog.provider == filters.provider.lower())
    if filters.provider_model_id:
        stmt = stmt.where(AiModelPricingCatalog.provider_model_id == filters.provider_model_id.strip())
    if filters.pricing_scope_code:
        stmt = stmt.where(AiModelPricingCatalog.pricing_scope_code == filters.pricing_scope_code.strip().lower())
    if filters.currency:
        stmt = stmt.where(AiModelPricingCatalog.currency == filters.currency.upper())
    if filters.is_active is not None:
        stmt = stmt.where(AiModelPricingCatalog.is_active == filters.is_active)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AiModelPricingCatalog.created_at.desc()).limit(limit).offset(offset)))
    reads = [_catalog_read(db, row) for row in rows]
    if filters.has_current_version is not None:
        reads = [item for item in reads if (item.current_effective_version is not None) == filters.has_current_version]
    if filters.has_future_version is not None:
        reads = [item for item in reads if item.has_future_version == filters.has_future_version]
    return reads, total


def create_pricing_catalog(db: Session, payload: AiPricingCatalogCreate, idempotency_key: str, admin: Admin) -> AiPricingCatalogRead | dict:
    request_hash = _request_hash(payload.model_dump(mode="json"))
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type="ai_pricing.catalog.create", admin=admin, request_hash=request_hash)
        if isinstance(record, dict):
            return record
        catalog = AiModelPricingCatalog(
            provider=payload.provider,
            provider_model_id=payload.provider_model_id,
            display_name=payload.display_name,
            pricing_scope_code=payload.pricing_scope_code,
            currency=payload.currency,
            description=payload.description,
            is_active=payload.is_active,
        )
        db.add(catalog)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI pricing catalog identity already exists") from exc
        _audit(db, admin=admin, action="ai_pricing_catalog.created", new_value={**_snapshot_catalog(catalog), "reason": payload.reason}, idempotency_key=idempotency_key)
        response = _catalog_read(db, catalog).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def get_pricing_catalog(db: Session, pricing_id: UUID) -> AiPricingCatalogRead:
    catalog = db.get(AiModelPricingCatalog, pricing_id)
    if catalog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI pricing catalog not found")
    return _catalog_read(db, catalog)


def update_pricing_catalog(db: Session, pricing_id: UUID, payload: AiPricingCatalogUpdate, admin: Admin) -> AiPricingCatalogRead:
    catalog = db.get(AiModelPricingCatalog, pricing_id)
    if catalog is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI pricing catalog not found")
    old_value = _snapshot_catalog(catalog)
    data = payload.model_dump(exclude_unset=True)
    for field in ("display_name", "description", "is_active"):
        if field in data:
            setattr(catalog, field, data[field])
    action = "ai_pricing_catalog.updated"
    if "is_active" in data:
        action = "ai_pricing_catalog.activated" if catalog.is_active else "ai_pricing_catalog.deactivated"
    _audit(db, admin=admin, action=action, old_value=old_value, new_value={**_snapshot_catalog(catalog), "reason": payload.reason})
    db.commit()
    db.refresh(catalog)
    return _catalog_read(db, catalog)


def create_pricing_version(db: Session, pricing_id: UUID, payload: AiPricingVersionCreate, idempotency_key: str, admin: Admin) -> AiPricingVersionRead | dict:
    _validate_version_payload(payload)
    request_hash = _request_hash({"pricing_id": str(pricing_id), **payload.model_dump(mode="json")})
    try:
        catalog = db.scalar(select(AiModelPricingCatalog).where(AiModelPricingCatalog.id == pricing_id).with_for_update(of=AiModelPricingCatalog))
        if catalog is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI pricing catalog not found")
        record = _start_idempotency(db, key=idempotency_key, action_type="ai_pricing.version.create", admin=admin, request_hash=request_hash)
        if isinstance(record, dict):
            return record
        if not catalog.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot create a version for an inactive pricing catalog")
        versions = list(db.scalars(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == catalog.id)))
        close_previous = _current_open_ended(versions, payload.effective_from)
        overlap_candidates = [version for version in versions if version is not close_previous]
        if any(_overlaps(version, payload.effective_from, payload.effective_to) for version in overlap_candidates):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pricing version effective period overlaps an existing version")
        if close_previous is not None:
            if _utc(payload.effective_from) <= _utc(close_previous.effective_from):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot safely close the current pricing version")
            close_previous.effective_to = payload.effective_from
            _audit(
                db,
                admin=admin,
                action="ai_pricing_version.closed",
                old_value=_snapshot_version(catalog, close_previous),
                new_value={**_snapshot_version(catalog, close_previous), "closed_at": payload.effective_from.isoformat()},
                idempotency_key=idempotency_key,
            )
        next_version = (max((version.version_number for version in versions), default=0) + 1)
        version = AiModelPricingVersion(
            pricing_catalog_id=catalog.id,
            provider=catalog.provider,
            model_name=catalog.provider_model_id,
            input_token_cost=payload.input_token_price,
            output_token_cost=payload.output_token_price,
            pricing_unit_tokens=payload.pricing_unit_tokens,
            currency=catalog.currency,
            currency_snapshot=catalog.currency,
            pricing_scope_snapshot=catalog.pricing_scope_code,
            pricing_source="manual",
            source_type=AiPricingSourceType.manual,
            source_reference=payload.source_reference,
            version_number=next_version,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            is_active=True,
            created_by=PricingCreatedBy.admin,
            created_by_admin_id=admin.id,
            note=payload.reason,
            created_at=_now(),
        )
        db.add(version)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Concurrent pricing version creation conflicted; retry the request") from exc
        _audit(db, admin=admin, action="ai_pricing_version.created", new_value=_snapshot_version(catalog, version), idempotency_key=idempotency_key)
        response = _version_read(version).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def list_pricing_versions(db: Session, pricing_id: UUID) -> list[AiPricingVersionRead]:
    if db.get(AiModelPricingCatalog, pricing_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI pricing catalog not found")
    rows = list(db.scalars(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == pricing_id).order_by(AiModelPricingVersion.version_number.desc())))
    return [item for item in (_version_read(row) for row in rows) if item is not None]


def get_pricing_version(db: Session, pricing_id: UUID, version_id: UUID) -> AiPricingVersionRead:
    version = db.get(AiModelPricingVersion, version_id)
    if version is None or version.pricing_catalog_id != pricing_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI pricing version not found")
    read = _version_read(version)
    assert read is not None
    return read
