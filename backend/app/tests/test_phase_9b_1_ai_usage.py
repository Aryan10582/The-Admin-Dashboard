from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import BillingMode, AiUsageConflictStatus, AiUsageMappingResolutionStatus, AiUsagePricingResolutionStatus, Environment, MappingStatus
from app.integrations.product_admin_client import ProductAdminClient, ProductTokenUsageItem, ProductTokenUsageListResult
from app.models.admin import Admin
from app.models.ai import AIUsageSyncRun, AIUsageSyncState, AiModelPricingCatalog, AiModelPricingVersion, AiUsageRecord, ProductAIModelPricingMapping
from app.models.organization import Organization, OrganizationMapping
from app.models.product import ProductDeployment
from app.schemas.ai_pricing import AiPricingCatalogCreate, AiPricingVersionCreate
from app.schemas.ai_usage import ProductAIModelPricingMappingCreate, TokenUsageSyncRequest
from app.services.ai_pricing_catalog_service import create_pricing_catalog, create_pricing_version
from app.services.ai_usage_service import create_model_mapping, sync_token_usage


def admin(db: Session) -> Admin:
    return db.scalar(select(Admin))  # type: ignore[return-value]


def login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert response.status_code == 200


def make_product(db: Session, name: str = "Usage Product", token_usage_list_path: str | None = "/v1/admin/token-usage") -> ProductDeployment:
    product = ProductDeployment(
        product_name=name,
        region="us",
        environment=Environment.development,
        currency="USD",
        api_base_url="http://mock-product",
        admin_api_version="v1",
        token_usage_list_path=token_usage_list_path,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def make_catalog_with_versions(db: Session) -> tuple[AiModelPricingCatalog, UUID, UUID]:
    result = create_pricing_catalog(
        db,
        AiPricingCatalogCreate(provider="mock-ai", provider_model_id="central-model", display_name="Central Model", pricing_scope_code="standard", currency="USD", reason="catalog"),
        "usage-catalog",
        admin(db),
    )
    catalog = db.get(AiModelPricingCatalog, UUID(result["id"]))
    now = datetime.now(timezone.utc)
    old = create_pricing_version(
        db,
        catalog.id,
        AiPricingVersionCreate(input_token_price=Decimal("2.00000000"), output_token_price=Decimal("8.00000000"), pricing_unit_tokens=1000, effective_from=now - timedelta(days=10), reason="old"),
        "usage-version-old",
        admin(db),
    )
    new = create_pricing_version(
        db,
        catalog.id,
        AiPricingVersionCreate(input_token_price=Decimal("3.00000000"), output_token_price=Decimal("9.00000000"), pricing_unit_tokens=1000, effective_from=now - timedelta(days=1), reason="new"),
        "usage-version-new",
        admin(db),
    )
    return catalog, UUID(old["id"]), UUID(new["id"])


def make_mapping(db: Session, product: ProductDeployment, catalog: AiModelPricingCatalog) -> ProductAIModelPricingMapping:
    result = create_model_mapping(
        db,
        product.id,
        ProductAIModelPricingMappingCreate(product_provider="Mock-AI", product_model_id="product-model", pricing_catalog_id=catalog.id, reason="map model"),
        f"mapping-{product.id}",
        admin(db),
    )
    row = db.get(ProductAIModelPricingMapping, UUID(result["id"]))
    assert row.product_provider == "mock-ai"
    return row


def make_org_mapping(db: Session, product: ProductDeployment, product_org_id: str = "org_101") -> Organization:
    org = Organization(
        central_organization_id=f"central-usage-{product.id}",
        name="Usage Org",
        product_deployment_id=product.id,
        currency="USD",
        billing_mode=BillingMode.prepaid_credits,
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMapping(organization_id=org.id, product_deployment_id=product.id, product_organization_id=product_org_id, product_api_version="v1", mapping_status=MappingStatus.active))
    db.commit()
    db.refresh(org)
    return org


class UsageClient:
    def __init__(self, pages: list[list[ProductTokenUsageItem]]):
        self.pages = pages
        self.calls = 0

    async def list_token_usage(self, *, cursor: str | None = None, limit: int = 100) -> ProductTokenUsageListResult:
        index = int(cursor or "0")
        self.calls += 1
        next_cursor = str(index + 1) if index + 1 < len(self.pages) else None
        return ProductTokenUsageListResult(True, self.pages[index], next_cursor=next_cursor, has_more=next_cursor is not None)


def usage_item(**overrides) -> ProductTokenUsageItem:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    data = {
        "product_usage_id": "usage-1",
        "product_organization_id": "org_101",
        "provider": "mock-ai",
        "product_model_id": "product-model",
        "input_tokens": 1000,
        "output_tokens": 500,
        "usage_at": (now - timedelta(hours=2)).isoformat(),
        "is_final": True,
        "finalized_at": (now - timedelta(hours=1)).isoformat(),
    }
    data.update(overrides)
    return ProductTokenUsageItem(**data)


def test_product_admin_client_uses_configured_token_usage_paths() -> None:
    india = ProductAdminClient("https://india.example.com", token_usage_list_path="/api/v1/admin/ai-usage")
    dubai = ProductAdminClient("https://dubai.example.com/root", token_usage_list_path="/internal/admin/token-usage")

    assert india._url_for_path(india.token_usage_list_path) == "https://india.example.com/api/v1/admin/ai-usage"
    assert dubai._url_for_path(dubai.token_usage_list_path) == "https://dubai.example.com/root/internal/admin/token-usage"


@pytest.mark.asyncio
async def test_missing_token_usage_path_makes_no_http_call() -> None:
    client = ProductAdminClient("https://product.example.com")
    result = await client.list_token_usage()
    assert result.is_success is False
    assert result.error_category == "not_configured"


def test_product_admin_client_rejects_unsafe_token_usage_path() -> None:
    client = ProductAdminClient("https://product.example.com", token_usage_list_path="//evil.example.com/usage")
    with pytest.raises(ValueError):
        client._url_for_path(client.token_usage_list_path)


@pytest.mark.asyncio
async def test_sync_imports_paginated_usage_resolves_mapping_pricing_and_cost(db_session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, old_version_id, new_version_id = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    org = make_org_mapping(db_session, product)
    old_usage = usage_item(product_usage_id="old", usage_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), input_tokens=1000, output_tokens=500)
    current_usage = usage_item(product_usage_id="current", usage_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), input_tokens=2000, output_tokens=1000)
    stub = UsageClient([[old_usage], [current_usage]])
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: stub)

    result = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync", limit=1, max_pages=3), "usage-sync", admin(db_session))
    assert result["pages_fetched"] == 2
    assert result["imported_count"] == 2
    assert result["finalized_cost_count"] == 2
    assert result["status"] == "success"
    rows = db_session.query(AiUsageRecord).order_by(AiUsageRecord.product_usage_id).all()
    assert len(rows) == 2
    assert {row.pricing_version_id for row in rows} == {old_version_id, new_version_id}
    current = next(row for row in rows if row.product_usage_id == "current")
    assert current.organization_id == org.id
    assert current.total_cost == Decimal("15.0000000000")
    assert current.input_token_price == Decimal("3.00000000")
    assert current.output_token_price == Decimal("9.00000000")
    assert db_session.get(AIUsageSyncState, product.id).last_committed_cursor is None
    login(client)
    state_response = client.get(f"/api/v1/products/{product.id}/ai-usage-sync-state")
    runs_response = client.get(f"/api/v1/products/{product.id}/ai-usage-sync-runs")
    assert state_response.status_code == 200
    assert runs_response.status_code == 200
    assert state_response.json()["data"]["product_deployment_id"] == str(product.id)
    assert runs_response.json()["data"]["total"] == 1


@pytest.mark.asyncio
async def test_unconfigured_product_sync_records_failed_run_without_product_call(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session, token_usage_list_path=None)

    def fail_build_client(*args, **kwargs):
        raise AssertionError("Product client should not be built when token usage path is missing")

    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", fail_build_client)
    result = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "usage-not-configured", admin(db_session))
    replay = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "usage-not-configured", admin(db_session))

    assert result == replay
    assert result["status"] == "failed"
    assert result["safe_error"] == "Token usage synchronization is not configured for this product."
    assert db_session.query(AiUsageRecord).count() == 0
    assert db_session.query(AIUsageSyncRun).filter_by(product_deployment_id=product.id).count() == 1
    state = db_session.get(AIUsageSyncState, product.id)
    assert state is not None
    assert state.safe_last_error == "Token usage synchronization is not configured for this product."
    db_session.refresh(product)
    assert product.last_usage_sync_error == "Token usage synchronization is not configured for this product."


@pytest.mark.asyncio
async def test_replay_dedupes_and_conflicting_replay_preserves_original_cost(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    item = usage_item()
    stub = UsageClient([[item]])
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: stub)
    first = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "usage-sync-1", admin(db_session))
    replay = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "usage-sync-1", admin(db_session))
    assert first == replay
    second = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync again"), "usage-sync-2", admin(db_session))
    assert second["unchanged_count"] == 1, second

    original = db_session.query(AiUsageRecord).filter_by(product_usage_id="usage-1").one()
    original_cost = original.total_cost
    changed = usage_item(input_tokens=9999)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[changed]]))
    conflict = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="conflict"), "usage-sync-3", admin(db_session))
    assert conflict["conflict_count"] == 1
    stored = db_session.query(AiUsageRecord).filter_by(product_usage_id="usage-1").one()
    assert stored.input_tokens == 1000
    assert stored.total_cost == original_cost
    assert stored.conflict_status == AiUsageConflictStatus.conflict
    assert db_session.query(AiUsageRecord).count() == 1


@pytest.mark.asyncio
async def test_pricing_and_organization_resolution_are_independent(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_organization_id="missing-org")]]))
    result = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "usage-unmapped", admin(db_session))
    row = db_session.query(AiUsageRecord).one()
    assert result["unresolved_mapping_count"] == 1
    assert row.organization_id is None
    assert row.mapping_resolution_status == AiUsageMappingResolutionStatus.requires_mapping_resolution
    assert row.pricing_resolution_status == AiUsagePricingResolutionStatus.resolved
    assert row.total_cost is not None


@pytest.mark.asyncio
async def test_unknown_model_invalid_non_final_and_unsupported_dimensions_are_preserved(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    items = [
        usage_item(product_usage_id="unknown", product_model_id="unknown"),
        usage_item(product_usage_id="bad-time", usage_at="not-a-date"),
        usage_item(product_usage_id="negative", input_tokens=-1),
        usage_item(product_usage_id="special", unsupported_dimensions={"cached_input_tokens": 10}),
        usage_item(product_usage_id="non-final", is_final=False, usage_revision="rev-1", finalized_at=None),
    ]
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([items]))
    result = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "usage-mixed", admin(db_session))
    assert result["invalid_count"] == 2
    assert result["unresolved_pricing_count"] >= 3
    assert db_session.query(AiUsageRecord).count() == 5
    special = db_session.query(AiUsageRecord).filter_by(product_usage_id="special").one()
    assert special.pricing_resolution_status == AiUsagePricingResolutionStatus.unsupported_dimensions
    assert special.total_cost is None
    non_final = db_session.query(AiUsageRecord).filter_by(product_usage_id="non-final").one()
    assert non_final.is_final is False
    assert non_final.total_cost is None


@pytest.mark.asyncio
async def test_same_usage_id_allowed_in_different_deployments_and_product_delete_blocks_usage(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product_one = make_product(db_session, "Usage One")
    product_two = make_product(db_session, "Usage Two")
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product_one, catalog)
    make_mapping(db_session, product_two, catalog)
    make_org_mapping(db_session, product_one)
    make_org_mapping(db_session, product_two)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_usage_id="shared")]]))
    await sync_token_usage(db_session, product_one.id, TokenUsageSyncRequest(reason="sync"), "usage-product-one", admin(db_session))
    await sync_token_usage(db_session, product_two.id, TokenUsageSyncRequest(reason="sync"), "usage-product-two", admin(db_session))
    assert db_session.query(AiUsageRecord).filter_by(product_usage_id="shared").count() == 2


@pytest.mark.asyncio
async def test_mock_product_token_usage_contract() -> None:
    from tools.mock_product_api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mock-product") as client:
        await client.delete("/mock/state")
        first = await client.get("/v1/admin/token-usage", params={"limit": 2, "scenario": "usage_multiple_pages"})
        assert first.status_code == 200
        payload = first.json()
        assert payload["items"][0]["is_final"] is True
        assert payload["next_cursor"] is not None
        bad = await client.get("/v1/admin/token-usage", params={"scenario": "usage_negative_tokens"})
        assert bad.json()["items"][0]["input_tokens"] < 0
