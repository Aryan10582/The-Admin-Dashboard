"""
Pre-manager-demo validation for Admin Dashboard Phase 1-7.

This script uses a disposable local SQLite database and the development-only
mock product API. It does not read or modify the real .env file.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from uuid import UUID
from decimal import Decimal

import httpx
import uvicorn
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _safe_local_url(url: str) -> None:
    lowered = url.lower()
    if not lowered.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("Pre-demo check refuses non-local product URLs")
    if "prod" in lowered or "india" in lowered or "dubai" in lowered:
        raise RuntimeError("Pre-demo check refuses production-looking product URLs")


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def pass_(self, section: str) -> None:
        print(f"PASS {section}")

    def fail(self, section: str, exc: Exception) -> None:
        self.failed = True
        print(f"FAIL {section}: {exc}")


def _start_mock_product_api(port: int):
    from tools.mock_product_api.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                return server, base_url
        except httpx.RequestError:
            time.sleep(0.1)
    raise RuntimeError("Mock product API did not start")


def _api(client: TestClient, method: str, path: str, *, json: dict | None = None, headers: dict | None = None) -> dict:
    response = client.request(method, path, json=json, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} returned {response.status_code}: {response.text[:300]}")
    return response.json()["data"]


def _idem(prefix: str) -> dict[str, str]:
    return {"Idempotency-Key": f"demo-{prefix}-{uuid4()}"}


def run() -> int:
    parser = argparse.ArgumentParser(description="Run a local disposable Admin Dashboard pre-demo validation.")
    parser.add_argument("--keep-db", action="store_true", help="Keep the temporary SQLite DB for inspection.")
    args = parser.parse_args()

    reporter = Reporter()
    tmp = tempfile.TemporaryDirectory()
    engine = None
    db_path = Path(tmp.name) / "admin_pre_demo.sqlite3"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["ADMIN_EMAIL"] = "demo-admin@example.com"
    os.environ["ADMIN_PASSWORD"] = "demo-password"
    os.environ["SESSION_SECRET"] = "pre-demo-session-secret"
    os.environ["PRODUCT_SECRET_ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")
    os.environ["CORS_ORIGINS"] = '["http://localhost:3001"]'
    os.environ["AI_PRICING_MOCK_ADAPTER_ENABLED"] = "true"

    mock_server = None
    try:
        mock_server, mock_url = _start_mock_product_api(_free_port())
        _safe_local_url(mock_url)

        from app.core.database import SessionLocal, engine
        from app.main import create_app, seed_admin
        from app.models import Base
        from app.models.organization import Organization

        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            seed_admin(db)
        client = TestClient(create_app())
        unique = f"demo-{uuid4()}"

        try:
            login = client.post("/api/v1/auth/login", json={"email": "demo-admin@example.com", "password": "demo-password"})
            assert login.status_code == 200
            reporter.pass_("login")
        except Exception as exc:
            reporter.fail("login", exc)
            return 1

        try:
            product = _api(
                client,
                "POST",
                "/api/v1/products",
                json={
                    "product_name": f"{unique}-product",
                    "region": "demo",
                    "environment": "testing",
                    "currency": "USD",
                    "api_base_url": mock_url,
                    "health_check_url": f"{mock_url}/health",
                    "admin_api_version": "v1",
                    "organization_list_path": "/v1/admin/organizations",
                    "organization_detail_path_template": "/v1/admin/organizations/{organization_id}",
                    "token_usage_list_path": "/v1/admin/token-usage",
                    "admin_api_secret": "mock-secret",
                    "is_active": True,
                    "is_under_maintenance": False,
                },
            )
            product_id = product["id"]
            _api(client, "POST", f"/api/v1/products/{product_id}/health-check")
            reporter.pass_("product create/update/health")
        except Exception as exc:
            reporter.fail("product create/update/health", exc)
            return 1

        try:
            discovered = _api(client, "GET", f"/api/v1/products/{product_id}/organizations/discovered")
            if not discovered["items"]:
                raise RuntimeError("No product organizations were discovered")
            imported = _api(
                client,
                "POST",
                f"/api/v1/products/{product_id}/organizations/import",
                json={"product_organization_ids": [discovered["items"][0]["product_organization_id"]]},
            )
            if imported["items"][0]["status"] not in {"imported", "already_mapped"}:
                raise RuntimeError(f"Unexpected import status: {imported['items'][0]['status']}")
            reporter.pass_("product organization discovery/import")
        except Exception as exc:
            reporter.fail("product organization discovery/import", exc)
            return 1

        try:
            org = _api(
                client,
                "POST",
                "/api/v1/organizations",
                json={
                    "central_organization_id": unique,
                    "name": f"{unique} Clinic",
                    "product_deployment_id": product_id,
                    "currency": "USD",
                    "lifecycle_status": "trial",
                    "billing_mode": "prepaid_credits",
                    "billing_calculation_status": "active",
                    "credit_status": "healthy_balance",
                    "service_status": "running",
                    "sync_status": "pending",
                },
            )
            org_id = org["id"]
            _api(client, "GET", "/api/v1/organizations", json=None)
            _api(client, "PATCH", f"/api/v1/organizations/{org_id}/mapping", json={"product_organization_id": "prod-demo-org"})
            _api(client, "POST", f"/api/v1/organizations/{org_id}/verify-mapping")
            reporter.pass_("organization and mapping")
        except Exception as exc:
            reporter.fail("organization and mapping", exc)
            return 1

        try:
            plan = _api(
                client,
                "POST",
                "/api/v1/plans",
                json={
                    "plan_code": f"{unique}_starter",
                    "name": f"{unique} Starter",
                    "description": "Pre-demo plan",
                    "product_deployment_id": product_id,
                    "currency": "USD",
                },
            )
            version_one = _api(
                client,
                "POST",
                f"/api/v1/plans/{plan['id']}/versions",
                json={
                    "currency": "USD",
                    "billing_mode_compatibility": "prepaid_credits",
                    "base_price": "49.00",
                    "pricing_structure": {"type": "flat_monthly"},
                    "limits": {"users": 3},
                    "included_tokens": 1000,
                    "included_leads": 25,
                    "overage_pricing": {"lead": "2.00"},
                    "effective_from": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                    "effective_to": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                    "reason": "pre-demo v1",
                },
            )
            version_two = _api(
                client,
                "POST",
                f"/api/v1/plans/{plan['id']}/versions",
                json={
                    "currency": "USD",
                    "billing_mode_compatibility": "prepaid_credits",
                    "base_price": "79.00",
                    "pricing_structure": {"type": "flat_monthly"},
                    "limits": {"users": 8},
                    "included_tokens": 2500,
                    "included_leads": 50,
                    "overage_pricing": {"lead": "1.50"},
                    "effective_from": (datetime.now(timezone.utc) + timedelta(days=40)).isoformat(),
                    "reason": "pre-demo v2",
                },
            )
            if version_one["price"] != "49.00" or version_two["version_number"] != 2:
                raise RuntimeError("Plan versions did not preserve immutable v1 and generated v2")
            assignment = _api(
                client,
                "POST",
                f"/api/v1/organizations/{org_id}/plan-assignment",
                json={"billing_plan_version_id": version_one["id"], "reason": "pre-demo assign plan"},
                headers=_idem("plan"),
            )
            before_confirm = _api(client, "GET", f"/api/v1/organizations/{org_id}/plan-assignment")
            if before_confirm["current_intended"]["product_confirmation_status"] != "pending":
                raise RuntimeError("Plan assignment was incorrectly product-confirmed before delivery")
            sync_result = _api(client, "POST", f"/api/v1/organizations/{org_id}/sync")
            after_confirm = _api(client, "GET", f"/api/v1/organizations/{org_id}/plan-assignment")
            history = _api(client, "GET", f"/api/v1/organizations/{org_id}/plan-assignment-history")
            if after_confirm["current_intended"]["product_confirmation_status"] != "confirmed" or not history:
                raise RuntimeError(f"Plan assignment did not confirm through pending-change delivery: {sync_result}")
            if assignment["assignment"]["billing_plan_version_id"] != version_one["id"]:
                raise RuntimeError("Assignment did not store the exact version")
            reporter.pass_("billing plans versions assignment and delivery")
        except Exception as exc:
            reporter.fail("billing plans versions assignment and delivery", exc)
            return 1

        try:
            _api(client, "POST", f"/api/v1/organizations/{org_id}/credits/add", json={"amount": "20.00", "currency": "USD", "reason": "pre-demo add"}, headers=_idem("add"))
            _api(client, "POST", f"/api/v1/organizations/{org_id}/credits/deduct", json={"amount": "5.00", "currency": "USD", "reason": "pre-demo deduct"}, headers=_idem("deduct"))
            _api(client, "GET", f"/api/v1/organizations/{org_id}/ledger")
            reporter.pass_("billing credits and ledger")
        except Exception as exc:
            reporter.fail("billing credits and ledger", exc)
            return 1

        try:
            # Seed outstanding dues directly in the disposable DB so the manual-payment endpoint can be exercised.
            from app.core.enums import BillingMode
            from app.core.database import SessionLocal

            with SessionLocal() as db:
                organization = db.get(Organization, UUID(org_id))
                organization.billing_mode = BillingMode.postpaid_manual_settlement
                organization.outstanding_dues = Decimal("12.00")
                db.commit()
            _api(client, "POST", f"/api/v1/organizations/{org_id}/manual-payment", json={"amount": "12.00", "currency": "USD", "reason": "pre-demo payment"}, headers=_idem("payment"))
            reporter.pass_("manual payment")
        except Exception as exc:
            reporter.fail("manual payment", exc)
            return 1

        try:
            from app.core.enums import BillingMode
            from app.core.database import SessionLocal

            with SessionLocal() as db:
                organization = db.get(Organization, UUID(org_id))
                organization.billing_mode = BillingMode.prepaid_credits
                db.commit()
            _api(client, "POST", f"/api/v1/organizations/{org_id}/service/pause", json={"reason": "pre-demo pause"}, headers=_idem("pause"))
            pending = _api(client, "GET", "/api/v1/pending-changes")
            if not pending["items"]:
                raise RuntimeError("No pending changes were created")
            reporter.pass_("service and pending changes")
        except Exception as exc:
            reporter.fail("service and pending changes", exc)
            return 1

        try:
            sync_result = _api(client, "POST", f"/api/v1/products/{product_id}/sync")
            _api(client, "GET", "/api/v1/sync/status")
            _api(client, "GET", "/api/v1/failures")
            if "results" not in sync_result:
                raise RuntimeError("Product sync did not return per-change results")
            reporter.pass_("delivery sync status and failures")
        except Exception as exc:
            reporter.fail("delivery sync status and failures", exc)
            return 1

        try:
            pricing_catalog = _api(
                client,
                "POST",
                "/api/v1/ai/pricing",
                json={
                    "provider": "OpenAI",
                    "provider_model_id": f"gpt-demo-{unique}",
                    "display_name": f"{unique} GPT Demo",
                    "pricing_scope_code": "standard",
                    "currency": "USD",
                    "description": "Pre-demo manual AI pricing",
                    "reason": "pre-demo pricing catalog",
                },
                headers=_idem("ai-pricing-catalog"),
            )
            pricing_start = datetime.now(timezone.utc) - timedelta(days=10)
            pricing_v1 = _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/{pricing_catalog['id']}/versions",
                json={
                    "input_token_price": "2.50000000",
                    "output_token_price": "10.00000000",
                    "pricing_unit_tokens": 1000000,
                    "effective_from": pricing_start.isoformat(),
                    "reason": "pre-demo pricing v1",
                },
                headers=_idem("ai-pricing-v1"),
            )
            pricing_v2 = _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/{pricing_catalog['id']}/versions",
                json={
                    "input_token_price": "3.00000000",
                    "output_token_price": "12.00000000",
                    "pricing_unit_tokens": 1000000,
                    "effective_from": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
                    "reason": "pre-demo pricing v2",
                },
                headers=_idem("ai-pricing-v2"),
            )
            overlap = client.post(
                f"/api/v1/ai/pricing/{pricing_catalog['id']}/versions",
                json={
                    "input_token_price": "1.00000000",
                    "output_token_price": "1.00000000",
                    "pricing_unit_tokens": 1000,
                    "effective_from": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
                    "reason": "pre-demo overlap",
                },
                headers=_idem("ai-pricing-overlap"),
            )
            history = _api(client, "GET", f"/api/v1/ai/pricing/{pricing_catalog['id']}/versions")
            listing = _api(client, "GET", "/api/v1/ai/pricing")
            if pricing_v1["version_number"] != 1 or pricing_v2["version_number"] != 2:
                raise RuntimeError("AI pricing versions did not receive sequential version numbers")
            if pricing_v1["input_token_price"] != "2.50000000":
                raise RuntimeError("AI pricing v1 did not remain unchanged")
            if overlap.status_code != 409:
                raise RuntimeError("AI pricing overlap was not rejected")
            states = {item["effective_state"] for item in history}
            if not {"current", "future"}.issubset(states):
                raise RuntimeError(f"AI pricing history did not show current/future states: {states}")
            if not listing["items"]:
                raise RuntimeError("AI pricing list did not include the created catalog")
            reporter.pass_("ai pricing catalog versions history")
        except Exception as exc:
            reporter.fail("ai pricing catalog versions history", exc)
            return 1

        try:
            mock_pricing_catalog = _api(
                client,
                "POST",
                "/api/v1/ai/pricing",
                json={
                    "provider": "mock-ai",
                    "provider_model_id": "mock-model",
                    "display_name": f"{unique} Mock AI",
                    "pricing_scope_code": "standard",
                    "currency": "USD",
                    "reason": "pre-demo mock pricing catalog",
                },
                headers=_idem("mock-ai-pricing-catalog"),
            )
            _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/{mock_pricing_catalog['id']}/versions",
                json={
                    "input_token_price": "2.50000000",
                    "output_token_price": "10.00000000",
                    "pricing_unit_tokens": 1000000,
                    "effective_from": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                    "reason": "pre-demo mock pricing v1",
                },
                headers=_idem("mock-ai-pricing-v1"),
            )
            unchanged = _api(
                client,
                "POST",
                "/api/v1/ai/pricing/sync-check",
                json={"pricing_catalog_id": mock_pricing_catalog["id"], "adapter_code": "development_mock", "mock_scenario": "unchanged", "reason": "pre-demo unchanged check"},
                headers=_idem("mock-ai-check-unchanged"),
            )
            changed = _api(
                client,
                "POST",
                "/api/v1/ai/pricing/sync-check",
                json={"pricing_catalog_id": mock_pricing_catalog["id"], "adapter_code": "development_mock", "mock_scenario": "duplicate_source_fingerprint", "reason": "pre-demo exact change"},
                headers=_idem("mock-ai-check-change"),
            )
            duplicate = _api(
                client,
                "POST",
                "/api/v1/ai/pricing/sync-check",
                json={"pricing_catalog_id": mock_pricing_catalog["id"], "adapter_code": "development_mock", "mock_scenario": "duplicate_source_fingerprint", "reason": "pre-demo duplicate fingerprint"},
                headers=_idem("mock-ai-check-duplicate"),
            )
            review = _api(
                client,
                "POST",
                "/api/v1/ai/pricing/sync-check",
                json={"pricing_catalog_id": mock_pricing_catalog["id"], "adapter_code": "development_mock", "mock_scenario": "unknown_model", "reason": "pre-demo review"},
                headers=_idem("mock-ai-check-review"),
            )
            # The mock scenario is intentionally review-only; the candidate is corrected here in disposable data to exercise approval.
            from app.models.ai import AIPriceCheckRun
            from app.core.database import SessionLocal

            with SessionLocal() as db:
                run = db.get(AIPriceCheckRun, UUID(review["id"]))
                run.candidate_provider_model_id = "mock-model"
                run.source_effective_at = datetime(2030, 1, 2, tzinfo=timezone.utc)
                run.safe_error = "Pre-demo admin verified model mapping"
                db.commit()
            approved = _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/check-runs/{review['id']}/approve",
                json={"reason": "pre-demo approve candidate"},
                headers=_idem("mock-ai-approve"),
            )
            reject_candidate = _api(
                client,
                "POST",
                "/api/v1/ai/pricing/sync-check",
                json={"pricing_catalog_id": mock_pricing_catalog["id"], "adapter_code": "development_mock", "mock_scenario": "missing_output_price", "reason": "pre-demo reject candidate"},
                headers=_idem("mock-ai-check-reject"),
            )
            rejected = _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/check-runs/{reject_candidate['id']}/reject",
                json={"reason": "pre-demo reject incomplete candidate"},
                headers=_idem("mock-ai-reject"),
            )
            check_history = _api(client, "GET", f"/api/v1/ai/pricing/check-runs?pricing_catalog_id={mock_pricing_catalog['id']}")
            if unchanged["status"] != "unchanged" or changed["status"] != "version_created" or duplicate["status"] != "unchanged":
                raise RuntimeError("Mock pricing check statuses did not match expected unchanged/change/dedupe flow")
            if approved["status"] != "approved" or rejected["status"] != "rejected" or len(check_history["items"]) < 5:
                raise RuntimeError("Mock pricing review history was not preserved")
            reporter.pass_("ai pricing trusted checks and review")
        except Exception as exc:
            reporter.fail("ai pricing trusted checks and review", exc)
            return 1

        try:
            usage_catalog = _api(
                client,
                "POST",
                "/api/v1/ai/pricing",
                json={
                    "provider": "mock-ai",
                    "provider_model_id": f"mock-model-usage-{unique}",
                    "display_name": f"{unique} Mock Usage Model",
                    "pricing_scope_code": "usage-standard",
                    "currency": "USD",
                    "reason": "pre-demo usage pricing catalog",
                },
                headers=_idem("usage-pricing-catalog"),
            )
            old_version = _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/{usage_catalog['id']}/versions",
                json={
                    "input_token_price": "2.00000000",
                    "output_token_price": "8.00000000",
                    "pricing_unit_tokens": 1000,
                    "effective_from": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                    "reason": "pre-demo usage pricing old",
                },
                headers=_idem("usage-pricing-old"),
            )
            current_version = _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/{usage_catalog['id']}/versions",
                json={
                    "input_token_price": "3.00000000",
                    "output_token_price": "9.00000000",
                    "pricing_unit_tokens": 1000,
                    "effective_from": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                    "reason": "pre-demo usage pricing current",
                },
                headers=_idem("usage-pricing-current"),
            )
            _api(
                client,
                "POST",
                f"/api/v1/products/{product_id}/ai-model-mappings",
                json={
                    "product_provider": "mock-ai",
                    "product_model_id": "mock-model",
                    "pricing_catalog_id": usage_catalog["id"],
                    "reason": "pre-demo map product model",
                },
                headers=_idem("usage-model-map"),
            )
            httpx.post(f"{mock_url}/mock/scenario", json={"scenario": "usage_multiple_pages"}, timeout=5).raise_for_status()
            usage_sync_headers = _idem("usage-sync")
            sync_run = _api(
                client,
                "POST",
                f"/api/v1/products/{product_id}/sync/token-usage",
                json={"reason": "pre-demo token usage sync", "limit": 2, "max_pages": 5},
                headers=usage_sync_headers,
            )
            usage_list = _api(client, "GET", f"/api/v1/products/{product_id}/ai-usage")
            usage_state = _api(client, "GET", f"/api/v1/products/{product_id}/ai-usage-sync-state")
            usage_runs = _api(client, "GET", f"/api/v1/products/{product_id}/ai-usage-sync-runs")
            unknown_model_usage = _api(client, "GET", f"/api/v1/ai/usage?product_deployment_id={product_id}&product_usage_id=usage-unknown-model")
            unknown_catalog = _api(
                client,
                "POST",
                "/api/v1/ai/pricing",
                json={
                    "provider": "mock-ai",
                    "provider_model_id": f"mock-unknown-usage-{unique}",
                    "display_name": f"{unique} Mock Unknown Model",
                    "pricing_scope_code": "usage-standard",
                    "currency": "USD",
                    "reason": "pre-demo unknown usage pricing catalog",
                },
                headers=_idem("unknown-usage-catalog"),
            )
            _api(
                client,
                "POST",
                f"/api/v1/ai/pricing/{unknown_catalog['id']}/versions",
                json={
                    "input_token_price": "4.00000000",
                    "output_token_price": "12.00000000",
                    "pricing_unit_tokens": 1000,
                    "effective_from": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                    "reason": "pre-demo unknown usage pricing version",
                },
                headers=_idem("unknown-usage-version"),
            )
            _api(
                client,
                "POST",
                f"/api/v1/products/{product_id}/ai-model-mappings",
                json={
                    "product_provider": "mock-ai",
                    "product_model_id": "mock-unknown",
                    "pricing_catalog_id": unknown_catalog["id"],
                    "reason": "pre-demo map unknown product model",
                },
                headers=_idem("unknown-usage-map"),
            )
            pricing_resolution = _api(
                client,
                "POST",
                "/api/v1/ai/usage/resolve-missing-pricing",
                json={"reason": "pre-demo resolve missing pricing", "product_deployment_id": product_id, "limit": 25},
                headers=_idem("resolve-missing-pricing"),
            )
            unmapped_org = _api(
                client,
                "POST",
                "/api/v1/organizations",
                json={
                    "central_organization_id": f"{unique}-unmapped",
                    "name": f"{unique} Unmapped Clinic",
                    "product_deployment_id": product_id,
                    "currency": "USD",
                    "lifecycle_status": "trial",
                    "billing_mode": "prepaid_credits",
                    "billing_calculation_status": "active",
                    "credit_status": "healthy_balance",
                    "service_status": "running",
                    "sync_status": "pending",
                },
            )
            _api(client, "PATCH", f"/api/v1/organizations/{unmapped_org['id']}/mapping", json={"product_organization_id": "org_unmapped"})
            _api(client, "POST", f"/api/v1/organizations/{unmapped_org['id']}/verify-mapping")
            mapping_resolution = _api(
                client,
                "POST",
                "/api/v1/ai/usage/resolve-mappings",
                json={"reason": "pre-demo resolve missing mapping", "product_deployment_id": product_id, "limit": 25},
                headers=_idem("resolve-missing-mapping"),
            )
            replay = _api(
                client,
                "POST",
                f"/api/v1/products/{product_id}/sync/token-usage",
                json={"reason": "pre-demo token usage sync", "limit": 2, "max_pages": 5},
                headers=usage_sync_headers,
            )
            httpx.post(f"{mock_url}/mock/scenario", json={"scenario": "usage_conflicting_replay"}, timeout=5).raise_for_status()
            conflict_run = _api(
                client,
                "POST",
                f"/api/v1/products/{product_id}/sync/token-usage",
                json={"reason": "pre-demo conflict replay", "limit": 2, "max_pages": 5},
                headers=_idem("usage-conflict"),
            )
            conflict_rows = _api(client, "GET", f"/api/v1/ai/usage?product_deployment_id={product_id}&conflict_status=conflict")
            conflict_detail = _api(client, "GET", f"/api/v1/ai/usage/{conflict_rows['items'][0]['id']}/conflict")
            conflict_review = _api(
                client,
                "POST",
                f"/api/v1/ai/usage/{conflict_rows['items'][0]['id']}/conflict/mark-reviewed",
                json={"reason": "pre-demo reviewed conflict without rewriting usage"},
                headers=_idem("review-usage-conflict"),
            )
            usage_summary = _api(client, "GET", f"/api/v1/ai/usage/summary?product_deployment_id={product_id}")
            version_ids = {item["pricing_version_id"] for item in usage_list["items"] if item["product_usage_id"] in {"usage-old-001", "usage-current-001"}}
            if sync_run["imported_count"] < 4 or sync_run["status"] != "partial_success":
                raise RuntimeError(f"AI usage sync did not preserve unresolved records: {sync_run}")
            if not {old_version["id"], current_version["id"]}.issubset(version_ids):
                raise RuntimeError(f"AI usage historical pricing versions were not selected: {version_ids}")
            if usage_state["product_deployment_id"] != product_id or usage_runs["total"] < 1:
                raise RuntimeError("AI usage sync state/run history was not queryable")
            if replay != sync_run:
                raise RuntimeError("AI usage sync idempotent replay did not return the original response")
            if not unknown_model_usage["items"] or pricing_resolution["resolved"] < 1:
                raise RuntimeError("AI usage missing pricing resolution did not resolve the unknown model")
            if mapping_resolution["resolved"] < 1:
                raise RuntimeError("AI usage missing organization mapping did not resolve")
            if conflict_run["conflict_count"] < 1:
                raise RuntimeError("AI usage conflicting replay was not detected")
            if not conflict_detail["candidate"] or not conflict_review["reviewed"]:
                raise RuntimeError("AI usage conflict review did not preserve candidate and mark reviewed")
            if not usage_summary["finalized_costs_by_currency"]:
                raise RuntimeError("AI usage summary did not return currency-separated finalized costs")
            reporter.pass_("ai usage resolution summary and conflict review")
        except Exception as exc:
            reporter.fail("ai usage resolution summary and conflict review", exc)
            return 1

        try:
            logout = client.post("/api/v1/auth/logout")
            assert logout.status_code == 200
            reporter.pass_("logout")
        except Exception as exc:
            reporter.fail("logout", exc)
            return 1
    finally:
        if mock_server is not None:
            mock_server.should_exit = True
        if engine is not None:
            engine.dispose()
        if not args.keep_db:
            try:
                tmp.cleanup()
            except PermissionError:
                pass

    return 1 if reporter.failed else 0


if __name__ == "__main__":
    sys.exit(run())
