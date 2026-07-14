from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    BillingCalculationStatus,
    BillingMode,
    CreditStatus,
    Environment,
    MappingStatus,
    OrganizationLifecycleStatus,
    ProductHealthStatus,
    ServiceStatus,
    SyncStatus,
)
from app.core.product_secrets import encrypt_product_secret
from app.integrations.product_admin_client import ProductOrganizationLookupResult
from app.models.audit import AuditLog
from app.models.failure_log import FailureLog
from app.models.organization import Organization, OrganizationMapping
from app.models.product import ProductDeployment
from app.services.organization_service import require_verified_mapping


def login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert response.status_code == 200


def create_deployment(
    db_session: Session,
    *,
    product_name: str = "Core CRM",
    region: str = "us-east",
    environment: Environment = Environment.staging,
) -> ProductDeployment:
    deployment = ProductDeployment(
        product_name=product_name,
        region=region,
        environment=environment,
        currency="USD",
        api_base_url="https://product.example.com",
        health_check_url="https://product.example.com/health",
        admin_api_version="v1",
        admin_api_secret_encrypted=encrypt_product_secret("product-secret"),
        is_active=True,
        is_under_maintenance=False,
        health_status=ProductHealthStatus.healthy,
        sync_status=SyncStatus.pending,
    )
    db_session.add(deployment)
    db_session.commit()
    db_session.refresh(deployment)
    return deployment


def org_payload(deployment: ProductDeployment, **overrides) -> dict:
    payload = {
        "central_organization_id": f"org-{uuid4()}",
        "name": "Acme Clinic",
        "product_deployment_id": str(deployment.id),
        "currency": "usd",
        "lifecycle_status": "trial",
        "billing_mode": "prepaid_credits",
        "billing_calculation_status": "usage_tracking_only",
        "credit_status": "not_applicable",
        "service_status": "pending_sync",
        "sync_status": "pending",
    }
    payload.update(overrides)
    return payload


def create_org(client: TestClient, deployment: ProductDeployment, **overrides) -> dict:
    response = client.post("/api/v1/organizations", json=org_payload(deployment, **overrides))
    assert response.status_code == 201
    return response.json()["data"]


class StubProductClient:
    calls = 0
    secrets: list[str | None] = []

    def __init__(self, result: ProductOrganizationLookupResult) -> None:
        self.result = result

    async def get_organization_detail(self, product_organization_id: str) -> ProductOrganizationLookupResult:
        StubProductClient.calls += 1
        return self.result


def stub_lookup(monkeypatch, result: ProductOrganizationLookupResult) -> None:
    StubProductClient.calls = 0
    StubProductClient.secrets = []

    def build_client(product: ProductDeployment, api_secret: str | None = None) -> StubProductClient:
        StubProductClient.secrets.append(api_secret)
        return StubProductClient(result)

    monkeypatch.setattr("app.services.organization_service.build_product_client", build_client)


def test_organization_endpoints_require_authentication(client: TestClient) -> None:
    org_id = UUID(int=0)
    assert client.get("/api/v1/organizations").status_code == 401
    assert client.post("/api/v1/organizations", json={}).status_code == 401
    assert client.get(f"/api/v1/organizations/{org_id}").status_code == 401
    assert client.patch(f"/api/v1/organizations/{org_id}", json={"name": "x"}).status_code == 401
    assert client.get(f"/api/v1/organizations/{org_id}/mapping").status_code == 401
    assert client.patch(f"/api/v1/organizations/{org_id}/mapping", json={}).status_code == 401
    assert client.post(f"/api/v1/organizations/{org_id}/verify-mapping").status_code == 401


def test_organization_create_list_detail_and_update_work(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    assert created["name"] == "Acme Clinic"
    assert created["currency"] == "USD"
    assert created["product_deployment"]["product_name"] == "Core CRM"

    list_response = client.get("/api/v1/organizations")
    assert list_response.status_code == 200
    assert list_response.json()["data"]["total"] == 1

    detail_response = client.get(f"/api/v1/organizations/{created['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["id"] == created["id"]

    update_response = client.patch(
        f"/api/v1/organizations/{created['id']}",
        json={"name": "Acme Clinic Updated", "service_status": "running"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["name"] == "Acme Clinic Updated"
    assert updated["service_status"] == "pending_sync"
    assert updated["service_enforcement_status"] == "pending_sync"

    actions = db_session.scalars(select(AuditLog.action)).all()
    assert "organization.created" in actions
    assert "organization.updated" in actions


def test_pagination_and_filters_work(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment_a = create_deployment(db_session, product_name="Core CRM", region="us-east", environment=Environment.production)
    deployment_b = create_deployment(db_session, product_name="Forms", region="eu-west", environment=Environment.staging)
    create_org(
        client,
        deployment_a,
        name="Alpha Health",
        currency="USD",
        lifecycle_status="active",
        billing_mode="prepaid_credits",
        credit_status="healthy_balance",
        service_status="running",
        sync_status="synced",
        last_active_at=datetime(2026, 7, 1, tzinfo=timezone.utc).isoformat(),
    )
    org_b = create_org(
        client,
        deployment_b,
        name="Beta Health",
        currency="EUR",
        lifecycle_status="trial",
        billing_mode="free_internal_testing",
        credit_status="not_applicable",
        service_status="pending_sync",
        sync_status="pending",
        last_active_at=datetime(2026, 7, 5, tzinfo=timezone.utc).isoformat(),
    )

    page = client.get("/api/v1/organizations", params={"limit": 1, "offset": 1})
    assert page.status_code == 200
    assert page.json()["data"]["limit"] == 1
    assert page.json()["data"]["offset"] == 1
    assert page.json()["data"]["total"] == 2

    filtered = client.get(
        "/api/v1/organizations",
        params={
            "product_name": "Forms",
            "region": "eu-west",
            "environment": "staging",
            "currency": "EUR",
            "lifecycle_status": "trial",
            "billing_mode": "free_internal_testing",
            "billing_calculation_status": "usage_tracking_only",
            "credit_status": "not_applicable",
            "service_status": "pending_sync",
            "sync_status": "pending",
            "last_active_from": "2026-07-04T00:00:00Z",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["data"]["total"] == 1
    assert filtered.json()["data"]["items"][0]["id"] == org_b["id"]


def test_organization_name_search_is_case_insensitive(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment, name="North Star Clinic")
    response = client.get("/api/v1/organizations", params={"search": "star"})
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["id"] == created["id"]


def test_mapping_can_be_created_or_updated_and_id_change_invalidates_verification(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    response = client.patch(
        f"/api/v1/organizations/{created['id']}/mapping",
        json={"product_organization_id": "prod-org-1", "mapping_status": "active"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["product_organization_id"] == "prod-org-1"
    assert response.json()["data"]["mapping_status"] == "requires_manual_review"
    assert response.json()["data"]["last_verified_at"] is None

    mapping = db_session.scalar(select(OrganizationMapping).where(OrganizationMapping.organization_id == UUID(created["id"])))
    assert mapping is not None
    mapping.mapping_status = MappingStatus.active
    mapping.last_verified_at = datetime.now(timezone.utc)
    db_session.commit()

    response = client.patch(f"/api/v1/organizations/{created['id']}/mapping", json={"product_organization_id": "prod-org-2"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mapping_status"] == "requires_manual_review"
    assert data["last_verified_at"] is None


def test_missing_product_side_id_does_not_call_product_client(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    stub_lookup(monkeypatch, ProductOrganizationLookupResult(is_success=True, product_organization_id="ignored"))
    response = client.post(f"/api/v1/organizations/{created['id']}/verify-mapping")
    assert response.status_code == 200
    assert response.json()["data"]["mapping"]["mapping_status"] == "missing_product_id"
    assert StubProductClient.calls == 0


def test_successful_verification_marks_mapping_active(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    client.patch(f"/api/v1/organizations/{created['id']}/mapping", json={"product_organization_id": "prod-org-1"})
    stub_lookup(monkeypatch, ProductOrganizationLookupResult(is_success=True, product_organization_id="prod-org-1"))
    response = client.post(f"/api/v1/organizations/{created['id']}/verify-mapping")
    assert response.status_code == 200
    assert response.json()["data"]["success"] is True
    assert response.json()["data"]["mapping"]["mapping_status"] == "active"
    assert response.json()["data"]["mapping"]["last_verified_at"] is not None
    assert StubProductClient.secrets == ["product-secret"]


def test_product_mismatch_sets_status_and_creates_failure_log(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    client.patch(f"/api/v1/organizations/{created['id']}/mapping", json={"product_organization_id": "prod-org-1"})
    stub_lookup(monkeypatch, ProductOrganizationLookupResult(is_success=True, product_organization_id="other-org"))
    response = client.post(f"/api/v1/organizations/{created['id']}/verify-mapping")
    assert response.status_code == 200
    assert response.json()["data"]["mapping"]["mapping_status"] == "product_mismatch"
    failure = db_session.scalar(select(FailureLog).where(FailureLog.organization_id == UUID(created["id"])))
    assert failure is not None
    assert failure.error_code == "product_mismatch"


def test_timeout_failure_creates_sanitized_failure_log(client: TestClient, db_session: Session, monkeypatch, caplog) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    client.patch(f"/api/v1/organizations/{created['id']}/mapping", json={"product_organization_id": "prod-org-1"})
    stub_lookup(
        monkeypatch,
        ProductOrganizationLookupResult(
            is_success=False,
            error_category="timeout",
            error_message="Product organization lookup timed out",
        ),
    )
    response = client.post(f"/api/v1/organizations/{created['id']}/verify-mapping")
    assert response.status_code == 200
    assert response.json()["data"]["mapping"]["mapping_status"] == "requires_manual_review"
    failure = db_session.scalar(select(FailureLog).where(FailureLog.organization_id == UUID(created["id"])))
    assert failure is not None
    assert failure.error_code == "timeout"
    assert "product-secret" not in failure.error_message
    assert "product-secret" not in response.text
    for record in caplog.records:
        assert "product-secret" not in record.getMessage()


def test_manual_verification_creates_audit_log(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    created = create_org(client, deployment)
    client.patch(f"/api/v1/organizations/{created['id']}/mapping", json={"product_organization_id": "prod-org-1"})
    stub_lookup(monkeypatch, ProductOrganizationLookupResult(is_success=True, product_organization_id="prod-org-1"))
    client.post(f"/api/v1/organizations/{created['id']}/verify-mapping")
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "organization.mapping.verify", AuditLog.organization_id == UUID(created["id"]))
    )
    assert audit is not None
    assert audit.new_value["mapping_status"] == "active"


def test_mapping_safety_helper_rejects_missing_mapping(db_session: Session) -> None:
    deployment = create_deployment(db_session)
    organization = Organization(
        central_organization_id="org-safety-missing",
        name="Safety Missing",
        product_deployment_id=deployment.id,
        currency="USD",
        lifecycle_status=OrganizationLifecycleStatus.trial,
        billing_mode=BillingMode.prepaid_credits,
        billing_calculation_status=BillingCalculationStatus.usage_tracking_only,
        credit_status=CreditStatus.not_applicable,
        service_status=ServiceStatus.pending_sync,
        service_enforcement_status=ServiceStatus.pending_sync,
        sync_status=SyncStatus.pending,
    )
    db_session.add(organization)
    db_session.commit()
    try:
        require_verified_mapping(db_session, organization.id, deployment.id)
        raise AssertionError("missing mapping should fail")
    except HTTPException as exc:
        assert exc.status_code == 409


def test_mapping_safety_helper_rejects_unverified_mapping(db_session: Session) -> None:
    deployment = create_deployment(db_session)
    organization = Organization(
        central_organization_id="org-safety-unverified",
        name="Safety Unverified",
        product_deployment_id=deployment.id,
        currency="USD",
        lifecycle_status=OrganizationLifecycleStatus.trial,
        billing_mode=BillingMode.prepaid_credits,
        billing_calculation_status=BillingCalculationStatus.usage_tracking_only,
        credit_status=CreditStatus.not_applicable,
        service_status=ServiceStatus.pending_sync,
        service_enforcement_status=ServiceStatus.pending_sync,
        sync_status=SyncStatus.pending,
    )
    db_session.add(organization)
    db_session.flush()
    db_session.add(
        OrganizationMapping(
            organization_id=organization.id,
            product_deployment_id=deployment.id,
            product_organization_id="prod-org-1",
            product_api_version="v1",
            mapping_status=MappingStatus.requires_manual_review,
        )
    )
    db_session.commit()
    try:
        require_verified_mapping(db_session, organization.id, deployment.id)
        raise AssertionError("unverified mapping should fail")
    except HTTPException as exc:
        assert exc.status_code == 409


def test_mapping_safety_helper_rejects_deployment_mismatch_and_accepts_verified_mapping(db_session: Session) -> None:
    deployment = create_deployment(db_session)
    other_deployment = create_deployment(db_session, product_name="Other")
    organization = Organization(
        central_organization_id="org-safety-ok",
        name="Safety Ok",
        product_deployment_id=deployment.id,
        currency="USD",
        lifecycle_status=OrganizationLifecycleStatus.trial,
        billing_mode=BillingMode.prepaid_credits,
        billing_calculation_status=BillingCalculationStatus.usage_tracking_only,
        credit_status=CreditStatus.not_applicable,
        service_status=ServiceStatus.pending_sync,
        service_enforcement_status=ServiceStatus.pending_sync,
        sync_status=SyncStatus.pending,
    )
    db_session.add(organization)
    db_session.flush()
    mapping = OrganizationMapping(
        organization_id=organization.id,
        product_deployment_id=deployment.id,
        product_organization_id="prod-org-1",
        product_api_version="v1",
        mapping_status=MappingStatus.active,
    )
    db_session.add(mapping)
    db_session.commit()
    try:
        require_verified_mapping(db_session, organization.id, other_deployment.id)
        raise AssertionError("deployment mismatch should fail")
    except HTTPException as exc:
        assert exc.status_code == 409
    assert require_verified_mapping(db_session, organization.id, deployment.id).id == mapping.id
