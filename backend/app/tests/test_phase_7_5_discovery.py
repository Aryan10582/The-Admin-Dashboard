from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import MappingStatus, OrganizationDiscoveryStatus
from app.integrations.product_admin_client import ProductOrganizationListItem, ProductOrganizationListResult, ProductOrganizationLookupResult
from app.models.discovery import ProductOrganizationDiscovery
from app.models.organization import Organization, OrganizationMapping
from app.models.product import ProductDeployment
from app.tests.test_organizations import create_deployment, login


class DiscoveryClient:
    calls = 0
    org_detail_result = ProductOrganizationLookupResult(is_success=True, product_organization_id="org_101")
    pages = [
        ProductOrganizationListResult(
            is_success=True,
            organizations=[
                ProductOrganizationListItem(
                    product_organization_id="org_101",
                    organization_name="City Clinic",
                    lifecycle_status="active",
                    billing_mode="prepaid_credits",
                    billing_calculation_status="active",
                    currency="USD",
                    credit_status="healthy_balance",
                    credit_balance="100.00",
                    outstanding_dues="0.00",
                    service_status="running",
                    product_active_status=True,
                    product_api_version="v1",
                ),
                ProductOrganizationListItem(
                    product_organization_id="org_205",
                    organization_name="City Clinic",
                    lifecycle_status="trial",
                    billing_mode="prepaid_credits",
                    currency="USD",
                    product_api_version="v1",
                ),
            ],
        )
    ]

    async def list_organizations(self, *, cursor=None, limit=100):
        self.__class__.calls += 1
        return self.pages[0]

    async def get_organization_detail(self, product_organization_id: str):
        return ProductOrganizationLookupResult(
            is_success=True,
            product_organization_id=product_organization_id,
            payload={
                "product_organization_id": product_organization_id,
                "organization_name": "Fetched Clinic",
                "currency": "USD",
                "lifecycle_status": "trial",
                "billing_mode": "prepaid_credits",
                "billing_calculation_status": "usage_tracking_only",
            },
        )


def stub_discovery(monkeypatch, result: ProductOrganizationListResult | None = None) -> None:
    DiscoveryClient.calls = 0
    if result is not None:
        DiscoveryClient.pages = [result]

    monkeypatch.setattr("app.services.discovery_service.build_product_client", lambda product, api_secret=None: DiscoveryClient())
    monkeypatch.setattr("app.services.organization_service.build_product_client", lambda product, api_secret=None: DiscoveryClient())


def product_payload(**overrides) -> dict:
    payload = {
        "product_name": "Discovery Product",
        "region": "us-east",
        "environment": "testing",
        "currency": "USD",
        "api_base_url": "https://product.example.com",
        "health_check_url": "https://product.example.com/health",
        "admin_api_version": "v1",
        "organization_list_path": "/v1/admin/organizations",
        "organization_detail_path_template": "/v1/admin/organizations/{organization_id}",
        "admin_api_secret": "product-secret",
        "is_active": True,
        "is_under_maintenance": False,
    }
    payload.update(overrides)
    return payload


def test_product_create_accepts_org_list_path_and_auto_discovers(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)

    response = client.post("/api/v1/products", json=product_payload())

    assert response.status_code == 201
    assert response.json()["meta"]["organization_discovery"]["discovered_count"] == 2
    product_id = UUID(response.json()["data"]["id"])
    discoveries = list(db_session.scalars(select(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product_id)))
    assert len(discoveries) == 2
    assert {item.product_organization_id for item in discoveries} == {"org_101", "org_205"}
    assert len({item.organization_name for item in discoveries}) == 1


def test_unsafe_organization_list_paths_are_rejected(client: TestClient) -> None:
    login(client)
    response = client.post("/api/v1/products", json=product_payload(organization_list_path="https://evil.example.com/orgs"))
    assert response.status_code == 422
    response = client.post("/api/v1/products", json=product_payload(organization_list_path="/../admin/orgs"))
    assert response.status_code == 422


def test_manual_discovery_is_idempotent_and_updates_existing_rows(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)
    product = create_deployment(db_session)
    product.organization_list_path = "/v1/admin/organizations"
    product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.commit()

    first = client.post(f"/api/v1/products/{product.id}/organizations/discover")
    second = client.post(f"/api/v1/products/{product.id}/organizations/discover")

    assert first.status_code == 200
    assert second.status_code == 200
    assert db_session.query(ProductOrganizationDiscovery).filter(ProductOrganizationDiscovery.product_deployment_id == product.id).count() == 2


def test_import_uses_product_values_external_ids_and_verifies_mapping(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)
    product = create_deployment(db_session)
    product.organization_list_path = "/v1/admin/organizations"
    product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.commit()
    assert client.post(f"/api/v1/products/{product.id}/organizations/discover").status_code == 200

    response = client.post(f"/api/v1/products/{product.id}/organizations/import", json={"product_organization_ids": ["org_101", "org_205"]})

    assert response.status_code == 200
    imported = response.json()["data"]["items"]
    assert len(imported) == 2
    organizations = list(db_session.scalars(select(Organization).where(Organization.product_deployment_id == product.id)))
    assert len(organizations) == 2
    assert {org.name for org in organizations} == {"City Clinic"}
    assert len({org.central_organization_id for org in organizations}) == 2
    mappings = list(db_session.scalars(select(OrganizationMapping).where(OrganizationMapping.product_deployment_id == product.id)))
    assert {mapping.product_organization_id for mapping in mappings} == {"org_101", "org_205"}
    assert all(mapping.mapping_status == MappingStatus.active for mapping in mappings)


def test_repeated_import_does_not_create_duplicate_organizations_or_mappings(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)
    product = create_deployment(db_session)
    product.organization_list_path = "/v1/admin/organizations"
    product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.commit()
    client.post(f"/api/v1/products/{product.id}/organizations/discover")

    first = client.post(f"/api/v1/products/{product.id}/organizations/import", json={"product_organization_ids": ["org_101"]})
    second = client.post(f"/api/v1/products/{product.id}/organizations/import", json={"product_organization_ids": ["org_101"]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["items"][0]["status"] == "skipped"
    assert db_session.query(Organization).filter(Organization.product_deployment_id == product.id).count() == 1
    assert db_session.query(OrganizationMapping).filter(OrganizationMapping.product_deployment_id == product.id, OrganizationMapping.product_organization_id == "org_101").count() == 1


def test_manual_add_link_fetches_product_values_and_verifies_mapping(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)
    product = create_deployment(db_session)
    product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.add(ProductOrganizationDiscovery(product_deployment_id=product.id, product_organization_id="org_101", organization_name="City Clinic"))
    db_session.commit()

    lookup = client.post("/api/v1/organizations/product-lookup", json={"product_deployment_id": str(product.id), "product_organization_id": "org_101"})
    linked = client.post("/api/v1/organizations/link-from-product", json={"product_deployment_id": str(product.id), "product_organization_id": "org_101"})

    assert lookup.status_code == 200
    assert lookup.json()["data"]["organization_name"] == "Fetched Clinic"
    assert linked.status_code == 201
    assert linked.json()["data"]["central_organization_id"].startswith("org_")
    assert linked.json()["data"]["mapping"]["product_organization_id"] == "org_101"
    assert linked.json()["data"]["mapping"]["mapping_status"] == "active"
    discovery = db_session.scalar(select(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product.id, ProductOrganizationDiscovery.product_organization_id == "org_101"))
    assert discovery is not None
    assert discovery.discovery_status == OrganizationDiscoveryStatus.already_mapped


def test_manual_add_link_requires_reason_for_product_lookup_fallback(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)

    class FailingClient(DiscoveryClient):
        async def get_organization_detail(self, product_organization_id: str):
            return ProductOrganizationLookupResult(is_success=False, error_category="timeout", error_message="Lookup timed out")

    monkeypatch.setattr("app.services.organization_service.build_product_client", lambda product, api_secret=None: FailingClient())
    product = create_deployment(db_session)

    blocked = client.post("/api/v1/organizations/link-from-product", json={"product_deployment_id": str(product.id), "product_organization_id": "org_manual"})
    fallback = client.post(
        "/api/v1/organizations/link-from-product",
        json={
            "product_deployment_id": str(product.id),
            "product_organization_id": "org_manual",
            "manual_name": "Manual Clinic",
            "manual_currency": "USD",
            "manual_billing_mode": "prepaid_credits",
            "reason": "Product lookup unavailable during onboarding",
        },
    )

    assert blocked.status_code == 409
    assert fallback.status_code == 201
    assert fallback.json()["data"]["mapping"]["mapping_status"] == "requires_manual_review"


def test_rediscovery_updates_snapshots_without_overwriting_central_financial_or_service_state(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)
    product = create_deployment(db_session)
    product.organization_list_path = "/v1/admin/organizations"
    product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.commit()
    client.post(f"/api/v1/products/{product.id}/organizations/discover")
    client.post(f"/api/v1/products/{product.id}/organizations/import", json={"product_organization_ids": ["org_101"]})
    organization = db_session.scalar(select(Organization).where(Organization.product_deployment_id == product.id))
    assert organization is not None
    organization.credit_balance = Decimal("42.00")
    organization.outstanding_dues = Decimal("7.00")
    db_session.commit()

    stub_discovery(
        monkeypatch,
        ProductOrganizationListResult(
            is_success=True,
            organizations=[ProductOrganizationListItem(product_organization_id="org_101", organization_name="City Clinic", currency="USD", credit_balance="999.00", outstanding_dues="0.00", service_status="disabled")],
        ),
    )
    response = client.post(f"/api/v1/products/{product.id}/organizations/discover")
    db_session.refresh(organization)
    discovery = db_session.scalar(select(ProductOrganizationDiscovery).where(ProductOrganizationDiscovery.product_deployment_id == product.id, ProductOrganizationDiscovery.product_organization_id == "org_101"))

    assert response.status_code == 200
    assert str(organization.credit_balance) == "42.00"
    assert str(organization.outstanding_dues) == "7.00"
    assert discovery is not None
    assert str(discovery.credit_balance_snapshot) == "999.00"


def test_same_external_id_is_scoped_by_deployment(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch, ProductOrganizationListResult(is_success=True, organizations=[ProductOrganizationListItem(product_organization_id="org_101", organization_name="City Clinic", currency="USD")]))
    first = create_deployment(db_session, product_name="First")
    second = create_deployment(db_session, product_name="Second")
    for product in (first, second):
        product.organization_list_path = "/v1/admin/organizations"
        product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.commit()

    assert client.post(f"/api/v1/products/{first.id}/organizations/discover").status_code == 200
    assert client.post(f"/api/v1/products/{second.id}/organizations/discover").status_code == 200
    assert client.post(f"/api/v1/products/{first.id}/organizations/import", json={"product_organization_ids": ["org_101"]}).status_code == 200
    assert client.post(f"/api/v1/products/{second.id}/organizations/import", json={"product_organization_ids": ["org_101"]}).status_code == 200

    assert db_session.query(OrganizationMapping).filter(OrganizationMapping.product_organization_id == "org_101").count() == 2


def test_import_all_skips_already_mapped_records(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch)
    product = create_deployment(db_session)
    product.organization_list_path = "/v1/admin/organizations"
    product.organization_detail_path_template = "/v1/admin/organizations/{organization_id}"
    db_session.commit()
    client.post(f"/api/v1/products/{product.id}/organizations/discover")
    client.post(f"/api/v1/products/{product.id}/organizations/import", json={"product_organization_ids": ["org_101"]})

    response = client.post(f"/api/v1/products/{product.id}/organizations/import-all", json={"confirm": product.product_name, "limit": 100})

    assert response.status_code == 200
    statuses = {item["product_organization_id"]: item["status"] for item in response.json()["data"]["items"]}
    assert statuses["org_101"] == "skipped"


def test_product_delete_and_test_purge_safeguards(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    empty = create_deployment(db_session, product_name="Empty")
    delete_response = client.delete(f"/api/v1/products/{empty.id}")
    assert delete_response.status_code == 200

    product = create_deployment(db_session, product_name="With Dependency")
    discovery = ProductOrganizationDiscovery(product_deployment_id=product.id, product_organization_id="org_101", organization_name="City Clinic")
    db_session.add(discovery)
    db_session.commit()
    blocked = client.delete(f"/api/v1/products/{product.id}")
    assert blocked.status_code == 409

    purge_disabled = client.post(
        f"/api/v1/products/{product.id}/purge-test-data",
        json={"reason": "cleanup", "confirmation": product.product_name},
        headers={"Idempotency-Key": "purge-disabled"},
    )
    assert purge_disabled.status_code == 403


def test_product_test_purge_removes_disposable_admin_data_and_replays(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    monkeypatch.setattr("app.services.product_service.settings.environment", "development")
    monkeypatch.setattr("app.services.product_service.settings.allow_destructive_test_purge", True)
    product = create_deployment(db_session, product_name="Disposable Product")
    discovery = ProductOrganizationDiscovery(product_deployment_id=product.id, product_organization_id="org_101", organization_name="City Clinic")
    db_session.add(discovery)
    db_session.commit()

    response = client.post(
        f"/api/v1/products/{product.id}/purge-test-data",
        json={"reason": "disposable test cleanup", "confirmation": product.product_name},
        headers={"Idempotency-Key": "purge-enabled"},
    )
    replay = client.post(
        f"/api/v1/products/{product.id}/purge-test-data",
        json={"reason": "disposable test cleanup", "confirmation": product.product_name},
        headers={"Idempotency-Key": "purge-enabled"},
    )

    assert response.status_code == 200
    assert replay.status_code == 200
    assert response.json()["data"] == replay.json()["data"]
    assert response.json()["data"]["remote_product_deleted"] is False
    assert db_session.get(ProductDeployment, product.id) is None
    assert db_session.query(ProductOrganizationDiscovery).filter(ProductOrganizationDiscovery.product_deployment_id == product.id).count() == 0


def test_product_test_purge_refuses_production_environment_and_database_names(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    product = create_deployment(db_session, product_name="Prod Looking")
    monkeypatch.setattr("app.services.product_service.settings.allow_destructive_test_purge", True)
    monkeypatch.setattr("app.services.product_service.settings.environment", "production")
    blocked_env = client.post(
        f"/api/v1/products/{product.id}/purge-test-data",
        json={"reason": "cleanup", "confirmation": product.product_name},
        headers={"Idempotency-Key": "purge-prod-env"},
    )
    monkeypatch.setattr("app.services.product_service.settings.environment", "development")
    monkeypatch.setattr("app.services.product_service.settings.database_url", "postgresql://localhost/admin_production")
    blocked_db = client.post(
        f"/api/v1/products/{product.id}/purge-test-data",
        json={"reason": "cleanup", "confirmation": product.product_name},
        headers={"Idempotency-Key": "purge-prod-db"},
    )

    assert blocked_env.status_code == 403
    assert blocked_db.status_code == 403


def test_discovery_failure_does_not_roll_back_product_creation(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    stub_discovery(monkeypatch, ProductOrganizationListResult(is_success=False, organizations=[], error_category="temporary_5xx", error_message="Temporary failure"))
    response = client.post("/api/v1/products", json=product_payload(product_name="Failure Product"))

    assert response.status_code == 201
    assert response.json()["meta"]["organization_discovery"]["safe_failures"]
    assert db_session.get(ProductDeployment, UUID(response.json()["data"]["id"])) is not None
