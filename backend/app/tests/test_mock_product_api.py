import pytest
from httpx import ASGITransport, AsyncClient

from tools.mock_product_api.main import app


@pytest.mark.asyncio
async def test_mock_product_confirmed_delivery_and_status_replay() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mock-product") as client:
        await client.delete("/mock/state")
        payload = {
            "product_organization_id": "prod-demo-org",
            "action": "credits.add",
            "payload": {"amount": "10.00"},
            "idempotency_key": "demo-key",
            "admin_id": "admin",
            "reason": "demo",
        }
        delivered = await client.post("/v1/admin/pending-changes", json=payload)
        replayed = await client.get("/v1/admin/pending-changes/demo-key")

    assert delivered.status_code == 200
    assert replayed.status_code == 200
    assert delivered.json()["sync_confirmed"] is True
    assert replayed.json()["idempotency_key"] == "demo-key"
    assert replayed.json()["from_status_lookup"] is True


@pytest.mark.asyncio
async def test_mock_product_scenarios_cover_ambiguous_and_rejected_results() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mock-product") as client:
        await client.delete("/mock/state")
        await client.post("/mock/scenario", json={"scenario": "ambiguous_2xx"})
        ambiguous = await client.post("/v1/admin/pending-changes", json={"idempotency_key": "ambiguous", "action": "credits.add"})
        await client.post("/mock/scenario", json={"scenario": "product_rejection"})
        rejected = await client.post("/v1/admin/pending-changes", json={"idempotency_key": "rejected", "action": "credits.add"})

    assert ambiguous.status_code == 200
    assert "sync_confirmed" not in ambiguous.json()
    assert rejected.status_code == 200
    assert rejected.json()["success"] is False
    assert rejected.json()["error_code"] == "product_rejection"


@pytest.mark.asyncio
async def test_mock_product_organization_lookup_scenarios() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mock-product") as client:
        await client.delete("/mock/state")
        ok = await client.get("/v1/organizations/prod-demo-org")
        await client.post("/mock/scenario", json={"scenario": "organization_not_found"})
        missing = await client.get("/v1/organizations/prod-demo-org")

    assert ok.status_code == 200
    assert ok.json()["product_organization_id"] == "prod-demo-org"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_mock_product_lists_product_organizations_with_pagination_and_scenarios() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mock-product") as client:
        await client.delete("/mock/state")
        first_page = await client.get("/v1/admin/organizations", params={"limit": 2})
        second_page = await client.get("/v1/admin/organizations", params={"limit": 2, "cursor": first_page.json()["next_cursor"]})

        await client.post("/mock/scenario", json={"scenario": "empty_organizations"})
        empty = await client.get("/v1/admin/organizations")

        await client.post("/mock/scenario", json={"scenario": "malformed_organizations"})
        malformed = await client.get("/v1/admin/organizations")

    assert first_page.status_code == 200
    assert [item["product_organization_id"] for item in first_page.json()["items"]] == ["org_101", "org_205"]
    assert first_page.json()["has_more"] is True
    assert first_page.json()["next_cursor"] == "2"
    assert second_page.status_code == 200
    assert [item["product_organization_id"] for item in second_page.json()["items"]] == ["org_309"]
    assert second_page.json()["has_more"] is False
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert malformed.status_code == 200
    assert "product_organization_id" not in malformed.json()["items"][0]
