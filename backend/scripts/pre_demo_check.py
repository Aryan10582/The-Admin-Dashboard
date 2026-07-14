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
