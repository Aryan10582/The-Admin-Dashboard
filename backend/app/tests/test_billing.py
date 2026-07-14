from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import BillingMode, BillingTransactionType, MappingStatus, PendingChangeStatus
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingLedgerEntry, ManualPayment
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization, OrganizationMapping
from app.models.pending_change import PendingProductChange
from app.schemas.billing import AddCreditsRequest
from app.services.billing_service import add_credits
from app.tests.test_organizations import create_deployment, create_org, login


def idempotency_headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


def create_verified_mapping(
    db_session: Session,
    org_id: str,
    deployment_id: UUID,
    *,
    product_organization_id: str | None = None,
    status: MappingStatus = MappingStatus.active,
) -> OrganizationMapping:
    mapping = OrganizationMapping(
        organization_id=UUID(org_id),
        product_deployment_id=deployment_id,
        product_organization_id=product_organization_id or f"prod-{org_id}",
        product_api_version="v1",
        mapping_status=status,
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


def financial_payload(amount: str, reason: str = "Financial safety test", currency: str = "USD") -> dict[str, str]:
    return {"amount": amount, "currency": currency, "reason": reason}


def ledger_count(db_session: Session, org_id: str) -> int:
    return (
        db_session.scalar(
            select(func.count()).select_from(BillingLedgerEntry).where(BillingLedgerEntry.organization_id == UUID(org_id))
        )
        or 0
    )


def test_financial_write_endpoints_reject_unauthenticated(client: TestClient) -> None:
    org_id = UUID(int=0)
    assert client.post(f"/api/v1/organizations/{org_id}/credits/add", json={}, headers=idempotency_headers("k1")).status_code == 401
    assert client.post(f"/api/v1/organizations/{org_id}/credits/deduct", json={}, headers=idempotency_headers("k2")).status_code == 401
    assert client.post(f"/api/v1/organizations/{org_id}/manual-payment", json={}, headers=idempotency_headers("k3")).status_code == 401


def test_reason_required_for_financial_actions(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json={"amount": "10.00", "currency": "USD"},
        headers=idempotency_headers("missing-reason"),
    )

    assert response.status_code == 422


def test_add_credits_duplicate_idempotency_replays_original_without_duplicates(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("25.50", "Initial credit grant"),
        headers=idempotency_headers("add-credit-key"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["organization"]["credit_balance"] == "25.50"
    ledger_id = data["ledger_entry"]["id"]

    duplicate = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("99.00", "Should replay original"),
        headers=idempotency_headers("add-credit-key"),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"] == data

    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.credit_balance == Decimal("25.50")
    assert db_session.scalar(select(BillingLedgerEntry).where(BillingLedgerEntry.idempotency_key == "add-credit-key")).id == UUID(ledger_id)
    assert ledger_count(db_session, org["id"]) == 1


def test_idempotency_key_does_not_cross_organization_or_action_scope(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org_a = create_org(client, deployment)
    org_b = create_org(client, deployment)
    create_verified_mapping(db_session, org_a["id"], deployment.id, product_organization_id="prod-a")
    create_verified_mapping(db_session, org_b["id"], deployment.id, product_organization_id="prod-b")

    response = client.post(
        f"/api/v1/organizations/{org_a['id']}/credits/add",
        json=financial_payload("10.00"),
        headers=idempotency_headers("scoped-key"),
    )
    assert response.status_code == 200

    other_org = client.post(
        f"/api/v1/organizations/{org_b['id']}/credits/add",
        json=financial_payload("10.00"),
        headers=idempotency_headers("scoped-key"),
    )
    other_action = client.post(
        f"/api/v1/organizations/{org_a['id']}/credits/deduct",
        json=financial_payload("1.00"),
        headers=idempotency_headers("scoped-key"),
    )

    assert other_org.status_code == 409
    assert other_action.status_code == 409
    assert ledger_count(db_session, org_a["id"]) == 1
    assert ledger_count(db_session, org_b["id"]) == 0


def test_complete_rollback_when_later_write_fails(db_session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)
    admin = db_session.scalar(select(Admin).where(Admin.email == "admin@example.com"))
    assert admin is not None

    def fail_audit(*args, **kwargs) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr("app.services.billing_service._add_audit", fail_audit)

    with pytest.raises(RuntimeError):
        add_credits(
            db_session,
            UUID(org["id"]),
            AddCreditsRequest(amount=Decimal("12.00"), currency="USD", reason="Rollback test"),
            "rollback-key",
            admin,
        )

    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.credit_balance == Decimal("0.00")
    assert ledger_count(db_session, org["id"]) == 0
    assert db_session.scalar(select(func.count()).select_from(PendingProductChange)) == 0
    assert db_session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0


def test_deduct_credits_once_creates_ledger_audit_and_pending_change(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)
    client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("40.00", "Fund account"),
        headers=idempotency_headers("fund-before-deduct"),
    )

    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/deduct",
        json=financial_payload("15.00", "Usage adjustment"),
        headers=idempotency_headers("deduct-key"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["organization"]["credit_balance"] == "25.00"
    assert data["ledger_entry"]["transaction_type"] == BillingTransactionType.credit_deduction.value

    organization_id = UUID(org["id"])
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "billing.credits.deduct", AuditLog.organization_id == organization_id)) is not None
    pending = db_session.scalar(
        select(PendingProductChange).where(
            PendingProductChange.organization_id == organization_id,
            PendingProductChange.idempotency_key == "deduct-key",
        )
    )
    assert pending is not None
    assert pending.status == PendingChangeStatus.saved


def test_two_deductions_cannot_overspend_same_balance(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)
    client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("10.00", "Fund account"),
        headers=idempotency_headers("overspend-fund"),
    )

    first = client.post(
        f"/api/v1/organizations/{org['id']}/credits/deduct",
        json=financial_payload("7.00", "First spend"),
        headers=idempotency_headers("overspend-1"),
    )
    second = client.post(
        f"/api/v1/organizations/{org['id']}/credits/deduct",
        json=financial_payload("7.00", "Second spend"),
        headers=idempotency_headers("overspend-2"),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.credit_balance == Decimal("3.00")
    assert ledger_count(db_session, org["id"]) == 2


def test_manual_payment_reduces_dues_without_altering_credit_balance(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment, billing_mode=BillingMode.postpaid_manual_settlement.value)
    create_verified_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("8.00")
    organization.outstanding_dues = Decimal("100.00")
    db_session.commit()

    response = client.post(
        f"/api/v1/organizations/{org['id']}/manual-payment",
        json={
            **financial_payload("30.00", "Wire received"),
            "payment_method": "wire",
            "payment_reference": "WIRE-001",
        },
        headers=idempotency_headers("manual-payment-key"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["organization"]["credit_balance"] == "8.00"
    assert data["organization"]["outstanding_dues"] == "70.00"
    assert data["manual_payment"]["payment_reference"] == "WIRE-001"
    assert data["ledger_entry"]["transaction_type"] == BillingTransactionType.manual_payment.value

    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.credit_balance == Decimal("8.00")
    assert organization.outstanding_dues == Decimal("70.00")
    assert db_session.scalar(select(ManualPayment).where(ManualPayment.idempotency_key == "manual-payment-key")) is not None
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "billing.manual_payment", AuditLog.organization_id == organization.id)) is not None
    assert db_session.scalar(select(PendingProductChange).where(PendingProductChange.idempotency_key == "manual-payment-key")) is not None


def test_manual_payment_overpayment_is_rejected(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment, billing_mode=BillingMode.postpaid_manual_settlement.value)
    create_verified_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.outstanding_dues = Decimal("20.00")
    db_session.commit()

    response = client.post(
        f"/api/v1/organizations/{org['id']}/manual-payment",
        json=financial_payload("20.01", "Overpayment"),
        headers=idempotency_headers("overpayment-key"),
    )

    assert response.status_code == 409
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.outstanding_dues == Decimal("20.00")
    assert ledger_count(db_session, org["id"]) == 0


def test_billing_mode_currency_and_amount_validation(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment, billing_mode=BillingMode.free_internal_testing.value)
    create_verified_mapping(db_session, org["id"], deployment.id)

    wrong_mode = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("10.00"),
        headers=idempotency_headers("wrong-mode"),
    )
    currency_mismatch = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("10.00", currency="EUR"),
        headers=idempotency_headers("currency-mismatch"),
    )
    zero_amount = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("0.00"),
        headers=idempotency_headers("zero-amount"),
    )
    negative_amount = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("-1.00"),
        headers=idempotency_headers("negative-amount"),
    )

    assert wrong_mode.status_code == 409
    assert currency_mismatch.status_code == 409
    assert zero_amount.status_code == 422
    assert negative_amount.status_code == 422
    assert ledger_count(db_session, org["id"]) == 0


def test_decimal_precision_is_preserved(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("10.25", "Decimal precision"),
        headers=idempotency_headers("decimal-key"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ledger_entry"]["amount"] == "10.25"
    assert data["organization"]["credit_balance"] == "10.25"
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.credit_balance == Decimal("10.25")


def test_missing_unverified_and_mismatched_mapping_block_before_financial_change(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    other_deployment = create_deployment(db_session, product_name="Other")
    missing = create_org(client, deployment)
    unverified = create_org(client, deployment)
    mismatched = create_org(client, deployment)
    create_verified_mapping(db_session, unverified["id"], deployment.id, status=MappingStatus.requires_manual_review)
    create_verified_mapping(db_session, mismatched["id"], other_deployment.id)

    for key, org in (("missing-map", missing), ("unverified-map", unverified), ("mismatch-map", mismatched)):
        response = client.post(
            f"/api/v1/organizations/{org['id']}/credits/add",
            json=financial_payload("10.00"),
            headers=idempotency_headers(key),
        )
        assert response.status_code == 409
        organization = db_session.get(Organization, UUID(org["id"]))
        assert organization is not None
        assert organization.credit_balance == Decimal("0.00")
        assert ledger_count(db_session, org["id"]) == 0


def test_ledger_entries_remain_unchanged_after_idempotent_replay(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)
    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("10.00", "Original note"),
        headers=idempotency_headers("append-only-key"),
    )
    assert response.status_code == 200
    ledger_id = UUID(response.json()["data"]["ledger_entry"]["id"])
    original = db_session.get(BillingLedgerEntry, ledger_id)
    assert original is not None
    original_created_at = original.created_at

    duplicate = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("12.00", "Replacement note"),
        headers=idempotency_headers("append-only-key"),
    )
    assert duplicate.status_code == 200

    current = db_session.get(BillingLedgerEntry, ledger_id)
    assert current is not None
    assert current.amount == Decimal("10.00")
    assert current.note == "Original note"
    assert current.created_at == original_created_at
    assert ledger_count(db_session, org["id"]) == 1


def test_product_secret_absent_from_financial_metadata(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("5.00", "Safe metadata"),
        headers=idempotency_headers("secret-metadata-key"),
    )

    assert response.status_code == 200
    audit = db_session.scalar(select(AuditLog).where(AuditLog.idempotency_key == "secret-metadata-key"))
    idempotency = db_session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "secret-metadata-key"))
    pending = db_session.scalar(select(PendingProductChange).where(PendingProductChange.idempotency_key == "secret-metadata-key"))
    assert audit is not None
    assert idempotency is not None
    assert pending is not None

    metadata_text = f"{audit.old_value} {audit.new_value} {audit.failure_message} {idempotency.response_json} {pending.payload}"
    assert "product-secret" not in metadata_text


def test_organization_and_global_ledger_endpoints(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_verified_mapping(db_session, org["id"], deployment.id)
    client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("10.00", "Ledger visibility"),
        headers=idempotency_headers("ledger-key"),
    )

    org_ledger = client.get(f"/api/v1/organizations/{org['id']}/ledger")
    assert org_ledger.status_code == 200
    assert org_ledger.json()["data"]["total"] == 1

    global_ledger = client.get(
        "/api/v1/billing/ledger",
        params={
            "organization_id": org["id"],
            "product_name": deployment.product_name,
            "region": deployment.region,
            "environment": deployment.environment.value,
            "currency": "USD",
            "transaction_type": "credit_grant",
        },
    )
    assert global_ledger.status_code == 200
    assert global_ledger.json()["data"]["total"] == 1
    assert global_ledger.json()["data"]["items"][0]["note"] == "Ledger visibility"
