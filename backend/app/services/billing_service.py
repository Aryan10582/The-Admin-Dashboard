from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.enums import AuditResultStatus, BillingMode, BillingTransactionType, IdempotencyRecordStatus, PendingChangeStatus, SyncStatus
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingLedgerEntry, ManualPayment
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.schemas.billing import (
    AddCreditsRequest,
    BillingLedgerEntryRead,
    BillingSummaryRead,
    DeductCreditsRequest,
    FinancialActionResult,
    ManualPaymentRead,
    ManualPaymentRequest,
)
from app.services.organization_service import require_verified_mapping
from app.services.service_enforcement import maybe_auto_pause_for_zero_balance


@dataclass(frozen=True)
class LedgerFilters:
    organization_id: UUID | None = None
    product_deployment_id: UUID | None = None
    product_name: str | None = None
    region: str | None = None
    environment: object | None = None
    currency: str | None = None
    transaction_type: object | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _summary(organization: Organization) -> BillingSummaryRead:
    return BillingSummaryRead(
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        currency=organization.currency,
        billing_mode=organization.billing_mode,
        credit_status=organization.credit_status,
        credit_balance=organization.credit_balance,
        outstanding_dues=organization.outstanding_dues,
    )


def _result_payload(
    organization: Organization,
    ledger_entry: BillingLedgerEntry,
    idempotency_key: str,
    pending_change: PendingProductChange | None,
    manual_payment: ManualPayment | None = None,
) -> dict:
    result = FinancialActionResult(
        organization=_summary(organization),
        ledger_entry=BillingLedgerEntryRead.model_validate(ledger_entry),
        pending_product_change_id=pending_change.id if pending_change else None,
        manual_payment=ManualPaymentRead.model_validate(manual_payment) if manual_payment else None,
        idempotency_key=idempotency_key,
    )
    return result.model_dump(mode="json")


def _safe_audit_payload(
    organization: Organization,
    ledger_entry: BillingLedgerEntry | None = None,
    pending_change: PendingProductChange | None = None,
) -> dict:
    payload = {
        "organization_id": str(organization.id),
        "product_deployment_id": str(organization.product_deployment_id),
        "credit_balance": str(organization.credit_balance),
        "outstanding_dues": str(organization.outstanding_dues),
    }
    if ledger_entry is not None:
        payload.update(
            {
                "ledger_entry_id": str(ledger_entry.id),
                "transaction_type": ledger_entry.transaction_type.value,
                "amount": str(ledger_entry.amount),
                "sync_status": ledger_entry.product_sync_status.value,
            }
        )
    if pending_change is not None:
        payload["pending_product_change_id"] = str(pending_change.id)
    return payload


def _add_audit(db: Session, *, admin: Admin, action: str, organization: Organization, ledger_entry: BillingLedgerEntry, pending_change: PendingProductChange | None) -> None:
    db.add(
        AuditLog(
            admin_id=admin.id,
            action=action,
            organization_id=organization.id,
            product_deployment_id=organization.product_deployment_id,
            new_value=_safe_audit_payload(organization, ledger_entry, pending_change),
            result_status=AuditResultStatus.success,
            sync_status=ledger_entry.product_sync_status,
            idempotency_key=ledger_entry.idempotency_key,
            created_at=_now(),
        )
    )


def get_organization_for_billing(db: Session, organization_id: UUID, *, lock: bool = False) -> Organization:
    stmt = select(Organization).where(Organization.id == organization_id)
    if lock:
        stmt = stmt.with_for_update(of=Organization)
    else:
        stmt = stmt.options(joinedload(Organization.product_deployment))
    organization = db.scalar(stmt)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


def get_billing_summary(db: Session, organization_id: UUID) -> dict:
    return _summary(get_organization_for_billing(db, organization_id)).model_dump(mode="json")


def _get_completed_idempotency(db: Session, key: str, action_type: str, organization_id: UUID) -> dict | None:
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
        replay = _get_completed_idempotency(db, key, action_type, organization.id)
        if replay is not None:
            return replay
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already in progress") from exc
    return record


def _validate_currency(organization: Organization, currency: str) -> None:
    if currency.upper() != organization.currency:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Currency does not match organization currency")


def _require_billing_mode(organization: Organization, allowed_modes: set[BillingMode]) -> None:
    if organization.billing_mode not in allowed_modes:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Financial action is not allowed for this billing mode")


def _prepare_financial_action(
    db: Session,
    *,
    organization_id: UUID,
    idempotency_key: str,
    action_type: str,
    admin: Admin,
    currency: str,
    allowed_modes: set[BillingMode],
) -> tuple[Organization | None, IdempotencyRecord | None, dict | None]:
    replay = _get_completed_idempotency(db, idempotency_key, action_type, organization_id)
    if replay is not None:
        return None, None, replay

    organization_for_record = get_organization_for_billing(db, organization_id)
    record = _start_idempotency(db, idempotency_key, action_type, admin, organization_for_record)
    if isinstance(record, dict):
        return None, None, record
    organization = get_organization_for_billing(db, organization_id, lock=True)
    _validate_currency(organization, currency)
    _require_billing_mode(organization, allowed_modes)
    require_verified_mapping(db, organization.id, organization.product_deployment_id)
    return organization, record, None


def _pending_change(db: Session, *, organization: Organization, action: str, reason: str, admin: Admin, idempotency_key: str, ledger_entry: BillingLedgerEntry) -> PendingProductChange:
    change = PendingProductChange(
        action=action,
        payload={
            "organization_id": str(organization.id),
            "ledger_entry_id": str(ledger_entry.id),
            "transaction_type": ledger_entry.transaction_type.value,
            "amount": str(ledger_entry.amount),
            "currency": ledger_entry.currency,
        },
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        status=PendingChangeStatus.saved,
        idempotency_key=idempotency_key,
        retry_count=0,
        reason=reason,
        admin_id=admin.id,
    )
    db.add(change)
    return change


def _ledger_entry(
    db: Session,
    *,
    organization: Organization,
    transaction_type: BillingTransactionType,
    amount: Decimal,
    note: str,
    admin: Admin,
    idempotency_key: str,
    balance_before: Decimal,
    balance_after: Decimal,
    outstanding_before: Decimal,
    outstanding_after: Decimal,
) -> BillingLedgerEntry:
    entry = BillingLedgerEntry(
        organization_id=organization.id,
        product_deployment_id=organization.product_deployment_id,
        currency=organization.currency,
        amount=amount,
        transaction_type=transaction_type,
        balance_before=balance_before,
        balance_after=balance_after,
        outstanding_dues_before=outstanding_before,
        outstanding_dues_after=outstanding_after,
        note=note,
        admin_id=admin.id,
        idempotency_key=idempotency_key,
        product_sync_status=SyncStatus.pending,
        created_at=_now(),
    )
    db.add(entry)
    db.flush()
    return entry


def add_credits(db: Session, organization_id: UUID, payload: AddCreditsRequest, idempotency_key: str, admin: Admin) -> dict:
    try:
        organization, record, replay = _prepare_financial_action(
            db,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            action_type="credits.add",
            admin=admin,
            currency=payload.currency,
            allowed_modes={BillingMode.prepaid_credits},
        )
        if replay is not None:
            return replay
        assert organization is not None and record is not None
        before = organization.credit_balance
        outstanding_before = organization.outstanding_dues
        organization.credit_balance = before + payload.amount
        ledger = _ledger_entry(
            db,
            organization=organization,
            transaction_type=BillingTransactionType.credit_grant,
            amount=payload.amount,
            note=payload.reason,
            admin=admin,
            idempotency_key=idempotency_key,
            balance_before=before,
            balance_after=organization.credit_balance,
            outstanding_before=outstanding_before,
            outstanding_after=organization.outstanding_dues,
        )
        change = _pending_change(db, organization=organization, action="credits.add", reason=payload.reason, admin=admin, idempotency_key=idempotency_key, ledger_entry=ledger)
        _add_audit(db, admin=admin, action="billing.credits.add", organization=organization, ledger_entry=ledger, pending_change=change)
        db.flush()
        response = _result_payload(organization, ledger, idempotency_key, change)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def deduct_credits(db: Session, organization_id: UUID, payload: DeductCreditsRequest, idempotency_key: str, admin: Admin) -> dict:
    try:
        organization, record, replay = _prepare_financial_action(
            db,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            action_type="credits.deduct",
            admin=admin,
            currency=payload.currency,
            allowed_modes={BillingMode.prepaid_credits},
        )
        if replay is not None:
            return replay
        assert organization is not None and record is not None
        if organization.credit_balance - payload.amount < 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Credit balance cannot go below zero")
        before = organization.credit_balance
        outstanding_before = organization.outstanding_dues
        organization.credit_balance = before - payload.amount
        ledger = _ledger_entry(
            db,
            organization=organization,
            transaction_type=BillingTransactionType.credit_deduction,
            amount=payload.amount,
            note=payload.reason,
            admin=admin,
            idempotency_key=idempotency_key,
            balance_before=before,
            balance_after=organization.credit_balance,
            outstanding_before=outstanding_before,
            outstanding_after=organization.outstanding_dues,
        )
        change = _pending_change(db, organization=organization, action="credits.deduct", reason=payload.reason, admin=admin, idempotency_key=idempotency_key, ledger_entry=ledger)
        maybe_auto_pause_for_zero_balance(
            db,
            organization=organization,
            reason=payload.reason,
            admin=admin,
            idempotency_key=idempotency_key,
        )
        _add_audit(db, admin=admin, action="billing.credits.deduct", organization=organization, ledger_entry=ledger, pending_change=change)
        db.flush()
        response = _result_payload(organization, ledger, idempotency_key, change)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def record_manual_payment(db: Session, organization_id: UUID, payload: ManualPaymentRequest, idempotency_key: str, admin: Admin) -> dict:
    try:
        organization, record, replay = _prepare_financial_action(
            db,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            action_type="manual_payment",
            admin=admin,
            currency=payload.currency,
            allowed_modes={BillingMode.postpaid_manual_settlement},
        )
        if replay is not None:
            return replay
        assert organization is not None and record is not None
        before = organization.credit_balance
        outstanding_before = organization.outstanding_dues
        if payload.amount > outstanding_before:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Manual payment exceeds outstanding dues")
        organization.outstanding_dues = outstanding_before - payload.amount
        payment = ManualPayment(
            organization_id=organization.id,
            product_deployment_id=organization.product_deployment_id,
            currency=organization.currency,
            payment_amount=payload.amount,
            payment_date=payload.payment_date or date.today(),
            payment_method=payload.payment_method,
            payment_reference=payload.payment_reference,
            admin_id=admin.id,
            note=payload.reason,
            idempotency_key=idempotency_key,
            product_sync_status=SyncStatus.pending,
        )
        db.add(payment)
        ledger = _ledger_entry(
            db,
            organization=organization,
            transaction_type=BillingTransactionType.manual_payment,
            amount=payload.amount,
            note=payload.reason,
            admin=admin,
            idempotency_key=idempotency_key,
            balance_before=before,
            balance_after=organization.credit_balance,
            outstanding_before=outstanding_before,
            outstanding_after=organization.outstanding_dues,
        )
        change = _pending_change(db, organization=organization, action="manual_payment", reason=payload.reason, admin=admin, idempotency_key=idempotency_key, ledger_entry=ledger)
        _add_audit(db, admin=admin, action="billing.manual_payment", organization=organization, ledger_entry=ledger, pending_change=change)
        db.flush()
        response = _result_payload(organization, ledger, idempotency_key, change, payment)
        record.status = IdempotencyRecordStatus.completed
        record.response_json = response
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def _ledger_query(filters: LedgerFilters) -> Select:
    stmt = select(BillingLedgerEntry).join(ProductDeployment, ProductDeployment.id == BillingLedgerEntry.product_deployment_id)
    if filters.organization_id:
        stmt = stmt.where(BillingLedgerEntry.organization_id == filters.organization_id)
    if filters.product_deployment_id:
        stmt = stmt.where(BillingLedgerEntry.product_deployment_id == filters.product_deployment_id)
    if filters.product_name:
        stmt = stmt.where(ProductDeployment.product_name == filters.product_name)
    if filters.region:
        stmt = stmt.where(ProductDeployment.region == filters.region)
    if filters.environment:
        stmt = stmt.where(ProductDeployment.environment == filters.environment)
    if filters.currency:
        stmt = stmt.where(BillingLedgerEntry.currency == filters.currency.upper())
    if filters.transaction_type:
        stmt = stmt.where(BillingLedgerEntry.transaction_type == filters.transaction_type)
    if filters.date_from:
        stmt = stmt.where(BillingLedgerEntry.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(BillingLedgerEntry.created_at <= filters.date_to)
    return stmt


def list_ledger(db: Session, filters: LedgerFilters, *, limit: int, offset: int) -> tuple[list[BillingLedgerEntry], int]:
    stmt = _ledger_query(filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(db.scalars(stmt.order_by(BillingLedgerEntry.created_at.desc()).limit(limit).offset(offset)))
    return items, total
