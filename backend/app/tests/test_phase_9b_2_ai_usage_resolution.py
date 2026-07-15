from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.enums import AiUsageConflictStatus, AiUsageMappingResolutionStatus, AiUsagePricingResolutionStatus
from app.models.ai import AiModelPricingVersion, AiUsageRecord
from app.schemas.ai_usage import (
    AIUsageBatchResolveMappingsRequest,
    AIUsageBatchResolvePricingRequest,
    AIUsageConflictReviewRequest,
    AIUsageResolvePricingRequest,
    TokenUsageSyncRequest,
)
from app.services.ai_usage_service import UsageFilters, mark_conflict_reviewed, resolve_missing_mappings, resolve_usage_pricing, summarize_usage, sync_token_usage
from app.services.product_service import product_dependency_summary
from app.tests.test_phase_9b_1_ai_usage import UsageClient, admin, make_catalog_with_versions, make_mapping, make_org_mapping, make_product, usage_item


def login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_exact_mapping_required_then_missing_pricing_resolves_historical_version(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, old_version_id, _new_version_id = make_catalog_with_versions(db_session)
    make_org_mapping(db_session, product)
    old_usage = usage_item(product_usage_id="needs-pricing", usage_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[old_usage]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b2-sync-unpriced", admin(db_session))
    row = db_session.query(AiUsageRecord).filter_by(product_usage_id="needs-pricing").one()
    assert row.total_cost is None
    blocked = resolve_usage_pricing(db_session, row.id, AIUsageResolvePricingRequest(reason="try"), "9b2-resolve-blocked", admin(db_session))
    assert blocked["outcome"] == "mapping_missing"

    make_mapping(db_session, product, catalog)
    resolved = resolve_usage_pricing(db_session, row.id, AIUsageResolvePricingRequest(reason="resolve"), "9b2-resolve-one", admin(db_session))
    assert resolved["outcome"] == "resolved"
    refreshed = db_session.get(AiUsageRecord, row.id)
    assert refreshed.pricing_version_id == old_version_id
    original_cost = refreshed.total_cost
    replay = resolve_usage_pricing(db_session, row.id, AIUsageResolvePricingRequest(reason="resolve"), "9b2-resolve-one", admin(db_session))
    assert replay == resolved
    assert db_session.get(AiUsageRecord, row.id).total_cost == original_cost


@pytest.mark.asyncio
async def test_inactive_mapping_and_wrong_version_remain_unresolved(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, old_version_id, _new_version_id = make_catalog_with_versions(db_session)
    mapping = make_mapping(db_session, product, catalog)
    mapping.is_active = False
    db_session.commit()
    make_org_mapping(db_session, product)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_usage_id="inactive-map")]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b-accept-inactive-sync", admin(db_session))
    row = db_session.query(AiUsageRecord).filter_by(product_usage_id="inactive-map").one()

    result = resolve_usage_pricing(db_session, row.id, AIUsageResolvePricingRequest(reason="resolve", pricing_version_id=old_version_id), "9b-accept-inactive-resolve", admin(db_session))

    assert result["outcome"] == "mapping_inactive"
    assert db_session.get(AiUsageRecord, row.id).total_cost is None


@pytest.mark.asyncio
async def test_historical_version_effective_from_boundary_uses_new_version(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _old_version_id, new_version_id = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    new_version = db_session.get(AiModelPricingVersion, new_version_id)
    boundary = new_version.effective_from
    if boundary.tzinfo is None:
        boundary = boundary.replace(tzinfo=timezone.utc)
    items = [
        usage_item(product_usage_id="at-boundary", usage_at=boundary.isoformat(), finalized_at=boundary.isoformat()),
    ]
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([items]))

    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b-accept-boundary-sync", admin(db_session))

    at = db_session.query(AiUsageRecord).filter_by(product_usage_id="at-boundary").one()
    assert at.pricing_version_id == new_version_id


@pytest.mark.asyncio
async def test_batch_mapping_resolution_links_verified_mapping_without_changing_cost(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    item = usage_item(product_usage_id="unmapped-costed", product_organization_id="org_later")
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[item]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b2-sync-unmapped", admin(db_session))
    row = db_session.query(AiUsageRecord).filter_by(product_usage_id="unmapped-costed").one()
    assert row.total_cost is not None
    original_cost = row.total_cost
    assert row.organization_id is None

    unresolved = resolve_missing_mappings(db_session, AIUsageBatchResolveMappingsRequest(reason="still missing", product_deployment_id=product.id), "9b2-map-missing", admin(db_session))
    assert unresolved["items"][0]["outcome"] == "mapping_missing"
    org = make_org_mapping(db_session, product, "org_later")
    resolved = resolve_missing_mappings(db_session, AIUsageBatchResolveMappingsRequest(reason="resolve", product_deployment_id=product.id), "9b2-map-resolve", admin(db_session))
    assert resolved["resolved"] == 1
    refreshed = db_session.get(AiUsageRecord, row.id)
    assert refreshed.organization_id == org.id
    assert refreshed.mapping_resolution_status == AiUsageMappingResolutionStatus.resolved
    assert refreshed.total_cost == original_cost


@pytest.mark.asyncio
async def test_conflict_review_is_idempotent_and_preserves_original_usage_and_cost(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_usage_id="conflict-me")]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b2-conflict-sync", admin(db_session))
    original = db_session.query(AiUsageRecord).filter_by(product_usage_id="conflict-me").one()
    original_cost = original.total_cost
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_usage_id="conflict-me", input_tokens=9999)]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="conflict"), "9b2-conflict-sync-2", admin(db_session))
    conflicted = db_session.get(AiUsageRecord, original.id)
    assert conflicted.conflict_status == AiUsageConflictStatus.conflict

    reviewed = mark_conflict_reviewed(db_session, original.id, AIUsageConflictReviewRequest(reason="reviewed safely"), "9b2-review-conflict", admin(db_session))
    replay = mark_conflict_reviewed(db_session, original.id, AIUsageConflictReviewRequest(reason="reviewed safely"), "9b2-review-conflict", admin(db_session))
    assert replay == reviewed
    refreshed = db_session.get(AiUsageRecord, original.id)
    assert refreshed.input_tokens == 1000
    assert refreshed.total_cost == original_cost
    assert refreshed.conflict_reviewed_at is not None


@pytest.mark.asyncio
async def test_conflicting_replay_preserves_original_for_changed_identity_fields(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    original_usage_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)
    original = usage_item(product_usage_id="identity-conflict", usage_at=original_usage_at.isoformat())
    changed = usage_item(product_usage_id="identity-conflict", product_organization_id="org_changed", provider="other-ai", product_model_id="other-model", output_tokens=999, usage_at=(original_usage_at + timedelta(minutes=1)).isoformat())
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[original]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b-accept-identity-sync", admin(db_session))
    stored = db_session.query(AiUsageRecord).filter_by(product_usage_id="identity-conflict").one()
    original_snapshot = (stored.product_organization_id, stored.provider, stored.product_model_id, stored.output_tokens, stored.usage_at, stored.total_cost)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[changed]]))

    result = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="conflict"), "9b-accept-identity-conflict", admin(db_session))

    refreshed = db_session.get(AiUsageRecord, stored.id)
    assert result["conflict_count"] == 1
    assert (refreshed.product_organization_id, refreshed.provider, refreshed.product_model_id, refreshed.output_tokens, refreshed.usage_at, refreshed.total_cost) == original_snapshot
    assert refreshed.conflict_snapshot["candidate"]["product_organization_id"] == "org_changed"
    assert refreshed.conflict_snapshot["candidate"]["provider"] == "other-ai"


@pytest.mark.asyncio
async def test_summaries_are_currency_separated_and_unresolved_not_zero_cost(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    items = [usage_item(product_usage_id="priced"), usage_item(product_usage_id="unknown", product_model_id="missing")]
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([items]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b2-summary-sync", admin(db_session))
    summary = summarize_usage(db_session, filters=UsageFilters(product_deployment_id=product.id))
    assert summary.usage_record_count == 2
    assert summary.unpriced_usage_count == 1
    assert summary.finalized_costs_by_currency[0].currency == "USD"
    assert summary.finalized_costs_by_currency[0].total_cost > 0


@pytest.mark.asyncio
async def test_summary_rankings_are_scoped_to_filters(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product_one = make_product(db_session, "Scoped One")
    product_two = make_product(db_session, "Scoped Two")
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product_one, catalog)
    make_mapping(db_session, product_two, catalog)
    make_org_mapping(db_session, product_one)
    make_org_mapping(db_session, product_two)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_usage_id=f"usage-{product.product_name}", input_tokens=1000 if product.id == product_one.id else 9000)]]))
    await sync_token_usage(db_session, product_one.id, TokenUsageSyncRequest(reason="sync"), "9b-accept-scope-one", admin(db_session))
    await sync_token_usage(db_session, product_two.id, TokenUsageSyncRequest(reason="sync"), "9b-accept-scope-two", admin(db_session))

    summary = summarize_usage(db_session, UsageFilters(product_deployment_id=product_one.id))

    assert summary.usage_record_count == 1
    assert all(item.id == product_one.id for item in summary.highest_cost_products)


@pytest.mark.asyncio
async def test_duplicate_items_in_one_sync_create_one_row_and_one_cost(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    item = usage_item(product_usage_id="duplicate-in-page")
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[item, item]]))

    result = await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b-accept-duplicate-page", admin(db_session))

    rows = db_session.query(AiUsageRecord).filter_by(product_usage_id="duplicate-in-page").all()
    assert len(rows) == 1
    assert result["imported_count"] == 1
    assert result["unchanged_count"] == 1
    assert rows[0].total_cost is not None


@pytest.mark.asyncio
async def test_product_dependency_summary_counts_ai_usage_resolution_and_conflicts(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    product = make_product(db_session)
    catalog, _, _ = make_catalog_with_versions(db_session)
    make_mapping(db_session, product, catalog)
    make_org_mapping(db_session, product)
    monkeypatch.setattr("app.services.ai_usage_service.build_product_client", lambda product, api_secret=None: UsageClient([[usage_item(product_usage_id="dependency")]]))
    await sync_token_usage(db_session, product.id, TokenUsageSyncRequest(reason="sync"), "9b2-dep-sync", admin(db_session))
    summary = product_dependency_summary(db_session, product.id)
    assert summary["ai_usage_records"] == 1
    assert summary["ai_usage_finalized"] == 1
    assert summary["ai_model_pricing_mappings"] == 1
