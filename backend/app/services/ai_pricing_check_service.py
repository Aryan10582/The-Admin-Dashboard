from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
import hashlib
import json

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import AiPriceCheckStatus, AiPriceReviewDecision, AiPricingSourceType, AuditResultStatus, IdempotencyRecordStatus, PricingCreatedBy
from app.integrations.ai_pricing_adapters import NormalizedPricing, get_trusted_pricing_adapter
from app.models.admin import Admin
from app.models.ai import AIPriceCheckRun, AiModelPricingCatalog, AiModelPricingVersion
from app.models.audit import AuditLog
from app.models.idempotency import IdempotencyRecord
from app.schemas.ai_pricing import AiPriceCheckReviewRequest, AiPriceCheckRunRead, AiPricingSyncCheckRequest
from app.services.ai_pricing_catalog_service import _effective_state, _overlaps, _utc

STALE_RUNNING_AFTER = timedelta(minutes=15)


@dataclass(frozen=True)
class CheckRunFilters:
    pricing_catalog_id: UUID | None = None
    provider: str | None = None
    status: AiPriceCheckStatus | None = None
    reviewed: bool | None = None
    source_fingerprint: str | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.split())[:500]


def _request_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _audit(db: Session, *, admin: Admin, action: str, new_value: dict | None = None, idempotency_key: str | None = None, failure_message: str | None = None, result_status: AuditResultStatus = AuditResultStatus.success) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id,
            action=action,
            new_value=new_value,
            result_status=result_status,
            idempotency_key=idempotency_key,
            failure_message=_safe_error(failure_message),
            created_at=_now(),
        )
    )


def _read(run: AIPriceCheckRun) -> AiPriceCheckRunRead:
    return AiPriceCheckRunRead.model_validate(run)


def _complete_idempotency(db: Session, *, record: IdempotencyRecord | None, response: dict) -> None:
    if record is None:
        return
    record.status = IdempotencyRecordStatus.completed
    record.response_json = response


def _finalize_stale_running_checks(db: Session) -> None:
    cutoff = _now() - STALE_RUNNING_AFTER
    stale_runs = list(
        db.scalars(
            select(AIPriceCheckRun).where(
                AIPriceCheckRun.status == AiPriceCheckStatus.running,
                AIPriceCheckRun.started_at < cutoff,
            )
        )
    )
    if not stale_runs:
        return
    for run in stale_runs:
        run.status = AiPriceCheckStatus.failed
        run.completed_at = _now()
        run.safe_error = "Pricing check did not finish within the stale-run recovery window"
        if run.request_idempotency_key:
            record = db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.idempotency_key == run.request_idempotency_key,
                    IdempotencyRecord.action_type == "ai_pricing.sync_check",
                )
            )
            _complete_idempotency(db, record=record, response=_read(run).model_dump(mode="json"))
    db.commit()


def _get_replay(db: Session, key: str, action_type: str, request_hash: str) -> dict | None:
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))
    if record is None:
        return None
    if record.action_type != action_type:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different action")
    if record.request_hash and record.request_hash != request_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different pricing check request")
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


def _current_version(db: Session, catalog_id: UUID) -> AiModelPricingVersion | None:
    versions = list(db.scalars(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == catalog_id)))
    return next((version for version in versions if version.is_active and _effective_state(version) == "current"), None)


def _duplicate_fingerprint_version(db: Session, catalog_id: UUID, fingerprint: str | None) -> AiModelPricingVersion | None:
    if not fingerprint:
        return None
    return db.scalar(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == catalog_id, AiModelPricingVersion.source_fingerprint == fingerprint))


def _create_system_version(db: Session, *, catalog: AiModelPricingCatalog, candidate: NormalizedPricing | AIPriceCheckRun, admin: Admin, idempotency_key: str, note: str) -> AiModelPricingVersion | None:
    fingerprint = candidate.source_fingerprint
    existing = _duplicate_fingerprint_version(db, catalog.id, fingerprint)
    if existing is not None:
        return None
    effective_from = candidate.source_effective_at or _now()
    versions = list(db.scalars(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == catalog.id)))
    close_previous = next((version for version in versions if version.effective_to is None and _utc(version.effective_from) < _utc(effective_from)), None)
    overlap_candidates = [version for version in versions if version is not close_previous]
    if any(_overlaps(version, effective_from, None) for version in overlap_candidates):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate effective period conflicts with an existing pricing version")
    if close_previous is not None:
        close_previous.effective_to = effective_from
    next_version = (max((version.version_number for version in versions), default=0) + 1)
    version = AiModelPricingVersion(
        pricing_catalog_id=catalog.id,
        provider=catalog.provider,
        model_name=catalog.provider_model_id,
        input_token_cost=candidate.candidate_input_price if isinstance(candidate, AIPriceCheckRun) else candidate.input_token_price,
        output_token_cost=candidate.candidate_output_price if isinstance(candidate, AIPriceCheckRun) else candidate.output_token_price,
        pricing_unit_tokens=candidate.candidate_pricing_unit_tokens if isinstance(candidate, AIPriceCheckRun) else candidate.pricing_unit_tokens,
        currency=catalog.currency,
        currency_snapshot=catalog.currency,
        pricing_scope_snapshot=catalog.pricing_scope_code,
        pricing_source="trusted_adapter",
        source_type=AiPricingSourceType.provider_check,
        source_reference=candidate.source_reference,
        source_fingerprint=fingerprint,
        version_number=next_version,
        effective_from=effective_from,
        effective_to=None,
        is_active=True,
        created_by=PricingCreatedBy.system if not isinstance(candidate, AIPriceCheckRun) else PricingCreatedBy.admin,
        created_by_admin_id=admin.id,
        note=note,
        created_at=_now(),
    )
    db.add(version)
    db.flush()
    return version


def _candidate_requires_review(catalog: AiModelPricingCatalog, candidate: NormalizedPricing) -> str | None:
    if candidate.is_ambiguous:
        return candidate.safe_error or "Pricing source returned ambiguous values"
    if candidate.provider_model_id != catalog.provider_model_id:
        return "Source model does not match pricing catalog"
    if candidate.pricing_scope_code != catalog.pricing_scope_code:
        return "Source pricing scope does not match pricing catalog"
    if not candidate.currency:
        return "Pricing source did not include currency"
    if candidate.currency != catalog.currency:
        return "Pricing source currency does not match catalog"
    if candidate.pricing_unit_tokens is None or candidate.pricing_unit_tokens <= 0:
        return "Pricing source did not include a valid pricing unit"
    if candidate.input_token_price is None:
        return "Pricing source did not include input token price"
    if candidate.output_token_price is None:
        return "Pricing source did not include output token price"
    if candidate.source_effective_at is None:
        return "Pricing source did not include a trustworthy effective time"
    if candidate.source_fingerprint is None:
        return "Pricing source did not include a valid fingerprint"
    return None


def _prices_unchanged(current: AiModelPricingVersion | None, candidate: NormalizedPricing) -> bool:
    if current is None:
        return False
    return (
        current.input_token_cost == candidate.input_token_price
        and current.output_token_cost == candidate.output_token_price
        and current.pricing_unit_tokens == candidate.pricing_unit_tokens
        and current.currency == candidate.currency
    )


def run_pricing_sync_check(db: Session, payload: AiPricingSyncCheckRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash(payload.model_dump(mode="json"))
    action_type = "ai_pricing.sync_check"
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type=action_type, admin=admin, request_hash=request_hash)
        if isinstance(record, dict):
            return record
        catalog = db.get(AiModelPricingCatalog, payload.pricing_catalog_id) if payload.pricing_catalog_id else None
        if catalog is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing catalog is required for Phase 9A.2 sync checks")
        run = AIPriceCheckRun(
            pricing_catalog_id=catalog.id,
            provider=catalog.provider,
            pricing_scope_code=catalog.pricing_scope_code,
            started_at=_now(),
            requested_by_admin_id=admin.id,
            reason=payload.reason,
            request_idempotency_key=idempotency_key,
            status=AiPriceCheckStatus.running,
        )
        db.add(run)
        _audit(db, admin=admin, action="ai_pricing_check.started", new_value={"pricing_catalog_id": str(catalog.id), "provider": catalog.provider}, idempotency_key=idempotency_key)
        db.flush()
        db.commit()

        adapter = get_trusted_pricing_adapter(payload.adapter_code, catalog.provider)
        if adapter is None:
            run = db.get(AIPriceCheckRun, run.id)
            run.status = AiPriceCheckStatus.unsupported
            run.completed_at = _now()
            run.safe_error = "No trusted configured pricing adapter supports this provider"
            _audit(db, admin=admin, action="ai_pricing_check.unsupported", new_value={"check_run_id": str(run.id), "provider": catalog.provider}, idempotency_key=idempotency_key, failure_message=run.safe_error)
            record = db.get(IdempotencyRecord, record.id)
            response = _read(run).model_dump(mode="json")
            record.status = IdempotencyRecordStatus.completed
            record.response_json = response
            db.commit()
            return response

        try:
            candidate = adapter.fetch_pricing(provider=catalog.provider, provider_model_id=catalog.provider_model_id, pricing_scope_code=catalog.pricing_scope_code, scenario=payload.mock_scenario)
        except Exception as exc:  # noqa: BLE001 - adapter failures must finalize safely
            run = db.get(AIPriceCheckRun, run.id)
            run.status = AiPriceCheckStatus.failed
            run.completed_at = _now()
            run.safe_error = "Trusted pricing adapter failed"
            _audit(db, admin=admin, action="ai_pricing_check.failed", new_value={"check_run_id": str(run.id)}, idempotency_key=idempotency_key, failure_message=run.safe_error, result_status=AuditResultStatus.failure)
            record = db.get(IdempotencyRecord, record.id)
            response = _read(run).model_dump(mode="json")
            _complete_idempotency(db, record=record, response=response)
            db.commit()
            return response
        catalog = db.scalar(select(AiModelPricingCatalog).where(AiModelPricingCatalog.id == catalog.id).with_for_update(of=AiModelPricingCatalog))
        run = db.get(AIPriceCheckRun, run.id)
        run.source_reference = candidate.source_reference
        run.source_fingerprint = candidate.source_fingerprint
        run.source_effective_at = candidate.source_effective_at
        run.candidate_input_price = candidate.input_token_price
        run.candidate_output_price = candidate.output_token_price
        run.candidate_currency = candidate.currency
        run.candidate_pricing_unit_tokens = candidate.pricing_unit_tokens
        run.candidate_provider_model_id = candidate.provider_model_id
        run.completed_at = _now()
        if not candidate.is_authoritative and not any([candidate.currency, candidate.input_token_price, candidate.output_token_price]):
            run.status = AiPriceCheckStatus.source_unavailable if "timeout" in (candidate.safe_error or "").lower() or "failure" in (candidate.safe_error or "").lower() else AiPriceCheckStatus.invalid_response
            run.safe_error = candidate.safe_error
            _audit(db, admin=admin, action="ai_pricing_check.failed", new_value={"check_run_id": str(run.id)}, idempotency_key=idempotency_key, failure_message=run.safe_error, result_status=AuditResultStatus.failure)
        else:
            review_reason = _candidate_requires_review(catalog, candidate)
            if review_reason:
                run.status = AiPriceCheckStatus.requires_manual_review
                run.safe_error = review_reason
                _audit(db, admin=admin, action="ai_pricing_check.review_created", new_value={"check_run_id": str(run.id), "reason": review_reason}, idempotency_key=idempotency_key)
            elif _prices_unchanged(_current_version(db, catalog.id), candidate):
                run.status = AiPriceCheckStatus.unchanged
                _audit(db, admin=admin, action="ai_pricing_check.unchanged", new_value={"check_run_id": str(run.id)}, idempotency_key=idempotency_key)
            elif _duplicate_fingerprint_version(db, catalog.id, candidate.source_fingerprint) is not None:
                run.status = AiPriceCheckStatus.unchanged
                run.safe_error = "Source fingerprint already processed"
                _audit(db, admin=admin, action="ai_pricing_check.unchanged", new_value={"check_run_id": str(run.id), "source_fingerprint": candidate.source_fingerprint}, idempotency_key=idempotency_key)
            else:
                version = _create_system_version(db, catalog=catalog, candidate=candidate, admin=admin, idempotency_key=idempotency_key, note=payload.reason)
                run.created_version_id = version.id if version else None
                run.status = AiPriceCheckStatus.version_created if version else AiPriceCheckStatus.unchanged
                _audit(
                    db,
                    admin=admin,
                    action="ai_pricing_check.version_created" if version else "ai_pricing_check.unchanged",
                    new_value={"check_run_id": str(run.id), "created_version_id": str(run.created_version_id)},
                    idempotency_key=idempotency_key,
                )
        response = _read(run).model_dump(mode="json")
        record = db.get(IdempotencyRecord, record.id)
        _complete_idempotency(db, record=record, response=response)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def list_check_runs(db: Session, filters: CheckRunFilters, *, limit: int, offset: int) -> tuple[list[AiPriceCheckRunRead], int]:
    _finalize_stale_running_checks(db)
    stmt: Select = select(AIPriceCheckRun)
    if filters.pricing_catalog_id:
        stmt = stmt.where(AIPriceCheckRun.pricing_catalog_id == filters.pricing_catalog_id)
    if filters.provider:
        stmt = stmt.where(AIPriceCheckRun.provider == filters.provider.lower())
    if filters.status:
        stmt = stmt.where(AIPriceCheckRun.status == filters.status)
    if filters.reviewed is not None:
        stmt = stmt.where(AIPriceCheckRun.reviewed_at.is_not(None) if filters.reviewed else AIPriceCheckRun.reviewed_at.is_(None))
    if filters.source_fingerprint:
        stmt = stmt.where(AIPriceCheckRun.source_fingerprint == filters.source_fingerprint)
    if filters.started_from:
        stmt = stmt.where(AIPriceCheckRun.started_at >= filters.started_from)
    if filters.started_to:
        stmt = stmt.where(AIPriceCheckRun.started_at <= filters.started_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AIPriceCheckRun.started_at.desc()).limit(limit).offset(offset)))
    return [_read(row) for row in rows], total


def get_check_run(db: Session, check_run_id: UUID) -> AiPriceCheckRunRead:
    _finalize_stale_running_checks(db)
    run = db.get(AIPriceCheckRun, check_run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing check run not found")
    return _read(run)


def approve_check_run(db: Session, check_run_id: UUID, payload: AiPriceCheckReviewRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash({"check_run_id": str(check_run_id), "reason": payload.reason})
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type="ai_pricing.check_run.approve", admin=admin, request_hash=request_hash)
        if isinstance(record, dict):
            return record
        run = db.scalar(select(AIPriceCheckRun).where(AIPriceCheckRun.id == check_run_id).with_for_update(of=AIPriceCheckRun))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing check run not found")
        if run.status != AiPriceCheckStatus.requires_manual_review or run.reviewed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pricing check run is not awaiting review")
        catalog = db.scalar(select(AiModelPricingCatalog).where(AiModelPricingCatalog.id == run.pricing_catalog_id).with_for_update(of=AiModelPricingCatalog))
        if catalog is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing catalog not found")
        if _duplicate_fingerprint_version(db, catalog.id, run.source_fingerprint) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source fingerprint already created a pricing version")
        if (
            run.provider != catalog.provider
            or run.pricing_scope_code != catalog.pricing_scope_code
            or run.candidate_currency != catalog.currency
            or run.candidate_provider_model_id != catalog.provider_model_id
            or run.source_effective_at is None
            or run.source_fingerprint is None
            or run.candidate_input_price is None
            or run.candidate_output_price is None
            or not run.candidate_pricing_unit_tokens
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate values are not complete enough for approval")
        version = _create_system_version(db, catalog=catalog, candidate=run, admin=admin, idempotency_key=idempotency_key, note=payload.reason)
        if version is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source fingerprint already created a pricing version")
        run.status = AiPriceCheckStatus.approved
        run.review_decision = AiPriceReviewDecision.approved
        run.reviewed_by_admin_id = admin.id
        run.reviewed_at = _now()
        run.review_note = payload.reason
        run.created_version_id = version.id if version else None
        _audit(db, admin=admin, action="ai_pricing_check.approved", new_value={"check_run_id": str(run.id), "created_version_id": str(run.created_version_id)}, idempotency_key=idempotency_key)
        response = _read(run).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def reject_check_run(db: Session, check_run_id: UUID, payload: AiPriceCheckReviewRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash({"check_run_id": str(check_run_id), "reason": payload.reason})
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type="ai_pricing.check_run.reject", admin=admin, request_hash=request_hash)
        if isinstance(record, dict):
            return record
        run = db.scalar(select(AIPriceCheckRun).where(AIPriceCheckRun.id == check_run_id).with_for_update(of=AIPriceCheckRun))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing check run not found")
        if run.status != AiPriceCheckStatus.requires_manual_review or run.reviewed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pricing check run is not awaiting review")
        run.status = AiPriceCheckStatus.rejected
        run.review_decision = AiPriceReviewDecision.rejected
        run.reviewed_by_admin_id = admin.id
        run.reviewed_at = _now()
        run.review_note = payload.reason
        _audit(db, admin=admin, action="ai_pricing_check.rejected", new_value={"check_run_id": str(run.id), "reason": payload.reason}, idempotency_key=idempotency_key)
        response = _read(run).model_dump(mode="json")
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
