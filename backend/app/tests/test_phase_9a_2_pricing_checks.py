from datetime import datetime, timezone, timedelta
from decimal import Decimal
import os
import threading
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.enums import AiPriceCheckStatus, AuditResultStatus, IdempotencyRecordStatus, PricingCreatedBy
from app.integrations.ai_pricing_adapters import DevelopmentMockPricingAdapter, get_trusted_pricing_adapter
from app.models import Base
from app.models.admin import Admin
from app.models.ai import AIPriceCheckRun, AiModelPricingCatalog, AiModelPricingVersion
from app.models.audit import AuditLog
from app.models.idempotency import IdempotencyRecord
from app.schemas.ai_pricing import AiPriceCheckReviewRequest, AiPricingCatalogCreate, AiPricingSyncCheckRequest, AiPricingVersionCreate
from app.services.ai_pricing_catalog_service import create_pricing_catalog, create_pricing_version
from app.services.ai_pricing_check_service import get_check_run, approve_check_run, reject_check_run, run_pricing_sync_check


def admin(db: Session) -> Admin:
    return db.scalar(select(Admin))  # type: ignore[return-value]


def make_catalog(db: Session, provider: str = "mock-ai") -> AiModelPricingCatalog:
    result = create_pricing_catalog(
        db,
        AiPricingCatalogCreate(
            provider=provider,
            provider_model_id="mock-model",
            display_name="Mock Model",
            pricing_scope_code="standard",
            currency="USD",
            reason="create mock catalog",
        ),
        f"catalog-{provider}",
        admin(db),
    )
    assert isinstance(result, dict)
    catalog = db.get(AiModelPricingCatalog, UUID(result["id"]))
    assert catalog is not None
    return catalog


def seed_version(db: Session, catalog: AiModelPricingCatalog, *, input_price: str = "2.50000000", output_price: str = "10.00000000") -> AiModelPricingVersion:
    result = create_pricing_version(
        db,
        catalog.id,
        AiPricingVersionCreate(
            input_token_price=Decimal(input_price),
            output_token_price=Decimal(output_price),
            pricing_unit_tokens=1000000,
            effective_from=datetime.now(timezone.utc) - timedelta(days=1),
            reason="seed manual version",
        ),
        f"version-{input_price}-{output_price}",
        admin(db),
    )
    assert isinstance(result, dict)
    version = db.get(AiModelPricingVersion, UUID(result["id"]))
    assert version is not None
    return version


def check_payload(catalog: AiModelPricingCatalog, scenario: str) -> AiPricingSyncCheckRequest:
    return AiPricingSyncCheckRequest(pricing_catalog_id=catalog.id, adapter_code="development_mock", mock_scenario=scenario, reason=f"check {scenario}")


def test_check_run_persisted_and_idempotent_replay(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    seed_version(db_session, catalog)
    first = run_pricing_sync_check(db_session, check_payload(catalog, "unchanged"), "check-unchanged", admin(db_session))
    replay = run_pricing_sync_check(db_session, check_payload(catalog, "unchanged"), "check-unchanged", admin(db_session))
    assert first == replay
    assert first["status"] == AiPriceCheckStatus.unchanged.value
    assert db_session.query(AIPriceCheckRun).count() == 1
    assert db_session.query(AiModelPricingVersion).count() == 1
    assert db_session.query(AuditLog).filter(AuditLog.action == "ai_pricing_check.unchanged").count() == 1


def test_same_key_different_check_body_conflicts(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    seed_version(db_session, catalog)
    run_pricing_sync_check(db_session, check_payload(catalog, "unchanged"), "check-conflict", admin(db_session))
    with pytest.raises(Exception) as exc:
        run_pricing_sync_check(db_session, check_payload(catalog, "input_price_changed"), "check-conflict", admin(db_session))
    assert "different pricing check request" in str(exc.value)


def test_exact_trusted_change_creates_one_system_version_and_dedupes_fingerprint(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    v1 = seed_version(db_session, catalog)
    result = run_pricing_sync_check(db_session, check_payload(catalog, "duplicate_source_fingerprint"), "check-change", admin(db_session))
    assert result["status"] == AiPriceCheckStatus.version_created.value
    versions = db_session.query(AiModelPricingVersion).order_by(AiModelPricingVersion.version_number).all()
    assert len(versions) == 2
    assert versions[0].id == v1.id
    assert versions[0].input_token_cost == Decimal("2.50000000")
    assert versions[0].effective_to is not None
    assert versions[1].created_by == PricingCreatedBy.system
    assert versions[1].source_fingerprint == result["source_fingerprint"]

    second = run_pricing_sync_check(db_session, check_payload(catalog, "duplicate_source_fingerprint"), "check-change-duplicate-fingerprint", admin(db_session))
    assert second["status"] == AiPriceCheckStatus.unchanged.value
    assert db_session.query(AiModelPricingVersion).count() == 2


def test_manual_review_candidates_persist_without_changing_current_version(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    seed_version(db_session, catalog)
    missing_currency = run_pricing_sync_check(db_session, check_payload(catalog, "missing_currency"), "check-missing-currency", admin(db_session))
    missing_unit = run_pricing_sync_check(db_session, check_payload(catalog, "missing_pricing_unit"), "check-missing-unit", admin(db_session))
    missing_input = run_pricing_sync_check(db_session, check_payload(catalog, "missing_input_price"), "check-missing-input", admin(db_session))
    missing_output = run_pricing_sync_check(db_session, check_payload(catalog, "missing_output_price"), "check-missing-output", admin(db_session))
    ambiguous = run_pricing_sync_check(db_session, check_payload(catalog, "contradictory_duplicate_entries"), "check-ambiguous", admin(db_session))
    assert {missing_currency["status"], missing_unit["status"], missing_input["status"], missing_output["status"], ambiguous["status"]} == {AiPriceCheckStatus.requires_manual_review.value}
    assert db_session.query(AIPriceCheckRun).count() == 5
    assert db_session.query(AiModelPricingVersion).count() == 1
    assert db_session.query(AIPriceCheckRun).filter(AIPriceCheckRun.candidate_input_price.is_not(None)).count() >= 1


def test_approval_creates_version_and_rejection_preserves_candidate(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    seed_version(db_session, catalog)
    review = run_pricing_sync_check(db_session, check_payload(catalog, "unknown_model"), "check-review", admin(db_session))
    run = db_session.get(AIPriceCheckRun, UUID(review["id"]))
    run.candidate_provider_model_id = catalog.provider_model_id
    run.safe_error = "Admin verified source model mapping"
    db_session.commit()

    approved = approve_check_run(db_session, run.id, AiPriceCheckReviewRequest(reason="approve verified candidate"), "approve-key", admin(db_session))
    replay = approve_check_run(db_session, run.id, AiPriceCheckReviewRequest(reason="approve verified candidate"), "approve-key", admin(db_session))
    assert approved == replay
    assert approved["status"] == AiPriceCheckStatus.approved.value
    assert approved["created_version_id"] is not None
    assert db_session.query(AiModelPricingVersion).count() == 2

    review_two = run_pricing_sync_check(db_session, check_payload(catalog, "missing_output_price"), "check-reject", admin(db_session))
    rejected = reject_check_run(db_session, UUID(review_two["id"]), AiPriceCheckReviewRequest(reason="reject incomplete candidate"), "reject-key", admin(db_session))
    assert rejected["status"] == AiPriceCheckStatus.rejected.value
    stored = db_session.get(AIPriceCheckRun, UUID(review_two["id"]))
    assert stored.candidate_input_price is not None
    assert stored.created_version_id is None


def test_adapter_exception_finalizes_failed_check_and_idempotency(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = make_catalog(db_session)
    seed_version(db_session, catalog)

    class FailingAdapter:
        def fetch_pricing(self, **kwargs):
            raise RuntimeError("secret provider stack trace should not escape")

    monkeypatch.setattr("app.services.ai_pricing_check_service.get_trusted_pricing_adapter", lambda adapter_code, provider: FailingAdapter())
    result = run_pricing_sync_check(db_session, check_payload(catalog, "unchanged"), "check-adapter-exception", admin(db_session))
    replay = run_pricing_sync_check(db_session, check_payload(catalog, "unchanged"), "check-adapter-exception", admin(db_session))
    assert result == replay
    assert result["status"] == AiPriceCheckStatus.failed.value
    assert result["safe_error"] == "Trusted pricing adapter failed"
    assert "secret provider" not in str(result)
    assert db_session.query(AIPriceCheckRun).count() == 1
    assert db_session.query(AuditLog).filter(AuditLog.result_status == AuditResultStatus.failure).count() == 1
    record = db_session.query(IdempotencyRecord).filter_by(idempotency_key="check-adapter-exception").one()
    assert record.status.value == "completed"


def test_stale_running_check_is_finalized_without_adapter_replay(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    run = AIPriceCheckRun(
        pricing_catalog_id=catalog.id,
        provider=catalog.provider,
        pricing_scope_code=catalog.pricing_scope_code,
        started_at=started_at,
        requested_by_admin_id=admin(db_session).id,
        reason="stale check",
        request_idempotency_key="stale-check",
        status=AiPriceCheckStatus.running,
    )
    record = IdempotencyRecord(idempotency_key="stale-check", action_type="ai_pricing.sync_check", request_hash="stale", status=IdempotencyRecordStatus.started, admin_id=admin(db_session).id, created_at=started_at)
    db_session.add_all([run, record])
    db_session.commit()

    read = get_check_run(db_session, run.id)
    assert read.status == AiPriceCheckStatus.failed
    assert read.safe_error == "Pricing check did not finish within the stale-run recovery window"
    stored_record = db_session.query(IdempotencyRecord).filter_by(idempotency_key="stale-check").one()
    assert stored_record.status.value == "completed"
    assert stored_record.response_json["status"] == AiPriceCheckStatus.failed.value


def test_unsupported_provider_and_mock_disabled_are_safe(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = make_catalog(db_session, provider="manual-only")
    result = run_pricing_sync_check(db_session, check_payload(catalog, "unchanged"), "unsupported-provider", admin(db_session))
    assert result["status"] == AiPriceCheckStatus.unsupported.value

    adapter = DevelopmentMockPricingAdapter()
    monkeypatch.setattr(settings, "ai_pricing_mock_adapter_enabled", False)
    disabled = adapter.fetch_pricing(provider="mock-ai", provider_model_id="mock-model", pricing_scope_code="standard")
    assert disabled.is_authoritative is False
    assert "disabled" in (disabled.safe_error or "")
    assert get_trusted_pricing_adapter("development_mock", "mock-ai") is None
    monkeypatch.setattr(settings, "ai_pricing_mock_adapter_enabled", True)

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "ai_pricing_mock_adapter_enabled", True)
    assert get_trusted_pricing_adapter("development_mock", "mock-ai") is None
    production_disabled = adapter.fetch_pricing(provider="mock-ai", provider_model_id="mock-model", pricing_scope_code="standard")
    assert production_disabled.is_authoritative is False
    assert "disabled" in (production_disabled.safe_error or "")
    monkeypatch.setattr(settings, "environment", "development")


def test_sync_check_endpoint_requires_idempotency_and_no_url_payload(client) -> None:
    login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-password"})
    assert login.status_code == 200
    response = client.post("/api/v1/ai/pricing/sync-check", json={"reason": "missing key", "source_url": "http://example.com"})
    assert response.status_code == 400
    rejected_url = client.post(
        "/api/v1/ai/pricing/sync-check",
        json={"reason": "no arbitrary url", "source_url": "http://example.com"},
        headers={"Idempotency-Key": "reject-url"},
    )
    assert rejected_url.status_code == 422


def test_stale_approval_conflicts_without_partial_review_update(db_session: Session) -> None:
    catalog = make_catalog(db_session)
    seed_version(db_session, catalog)
    review = run_pricing_sync_check(db_session, check_payload(catalog, "unknown_model"), "check-stale-review", admin(db_session))
    run = db_session.get(AIPriceCheckRun, UUID(review["id"]))
    assert run is not None
    run.candidate_provider_model_id = catalog.provider_model_id
    db_session.commit()

    create_pricing_version(
        db_session,
        catalog.id,
        AiPricingVersionCreate(
            input_token_price=Decimal("4.00000000"),
            output_token_price=Decimal("14.00000000"),
            pricing_unit_tokens=1000000,
            effective_from=datetime.now(timezone.utc) + timedelta(days=1),
            reason="newer manual version",
        ),
        "newer-manual-version",
        admin(db_session),
    )
    with pytest.raises(Exception) as exc:
        approve_check_run(db_session, run.id, AiPriceCheckReviewRequest(reason="approve stale candidate"), "approve-stale", admin(db_session))
    assert "conflicts with an existing pricing version" in str(exc.value)
    stored = db_session.get(AIPriceCheckRun, run.id)
    assert stored.status == AiPriceCheckStatus.requires_manual_review
    assert stored.reviewed_at is None
    assert stored.created_version_id is None
    assert db_session.query(AiModelPricingVersion).count() == 2


def _postgres_url() -> str | None:
    url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if not url:
        return None
    lowered = url.lower()
    if any(marker in lowered for marker in ("prod", "production", "render.com", "amazonaws.com", "azure.com")):
        return None
    return url


def test_postgres_concurrent_duplicate_source_fingerprint_creates_one_version() -> None:
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
        catalog = make_catalog(db)
        seed_version(db, catalog)
        catalog_id = catalog.id
        admin_id = admin_model.id

    errors: list[str] = []

    def worker(key: str) -> None:
        with SessionLocal() as db:
            try:
                admin_model = db.get(Admin, admin_id)
                catalog = db.get(AiModelPricingCatalog, catalog_id)
                assert catalog is not None
                run_pricing_sync_check(db, check_payload(catalog, "duplicate_source_fingerprint"), key, admin_model)
            except Exception as exc:  # noqa: BLE001 - test records race outcome
                errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(f"pg-check-{idx}",)) for idx in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with SessionLocal() as db:
        versions = list(db.scalars(select(AiModelPricingVersion).where(AiModelPricingVersion.pricing_catalog_id == catalog_id)))
        assert len(versions) == 2
        assert len([version for version in versions if version.source_fingerprint]) == 1
        assert db.query(AIPriceCheckRun).filter(AIPriceCheckRun.status == AiPriceCheckStatus.version_created).count() == 1
    assert errors == []
