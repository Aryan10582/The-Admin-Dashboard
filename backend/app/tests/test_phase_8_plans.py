from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import threading
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import BillingCalculationStatus, BillingMode, Environment, MappingStatus, OrganizationLifecycleStatus, PendingChangeStatus, ProductConfirmationStatus, ProductHealthStatus, SyncStatus
from app.integrations.product_admin_client import ProductDeliveryResult
from app.models import Base
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingPlan, BillingPlanVersion, OrganizationPlanAssignment
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization, OrganizationMapping
from app.models.pending_change import PendingProductChange
from app.models.product import ProductDeployment
from app.schemas.billing import BillingPlanVersionCreate, PlanAssignmentRequest
from app.services.product_service import product_dependency_summary
from app.services.plan_service import assign_plan_version, create_plan_version
from app.tests.test_organizations import create_deployment, create_org, login
from app.tests.test_service_enforcement import create_mapping


def idempotency_headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


def version_payload(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    price: str = "99.00",
    billing_mode: str = BillingMode.prepaid_credits.value,
) -> dict:
    return {
        "currency": "USD",
        "billing_mode_compatibility": billing_mode,
        "base_price": price,
        "pricing_structure": {"type": "flat_monthly"},
        "limits": {"users": 5},
        "included_tokens": 1000,
        "included_leads": 25,
        "overage_pricing": {"lead": "2.00"},
        "effective_from": (start or (datetime.now(timezone.utc) - timedelta(days=1))).isoformat(),
        "effective_to": end.isoformat() if end else None,
        "reason": "Phase 8 version",
    }


def create_plan_and_version(client: TestClient, deployment_id: UUID) -> tuple[dict, dict]:
    plan_response = client.post(
        "/api/v1/plans",
        json={
            "plan_code": "clinic_starter",
            "name": "Clinic Starter",
            "description": "Starter package",
            "product_deployment_id": str(deployment_id),
            "currency": "USD",
        },
    )
    assert plan_response.status_code == 201
    plan = plan_response.json()["data"]
    version_response = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(end=datetime.now(timezone.utc) + timedelta(days=30)),
    )
    assert version_response.status_code == 201
    return plan, version_response.json()["data"]


def create_plan_only(client: TestClient, deployment_id: UUID, code: str = "clinic_starter") -> dict:
    response = client.post(
        "/api/v1/plans",
        json={
            "plan_code": code,
            "name": code.replace("_", " ").title(),
            "description": "Phase 8 plan",
            "product_deployment_id": str(deployment_id),
            "currency": "USD",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_plan_create_update_and_code_uniqueness(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    plan, _version = create_plan_and_version(client, deployment.id)

    duplicate = client.post(
        "/api/v1/plans",
        json={
            "plan_code": "clinic_starter",
            "name": "Duplicate",
            "product_deployment_id": str(deployment.id),
            "currency": "USD",
        },
    )
    patch = client.patch(f"/api/v1/plans/{plan['id']}", json={"name": "Clinic Starter Updated", "description": "Updated safely"})

    assert duplicate.status_code == 409
    assert patch.status_code == 200
    assert patch.json()["data"]["plan_code"] == "clinic_starter"
    assert patch.json()["data"]["name"] == "Clinic Starter Updated"
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "billing_plan.created")) is not None


def test_plan_versions_are_generated_and_existing_terms_are_not_rewritten(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    plan, version_one = create_plan_and_version(client, deployment.id)
    version_two = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=datetime.now(timezone.utc) + timedelta(days=40), price="149.00"),
    )
    overlap = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=datetime.now(timezone.utc), end=datetime.now(timezone.utc) + timedelta(days=10), price="129.00"),
    )
    negative = client.post(f"/api/v1/plans/{plan['id']}/versions", json={**version_payload(), "base_price": "-1.00"})

    assert version_two.status_code == 201
    assert version_two.json()["data"]["version_number"] == 2
    assert overlap.status_code == 409
    assert negative.status_code == 422
    first_in_db = db_session.get(BillingPlanVersion, UUID(version_one["id"]))
    assert first_in_db is not None
    assert first_in_db.price == Decimal("99.00")
    assert first_in_db.version_number == 1


def test_assign_exact_plan_version_creates_one_assignment_pending_change_and_replays(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    _plan, version = create_plan_and_version(client, deployment.id)

    first = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": version["id"], "reason": "Assign starter"},
        headers=idempotency_headers("assign-plan-key"),
    )
    second = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": version["id"], "reason": "Assign starter"},
        headers=idempotency_headers("assign-plan-key"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert db_session.scalar(select(func.count()).select_from(OrganizationPlanAssignment)) == 1
    assert db_session.scalar(select(func.count()).select_from(PendingProductChange)) == 1
    assert db_session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "organization.plan_assigned")) == 1
    record = db_session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "assign-plan-key"))
    assert record is not None
    assert record.response_json == first.json()["data"]


def test_assignment_validates_mapping_product_currency_billing_mode_and_reason(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    other_deployment = create_deployment(db_session, product_name="Other Product")
    org = create_org(client, deployment)
    _plan, wrong_product_version = create_plan_and_version(client, other_deployment.id)
    no_mapping = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": wrong_product_version["id"], "reason": "Missing mapping"},
        headers=idempotency_headers("plan-no-map"),
    )
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    wrong_product = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": wrong_product_version["id"], "reason": "Wrong product"},
        headers=idempotency_headers("plan-wrong-product"),
    )
    reason_missing = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": wrong_product_version["id"], "reason": ""},
        headers=idempotency_headers("plan-no-reason"),
    )

    assert no_mapping.status_code == 409
    assert wrong_product.status_code == 409
    assert reason_missing.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(OrganizationPlanAssignment)) == 0


def test_assignment_confirmation_requires_exact_plan_code_and_version(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    _plan, version = create_plan_and_version(client, deployment.id)
    assignment_response = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": version["id"], "reason": "Assign starter"},
        headers=idempotency_headers("assign-confirm-key"),
    )
    assert assignment_response.status_code == 200
    change = db_session.scalar(select(PendingProductChange).where(PendingProductChange.idempotency_key == "assign-confirm-key"))
    assert change is not None

    class StubProductClient:
        async def deliver_pending_change(self, **kwargs):
            payload = kwargs["payload"]
            return ProductDeliveryResult(
                success=True,
                product_organization_id=kwargs["product_organization_id"],
                applied_change=kwargs["action"],
                product_api_version="v1",
                sync_confirmed=True,
                product_request_id="plan-req",
                idempotency_key=kwargs["idempotency_key"],
                plan_code=payload["plan_code"],
                plan_version_number=payload["plan_version_number"],
            )

    monkeypatch.setattr("app.services.sync_service.build_product_client", lambda product, api_secret=None: StubProductClient())
    confirmed = client.post(f"/api/v1/pending-changes/{change.id}/retry", json={"reason": "Deliver"}, headers=idempotency_headers("retry-plan-confirm"))

    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == PendingChangeStatus.confirmed_and_synced.value
    assignment = db_session.get(OrganizationPlanAssignment, UUID(assignment_response.json()["data"]["assignment"]["id"]))
    assert assignment is not None
    assert assignment.product_confirmation_status == ProductConfirmationStatus.confirmed
    assert assignment.product_confirmed_plan_code == "clinic_starter"
    assert assignment.product_confirmed_version_number == 1


def test_wrong_plan_confirmation_requires_manual_resolution(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    _plan, version = create_plan_and_version(client, deployment.id)
    assignment_response = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": version["id"], "reason": "Assign starter"},
        headers=idempotency_headers("assign-mismatch-key"),
    )
    assert assignment_response.status_code == 200
    change = db_session.scalar(select(PendingProductChange).where(PendingProductChange.idempotency_key == "assign-mismatch-key"))
    assert change is not None

    class StubProductClient:
        async def deliver_pending_change(self, **kwargs):
            return ProductDeliveryResult(
                success=True,
                product_organization_id=kwargs["product_organization_id"],
                applied_change=kwargs["action"],
                product_api_version="v1",
                sync_confirmed=True,
                product_request_id="plan-bad",
                idempotency_key=kwargs["idempotency_key"],
                plan_code="wrong_plan",
                plan_version_number=999,
            )

    monkeypatch.setattr("app.services.sync_service.build_product_client", lambda product, api_secret=None: StubProductClient())
    response = client.post(f"/api/v1/pending-changes/{change.id}/retry", json={"reason": "Deliver"}, headers=idempotency_headers("retry-plan-bad"))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    assignment = db_session.get(OrganizationPlanAssignment, UUID(assignment_response.json()["data"]["assignment"]["id"]))
    assert assignment is not None
    assert assignment.product_confirmation_status == ProductConfirmationStatus.pending


def test_version_history_assignment_history_rename_and_deactivation_preserve_terms(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    plan = create_plan_only(client, deployment.id)
    first_end = datetime.now(timezone.utc) + timedelta(days=10)
    version_one = client.post(f"/api/v1/plans/{plan['id']}/versions", json=version_payload(end=first_end, price="10.00"))
    version_two = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=first_end, end=first_end + timedelta(days=10), price="20.00"),
    )
    version_three = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=first_end + timedelta(days=10), price="30.00"),
    )
    assignment = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": version_one.json()["data"]["id"], "reason": "Assign immutable v1"},
        headers=idempotency_headers("immutable-history"),
    )
    rename = client.patch(f"/api/v1/plans/{plan['id']}", json={"name": "Renamed Plan", "is_active": False})
    history = client.get(f"/api/v1/organizations/{org['id']}/plan-assignment-history")

    assert version_one.status_code == 201
    assert version_two.status_code == 201
    assert version_three.status_code == 201
    assert version_two.json()["data"]["version_number"] == 2
    assert version_three.json()["data"]["version_number"] == 3
    assert assignment.status_code == 200
    assert rename.status_code == 200
    stored_v1 = db_session.get(BillingPlanVersion, UUID(version_one.json()["data"]["id"]))
    assert stored_v1 is not None
    assert stored_v1.price == Decimal("10.00")
    assert stored_v1.version_number == 1
    stored_assignment = db_session.get(OrganizationPlanAssignment, UUID(assignment.json()["data"]["assignment"]["id"]))
    assert stored_assignment is not None
    assert stored_assignment.billing_plan_version_id == stored_v1.id
    assert history.status_code == 200
    assert history.json()["data"][0]["plan_name"] == "Renamed Plan"
    assert history.json()["data"][0]["version_number"] == 1


def test_effective_date_boundaries_and_assignability(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    plan = create_plan_only(client, deployment.id)
    boundary = datetime.now(timezone.utc) + timedelta(days=1)
    adjacent_one = client.post(f"/api/v1/plans/{plan['id']}/versions", json=version_payload(end=boundary))
    adjacent_two = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=boundary, end=boundary + timedelta(days=1), price="109.00"),
    )
    one_second_overlap = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=boundary - timedelta(seconds=1), end=boundary + timedelta(days=2), price="119.00"),
    )
    invalid_range = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=boundary + timedelta(days=4), end=boundary + timedelta(days=3), price="129.00"),
    )
    future = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=boundary + timedelta(days=5), end=boundary + timedelta(days=6), price="139.00"),
    )
    assign_expired = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": adjacent_two.json()["data"]["id"], "reason": "future not assignable"},
        headers=idempotency_headers("future-version"),
    )

    assert adjacent_one.status_code == 201
    assert adjacent_two.status_code == 201
    assert one_second_overlap.status_code == 409
    assert invalid_range.status_code == 422
    assert future.status_code == 201
    assert assign_expired.status_code == 409


def test_open_ended_current_version_blocks_overlap_and_is_resolved(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    plan = create_plan_only(client, deployment.id)
    open_current = client.post(f"/api/v1/plans/{plan['id']}/versions", json=version_payload())
    overlapping_future = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=datetime.now(timezone.utc) + timedelta(days=5), price="111.00"),
    )
    detail = client.get(f"/api/v1/plans/{plan['id']}")

    assert open_current.status_code == 201
    assert overlapping_future.status_code == 409
    assert detail.status_code == 200
    assert detail.json()["data"]["current_effective_version"]["id"] == open_current.json()["data"]["id"]


def test_plan_assignment_idempotency_conflicts_and_record_counts(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org_a = create_org(client, deployment)
    org_b = create_org(client, deployment, name="Second Clinic")
    create_mapping(db_session, org_a["id"], deployment.id, product_organization_id="prod-a")
    create_mapping(db_session, org_b["id"], deployment.id, product_organization_id="prod-b")
    plan = create_plan_only(client, deployment.id)
    version_one = client.post(f"/api/v1/plans/{plan['id']}/versions", json=version_payload(end=datetime.now(timezone.utc) + timedelta(days=5)))
    version_two = client.post(
        f"/api/v1/plans/{plan['id']}/versions",
        json=version_payload(start=datetime.now(timezone.utc) + timedelta(days=6), end=datetime.now(timezone.utc) + timedelta(days=7), price="120.00"),
    )

    first = client.post(
        f"/api/v1/organizations/{org_a['id']}/plan-assignment",
        json={"billing_plan_version_id": version_one.json()["data"]["id"], "reason": "Original reason"},
        headers=idempotency_headers("plan-idem-conflict"),
    )
    different_reason = client.post(
        f"/api/v1/organizations/{org_a['id']}/plan-assignment",
        json={"billing_plan_version_id": version_one.json()["data"]["id"], "reason": "Different reason"},
        headers=idempotency_headers("plan-idem-conflict"),
    )
    different_org = client.post(
        f"/api/v1/organizations/{org_b['id']}/plan-assignment",
        json={"billing_plan_version_id": version_one.json()["data"]["id"], "reason": "Original reason"},
        headers=idempotency_headers("plan-idem-conflict"),
    )
    different_version = client.post(
        f"/api/v1/organizations/{org_a['id']}/plan-assignment",
        json={"billing_plan_version_id": version_two.json()["data"]["id"], "reason": "Original reason"},
        headers=idempotency_headers("plan-idem-conflict"),
    )

    assert first.status_code == 200
    assert different_reason.status_code == 409
    assert different_org.status_code == 409
    assert different_version.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(OrganizationPlanAssignment)) == 1
    assert db_session.scalar(select(func.count()).select_from(PendingProductChange)) == 1
    assert db_session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "organization.plan_assigned")) == 1


def test_assignment_rollback_after_pending_change_write_failure_restores_previous_state(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    plan = create_plan_only(client, deployment.id)
    now = datetime.now(timezone.utc)
    v1 = client.post(f"/api/v1/plans/{plan['id']}/versions", json=version_payload(end=now + timedelta(days=3)))
    v2 = client.post(f"/api/v1/plans/{plan['id']}/versions", json=version_payload(start=now + timedelta(days=4), end=now + timedelta(days=5), price="200.00"))
    first = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": v1.json()["data"]["id"], "reason": "Initial"},
        headers=idempotency_headers("rollback-initial"),
    )
    db_session.get(PendingProductChange, UUID(first.json()["data"]["pending_product_change_id"])).status = PendingChangeStatus.confirmed_and_synced
    db_session.get(OrganizationPlanAssignment, UUID(first.json()["data"]["assignment"]["id"])).product_confirmation_status = ProductConfirmationStatus.confirmed
    # Make v2 assignable without mutating v1 through an API path.
    stored_v2 = db_session.get(BillingPlanVersion, UUID(v2.json()["data"]["id"]))
    stored_v2.effective_from = now - timedelta(hours=1)
    stored_v2.effective_to = now + timedelta(days=5)
    db_session.commit()

    def fail_payload(*args, **kwargs):
        raise RuntimeError("pending change payload failed")

    monkeypatch.setattr("app.services.plan_service._assignment_payload", fail_payload)
    with pytest.raises(RuntimeError):
        client.post(
            f"/api/v1/organizations/{org['id']}/plan-assignment",
            json={"billing_plan_version_id": v2.json()["data"]["id"], "reason": "Should roll back"},
            headers=idempotency_headers("rollback-change"),
        )
    db_session.rollback()
    previous = db_session.get(OrganizationPlanAssignment, UUID(first.json()["data"]["assignment"]["id"]))
    assert previous is not None
    assert previous.is_active is True
    assert previous.effective_to is None
    assert db_session.scalar(select(func.count()).select_from(OrganizationPlanAssignment)) == 1
    assert db_session.scalar(select(func.count()).select_from(PendingProductChange)) == 1
    assert db_session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "rollback-change")) is None


def test_intended_and_confirmed_state_diverge_after_failed_plan_delivery(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    starter = create_plan_only(client, deployment.id, "starter")
    professional = create_plan_only(client, deployment.id, "professional")
    starter_version = client.post(f"/api/v1/plans/{starter['id']}/versions", json=version_payload(end=datetime.now(timezone.utc) + timedelta(days=30), price="50.00"))
    professional_version = client.post(f"/api/v1/plans/{professional['id']}/versions", json=version_payload(end=datetime.now(timezone.utc) + timedelta(days=30), price="100.00"))
    starter_assignment = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": starter_version.json()["data"]["id"], "reason": "Starter"},
        headers=idempotency_headers("starter-confirm"),
    )
    starter_change = db_session.get(PendingProductChange, UUID(starter_assignment.json()["data"]["pending_product_change_id"]))
    starter_change.status = PendingChangeStatus.confirmed_and_synced
    starter_row = db_session.get(OrganizationPlanAssignment, UUID(starter_assignment.json()["data"]["assignment"]["id"]))
    starter_row.product_confirmation_status = ProductConfirmationStatus.confirmed
    starter_row.product_confirmed_at = datetime.now(timezone.utc)
    starter_row.product_confirmed_plan_code = "starter"
    starter_row.product_confirmed_version_number = 1
    db_session.commit()
    professional_assignment = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": professional_version.json()["data"]["id"], "reason": "Upgrade"},
        headers=idempotency_headers("professional-fail"),
    )

    class RejectingClient:
        async def deliver_pending_change(self, **kwargs):
            return ProductDeliveryResult(
                success=False,
                product_organization_id=kwargs["product_organization_id"],
                applied_change=kwargs["action"],
                product_api_version="v1",
                sync_confirmed=False,
                product_request_id="reject",
                idempotency_key=kwargs["idempotency_key"],
                error_code="product_rejection",
                safe_error_message="Rejected",
            )

    monkeypatch.setattr("app.services.sync_service.build_product_client", lambda product, api_secret=None: RejectingClient())
    change_id = professional_assignment.json()["data"]["pending_product_change_id"]
    retry = client.post(f"/api/v1/pending-changes/{change_id}/retry", json={"reason": "Deliver"}, headers=idempotency_headers("professional-retry"))
    state = client.get(f"/api/v1/organizations/{org['id']}/plan-assignment")

    assert professional_assignment.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
    assert state.json()["data"]["current_intended"]["plan_code"] == "professional"
    assert state.json()["data"]["current_intended"]["product_confirmation_status"] == "pending"
    assert state.json()["data"]["last_product_confirmed"]["plan_code"] == "starter"


def test_product_dependency_summary_includes_plan_versions_and_assignments(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    _plan, version = create_plan_and_version(client, deployment.id)
    assignment = client.post(
        f"/api/v1/organizations/{org['id']}/plan-assignment",
        json={"billing_plan_version_id": version["id"], "reason": "Dependency"},
        headers=idempotency_headers("delete-dependency"),
    )
    response = client.delete(f"/api/v1/products/{deployment.id}")

    assert assignment.status_code == 200
    assert response.status_code == 409
    summary = product_dependency_summary(db_session, deployment.id)
    assert summary["billing_plans"] == 1
    assert summary["billing_plan_versions"] == 1
    assert summary["plan_assignments"] == 1


def test_plan_confirmation_mismatch_matrix(client: TestClient, db_session: Session, monkeypatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id, product_organization_id="prod-org")
    _plan, version = create_plan_and_version(client, deployment.id)

    cases = [
        ("plain_200", ProductDeliveryResult(success=False, sync_confirmed=False, product_request_id="plain"), "unclear_confirmation"),
        ("missing_sync", ProductDeliveryResult(success=True, sync_confirmed=False, product_request_id="missing"), "unclear_confirmation"),
        ("wrong_org", ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="wrong", applied_change="assign_plan_version", product_api_version="v1", idempotency_key="CASE_KEY", plan_code="clinic_starter", plan_version_number=1), "organization_mismatch"),
        ("wrong_key", ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="prod-org", applied_change="assign_plan_version", product_api_version="v1", idempotency_key="wrong", plan_code="clinic_starter", plan_version_number=1), "idempotency_mismatch"),
        ("wrong_api", ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="prod-org", applied_change="assign_plan_version", product_api_version="v999", idempotency_key="CASE_KEY", plan_code="clinic_starter", plan_version_number=1), "incompatible_api_version"),
        ("wrong_action", ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="prod-org", applied_change="credits.add", product_api_version="v1", idempotency_key="CASE_KEY", plan_code="clinic_starter", plan_version_number=1), "contradictory_product_value"),
        ("wrong_plan", ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="prod-org", applied_change="assign_plan_version", product_api_version="v1", idempotency_key="CASE_KEY", plan_code="wrong", plan_version_number=1), "contradictory_product_value"),
        ("wrong_version", ProductDeliveryResult(success=True, sync_confirmed=True, product_organization_id="prod-org", applied_change="assign_plan_version", product_api_version="v1", idempotency_key="CASE_KEY", plan_code="clinic_starter", plan_version_number=2), "contradictory_product_value"),
    ]
    for label, result, expected_failure in cases:
        assignment = client.post(
            f"/api/v1/organizations/{org['id']}/plan-assignment",
            json={"billing_plan_version_id": version["id"], "reason": label},
            headers=idempotency_headers(f"assign-{label}"),
        )
        assert assignment.status_code == 200
        change_id = assignment.json()["data"]["pending_product_change_id"]
        change = db_session.get(PendingProductChange, UUID(change_id))
        assert change is not None
        result_for_case = result
        if result.idempotency_key == "CASE_KEY":
            result_for_case = ProductDeliveryResult(
                success=result.success,
                product_organization_id=result.product_organization_id,
                applied_change=result.applied_change,
                product_api_version=result.product_api_version,
                sync_confirmed=result.sync_confirmed,
                error_code=result.error_code,
                safe_error_message=result.safe_error_message,
                product_request_id=result.product_request_id,
                idempotency_key=change.idempotency_key,
                plan_code=result.plan_code,
                plan_version_number=result.plan_version_number,
            )

        class CaseClient:
            async def deliver_pending_change(self, **kwargs):
                return result_for_case

        monkeypatch.setattr("app.services.sync_service.build_product_client", lambda product, api_secret=None: CaseClient())
        response = client.post(f"/api/v1/pending-changes/{change_id}/retry", json={"reason": "Deliver"}, headers=idempotency_headers(f"retry-{label}"))
        assert response.status_code == 200
        assert response.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value
        failure = db_session.scalar(select(PendingProductChange).where(PendingProductChange.id == UUID(change_id)))
        assert failure.status == PendingChangeStatus.requires_manual_resolution
        db_failure = db_session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.idempotency_key == change.idempotency_key))
        assert db_failure >= 1
        # Clear the unresolved blocker so the next mismatch scenario can create its own assignment.
        change.status = PendingChangeStatus.cancelled
        assignment_row = db_session.get(OrganizationPlanAssignment, UUID(assignment.json()["data"]["assignment"]["id"]))
        assignment_row.is_active = False
        assignment_row.effective_to = datetime.now(timezone.utc)
        db_session.commit()


def test_postgres_concurrent_version_creation_is_serialized() -> None:
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not configured")
    if "prod" in database_url.lower() or "production" in database_url.lower():
        pytest.skip("Refusing production-looking PostgreSQL test database")

    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    unique = f"phase8_{datetime.now(timezone.utc).timestamp()}".replace(".", "_")
    with SessionLocal() as db:
        admin = Admin(email=f"{unique}@example.com", username=unique, password_hash="hash")
        deployment = ProductDeployment(
            product_name=unique,
            region="test",
            environment=Environment.testing,
            currency="USD",
            api_base_url="http://127.0.0.1:1",
            admin_api_version="v1",
            health_status=ProductHealthStatus.healthy,
            sync_status=SyncStatus.pending,
        )
        db.add_all([admin, deployment])
        db.flush()
        plan = BillingPlan(plan_code=unique, name=unique, product_deployment_id=deployment.id, currency="USD")
        db.add(plan)
        db.commit()
        plan_id = plan.id
        admin_id = admin.id

    barrier = threading.Barrier(2)
    results: list[str] = []

    def create_version(index: int) -> None:
        with SessionLocal() as db:
            admin = db.get(Admin, admin_id)
            barrier.wait(timeout=10)
            start = datetime.now(timezone.utc) + timedelta(days=index * 10)
            payload = BillingPlanVersionCreate(
                currency="USD",
                billing_mode_compatibility=BillingMode.prepaid_credits,
                base_price=Decimal(f"{index}.00"),
                pricing_structure={"type": "flat"},
                limits={},
                overage_pricing={},
                included_tokens=0,
                included_leads=0,
                effective_from=start,
                effective_to=start + timedelta(days=5),
                reason=f"concurrent {index}",
            )
            try:
                create_plan_version(db, plan_id, payload, admin)
                results.append("created")
            except Exception as exc:
                results.append(type(exc).__name__)

    threads = [threading.Thread(target=create_version, args=(1,)), threading.Thread(target=create_version, args=(2,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    with SessionLocal() as db:
        versions = list(db.scalars(select(BillingPlanVersion).where(BillingPlanVersion.billing_plan_id == plan_id).order_by(BillingPlanVersion.version_number.asc())))
        assert [version.version_number for version in versions] in ([1, 2], [1])
        assert len({version.version_number for version in versions}) == len(versions)
        assert len(versions) == results.count("created")


def test_postgres_concurrent_assignments_leave_one_current_assignment() -> None:
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not configured")
    if "prod" in database_url.lower() or "production" in database_url.lower():
        pytest.skip("Refusing production-looking PostgreSQL test database")

    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    unique = f"phase8_assign_{datetime.now(timezone.utc).timestamp()}".replace(".", "_")
    with SessionLocal() as db:
        admin = Admin(email=f"{unique}@example.com", username=unique, password_hash="hash")
        deployment = ProductDeployment(
            product_name=unique,
            region="test",
            environment=Environment.testing,
            currency="USD",
            api_base_url="http://127.0.0.1:1",
            admin_api_version="v1",
            health_status=ProductHealthStatus.healthy,
            sync_status=SyncStatus.pending,
        )
        db.add_all([admin, deployment])
        db.flush()
        organization = Organization(
            central_organization_id=unique,
            name=unique,
            product_deployment_id=deployment.id,
            currency="USD",
            lifecycle_status=OrganizationLifecycleStatus.trial,
            billing_mode=BillingMode.prepaid_credits,
            billing_calculation_status=BillingCalculationStatus.active,
        )
        db.add(organization)
        db.flush()
        db.add(
            OrganizationMapping(
                organization_id=organization.id,
                product_deployment_id=deployment.id,
                product_organization_id=f"prod-{unique}",
                product_api_version="v1",
                mapping_status=MappingStatus.active,
            )
        )
        versions = []
        for index in (1, 2):
            plan = BillingPlan(plan_code=f"{unique}_{index}", name=f"{unique} {index}", product_deployment_id=deployment.id, currency="USD")
            db.add(plan)
            db.flush()
            version = BillingPlanVersion(
                billing_plan_id=plan.id,
                version_number=1,
                currency="USD",
                billing_mode_compatibility=BillingMode.prepaid_credits,
                pricing_structure={"type": "flat"},
                price=Decimal(f"{index}.00"),
                included_tokens=0,
                included_leads=0,
                effective_from=datetime.now(timezone.utc) - timedelta(days=1),
                effective_to=datetime.now(timezone.utc) + timedelta(days=1),
                is_active=True,
            )
            db.add(version)
            db.flush()
            versions.append(version.id)
        db.commit()
        org_id = organization.id
        admin_id = admin.id

    barrier = threading.Barrier(2)
    results: list[str] = []

    def assign(index: int) -> None:
        with SessionLocal() as db:
            admin = db.get(Admin, admin_id)
            barrier.wait(timeout=10)
            try:
                assign_plan_version(
                    db,
                    org_id,
                    PlanAssignmentRequest(billing_plan_version_id=versions[index], reason=f"assign {index}"),
                    f"{unique}-key-{index}",
                    admin,
                )
                results.append("assigned")
            except Exception as exc:
                results.append(type(exc).__name__)

    threads = [threading.Thread(target=assign, args=(0,)), threading.Thread(target=assign, args=(1,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    with SessionLocal() as db:
        current_count = db.scalar(
            select(func.count()).select_from(OrganizationPlanAssignment).where(
                OrganizationPlanAssignment.organization_id == org_id,
                OrganizationPlanAssignment.is_active.is_(True),
            )
        )
        total_count = db.scalar(select(func.count()).select_from(OrganizationPlanAssignment).where(OrganizationPlanAssignment.organization_id == org_id))
        assert current_count == 1
        assert total_count == results.count("assigned")
