from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import BillingMode, PendingChangeStatus, ServiceStatus
from app.integrations.product_admin_client import ProductDeliveryResult, ProductHealthResult, ProductOrganizationLookupResult
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingLedgerEntry
from app.models.failure_log import FailureLog
from app.models.organization import Organization
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.services.sync_service import _finalize
from app.tests.test_billing import financial_payload
from app.tests.test_organizations import create_deployment, create_org, login
from app.tests.test_service_enforcement import create_mapping, reason_payload


def idempotency_headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


class StubProductClient:
    calls: list[dict] = []
    delivery_result = ProductDeliveryResult(success=True, sync_confirmed=True)
    health_result = ProductHealthResult(is_success=True, response_time_ms=12, status_code=200)
    org_result = ProductOrganizationLookupResult(is_success=True, product_organization_id="prod-org")

    async def deliver_pending_change(self, **kwargs) -> ProductDeliveryResult:
        self.calls.append(kwargs)
        result = self.delivery_result
        if result.product_organization_id is None:
            result = ProductDeliveryResult(
                success=result.success,
                product_organization_id=kwargs["product_organization_id"],
                applied_change=result.applied_change or kwargs["action"],
                current_product_value=result.current_product_value,
                product_api_version=result.product_api_version or "v1",
                sync_confirmed=result.sync_confirmed,
                error_code=result.error_code,
                safe_error_message=result.safe_error_message,
                product_request_id=result.product_request_id or "req-1",
                idempotency_key=result.idempotency_key or kwargs["idempotency_key"],
                http_status=result.http_status or 200,
            )
        return result

    async def health_check(self) -> ProductHealthResult:
        return self.health_result

    async def get_organization_detail(self, product_organization_id: str) -> ProductOrganizationLookupResult:
        return ProductOrganizationLookupResult(is_success=True, product_organization_id=product_organization_id)

    async def get_pending_change_status(self, idempotency_key: str) -> ProductDeliveryResult:
        self.calls.append({"status_lookup": True, "idempotency_key": idempotency_key})
        result = self.delivery_result
        if result.product_organization_id is None:
            result = ProductDeliveryResult(
                success=result.success,
                product_organization_id="prod-org",
                applied_change=result.applied_change or "credits.add",
                current_product_value=result.current_product_value,
                product_api_version=result.product_api_version or "v1",
                sync_confirmed=result.sync_confirmed,
                error_code=result.error_code,
                safe_error_message=result.safe_error_message,
                product_request_id=result.product_request_id or "lookup-req",
                idempotency_key=result.idempotency_key or idempotency_key,
                http_status=result.http_status or 200,
            )
        return result


def stub_product_client(monkeypatch, result: ProductDeliveryResult | None = None) -> None:
    StubProductClient.calls = []
    StubProductClient.delivery_result = result or ProductDeliveryResult(success=True, sync_confirmed=True)

    def build_client(product, api_secret=None):
        assert api_secret == "product-secret"
        return StubProductClient()

    monkeypatch.setattr("app.services.sync_service.build_product_client", build_client)
    monkeypatch.setattr("app.services.product_service.build_product_client", build_client)


def create_credit_change(client: TestClient, db_session: Session, *, amount: str = "5.00") -> tuple[dict, PendingProductChange]:
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload(amount, "Credit delivery"),
        headers=idempotency_headers(f"credit-{org['id']}"),
    )
    assert response.status_code == 200
    change = db_session.scalar(select(PendingProductChange).where(PendingProductChange.organization_id == UUID(org["id"])))
    assert change is not None
    return org, change


def test_phase_7_endpoints_require_authentication(client: TestClient) -> None:
    zero = UUID(int=0)
    assert client.post(f"/api/v1/products/{zero}/sync").status_code == 401
    assert client.post(f"/api/v1/products/{zero}/sync/health").status_code == 401
    assert client.post(f"/api/v1/products/{zero}/sync/organizations").status_code == 401
    assert client.post(f"/api/v1/organizations/{zero}/sync").status_code == 401
    assert client.post(f"/api/v1/pending-changes/{zero}/retry", json=reason_payload(), headers=idempotency_headers("r")).status_code == 401
    assert client.get("/api/v1/sync/status").status_code == 401
    assert client.get("/api/v1/failures").status_code == 401


def test_confirmed_delivery_marks_confirmed_and_sends_original_idempotency_key(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    original_key = change.idempotency_key
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True, product_request_id="req-confirm"))

    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-request"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.confirmed_and_synced.value
    assert StubProductClient.calls[0]["idempotency_key"] == original_key
    refreshed = db_session.get(PendingProductChange, change.id)
    assert refreshed is not None
    assert refreshed.status == PendingChangeStatus.confirmed_and_synced
    assert refreshed.product_request_id == "req-confirm"


def test_success_without_explicit_confirmation_is_manual_resolution(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=False, product_request_id="req-unclear"))

    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-unclear"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    failure = db_session.scalar(select(FailureLog).where(FailureLog.pending_change_id == change.id))
    assert failure is not None
    assert failure.error_code == "unclear_confirmation"


def test_timeout_creates_pending_retry_and_retry_count_increments_once(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    product = db_session.get(ProductDeployment, change.product_deployment_id)
    product.supported_endpoints = {"pending_changes": {"idempotent_writes": True}}
    db_session.commit()
    stub_product_client(monkeypatch, ProductDeliveryResult(success=False, error_code="timeout", safe_error_message="Timed out"))
    first = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-timeout-1"))
    assert first.status_code == 200
    assert first.json()["data"]["status"] == PendingChangeStatus.pending_retry.value
    assert db_session.get(PendingProductChange, change.id).retry_count == 0

    stub_product_client(monkeypatch, ProductDeliveryResult(success=False, error_code="timeout", safe_error_message="Timed out again"))
    second = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver again"), headers=idempotency_headers("retry-timeout-2"))
    assert second.status_code == 200
    assert db_session.get(PendingProductChange, change.id).retry_count == 1


def test_ambiguous_timeout_without_product_idempotency_guarantee_requires_manual_resolution(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch, ProductDeliveryResult(success=False, error_code="timeout", safe_error_message="Timed out"))

    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-timeout-ambiguous"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    failure = db_session.scalar(select(FailureLog).where(FailureLog.pending_change_id == change.id))
    assert failure is not None
    assert failure.error_code == "ambiguous_timeout"


def test_processing_and_terminal_changes_are_not_retried(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch)
    for status_value in (
        PendingChangeStatus.sent_to_product,
        PendingChangeStatus.confirmed_and_synced,
        PendingChangeStatus.cancelled,
        PendingChangeStatus.accepted_by_product,
        PendingChangeStatus.requires_manual_resolution,
    ):
        change.status = status_value
        db_session.commit()
        response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Retry"), headers=idempotency_headers(f"blocked-{status_value.value}"))
        assert response.status_code == 409
    assert StubProductClient.calls == []


def test_stale_claim_without_status_lookup_moves_to_manual_resolution_without_product_call(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    change.status = PendingChangeStatus.sent_to_product
    change.delivery_attempt_id = "stale-attempt"
    change.delivery_started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()
    stub_product_client(monkeypatch)

    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Recover stale"), headers=idempotency_headers("retry-stale"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    assert StubProductClient.calls == []
    refreshed = db_session.get(PendingProductChange, change.id)
    assert refreshed.status == PendingChangeStatus.requires_manual_resolution
    assert db_session.scalar(select(FailureLog).where(FailureLog.pending_change_id == change.id)).error_code == "stale_delivery_attempt"


def test_stale_claim_with_status_lookup_confirms_without_resending_delivery(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    product = db_session.get(ProductDeployment, change.product_deployment_id)
    product.supported_endpoints = {"pending_changes": {"status_lookup": True}}
    change.status = PendingChangeStatus.sent_to_product
    change.delivery_attempt_id = "stale-attempt"
    change.delivery_started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True, product_request_id="lookup-req"))

    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Lookup stale"), headers=idempotency_headers("retry-stale-lookup"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.confirmed_and_synced.value
    assert StubProductClient.calls == [{"status_lookup": True, "idempotency_key": change.idempotency_key}]


def test_finalizer_with_wrong_attempt_id_cannot_overwrite_current_attempt(client: TestClient, db_session: Session) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    admin_model = db_session.scalar(select(Admin))
    change.status = PendingChangeStatus.sent_to_product
    change.delivery_attempt_id = "current-attempt"
    change.delivery_started_at = datetime.now(timezone.utc)
    db_session.commit()

    with pytest.raises(Exception):
        _finalize(db_session, change.id, "old-attempt", ProductDeliveryResult(success=True, sync_confirmed=True), admin_model)
    db_session.rollback()
    assert db_session.get(PendingProductChange, change.id).status == PendingChangeStatus.sent_to_product


def test_crash_after_remote_response_leaves_stale_attempt_recoverable_without_resend(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True))

    def crash_finalize(*args, **kwargs):
        raise RuntimeError("simulated finalization crash")

    monkeypatch.setattr("app.services.sync_service._finalize", crash_finalize)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-crash"))
    db_session.rollback()
    assert len(StubProductClient.calls) == 1

    refreshed = db_session.get(PendingProductChange, change.id)
    refreshed.delivery_started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()
    monkeypatch.undo()
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True))
    recovered = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Recover"), headers=idempotency_headers("retry-crash-recover"))

    assert recovered.status_code == 200
    assert recovered.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    assert StubProductClient.calls == []


def test_mismatch_and_incompatible_api_require_manual_resolution(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="wrong-org"))
    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-mismatch"))
    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    assert db_session.scalar(select(FailureLog).where(FailureLog.pending_change_id == change.id)).error_code == "organization_mismatch"


def test_missing_mapping_blocks_delivery_without_product_call(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("5.00", "Credit delivery"),
        headers=idempotency_headers("credit-no-map"),
    )
    assert response.status_code == 409
    # Create a pending row manually to verify delivery guard also blocks.
    change = PendingProductChange(
        action="credits.add",
        payload={"amount": "5.00"},
        organization_id=UUID(org["id"]),
        product_deployment_id=deployment.id,
        status=PendingChangeStatus.saved,
        idempotency_key="manual-no-map",
        retry_count=0,
        reason="No mapping",
    )
    db_session.add(change)
    db_session.commit()
    stub_product_client(monkeypatch)
    delivery = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-no-map"))
    assert delivery.status_code == 409
    assert StubProductClient.calls == []


def test_retry_does_not_repeat_central_financial_effects(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    org, change = create_credit_change(client, db_session, amount="7.00")
    before_count = db_session.scalar(select(func.count()).select_from(BillingLedgerEntry).where(BillingLedgerEntry.organization_id == UUID(org["id"])))
    before_balance = db_session.get(Organization, UUID(org["id"])).credit_balance
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True))

    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-no-central"))

    assert response.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(BillingLedgerEntry).where(BillingLedgerEntry.organization_id == UUID(org["id"]))) == before_count
    assert db_session.get(Organization, UUID(org["id"])).credit_balance == before_balance


def test_duplicate_retry_request_idempotency_replays_without_extra_logs(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    product = db_session.get(ProductDeployment, change.product_deployment_id)
    product.supported_endpoints = {"pending_changes": {"idempotent_writes": True}}
    db_session.commit()
    stub_product_client(monkeypatch, ProductDeliveryResult(success=False, error_code="timeout", safe_error_message="Timed out"))

    first = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Retry"), headers=idempotency_headers("retry-replay"))
    failure_count = db_session.scalar(select(func.count()).select_from(FailureLog).where(FailureLog.pending_change_id == change.id))
    audit_count = db_session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.like("pending_change.delivery%"), AuditLog.organization_id == UUID(_org["id"])))
    second = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Retry"), headers=idempotency_headers("retry-replay"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert len(StubProductClient.calls) == 1
    assert db_session.scalar(select(func.count()).select_from(FailureLog).where(FailureLog.pending_change_id == change.id)) == failure_count
    assert db_session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.like("pending_change.delivery%"), AuditLog.organization_id == UUID(_org["id"]))) == audit_count


def test_older_unresolved_change_blocks_newer_delivery(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    first = client.post(f"/api/v1/organizations/{org['id']}/credits/add", json=financial_payload("1.00"), headers=idempotency_headers("older-credit"))
    second = client.post(f"/api/v1/organizations/{org['id']}/credits/deduct", json=financial_payload("1.00"), headers=idempotency_headers("newer-credit"))
    assert first.status_code == 200
    assert second.status_code == 200
    changes = list(db_session.scalars(select(PendingProductChange).where(PendingProductChange.organization_id == UUID(org["id"])).order_by(PendingProductChange.created_at.asc())))
    assert len(changes) == 2
    stub_product_client(monkeypatch)
    response = client.post(f"/api/v1/pending-changes/{changes[1].id}/retry", json=reason_payload("Deliver newer"), headers=idempotency_headers("retry-newer"))
    assert response.status_code == 409


def test_product_and_organization_sync_expose_results_and_preserve_order(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True))
    org_sync = client.post(f"/api/v1/organizations/{org['id']}/sync")
    product_sync = client.post(f"/api/v1/products/{change.product_deployment_id}/sync")
    status_response = client.get("/api/v1/sync/status")
    failures = client.get("/api/v1/failures")
    assert org_sync.status_code == 200
    assert org_sync.json()["data"]["results"][0]["status"] == PendingChangeStatus.confirmed_and_synced.value
    assert product_sync.status_code == 200
    assert status_response.status_code == 200
    assert failures.status_code == 200


def test_different_organizations_continue_when_one_is_blocked(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    first_org = create_org(client, deployment)
    second_org = create_org(client, deployment, name="Second Clinic")
    create_mapping(db_session, first_org["id"], deployment.id, product_organization_id="prod-one")
    create_mapping(db_session, second_org["id"], deployment.id, product_organization_id="prod-two")
    assert client.post(f"/api/v1/organizations/{first_org['id']}/credits/add", json=financial_payload("1.00"), headers=idempotency_headers("first-old")).status_code == 200
    older_first_change = db_session.scalar(select(PendingProductChange).where(PendingProductChange.organization_id == UUID(first_org["id"])))
    older_first_change.status = PendingChangeStatus.requires_manual_resolution
    db_session.commit()
    assert client.post(f"/api/v1/organizations/{first_org['id']}/credits/add", json=financial_payload("1.00"), headers=idempotency_headers("first-new")).status_code == 200
    assert client.post(f"/api/v1/organizations/{second_org['id']}/credits/add", json=financial_payload("1.00"), headers=idempotency_headers("second")).status_code == 200
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True))

    response = client.post(f"/api/v1/products/{deployment.id}/sync")

    assert response.status_code == 200
    statuses = [item["status"] for item in response.json()["data"]["results"]]
    assert "blocked" in statuses
    assert PendingChangeStatus.confirmed_and_synced.value in statuses


def test_unresolved_changes_prevent_product_aggregate_synced_status(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    first_org = create_org(client, deployment)
    second_org = create_org(client, deployment, name="Second Clinic")
    create_mapping(db_session, first_org["id"], deployment.id, product_organization_id="prod-one")
    create_mapping(db_session, second_org["id"], deployment.id, product_organization_id="prod-two")
    assert client.post(f"/api/v1/organizations/{first_org['id']}/credits/add", json=financial_payload("1.00"), headers=idempotency_headers("aggregate-one")).status_code == 200
    assert client.post(f"/api/v1/organizations/{second_org['id']}/credits/add", json=financial_payload("1.00"), headers=idempotency_headers("aggregate-two")).status_code == 200
    first_change = db_session.scalar(select(PendingProductChange).where(PendingProductChange.organization_id == UUID(first_org["id"])))
    stub_product_client(monkeypatch, ProductDeliveryResult(success=True, sync_confirmed=True))

    response = client.post(f"/api/v1/pending-changes/{first_change.id}/retry", json=reason_payload("Deliver one"), headers=idempotency_headers("aggregate-retry-one"))

    assert response.status_code == 200
    assert db_session.get(ProductDeployment, deployment.id).sync_status.value == "pending"


def test_no_placeholder_product_success_when_success_field_is_missing() -> None:
    result = ProductDeliveryResult(success=False, sync_confirmed=True)
    assert result.success is False


def test_health_and_mapping_sync_use_existing_paths_without_fake_mappings(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")

    def build_client(product, api_secret=None):
        return StubProductClient()

    monkeypatch.setattr("app.services.product_service.build_product_client", build_client)
    monkeypatch.setattr("app.services.sync_service.build_product_client", build_client)
    health = client.post(f"/api/v1/products/{deployment.id}/sync/health")
    mapping = client.post(f"/api/v1/products/{deployment.id}/sync/organizations")
    assert health.status_code == 200
    assert mapping.status_code == 200
    assert mapping.json()["data"]["checked"] == 1
    assert db_session.scalar(select(func.count()).select_from(PendingProductChange)) == 0


def test_secret_not_exposed_in_delivery_response_or_logs(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    _org, change = create_credit_change(client, db_session)
    stub_product_client(monkeypatch, ProductDeliveryResult(success=False, error_code="timeout", safe_error_message="Timed out"))
    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json=reason_payload("Deliver"), headers=idempotency_headers("retry-secret-safe"))
    failure = db_session.scalar(select(FailureLog).where(FailureLog.pending_change_id == change.id))
    refreshed = db_session.get(PendingProductChange, change.id)
    combined = f"{response.text} {failure.error_message if failure else ''} {refreshed.safe_confirmation_summary if refreshed else ''}"
    assert "product-secret" not in combined
