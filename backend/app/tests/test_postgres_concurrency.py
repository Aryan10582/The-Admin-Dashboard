import asyncio
import os
import threading
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.enums import (
    BillingCalculationStatus,
    BillingMode,
    CreditStatus,
    Environment,
    MappingStatus,
    OrganizationLifecycleStatus,
    PendingChangeStatus,
    ProductHealthStatus,
    ServiceStatus,
    SyncStatus,
)
from app.core.product_secrets import encrypt_product_secret
from app.integrations.product_admin_client import ProductDeliveryResult
from app.models import Base
from app.models.admin import Admin
from app.models.organization import Organization, OrganizationMapping
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.services.sync_service import deliver_pending_change


POSTGRES_TEST_DATABASE_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")


def _require_postgres_url() -> str:
    if not POSTGRES_TEST_DATABASE_URL:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not configured; skipping PostgreSQL concurrency tests")
    lowered = POSTGRES_TEST_DATABASE_URL.lower()
    if not lowered.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not a PostgreSQL URL")
    if "test" not in lowered and "demo" not in lowered:
        pytest.skip("POSTGRES_TEST_DATABASE_URL must clearly identify a disposable test/demo database")
    return POSTGRES_TEST_DATABASE_URL


@pytest.fixture()
def pg_sessionmaker():
    engine = create_engine(_require_postgres_url(), pool_pre_ping=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        yield SessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_pending_delivery(SessionLocal):
    with SessionLocal() as db:
        admin = Admin(email=f"pg-{uuid4()}@example.com", username="pg-admin", password_hash="hash", is_active=True)
        product = ProductDeployment(
            product_name="PG Demo Product",
            region="test",
            environment=Environment.testing,
            currency="USD",
            api_base_url="https://mock-product.test",
            health_check_url="https://mock-product.test/health",
            admin_api_version="v1",
            admin_api_secret_encrypted=encrypt_product_secret("product-secret"),
            supported_endpoints={"pending_changes": {"idempotent_writes": True}},
            is_active=True,
            is_under_maintenance=False,
            health_status=ProductHealthStatus.healthy,
            sync_status=SyncStatus.pending,
        )
        db.add_all([admin, product])
        db.flush()
        organization = Organization(
            central_organization_id=f"pg-org-{uuid4()}",
            name="PG Demo Org",
            product_deployment_id=product.id,
            currency="USD",
            lifecycle_status=OrganizationLifecycleStatus.active,
            billing_mode=BillingMode.prepaid_credits,
            billing_calculation_status=BillingCalculationStatus.active,
            credit_status=CreditStatus.healthy_balance,
            service_status=ServiceStatus.running,
            service_enforcement_status=ServiceStatus.running,
            credit_balance=Decimal("10.00"),
            outstanding_dues=Decimal("0.00"),
            sync_status=SyncStatus.pending,
        )
        db.add(organization)
        db.flush()
        mapping = OrganizationMapping(
            organization_id=organization.id,
            product_deployment_id=product.id,
            product_organization_id="pg-prod-org",
            product_api_version="v1",
            mapping_status=MappingStatus.active,
        )
        change = PendingProductChange(
            action="credits.add",
            payload={"amount": "1.00", "currency": "USD"},
            organization_id=organization.id,
            product_deployment_id=product.id,
            status=PendingChangeStatus.saved,
            idempotency_key="pg-original-key",
            retry_count=0,
            reason="pg concurrency",
            admin_id=admin.id,
        )
        db.add_all([mapping, change])
        db.commit()
        return admin.id, change.id


def test_postgres_two_concurrent_retries_make_one_product_call(pg_sessionmaker, monkeypatch) -> None:
    admin_id, change_id = _seed_pending_delivery(pg_sessionmaker)
    call_count = 0
    call_lock = threading.Lock()
    release = threading.Event()

    class SlowProductClient:
        async def deliver_pending_change(self, **kwargs):
            nonlocal call_count
            with call_lock:
                call_count += 1
            release.wait(timeout=5)
            return ProductDeliveryResult(
                success=True,
                product_organization_id=kwargs["product_organization_id"],
                applied_change=kwargs["action"],
                product_api_version="v1",
                sync_confirmed=True,
                product_request_id="pg-request",
                idempotency_key=kwargs["idempotency_key"],
            )

    monkeypatch.setattr("app.services.sync_service.build_product_client", lambda product, api_secret=None: SlowProductClient())
    results: list[str] = []
    errors: list[str] = []

    def run_delivery(name: str) -> None:
        with pg_sessionmaker() as db:
            admin = db.get(Admin, admin_id)
            try:
                result = asyncio.run(deliver_pending_change(db, change_id, admin, retry_reason=name, retry_request_idempotency_key=f"pg-retry-{name}"))
                results.append(result["status"])
            except Exception as exc:
                errors.append(str(exc))

    first = threading.Thread(target=run_delivery, args=("one",))
    second = threading.Thread(target=run_delivery, args=("two",))
    first.start()
    second.start()
    deadline = time.monotonic() + 5
    while call_count == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    release.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert call_count == 1
    assert results == ["confirmed_and_synced"]
    assert errors
