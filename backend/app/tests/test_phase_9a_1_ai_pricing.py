from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.models.admin import Admin
from app.models.ai import AiModelPricingCatalog, AiModelPricingVersion
from app.models.audit import AuditLog
from app.models.idempotency import IdempotencyRecord
from app.schemas.ai_pricing import AiPricingCatalogCreate, AiPricingVersionCreate
from app.services.ai_pricing_catalog_service import create_pricing_catalog, create_pricing_version, get_pricing_catalog, list_pricing_versions


def admin(db: Session) -> Admin:
    return db.scalar(select(Admin))  # type: ignore[return-value]


def catalog_payload(**overrides):
    data = {
        "provider": "OpenAI",
        "provider_model_id": "gpt-5.1",
        "display_name": "GPT 5.1 Standard",
        "pricing_scope_code": "Standard",
        "currency": "usd",
        "description": "manual price",
        "reason": "create catalog",
    }
    data.update(overrides)
    return AiPricingCatalogCreate(**data)


def version_payload(start: datetime, **overrides):
    data = {
        "input_token_price": Decimal("2.50000000"),
        "output_token_price": Decimal("10.00000000"),
        "pricing_unit_tokens": 1_000_000,
        "effective_from": start,
        "effective_to": None,
        "source_reference": "manual sheet",
        "reason": "manual version",
    }
    data.update(overrides)
    return AiPricingVersionCreate(**data)


def create_catalog(db: Session, admin_model: Admin, key: str = "catalog-key"):
    result = create_pricing_catalog(db, catalog_payload(), key, admin_model)
    assert isinstance(result, dict)
    return db.get(AiModelPricingCatalog, UUID(result["id"]))


def test_create_pricing_catalog_identity_normalizes_and_rejects_duplicate(db_session: Session) -> None:
    catalog = create_catalog(db_session, admin(db_session))
    assert catalog is not None
    assert catalog.provider == "openai"
    assert catalog.provider_model_id == "gpt-5.1"
    assert catalog.pricing_scope_code == "standard"
    assert catalog.currency == "USD"

    duplicate = catalog_payload(display_name="Duplicate display name")
    with pytest.raises(Exception) as exc:
        create_pricing_catalog(db_session, duplicate, "catalog-duplicate", admin(db_session))
    assert "already exists" in str(exc.value)

    other_scope = create_pricing_catalog(db_session, catalog_payload(pricing_scope_code="batch"), "catalog-batch", admin(db_session))
    assert isinstance(other_scope, dict)


def test_pricing_unit_is_version_identity_not_catalog_identity(db_session: Session) -> None:
    catalog = create_catalog(db_session, admin(db_session))
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    v1 = create_pricing_version(db_session, catalog.id, version_payload(start, pricing_unit_tokens=1_000_000), "version-1", admin(db_session))
    v2 = create_pricing_version(
        db_session,
        catalog.id,
        version_payload(start + timedelta(days=31), input_token_price=Decimal("0.00250000"), output_token_price=Decimal("0.01000000"), pricing_unit_tokens=1000),
        "version-2",
        admin(db_session),
    )
    assert isinstance(v1, dict)
    assert isinstance(v2, dict)
    assert db_session.scalar(select(AiModelPricingCatalog).where(AiModelPricingCatalog.provider == "openai")).id == catalog.id
    assert v1["version_number"] == 1
    assert v2["version_number"] == 2


def test_version_immutability_effective_dates_and_current_resolution(db_session: Session) -> None:
    catalog = create_catalog(db_session, admin(db_session))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    v1 = create_pricing_version(db_session, catalog.id, version_payload(start, effective_to=datetime(2026, 7, 1, tzinfo=timezone.utc)), "v1", admin(db_session))
    v2 = create_pricing_version(db_session, catalog.id, version_payload(datetime(2026, 7, 1, tzinfo=timezone.utc)), "v2", admin(db_session))
    assert isinstance(v1, dict)
    assert isinstance(v2, dict)
    stored_v1 = db_session.get(AiModelPricingVersion, UUID(v1["id"]))
    assert stored_v1.input_token_cost == Decimal("2.50000000")
    assert stored_v1.effective_to.replace(tzinfo=timezone.utc) == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert get_pricing_catalog(db_session, catalog.id).latest_version.version_number == 2

    with pytest.raises(Exception) as exc:
        create_pricing_version(db_session, catalog.id, version_payload(datetime(2026, 6, 1, tzinfo=timezone.utc)), "overlap", admin(db_session))
    assert "overlaps" in str(exc.value)


def test_open_ended_transition_closes_previous_once(db_session: Session) -> None:
    catalog = create_catalog(db_session, admin(db_session))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    v1 = create_pricing_version(db_session, catalog.id, version_payload(start), "open-v1", admin(db_session))
    v2_start = start + timedelta(days=30)
    v2 = create_pricing_version(db_session, catalog.id, version_payload(v2_start), "open-v2", admin(db_session))
    assert isinstance(v1, dict)
    assert isinstance(v2, dict)
    stored_v1 = db_session.get(AiModelPricingVersion, UUID(v1["id"]))
    assert stored_v1.effective_to.replace(tzinfo=timezone.utc) == v2_start
    versions = list_pricing_versions(db_session, catalog.id)
    assert [version.version_number for version in versions] == [2, 1]


def test_utc_required_and_invalid_prices_units_rejected() -> None:
    with pytest.raises(ValueError):
        version_payload(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        version_payload(datetime(2026, 1, 1, tzinfo=timezone.utc), input_token_price=Decimal("-0.1"))
    with pytest.raises(ValueError):
        version_payload(datetime(2026, 1, 1, tzinfo=timezone.utc), pricing_unit_tokens=0)


def test_idempotent_catalog_and_version_replay_without_duplicate_audit(db_session: Session) -> None:
    admin_model = admin(db_session)
    first = create_pricing_catalog(db_session, catalog_payload(), "idem-catalog", admin_model)
    replay = create_pricing_catalog(db_session, catalog_payload(), "idem-catalog", admin_model)
    assert first == replay
    assert db_session.query(AiModelPricingCatalog).count() == 1

    catalog = db_session.get(AiModelPricingCatalog, UUID(first["id"]))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    v1 = create_pricing_version(db_session, catalog.id, version_payload(start), "idem-version", admin_model)
    v1_replay = create_pricing_version(db_session, catalog.id, version_payload(start), "idem-version", admin_model)
    assert v1 == v1_replay
    assert db_session.query(AiModelPricingVersion).filter(AiModelPricingVersion.pricing_catalog_id == catalog.id).count() == 1
    assert db_session.query(AuditLog).filter(AuditLog.action == "ai_pricing_version.created").count() == 1
    assert db_session.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == "idem-version").one().status.value == "completed"


def test_same_idempotency_key_different_body_conflicts(db_session: Session) -> None:
    admin_model = admin(db_session)
    create_pricing_catalog(db_session, catalog_payload(), "same-key", admin_model)
    with pytest.raises(Exception) as exc:
        create_pricing_catalog(db_session, catalog_payload(provider_model_id="gpt-other"), "same-key", admin_model)
    assert "different pricing request" in str(exc.value)


def test_authentication_required_for_pricing_endpoints(client) -> None:
    response = client.get("/api/v1/ai/pricing")
    assert response.status_code == 401


def test_api_create_and_list_do_not_expose_secrets(client) -> None:
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert login.status_code == 200
    response = client.post(
        "/api/v1/ai/pricing",
        json=catalog_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": "api-catalog"},
    )
    assert response.status_code == 201
    body = response.text.lower()
    assert "secret" not in body
    listed = client.get("/api/v1/ai/pricing")
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["current_effective_version"] is None


def _postgres_url() -> str | None:
    url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if not url:
        return None
    lowered = url.lower()
    if any(marker in lowered for marker in ("prod", "production", "render.com", "amazonaws.com", "azure.com")):
        return None
    return url


def test_postgres_concurrent_pricing_version_creation_is_serialized() -> None:
    url = _postgres_url()
    if not url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL not configured for disposable PostgreSQL concurrency test")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        admin_model = Admin(email=f"{uuid4()}@example.com", username="pg-admin", password_hash="hash", is_active=True)
        db.add(admin_model)
        db.commit()
        db.refresh(admin_model)
        catalog = create_catalog(db, admin_model, "pg-catalog")
        catalog_id = catalog.id
        admin_id = admin_model.id

    errors: list[str] = []

    def worker(key: str) -> None:
        with SessionLocal() as db:
            try:
                admin_model = db.get(Admin, admin_id)
                create_pricing_version(db, catalog_id, version_payload(datetime(2026, 1, 1, tzinfo=timezone.utc)), key, admin_model)
            except Exception as exc:  # noqa: BLE001 - test records conflict outcome
                errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(f"pg-version-{idx}",)) for idx in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as db:
        versions = list(db.scalars(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == catalog_id)))
        assert len(versions) == 1
        assert versions[0].version_number == 1
    assert errors
