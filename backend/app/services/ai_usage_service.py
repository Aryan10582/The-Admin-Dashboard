from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    AiUsageConflictStatus,
    AiUsageFinalizationStatus,
    AiUsageMappingResolutionStatus,
    AiUsagePricingResolutionStatus,
    AiUsageSyncRunStatus,
    AuditResultStatus,
    FailureStatus,
    IdempotencyRecordStatus,
    MappingStatus,
    SyncStatus,
)
from app.core.product_secrets import decrypt_product_secret
from app.integrations.product_admin_client import ProductTokenUsageItem
from app.models.admin import Admin
from app.models.ai import AIUsageSyncRun, AIUsageSyncState, AiModelPricingCatalog, AiModelPricingVersion, AiUsageRecord, ProductAIModelPricingMapping
from app.models.audit import AuditLog
from app.models.failure_log import FailureLog
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization, OrganizationMapping
from app.models.product import ProductDeployment
from app.schemas.ai_usage import (
    AIUsageBatchResolutionResponse,
    AIUsageBatchResolveMappingsRequest,
    AIUsageBatchResolvePricingRequest,
    AIUsageConflictDetail,
    AIUsageConflictReviewRequest,
    AIUsageListResponse,
    AIUsageRead,
    AIUsageResolutionItemResult,
    AIUsageResolvePricingRequest,
    AIUsageSummary,
    AIUsageSyncRunListResponse,
    AIUsageSyncRunRead,
    AIUsageSyncStateRead,
    CurrencyCostSummary,
    ProviderModelUsageSummary,
    ProductAIModelPricingMappingCreate,
    ProductAIModelPricingMappingRead,
    ProductAIModelPricingMappingUpdate,
    RankedCostSummary,
    TokenUsageSyncRequest,
)
from app.services.product_client import build_product_client


MAX_FUTURE_SKEW = timedelta(minutes=10)
MAX_HISTORY = timedelta(days=3650)


@dataclass(frozen=True)
class UsageFilters:
    product_deployment_id: UUID | None = None
    organization_id: UUID | None = None
    product_organization_id: str | None = None
    provider: str | None = None
    product_model_id: str | None = None
    usage_from: datetime | None = None
    usage_to: datetime | None = None
    pricing_catalog_id: UUID | None = None
    pricing_version_id: UUID | None = None
    cost_currency: str | None = None
    pricing_resolution_status: AiUsagePricingResolutionStatus | None = None
    mapping_resolution_status: AiUsageMappingResolutionStatus | None = None
    conflict_status: AiUsageConflictStatus | None = None
    finalization_status: AiUsageFinalizationStatus | None = None
    product_usage_id: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(message: str | None) -> str | None:
    if not message:
        return None
    return " ".join(message.split())[:500]


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _request_hash(payload: dict) -> str:
    return _hash(payload)


def _get_replay(db: Session, key: str, action_type: str, request_hash: str) -> dict | None:
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))
    if record is None:
        return None
    if record.action_type != action_type:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different action")
    if record.request_hash and record.request_hash != request_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used for a different request")
    if record.status == IdempotencyRecordStatus.completed and record.response_json is not None:
        return record.response_json
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress")


def _start_idempotency(db: Session, *, key: str, action_type: str, request_hash: str, admin: Admin) -> IdempotencyRecord | dict:
    replay = _get_replay(db, key, action_type, request_hash)
    if replay is not None:
        return replay
    record = IdempotencyRecord(idempotency_key=key, action_type=action_type, request_hash=request_hash, status=IdempotencyRecordStatus.started, created_at=_now(), admin_id=admin.id)
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


def _audit(db: Session, *, admin: Admin, product_id: UUID | None, action: str, new_value: dict | None = None, idempotency_key: str | None = None, result_status: AuditResultStatus = AuditResultStatus.success, failure_message: str | None = None) -> None:
    db.add(AuditLog(admin_id=admin.id, product_deployment_id=product_id, action=action, new_value=new_value, idempotency_key=idempotency_key, result_status=result_status, failure_message=_safe_error(failure_message), created_at=_now()))


def _failure(db: Session, *, admin: Admin, product: ProductDeployment, action: str, code: str, message: str, product_usage_id: str | None = None) -> None:
    db.add(
        FailureLog(
            product_deployment_id=product.id,
            action_attempted=action,
            error_message=_safe_error(message) or "AI usage sync failure",
            error_code=code,
            retry_count=0,
            current_status=FailureStatus.open,
            idempotency_key=product_usage_id,
            admin_id=admin.id,
            product_api_version=product.admin_api_version,
            created_at=_now(),
        )
    )


def _normalize_provider(value: str) -> str:
    return value.strip().lower()


def _parse_utc(value: str | None, field: str) -> datetime:
    if not value:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    utc = parsed.astimezone(timezone.utc)
    now = _now()
    if utc > now + MAX_FUTURE_SKEW:
        raise ValueError(f"{field} is unreasonably far in the future")
    if utc < now - MAX_HISTORY:
        raise ValueError(f"{field} is outside retention policy")
    return utc


def _identity_snapshot(item: ProductTokenUsageItem, usage_at: datetime | None = None) -> dict:
    return {
        "product_organization_id": item.product_organization_id,
        "provider": _normalize_provider(item.provider),
        "product_model_id": item.product_model_id.strip(),
        "input_tokens": item.input_tokens,
        "output_tokens": item.output_tokens,
        "usage_at": usage_at.isoformat() if usage_at else item.usage_at,
        "is_final": item.is_final,
        "usage_revision": item.usage_revision,
        "unsupported_dimensions": item.unsupported_dimensions or {},
    }


def _stored_identity_snapshot(row: AiUsageRecord) -> dict:
    usage_at = row.usage_at
    if usage_at is not None and (usage_at.tzinfo is None or usage_at.utcoffset() is None):
        usage_at = usage_at.replace(tzinfo=timezone.utc)
    return {
        "product_organization_id": row.product_organization_id,
        "provider": row.provider,
        "product_model_id": row.product_model_id or row.model_name,
        "input_tokens": int(row.input_tokens),
        "output_tokens": int(row.output_tokens),
        "usage_at": usage_at.isoformat() if usage_at else None,
        "is_final": bool(row.is_final),
        "usage_revision": row.usage_revision,
        "unsupported_dimensions": {},
    }


def _invalid_usage_id(item: ProductTokenUsageItem, index: int) -> str:
    return f"invalid:{_hash({'index': index, 'product_usage_id': item.product_usage_id, 'request_id': item.request_id})[:40]}"


def _find_organization_id(db: Session, product: ProductDeployment, product_organization_id: str) -> UUID | None:
    mapping = db.scalar(
        select(OrganizationMapping).where(
            OrganizationMapping.product_deployment_id == product.id,
            OrganizationMapping.product_organization_id == product_organization_id,
                OrganizationMapping.mapping_status == MappingStatus.active,
        )
    )
    return mapping.organization_id if mapping else None


def _find_pricing_mapping(db: Session, product: ProductDeployment, provider: str, product_model_id: str) -> ProductAIModelPricingMapping | None:
    return db.scalar(
        select(ProductAIModelPricingMapping).where(
            ProductAIModelPricingMapping.product_deployment_id == product.id,
            ProductAIModelPricingMapping.product_provider == provider,
            ProductAIModelPricingMapping.product_model_id == product_model_id,
            ProductAIModelPricingMapping.is_active.is_(True),
        )
    )


def _effective_versions(db: Session, catalog_id: UUID, usage_at: datetime) -> list[AiModelPricingVersion]:
    versions = list(
        db.scalars(
            select(AiModelPricingVersion)
            .where(
                AiModelPricingVersion.pricing_catalog_id == catalog_id,
                AiModelPricingVersion.is_active.is_(True),
            )
            .order_by(AiModelPricingVersion.effective_from.asc(), AiModelPricingVersion.id.asc())
        )
    )
    return [version for version in versions if _version_is_effective(version, usage_at)]


def _calculate_cost(tokens: int, unit: int, rate: Decimal) -> Decimal:
    return (Decimal(tokens) / Decimal(unit)) * rate


def _lock_usage(db: Session, usage_id: UUID) -> AiUsageRecord:
    row = db.scalar(select(AiUsageRecord).where(AiUsageRecord.id == usage_id).with_for_update(of=AiUsageRecord))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI usage record not found")
    return row


def _version_is_effective(version: AiModelPricingVersion, usage_at: datetime) -> bool:
    effective_from = version.effective_from
    effective_to = version.effective_to
    if effective_from.tzinfo is None:
        effective_from = effective_from.replace(tzinfo=timezone.utc)
    if effective_to is not None and effective_to.tzinfo is None:
        effective_to = effective_to.replace(tzinfo=timezone.utc)
    return effective_from <= usage_at and (effective_to is None or usage_at < effective_to)


def _safe_original_snapshot(row: AiUsageRecord) -> dict:
    return {
        "product_deployment_id": str(row.product_deployment_id),
        "product_usage_id": row.product_usage_id,
        "product_organization_id": row.product_organization_id,
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "provider": row.provider,
        "product_model_id": row.product_model_id,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "usage_at": row.usage_at.isoformat() if row.usage_at else None,
        "usage_revision": row.usage_revision,
        "is_final": row.is_final,
        "pricing_mapping_id": str(row.pricing_mapping_id) if row.pricing_mapping_id else None,
        "pricing_catalog_id": str(row.pricing_catalog_id) if row.pricing_catalog_id else None,
        "pricing_version_id": str(row.pricing_version_id) if row.pricing_version_id else None,
        "pricing_unit_tokens": row.pricing_unit_tokens,
        "input_token_price": str(row.input_token_price) if row.input_token_price is not None else None,
        "output_token_price": str(row.output_token_price) if row.output_token_price is not None else None,
        "cost_currency": row.cost_currency,
        "input_cost": str(row.input_cost) if row.input_cost is not None else None,
        "output_cost": str(row.output_cost) if row.output_cost is not None else None,
        "total_cost": str(row.total_cost) if row.total_cost is not None else None,
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


def _pricing_resolution_outcome(db: Session, row: AiUsageRecord, pricing_version_id: UUID | None = None) -> tuple[str, AiModelPricingVersion | None, ProductAIModelPricingMapping | None, str | None]:
    if row.total_cost is not None or row.pricing_resolution_status == AiUsagePricingResolutionStatus.resolved:
        return "already_resolved", None, None, None
    if row.conflict_status == AiUsageConflictStatus.conflict:
        return "conflict", None, None, "Conflicting usage must be reviewed before pricing resolution"
    if row.finalization_status == AiUsageFinalizationStatus.invalid or row.invalid_reason:
        return "invalid", None, None, "Invalid usage cannot be priced"
    if not row.is_final or row.finalization_status == AiUsageFinalizationStatus.non_final:
        return "non_final", None, None, "Non-final usage cannot be finalized"
    if row.pricing_resolution_status == AiUsagePricingResolutionStatus.unsupported_dimensions:
        return "unsupported_dimensions", None, None, "Unsupported pricing dimensions require a later correction workflow"
    if row.usage_at is None:
        return "failed", None, None, "Usage timestamp is required"
    product = db.get(ProductDeployment, row.product_deployment_id)
    if product is None or not row.product_model_id:
        return "failed", None, None, "Product deployment or model identity is missing"
    mapping = _find_pricing_mapping(db, product, row.provider, row.product_model_id)
    if mapping is None:
        inactive = db.scalar(
            select(ProductAIModelPricingMapping).where(
                ProductAIModelPricingMapping.product_deployment_id == product.id,
                ProductAIModelPricingMapping.product_provider == row.provider,
                ProductAIModelPricingMapping.product_model_id == row.product_model_id,
                ProductAIModelPricingMapping.is_active.is_(False),
            )
        )
        return ("mapping_inactive" if inactive else "mapping_missing"), None, None, "Create or activate the exact product-model pricing mapping first"
    catalog = db.get(AiModelPricingCatalog, mapping.pricing_catalog_id)
    if catalog is None:
        return "failed", None, mapping, "Mapped pricing catalog was not found"
    if catalog.provider != row.provider:
        return "failed", None, mapping, "Mapped catalog provider does not match usage provider"
    usage_at = row.usage_at if row.usage_at.tzinfo else row.usage_at.replace(tzinfo=timezone.utc)
    if pricing_version_id is not None:
        version = db.get(AiModelPricingVersion, pricing_version_id)
        if version is None or version.pricing_catalog_id != mapping.pricing_catalog_id:
            return "failed", None, mapping, "Pricing version must belong to the exact mapped catalog"
        if not version.is_active or not _version_is_effective(version, usage_at):
            return "no_effective_version", None, mapping, "Pricing version is not effective for usage_at"
        versions = [version]
    else:
        versions = _effective_versions(db, mapping.pricing_catalog_id, usage_at)
    if len(versions) == 0:
        return "no_effective_version", None, mapping, "No active pricing version is effective for usage_at"
    if len(versions) > 1:
        return "multiple_effective_versions", None, mapping, "Multiple pricing versions match usage_at; provide the exact version after fixing pricing history"
    version = versions[0]
    if version.currency != catalog.currency:
        return "failed", None, mapping, "Pricing version currency does not match mapped catalog"
    if version.provider != catalog.provider:
        return "failed", None, mapping, "Pricing version provider does not match mapped catalog"
    return "resolved", version, mapping, None


def _finalize_pricing(row: AiUsageRecord, version: AiModelPricingVersion, mapping: ProductAIModelPricingMapping) -> None:
    row.pricing_mapping_id = mapping.id
    row.pricing_catalog_id = mapping.pricing_catalog_id
    row.pricing_version_id = version.id
    row.pricing_unit_tokens = version.pricing_unit_tokens
    row.input_token_price = version.input_token_cost
    row.output_token_price = version.output_token_cost
    row.cost_currency = version.currency
    row.input_cost = _calculate_cost(row.input_tokens, version.pricing_unit_tokens, version.input_token_cost)
    row.output_cost = _calculate_cost(row.output_tokens, version.pricing_unit_tokens, version.output_token_cost)
    row.total_cost = row.input_cost + row.output_cost
    row.calculated_cost = row.total_cost
    row.calculated_at = _now()
    row.pricing_resolution_status = AiUsagePricingResolutionStatus.resolved


def _read_usage(row: AiUsageRecord) -> AIUsageRead:
    return AIUsageRead.model_validate(row)


def _apply_sync_outcome(run: AIUsageSyncRun, outcome: str, row: AiUsageRecord) -> None:
    if outcome == "imported":
        run.imported_count += 1
        if row.total_cost is not None:
            run.finalized_cost_count += 1
        if row.pricing_resolution_status != AiUsagePricingResolutionStatus.resolved:
            run.unresolved_pricing_count += 1
        if row.mapping_resolution_status != AiUsageMappingResolutionStatus.resolved:
            run.unresolved_mapping_count += 1
    elif outcome == "unchanged":
        run.unchanged_count += 1
    elif outcome == "conflict":
        run.conflict_count += 1
    elif outcome == "invalid":
        run.invalid_count += 1


def list_model_mappings(db: Session, product_id: UUID) -> list[ProductAIModelPricingMappingRead]:
    rows = list(db.scalars(select(ProductAIModelPricingMapping).where(ProductAIModelPricingMapping.product_deployment_id == product_id).order_by(ProductAIModelPricingMapping.created_at.desc())))
    return [ProductAIModelPricingMappingRead.model_validate(row) for row in rows]


def get_sync_state(db: Session, product_id: UUID) -> AIUsageSyncStateRead | None:
    state = db.get(AIUsageSyncState, product_id)
    return AIUsageSyncStateRead.model_validate(state) if state is not None else None


def list_sync_runs(db: Session, product_id: UUID, *, limit: int, offset: int) -> AIUsageSyncRunListResponse:
    stmt = select(AIUsageSyncRun).where(AIUsageSyncRun.product_deployment_id == product_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AIUsageSyncRun.started_at.desc(), AIUsageSyncRun.id.desc()).limit(limit).offset(offset)))
    return AIUsageSyncRunListResponse(items=[AIUsageSyncRunRead.model_validate(row) for row in rows], total=total, limit=limit, offset=offset)


def get_model_mapping(db: Session, product_id: UUID, mapping_id: UUID) -> ProductAIModelPricingMappingRead:
    row = db.get(ProductAIModelPricingMapping, mapping_id)
    if row is None or row.product_deployment_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI model pricing mapping not found")
    return ProductAIModelPricingMappingRead.model_validate(row)


def create_model_mapping(db: Session, product_id: UUID, payload: ProductAIModelPricingMappingCreate, idempotency_key: str, admin: Admin) -> ProductAIModelPricingMappingRead | dict:
    request_hash = _request_hash({"product_id": str(product_id), **payload.model_dump(mode="json")})
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type=f"ai_usage.model_mapping.create:{product_id}", request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        product = db.get(ProductDeployment, product_id)
        catalog = db.get(AiModelPricingCatalog, payload.pricing_catalog_id)
        if product is None or catalog is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment or pricing catalog not found")
        row = ProductAIModelPricingMapping(
            product_deployment_id=product_id,
            product_provider=payload.product_provider,
            product_model_id=payload.product_model_id,
            pricing_catalog_id=payload.pricing_catalog_id,
            is_active=True,
            verified_at=_now(),
            created_by_admin_id=admin.id,
            note=payload.reason,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product model pricing mapping already exists") from exc
        response = ProductAIModelPricingMappingRead.model_validate(row).model_dump(mode="json")
        _audit(db, admin=admin, product_id=product_id, action="ai_usage.model_mapping.created", new_value=response, idempotency_key=idempotency_key)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def update_model_mapping(db: Session, product_id: UUID, mapping_id: UUID, payload: ProductAIModelPricingMappingUpdate, idempotency_key: str, admin: Admin) -> ProductAIModelPricingMappingRead | dict:
    request_hash = _request_hash({"product_id": str(product_id), "mapping_id": str(mapping_id), **payload.model_dump(mode="json")})
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type=f"ai_usage.model_mapping.update:{mapping_id}", request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        row = db.scalar(select(ProductAIModelPricingMapping).where(ProductAIModelPricingMapping.id == mapping_id, ProductAIModelPricingMapping.product_deployment_id == product_id).with_for_update(of=ProductAIModelPricingMapping))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI model pricing mapping not found")
        if payload.pricing_catalog_id is not None and db.get(AiModelPricingCatalog, payload.pricing_catalog_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing catalog not found")
        if payload.pricing_catalog_id is not None:
            row.pricing_catalog_id = payload.pricing_catalog_id
            row.verified_at = _now()
        if payload.is_active is not None:
            row.is_active = payload.is_active
        row.note = payload.reason
        response = ProductAIModelPricingMappingRead.model_validate(row).model_dump(mode="json")
        _audit(db, admin=admin, product_id=product_id, action="ai_usage.model_mapping.updated", new_value=response, idempotency_key=idempotency_key)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def _process_item(db: Session, *, product: ProductDeployment, item: ProductTokenUsageItem, index: int, admin: Admin) -> tuple[str, AiUsageRecord]:
    usage_id = item.product_usage_id.strip() or _invalid_usage_id(item, index)
    existing = db.scalar(select(AiUsageRecord).where(AiUsageRecord.product_deployment_id == product.id, AiUsageRecord.product_usage_id == usage_id))
    try:
        if not item.product_usage_id.strip():
            raise ValueError("product_usage_id is required")
        if not item.product_organization_id.strip():
            raise ValueError("product_organization_id is required")
        provider = _normalize_provider(item.provider)
        if not provider:
            raise ValueError("provider is required")
        product_model_id = item.product_model_id.strip()
        if not product_model_id:
            raise ValueError("product_model_id is required")
        if item.input_tokens < 0 or item.output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        usage_at = _parse_utc(item.usage_at, "usage_at")
        finalized_at = _parse_utc(item.finalized_at, "finalized_at") if item.finalized_at else None
    except ValueError as exc:
        if existing is not None:
            return "unchanged", existing
        row = AiUsageRecord(
            product_deployment_id=product.id,
            product_usage_id=usage_id,
            product_organization_id=item.product_organization_id or None,
            provider=_normalize_provider(item.provider or "invalid"),
            model_name=item.product_model_id or "invalid",
            product_model_id=item.product_model_id or None,
            input_tokens=max(item.input_tokens, 0),
            output_tokens=max(item.output_tokens, 0),
            total_tokens=max(item.input_tokens, 0) + max(item.output_tokens, 0),
            usage_date=_now().date(),
            finalization_status=AiUsageFinalizationStatus.invalid,
            pricing_resolution_status=AiUsagePricingResolutionStatus.requires_pricing_resolution,
            mapping_resolution_status=AiUsageMappingResolutionStatus.requires_mapping_resolution,
            conflict_status=AiUsageConflictStatus.none,
            invalid_reason=_safe_error(str(exc)),
            sync_status=SyncStatus.failed,
            request_reference=item.request_id,
        )
        db.add(row)
        _failure(db, admin=admin, product=product, action="ai_usage.invalid_item", code="invalid_usage_item", message=str(exc), product_usage_id=usage_id)
        return "invalid", row

    snapshot = _identity_snapshot(item, usage_at)
    if existing is not None:
        existing_snapshot = _stored_identity_snapshot(existing)
        if existing_snapshot == snapshot:
            return "unchanged", existing
        existing.conflict_status = AiUsageConflictStatus.conflict
        existing.conflict_snapshot = {"candidate_fingerprint": _hash(snapshot), "candidate": snapshot}
        _failure(db, admin=admin, product=product, action="ai_usage.conflicting_replay", code="conflicting_usage_replay", message="Product usage replay changed immutable fields", product_usage_id=usage_id)
        return "conflict", existing

    organization_id = _find_organization_id(db, product, item.product_organization_id)
    mapping_status = AiUsageMappingResolutionStatus.resolved if organization_id else AiUsageMappingResolutionStatus.requires_mapping_resolution
    pricing_status = AiUsagePricingResolutionStatus.requires_pricing_resolution
    mapping = _find_pricing_mapping(db, product, provider, product_model_id)
    versions: list[AiModelPricingVersion] = []
    if mapping and not item.unsupported_dimensions:
        versions = _effective_versions(db, mapping.pricing_catalog_id, usage_at)
        if len(versions) == 1:
            pricing_status = AiUsagePricingResolutionStatus.resolved
        else:
            pricing_status = AiUsagePricingResolutionStatus.requires_pricing_resolution
    elif item.unsupported_dimensions:
        pricing_status = AiUsagePricingResolutionStatus.unsupported_dimensions

    row = AiUsageRecord(
        product_deployment_id=product.id,
        product_usage_id=usage_id,
        product_organization_id=item.product_organization_id,
        organization_id=organization_id,
        provider=provider,
        model_name=product_model_id,
        product_model_id=product_model_id,
        input_tokens=item.input_tokens,
        output_tokens=item.output_tokens,
        total_tokens=item.input_tokens + item.output_tokens,
        usage_at=usage_at,
        usage_date=usage_at.date(),
        usage_revision=item.usage_revision,
        is_final=item.is_final,
        finalized_at=finalized_at,
        finalization_status=AiUsageFinalizationStatus.finalized if item.is_final else AiUsageFinalizationStatus.non_final,
        pricing_mapping_id=mapping.id if mapping else None,
        pricing_catalog_id=mapping.pricing_catalog_id if mapping else None,
        pricing_resolution_status=pricing_status,
        mapping_resolution_status=mapping_status,
        conflict_status=AiUsageConflictStatus.none,
        campaign_reference=item.campaign_id,
        conversation_reference=item.conversation_id,
        lead_reference=item.lead_id,
        request_reference=item.request_id,
        sync_status=SyncStatus.synced,
    )
    if item.is_final and pricing_status == AiUsagePricingResolutionStatus.resolved:
        version = versions[0]
        row.pricing_version_id = version.id
        row.pricing_unit_tokens = version.pricing_unit_tokens
        row.input_token_price = version.input_token_cost
        row.output_token_price = version.output_token_cost
        row.cost_currency = version.currency
        row.input_cost = _calculate_cost(item.input_tokens, version.pricing_unit_tokens, version.input_token_cost)
        row.output_cost = _calculate_cost(item.output_tokens, version.pricing_unit_tokens, version.output_token_cost)
        row.total_cost = row.input_cost + row.output_cost
        row.calculated_cost = row.total_cost
        row.calculated_at = _now()
    elif not item.is_final:
        row.pricing_resolution_status = AiUsagePricingResolutionStatus.requires_pricing_resolution
    if pricing_status != AiUsagePricingResolutionStatus.resolved:
        _failure(db, admin=admin, product=product, action="ai_usage.pricing_resolution", code=pricing_status.value, message="AI usage pricing could not be resolved", product_usage_id=usage_id)
    db.add(row)
    return "imported", row


async def sync_token_usage(db: Session, product_id: UUID, payload: TokenUsageSyncRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash({"product_id": str(product_id), **payload.model_dump(mode="json")})
    action_type = f"ai_usage.sync:{product_id}"
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type=action_type, request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        product = db.get(ProductDeployment, product_id)
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product deployment not found")
        state = db.get(AIUsageSyncState, product_id)
        if state is None:
            state = AIUsageSyncState(product_deployment_id=product_id)
            db.add(state)
            db.flush()
        run = AIUsageSyncRun(product_deployment_id=product_id, started_at=_now(), starting_cursor=state.last_committed_cursor, status=AiUsageSyncRunStatus.failed, requested_by_admin_id=admin.id, reason=payload.reason)
        db.add(run)
        product.last_usage_sync_attempt_at = run.started_at
        state.last_attempt_at = run.started_at
        _audit(db, admin=admin, product_id=product_id, action="ai_usage.sync.started", new_value={"starting_cursor": state.last_committed_cursor}, idempotency_key=idempotency_key)
        if not product.token_usage_list_path:
            safe_error = "Token usage synchronization is not configured for this product."
            run.safe_error = safe_error
            run.status = AiUsageSyncRunStatus.failed
            run.completed_at = _now()
            product.last_failed_sync_at = run.completed_at
            product.last_usage_sync_error = safe_error
            state.safe_last_error = safe_error
            _failure(db, admin=admin, product=product, action="ai_usage.sync", code="token_usage_not_configured", message=safe_error)
            db.flush()
            response = AIUsageSyncRunRead.model_validate(run).model_dump(mode="json")
            record.status = IdempotencyRecordStatus.completed
            record.response_json = response
            _audit(
                db,
                admin=admin,
                product_id=product_id,
                action="ai_usage.sync.completed",
                new_value=response,
                idempotency_key=idempotency_key,
                result_status=AuditResultStatus.failure,
                failure_message=safe_error,
            )
            db.commit()
            return response
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    client = build_product_client(product, api_secret=decrypt_product_secret(product.admin_api_secret_encrypted))
    cursor = run.starting_cursor
    pages: list[tuple[list[ProductTokenUsageItem], str | None, bool]] = []
    safe_error: str | None = None
    for _ in range(payload.max_pages):
        result = await client.list_token_usage(cursor=cursor, limit=payload.limit)
        if not result.is_success:
            safe_error = result.error_message or "Product token usage sync failed"
            break
        pages.append((result.usage, result.next_cursor, result.has_more))
        cursor = result.next_cursor
        if not result.has_more:
            break

    try:
        product = db.get(ProductDeployment, product_id)
        state = db.get(AIUsageSyncState, product_id)
        run = db.get(AIUsageSyncRun, run.id)
        if safe_error:
            run.safe_error = _safe_error(safe_error)
            run.status = AiUsageSyncRunStatus.failed
            run.completed_at = _now()
            product.last_failed_sync_at = run.completed_at
            product.last_usage_sync_error = run.safe_error
            state.safe_last_error = run.safe_error
            _failure(db, admin=admin, product=product, action="ai_usage.sync", code="product_usage_sync_failed", message=safe_error)
        else:
            for page_index, (items, next_cursor, _has_more) in enumerate(pages):
                run.pages_fetched += 1
                run.records_received += len(items)
                for item_index, item in enumerate(items):
                    try:
                        with db.begin_nested():
                            outcome, row = _process_item(db, product=product, item=item, index=(page_index * payload.limit) + item_index, admin=admin)
                            db.flush()
                    except IntegrityError:
                        usage_id = item.product_usage_id.strip() or _invalid_usage_id(item, (page_index * payload.limit) + item_index)
                        row = db.scalar(
                            select(AiUsageRecord).where(
                                AiUsageRecord.product_deployment_id == product.id,
                                AiUsageRecord.product_usage_id == usage_id,
                            )
                        )
                        if row is None:
                            raise
                        outcome = "unchanged"
                    _apply_sync_outcome(run, outcome, row)
                state.last_committed_cursor = next_cursor
                run.ending_cursor = next_cursor
            run.safe_failure_count = run.invalid_count + run.conflict_count + run.unresolved_pricing_count
            run.status = AiUsageSyncRunStatus.success if run.safe_failure_count == 0 and run.unresolved_mapping_count == 0 else AiUsageSyncRunStatus.partial_success
            run.completed_at = _now()
            state.last_success_at = run.completed_at
            state.safe_last_error = None if run.status == AiUsageSyncRunStatus.success else "AI usage sync completed with unresolved or invalid records"
            product.last_successful_usage_sync_at = run.completed_at
            product.last_usage_sync_error = state.safe_last_error
        response = AIUsageSyncRunRead.model_validate(run).model_dump(mode="json")
        record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == idempotency_key))
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        _audit(db, admin=admin, product_id=product_id, action="ai_usage.sync.completed", new_value=response, idempotency_key=idempotency_key, result_status=AuditResultStatus.success if run.status != AiUsageSyncRunStatus.failed else AuditResultStatus.failure, failure_message=run.safe_error)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def resolve_usage_pricing(db: Session, usage_id: UUID, payload: AIUsageResolvePricingRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash({"usage_id": str(usage_id), **payload.model_dump(mode="json")})
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type=f"ai_usage.resolve_pricing:{usage_id}", request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        row = _lock_usage(db, usage_id)
        outcome, version, mapping, message = _pricing_resolution_outcome(db, row, payload.pricing_version_id)
        if outcome == "resolved" and version and mapping:
            _finalize_pricing(row, version, mapping)
            db.flush()
        result = AIUsageResolutionItemResult(usage_id=row.id, product_usage_id=row.product_usage_id, outcome=outcome, message=message, usage=_read_usage(row)).model_dump(mode="json")
        if outcome != "resolved":
            _failure(db, admin=admin, product=db.get(ProductDeployment, row.product_deployment_id), action="ai_usage.resolve_pricing", code=outcome, message=message or outcome, product_usage_id=row.product_usage_id)
        _audit(db, admin=admin, product_id=row.product_deployment_id, action="ai_usage.pricing_resolved" if outcome == "resolved" else "ai_usage.pricing_resolution_skipped", new_value=result, idempotency_key=idempotency_key, result_status=AuditResultStatus.success if outcome in {"resolved", "already_resolved"} else AuditResultStatus.failure, failure_message=message)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = result
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def resolve_missing_pricing(db: Session, payload: AIUsageBatchResolvePricingRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash(payload.model_dump(mode="json"))
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type="ai_usage.resolve_missing_pricing", request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        stmt = (
            select(AiUsageRecord)
            .where(AiUsageRecord.pricing_resolution_status != AiUsagePricingResolutionStatus.resolved)
            .order_by(AiUsageRecord.usage_at.asc().nullslast(), AiUsageRecord.id.asc())
            .limit(payload.limit)
            .with_for_update(of=AiUsageRecord)
        )
        if payload.product_deployment_id:
            stmt = stmt.where(AiUsageRecord.product_deployment_id == payload.product_deployment_id)
        rows = list(db.scalars(stmt))
        items: list[AIUsageResolutionItemResult] = []
        resolved = 0
        for row in rows:
            outcome, version, mapping, message = _pricing_resolution_outcome(db, row)
            if outcome == "resolved" and version and mapping:
                _finalize_pricing(row, version, mapping)
                resolved += 1
                db.flush()
            elif outcome not in {"already_resolved"}:
                product = db.get(ProductDeployment, row.product_deployment_id)
                if product is not None:
                    _failure(db, admin=admin, product=product, action="ai_usage.resolve_missing_pricing", code=outcome, message=message or outcome, product_usage_id=row.product_usage_id)
            items.append(AIUsageResolutionItemResult(usage_id=row.id, product_usage_id=row.product_usage_id, outcome=outcome, message=message, usage=_read_usage(row)))
        response = AIUsageBatchResolutionResponse(items=items, processed=len(items), resolved=resolved).model_dump(mode="json")
        _audit(db, admin=admin, product_id=payload.product_deployment_id, action="ai_usage.resolve_missing_pricing", new_value={"processed": len(items), "resolved": resolved}, idempotency_key=idempotency_key)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def resolve_missing_mappings(db: Session, payload: AIUsageBatchResolveMappingsRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash(payload.model_dump(mode="json"))
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type="ai_usage.resolve_mappings", request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        stmt = (
            select(AiUsageRecord)
            .where(AiUsageRecord.mapping_resolution_status != AiUsageMappingResolutionStatus.resolved)
            .order_by(AiUsageRecord.usage_at.asc().nullslast(), AiUsageRecord.id.asc())
            .limit(payload.limit)
            .with_for_update(of=AiUsageRecord)
        )
        if payload.product_deployment_id:
            stmt = stmt.where(AiUsageRecord.product_deployment_id == payload.product_deployment_id)
        rows = list(db.scalars(stmt))
        items: list[AIUsageResolutionItemResult] = []
        resolved = 0
        for row in rows:
            outcome = "failed"
            message: str | None = None
            if row.organization_id is not None and row.mapping_resolution_status == AiUsageMappingResolutionStatus.resolved:
                outcome = "already_resolved"
            elif not row.product_organization_id:
                outcome = "missing_mapping"
                message = "Product organization ID snapshot is missing"
            elif row.conflict_status == AiUsageConflictStatus.conflict:
                outcome = "conflict"
                message = "Conflicting usage must be reviewed before organization resolution"
            elif row.finalization_status == AiUsageFinalizationStatus.invalid:
                outcome = "invalid"
                message = "Invalid usage cannot be mapped"
            else:
                mapping = db.scalar(
                    select(OrganizationMapping).where(
                        OrganizationMapping.product_deployment_id == row.product_deployment_id,
                        OrganizationMapping.product_organization_id == row.product_organization_id,
                        OrganizationMapping.mapping_status == MappingStatus.active,
                    )
                )
                if mapping is None:
                    outcome = "mapping_missing"
                    message = "Verified organization mapping is missing"
                else:
                    row.organization_id = mapping.organization_id
                    row.mapping_resolution_status = AiUsageMappingResolutionStatus.resolved
                    outcome = "resolved"
                    resolved += 1
                    db.flush()
            if outcome not in {"resolved", "already_resolved"}:
                product = db.get(ProductDeployment, row.product_deployment_id)
                if product is not None:
                    _failure(db, admin=admin, product=product, action="ai_usage.resolve_mappings", code=outcome, message=message or outcome, product_usage_id=row.product_usage_id)
            items.append(AIUsageResolutionItemResult(usage_id=row.id, product_usage_id=row.product_usage_id, outcome=outcome, message=message, usage=_read_usage(row)))
        response = AIUsageBatchResolutionResponse(items=items, processed=len(items), resolved=resolved).model_dump(mode="json")
        _audit(db, admin=admin, product_id=payload.product_deployment_id, action="ai_usage.resolve_mappings", new_value={"processed": len(items), "resolved": resolved}, idempotency_key=idempotency_key)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def get_conflict_detail(db: Session, usage_id: UUID) -> AIUsageConflictDetail:
    row = db.get(AiUsageRecord, usage_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI usage record not found")
    if row.conflict_status != AiUsageConflictStatus.conflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI usage record is not in conflict")
    snapshot = row.conflict_snapshot or {}
    candidate = snapshot.get("candidate") if isinstance(snapshot, dict) else None
    original = _safe_original_snapshot(row)
    detected = sorted([key for key, value in (candidate or {}).items() if str(original.get(key)) != str(value)])
    return AIUsageConflictDetail(
        usage=_read_usage(row),
        original=original,
        candidate=candidate,
        candidate_fingerprint=snapshot.get("candidate_fingerprint") if isinstance(snapshot, dict) else None,
        detected_fields=detected,
        reviewed=row.conflict_reviewed_at is not None,
    )


def mark_conflict_reviewed(db: Session, usage_id: UUID, payload: AIUsageConflictReviewRequest, idempotency_key: str, admin: Admin) -> dict:
    request_hash = _request_hash({"usage_id": str(usage_id), **payload.model_dump(mode="json")})
    try:
        record = _start_idempotency(db, key=idempotency_key, action_type=f"ai_usage.conflict.review:{usage_id}", request_hash=request_hash, admin=admin)
        if isinstance(record, dict):
            return record
        row = _lock_usage(db, usage_id)
        if row.conflict_status != AiUsageConflictStatus.conflict:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI usage record is not in conflict")
        if row.conflict_reviewed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict has already been reviewed")
        row.conflict_reviewed_by_admin_id = admin.id
        row.conflict_reviewed_at = _now()
        row.conflict_review_note = payload.reason
        response = get_conflict_detail(db, usage_id).model_dump(mode="json")
        _audit(db, admin=admin, product_id=row.product_deployment_id, action="ai_usage.conflict.reviewed", new_value={"usage_id": str(row.id), "reviewed_at": row.conflict_reviewed_at.isoformat()}, idempotency_key=idempotency_key)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def summarize_usage(db: Session, filters: UsageFilters) -> AIUsageSummary:
    stmt: Select = select(AiUsageRecord)
    if filters.product_deployment_id:
        stmt = stmt.where(AiUsageRecord.product_deployment_id == filters.product_deployment_id)
    if filters.organization_id:
        stmt = stmt.where(AiUsageRecord.organization_id == filters.organization_id)
    if filters.product_organization_id:
        stmt = stmt.where(AiUsageRecord.product_organization_id == filters.product_organization_id)
    if filters.provider:
        stmt = stmt.where(AiUsageRecord.provider == filters.provider.lower())
    if filters.product_model_id:
        stmt = stmt.where(AiUsageRecord.product_model_id == filters.product_model_id)
    if filters.usage_from:
        stmt = stmt.where(AiUsageRecord.usage_at >= filters.usage_from)
    if filters.usage_to:
        stmt = stmt.where(AiUsageRecord.usage_at <= filters.usage_to)
    base = stmt.subquery()
    record_count = db.scalar(select(func.count()).select_from(base)) or 0
    tokens = db.execute(select(func.coalesce(func.sum(base.c.input_tokens), 0), func.coalesce(func.sum(base.c.output_tokens), 0), func.coalesce(func.sum(base.c.total_tokens), 0))).one()
    finalized = stmt.where(AiUsageRecord.pricing_resolution_status == AiUsagePricingResolutionStatus.resolved, AiUsageRecord.total_cost.is_not(None), AiUsageRecord.cost_currency.is_not(None)).subquery()
    currency_rows = db.execute(select(finalized.c.cost_currency, func.sum(finalized.c.total_cost)).select_from(finalized).group_by(finalized.c.cost_currency)).all()
    provider_rows = db.execute(
        select(base.c.provider, base.c.product_model_id, func.coalesce(func.sum(base.c.input_tokens), 0), func.coalesce(func.sum(base.c.output_tokens), 0), func.coalesce(func.sum(base.c.total_tokens), 0), func.count())
        .select_from(base)
        .group_by(base.c.provider, base.c.product_model_id)
    ).all()
    org_rows = db.execute(
        select(base.c.organization_id, Organization.name, base.c.cost_currency, func.sum(base.c.total_cost))
        .select_from(base)
        .join(Organization, Organization.id == base.c.organization_id, isouter=True)
        .where(base.c.total_cost.is_not(None), base.c.cost_currency.is_not(None), base.c.pricing_resolution_status == AiUsagePricingResolutionStatus.resolved)
        .group_by(base.c.organization_id, Organization.name, base.c.cost_currency)
        .order_by(base.c.cost_currency.asc(), func.sum(base.c.total_cost).desc())
        .limit(20)
    ).all()
    product_rows = db.execute(
        select(base.c.product_deployment_id, ProductDeployment.product_name, base.c.cost_currency, func.sum(base.c.total_cost))
        .select_from(base)
        .join(ProductDeployment, ProductDeployment.id == base.c.product_deployment_id)
        .where(base.c.total_cost.is_not(None), base.c.cost_currency.is_not(None), base.c.pricing_resolution_status == AiUsagePricingResolutionStatus.resolved)
        .group_by(base.c.product_deployment_id, ProductDeployment.product_name, base.c.cost_currency)
        .order_by(base.c.cost_currency.asc(), func.sum(base.c.total_cost).desc())
        .limit(20)
    ).all()
    free_rows = db.execute(
        select(base.c.cost_currency, func.sum(base.c.total_cost))
        .select_from(base)
        .join(Organization, Organization.id == base.c.organization_id)
        .where(Organization.billing_mode == "free_internal_testing", base.c.total_cost.is_not(None), base.c.cost_currency.is_not(None), base.c.pricing_resolution_status == AiUsagePricingResolutionStatus.resolved)
        .group_by(base.c.cost_currency)
    ).all()
    return AIUsageSummary(
        input_tokens=int(tokens[0] or 0),
        output_tokens=int(tokens[1] or 0),
        total_tokens=int(tokens[2] or 0),
        usage_record_count=record_count,
        finalized_costs_by_currency=[CurrencyCostSummary(currency=row[0], total_cost=row[1]) for row in currency_rows],
        unpriced_usage_count=db.scalar(select(func.count()).select_from(base).where(base.c.pricing_resolution_status != AiUsagePricingResolutionStatus.resolved)) or 0,
        unmapped_usage_count=db.scalar(select(func.count()).select_from(base).where(base.c.mapping_resolution_status != AiUsageMappingResolutionStatus.resolved)) or 0,
        non_final_usage_count=db.scalar(select(func.count()).select_from(base).where(base.c.finalization_status == AiUsageFinalizationStatus.non_final)) or 0,
        invalid_usage_count=db.scalar(select(func.count()).select_from(base).where(base.c.finalization_status == AiUsageFinalizationStatus.invalid)) or 0,
        conflict_count=db.scalar(select(func.count()).select_from(base).where(base.c.conflict_status == AiUsageConflictStatus.conflict)) or 0,
        reviewed_conflict_count=db.scalar(select(func.count()).select_from(base).where(base.c.conflict_reviewed_at.is_not(None))) or 0,
        unreviewed_conflict_count=db.scalar(select(func.count()).select_from(base).where(base.c.conflict_status == AiUsageConflictStatus.conflict, base.c.conflict_reviewed_at.is_(None))) or 0,
        highest_cost_organizations=[RankedCostSummary(id=row[0], label=row[1] or "Unmapped organization", currency=row[2], total_cost=row[3]) for row in org_rows],
        highest_cost_products=[RankedCostSummary(id=row[0], label=row[1], currency=row[2], total_cost=row[3]) for row in product_rows],
        provider_model_breakdown=[ProviderModelUsageSummary(provider=row[0], product_model_id=row[1], input_tokens=int(row[2] or 0), output_tokens=int(row[3] or 0), total_tokens=int(row[4] or 0), record_count=row[5]) for row in provider_rows],
        free_internal_testing_costs_by_currency=[CurrencyCostSummary(currency=row[0], total_cost=row[1]) for row in free_rows],
    )


def list_usage(db: Session, filters: UsageFilters, *, limit: int, offset: int) -> AIUsageListResponse:
    stmt: Select = select(AiUsageRecord)
    if filters.product_deployment_id:
        stmt = stmt.where(AiUsageRecord.product_deployment_id == filters.product_deployment_id)
    if filters.organization_id:
        stmt = stmt.where(AiUsageRecord.organization_id == filters.organization_id)
    if filters.product_organization_id:
        stmt = stmt.where(AiUsageRecord.product_organization_id == filters.product_organization_id)
    if filters.provider:
        stmt = stmt.where(AiUsageRecord.provider == filters.provider.lower())
    if filters.product_model_id:
        stmt = stmt.where(AiUsageRecord.product_model_id == filters.product_model_id)
    if filters.usage_from:
        stmt = stmt.where(AiUsageRecord.usage_at >= filters.usage_from)
    if filters.usage_to:
        stmt = stmt.where(AiUsageRecord.usage_at <= filters.usage_to)
    if filters.pricing_catalog_id:
        stmt = stmt.where(AiUsageRecord.pricing_catalog_id == filters.pricing_catalog_id)
    if filters.pricing_version_id:
        stmt = stmt.where(AiUsageRecord.pricing_version_id == filters.pricing_version_id)
    if filters.cost_currency:
        stmt = stmt.where(AiUsageRecord.cost_currency == filters.cost_currency.upper())
    if filters.pricing_resolution_status:
        stmt = stmt.where(AiUsageRecord.pricing_resolution_status == filters.pricing_resolution_status)
    if filters.mapping_resolution_status:
        stmt = stmt.where(AiUsageRecord.mapping_resolution_status == filters.mapping_resolution_status)
    if filters.conflict_status:
        stmt = stmt.where(AiUsageRecord.conflict_status == filters.conflict_status)
    if filters.finalization_status:
        stmt = stmt.where(AiUsageRecord.finalization_status == filters.finalization_status)
    if filters.product_usage_id:
        stmt = stmt.where(AiUsageRecord.product_usage_id == filters.product_usage_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AiUsageRecord.usage_at.desc().nullslast(), AiUsageRecord.id.desc()).limit(limit).offset(offset)))
    return AIUsageListResponse(items=[_read_usage(row) for row in rows], total=total, limit=limit, offset=offset)


def get_usage(db: Session, usage_id: UUID) -> AIUsageRead:
    row = db.get(AiUsageRecord, usage_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI usage record not found")
    return _read_usage(row)
