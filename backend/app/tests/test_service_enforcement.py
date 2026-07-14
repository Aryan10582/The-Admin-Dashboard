from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import BillingMode, MappingStatus, PendingChangeStatus, ServiceStatus
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.billing import BillingLedgerEntry
from app.models.organization import Organization, OrganizationMapping
from app.models.pending_change import PendingProductChange
from app.models.service_enforcement import ServiceEnforcementRule
from app.services.service_enforcement import apply_service_action, maybe_auto_pause_for_zero_balance
from app.tests.test_billing import financial_payload
from app.tests.test_organizations import create_deployment, create_org, login


def idempotency_headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


def reason_payload(reason: str = "Service safety test") -> dict[str, str]:
    return {"reason": reason}


def create_mapping(
    db_session: Session,
    org_id: str,
    deployment_id: UUID,
    *,
    status: MappingStatus = MappingStatus.active,
    product_organization_id: str | None = None,
) -> OrganizationMapping:
    mapping = OrganizationMapping(
        organization_id=UUID(org_id),
        product_deployment_id=deployment_id,
        product_organization_id=product_organization_id or f"prod-{org_id}",
        product_api_version="v1",
        mapping_status=status,
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


def create_service_rule(
    db_session: Session,
    org_id: str,
    *,
    manual_override: bool = False,
    reason: str | None = None,
    status: ServiceStatus = ServiceStatus.running,
) -> ServiceEnforcementRule:
    rule = ServiceEnforcementRule(
        organization_id=UUID(org_id),
        service_status=status,
        manual_continuation_override=manual_override,
        manual_override_reason=reason,
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    return rule


def change_count(db_session: Session, org_id: str, action: str | None = None) -> int:
    stmt = select(func.count()).select_from(PendingProductChange).where(PendingProductChange.organization_id == UUID(org_id))
    if action:
        stmt = stmt.where(PendingProductChange.action == action)
    return db_session.scalar(stmt) or 0


def audit_count(db_session: Session, org_id: str, action: str) -> int:
    return (
        db_session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.organization_id == UUID(org_id), AuditLog.action == action))
        or 0
    )


def test_service_endpoints_require_authentication(client: TestClient) -> None:
    org_id = UUID(int=0)
    endpoints = [
        ("get", f"/api/v1/organizations/{org_id}/service-enforcement"),
        ("patch", f"/api/v1/organizations/{org_id}/service-enforcement"),
        ("post", f"/api/v1/organizations/{org_id}/service/pause"),
        ("post", f"/api/v1/organizations/{org_id}/service/resume"),
        ("post", f"/api/v1/organizations/{org_id}/service/disable"),
        ("post", f"/api/v1/organizations/{org_id}/manual-continuation/apply"),
        ("post", f"/api/v1/organizations/{org_id}/manual-continuation/remove"),
        ("get", "/api/v1/pending-changes"),
        ("get", f"/api/v1/pending-changes/{org_id}"),
        ("post", f"/api/v1/pending-changes/{org_id}/cancel"),
        ("post", f"/api/v1/pending-changes/{org_id}/mark-manual-resolution"),
    ]
    for method, path in endpoints:
        if method == "get":
            response = client.get(path, headers=idempotency_headers(f"auth-{method}-{path}"))
        else:
            response = getattr(client, method)(path, json=reason_payload(), headers=idempotency_headers(f"auth-{method}-{path}"))
        assert response.status_code == 401


def test_pause_resume_and_disable_create_audit_and_saved_pending_change(client: TestClient, db_session: Session) -> None:
    login(client)
    for action, path, expected in (
        ("service.pause", "pause", ServiceStatus.paused),
        ("service.resume", "resume", ServiceStatus.running),
        ("service.disable", "disable", ServiceStatus.disabled),
    ):
        deployment = create_deployment(db_session, product_name=f"Core CRM {path}")
        org = create_org(client, deployment)
        create_mapping(db_session, org["id"], deployment.id)
        organization = db_session.get(Organization, UUID(org["id"]))
        assert organization is not None
        organization.credit_balance = Decimal("10.00")
        db_session.commit()
        response = client.post(
            f"/api/v1/organizations/{org['id']}/service/{path}",
            json=reason_payload(action),
            headers=idempotency_headers(action),
        )
        assert response.status_code == 200
        assert response.json()["data"]["intended_service_status"] == expected.value
        pending = db_session.scalar(select(PendingProductChange).where(PendingProductChange.idempotency_key == action))
        assert pending is not None
        assert pending.status == PendingChangeStatus.saved
        assert pending.action == action
        assert audit_count(db_session, org["id"], action) == 1


def test_conflicting_saved_service_changes_are_rejected(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("10.00")
    db_session.commit()

    pause = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("Pending pause"),
        headers=idempotency_headers("pending-pause"),
    )
    resume = client.post(
        f"/api/v1/organizations/{org['id']}/service/resume",
        json=reason_payload("Conflicting resume"),
        headers=idempotency_headers("conflicting-resume"),
    )
    disable = client.post(
        f"/api/v1/organizations/{org['id']}/service/disable",
        json=reason_payload("Conflicting disable"),
        headers=idempotency_headers("conflicting-disable"),
    )

    assert pause.status_code == 200
    assert resume.status_code == 409
    assert disable.status_code == 409
    assert change_count(db_session, org["id"]) == 1


def test_duplicate_service_idempotency_replays_without_duplicate_writes(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("10.00")
    db_session.commit()

    first = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("First pause"),
        headers=idempotency_headers("pause-replay"),
    )
    second = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("Second pause"),
        headers=idempotency_headers("pause-replay"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert change_count(db_session, org["id"], "service.pause") == 1
    assert audit_count(db_session, org["id"], "service.pause") == 1


def test_mapping_blocks_service_actions_before_state_change(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    other_deployment = create_deployment(db_session, product_name="Other")
    missing = create_org(client, deployment)
    unverified = create_org(client, deployment)
    mismatched = create_org(client, deployment)
    create_mapping(db_session, unverified["id"], deployment.id, status=MappingStatus.requires_manual_review)
    create_mapping(db_session, mismatched["id"], other_deployment.id)

    for key, org in (("missing", missing), ("unverified", unverified), ("mismatched", mismatched)):
        response = client.post(
            f"/api/v1/organizations/{org['id']}/service/pause",
            json=reason_payload(key),
            headers=idempotency_headers(f"map-{key}"),
        )
        assert response.status_code == 409
        organization = db_session.get(Organization, UUID(org["id"]))
        assert organization is not None
        assert organization.service_enforcement_status == ServiceStatus.pending_sync
        assert change_count(db_session, org["id"]) == 0


def test_prepaid_exhausted_resume_rules_and_manual_override(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("0.00")
    organization.service_enforcement_status = ServiceStatus.paused
    db_session.commit()

    blocked = client.post(
        f"/api/v1/organizations/{org['id']}/service/resume",
        json=reason_payload("No credits"),
        headers=idempotency_headers("resume-blocked"),
    )
    assert blocked.status_code == 409

    override = client.post(
        f"/api/v1/organizations/{org['id']}/manual-continuation/apply",
        json=reason_payload("Executive approval"),
        headers=idempotency_headers("override-apply"),
    )
    assert override.status_code == 200
    assert override.json()["data"]["intended_service_status"] == ServiceStatus.running.value

    duplicate_resume = client.post(
        f"/api/v1/organizations/{org['id']}/service/resume",
        json=reason_payload("Conflicts while override is pending"),
        headers=idempotency_headers("resume-override"),
    )
    assert duplicate_resume.status_code == 409


def test_zero_balance_credit_deduction_creates_one_auto_pause_pending_change(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("10.00")
    organization.service_enforcement_status = ServiceStatus.running
    db_session.commit()

    response = client.post(
        f"/api/v1/organizations/{org['id']}/credits/deduct",
        json=financial_payload("10.00", "Spend remaining balance"),
        headers=idempotency_headers("deduct-to-zero"),
    )
    replay = client.post(
        f"/api/v1/organizations/{org['id']}/credits/deduct",
        json=financial_payload("10.00", "Replay"),
        headers=idempotency_headers("deduct-to-zero"),
    )

    assert response.status_code == 200
    assert replay.status_code == 200
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.service_enforcement_status == ServiceStatus.paused
    assert change_count(db_session, org["id"], "service.auto_pause_zero_balance") == 1
    assert db_session.scalar(select(func.count()).select_from(BillingLedgerEntry).where(BillingLedgerEntry.organization_id == organization.id)) == 1


def test_auto_pause_skips_disabled_override_and_postpaid_orgs(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    disabled_org = create_org(client, deployment)
    override_org = create_org(client, deployment)
    postpaid_org = create_org(client, deployment, billing_mode=BillingMode.postpaid_manual_settlement.value)
    for org, product_org in ((disabled_org, "prod-disabled"), (override_org, "prod-override"), (postpaid_org, "prod-postpaid")):
        create_mapping(db_session, org["id"], deployment.id, product_organization_id=product_org)

    disabled = db_session.get(Organization, UUID(disabled_org["id"]))
    override = db_session.get(Organization, UUID(override_org["id"]))
    postpaid = db_session.get(Organization, UUID(postpaid_org["id"]))
    admin = db_session.scalar(select(Admin).where(Admin.email == "admin@example.com"))
    assert disabled is not None and override is not None and postpaid is not None and admin is not None
    disabled.credit_balance = Decimal("0.00")
    disabled.service_enforcement_status = ServiceStatus.disabled
    override.credit_balance = Decimal("0.00")
    override.service_enforcement_status = ServiceStatus.running
    postpaid.credit_balance = Decimal("0.00")
    postpaid.service_enforcement_status = ServiceStatus.running
    db_session.commit()
    create_service_rule(db_session, override_org["id"], manual_override=True, reason="Override")

    assert maybe_auto_pause_for_zero_balance(db_session, organization=disabled, reason="Skip disabled", admin=admin, idempotency_key="skip-disabled") is None
    assert maybe_auto_pause_for_zero_balance(db_session, organization=override, reason="Skip override", admin=admin, idempotency_key="skip-override") is None
    assert maybe_auto_pause_for_zero_balance(db_session, organization=postpaid, reason="Skip postpaid", admin=admin, idempotency_key="skip-postpaid") is None
    assert disabled.service_enforcement_status == ServiceStatus.disabled
    assert override.service_enforcement_status == ServiceStatus.running
    assert postpaid.service_enforcement_status == ServiceStatus.running


def test_postpaid_and_free_orgs_are_not_auto_stopped_by_balance_or_dues(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    postpaid = create_org(client, deployment, billing_mode=BillingMode.postpaid_manual_settlement.value)
    free = create_org(client, deployment, billing_mode=BillingMode.free_internal_testing.value)
    for org in (postpaid, free):
        create_mapping(db_session, org["id"], deployment.id, product_organization_id=f"prod-{org['id']}")
        organization = db_session.get(Organization, UUID(org["id"]))
        assert organization is not None
        organization.credit_balance = Decimal("0.00")
        organization.outstanding_dues = Decimal("999.00")
        organization.service_enforcement_status = ServiceStatus.running
    db_session.commit()

    for org in (postpaid, free):
        summary = client.get(f"/api/v1/organizations/{org['id']}/service-enforcement")
        assert summary.status_code == 200
        assert summary.json()["data"]["evaluated_service_status"] == ServiceStatus.running.value


def test_manual_override_removal_pauses_only_when_credits_exhausted(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("0.00")
    organization.service_enforcement_status = ServiceStatus.running
    db_session.commit()
    create_service_rule(db_session, org["id"], manual_override=True, reason="Existing approval")

    removed = client.post(
        f"/api/v1/organizations/{org['id']}/manual-continuation/remove",
        json=reason_payload("Remove approval"),
        headers=idempotency_headers("override-remove"),
    )

    assert removed.status_code == 200
    assert removed.json()["data"]["intended_service_status"] == ServiceStatus.paused.value
    assert removed.json()["data"]["manual_continuation_enabled"] is False


def test_manual_override_does_not_override_disabled_and_positive_balance_removal_does_not_pause(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    disabled_org = create_org(client, deployment)
    positive_org = create_org(client, deployment)
    create_mapping(db_session, disabled_org["id"], deployment.id, product_organization_id="prod-disabled")
    create_mapping(db_session, positive_org["id"], deployment.id, product_organization_id="prod-positive")

    disabled = db_session.get(Organization, UUID(disabled_org["id"]))
    positive = db_session.get(Organization, UUID(positive_org["id"]))
    assert disabled is not None and positive is not None
    disabled.credit_balance = Decimal("0.00")
    disabled.service_enforcement_status = ServiceStatus.disabled
    positive.credit_balance = Decimal("5.00")
    positive.service_enforcement_status = ServiceStatus.running
    db_session.commit()
    create_service_rule(db_session, positive_org["id"], manual_override=True, reason="Existing approval")

    apply_disabled = client.post(
        f"/api/v1/organizations/{disabled_org['id']}/manual-continuation/apply",
        json=reason_payload("Apply while disabled"),
        headers=idempotency_headers("apply-disabled"),
    )
    remove_positive = client.post(
        f"/api/v1/organizations/{positive_org['id']}/manual-continuation/remove",
        json=reason_payload("Remove with credits"),
        headers=idempotency_headers("remove-positive"),
    )

    assert apply_disabled.status_code == 200
    assert apply_disabled.json()["data"]["intended_service_status"] == ServiceStatus.disabled.value
    assert remove_positive.status_code == 200
    assert remove_positive.json()["data"]["intended_service_status"] == ServiceStatus.running.value


def test_manual_override_apply_rejects_positive_balance(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("1.00")
    db_session.commit()

    response = client.post(
        f"/api/v1/organizations/{org['id']}/manual-continuation/apply",
        json=reason_payload("Not exhausted"),
        headers=idempotency_headers("positive-override"),
    )

    assert response.status_code == 409


def test_manual_continuation_source_of_truth_is_service_rule() -> None:
    assert hasattr(ServiceEnforcementRule, "manual_continuation_override")
    assert not hasattr(Organization, "manual_continuation_enabled")


def test_failed_later_service_write_rolls_back_transaction(db_session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    admin = db_session.scalar(select(Admin).where(Admin.email == "admin@example.com"))
    assert admin is not None

    def fail_audit(*args, **kwargs) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr("app.services.service_enforcement._audit", fail_audit)
    with pytest.raises(RuntimeError):
        apply_service_action(
            db_session,
            organization_id=UUID(org["id"]),
            action="service.pause",
            reason="Rollback service",
            idempotency_key="service-rollback",
            admin=admin,
        )

    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.service_enforcement_status == ServiceStatus.pending_sync
    assert change_count(db_session, org["id"]) == 0


def test_pending_change_filters_pagination_cancel_and_manual_resolution(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("10.00")
    db_session.commit()
    first = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("Pause for filter"),
        headers=idempotency_headers("filter-pause"),
    )
    pause_change_id = first.json()["data"]["pending_product_change_id"]
    cancel = client.post(
        f"/api/v1/pending-changes/{pause_change_id}/cancel",
        json=reason_payload("Cancel before resume"),
        headers=idempotency_headers("cancel-before-resume"),
    )
    assert cancel.status_code == 200
    second = client.post(
        f"/api/v1/organizations/{org['id']}/service/resume",
        json=reason_payload("Resume for filter"),
        headers=idempotency_headers("filter-resume"),
    )
    assert first.status_code == 200
    assert second.status_code == 200

    listed = client.get("/api/v1/pending-changes", params={"organization_id": org["id"], "limit": 1, "offset": 0})
    filtered = client.get("/api/v1/pending-changes", params={"organization_id": org["id"], "action": "service.pause"})
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 2
    assert len(listed.json()["data"]["items"]) == 1
    assert filtered.status_code == 200
    assert filtered.json()["data"]["total"] == 1

    resume_change_id = second.json()["data"]["pending_product_change_id"]
    manual = client.post(
        f"/api/v1/pending-changes/{resume_change_id}/mark-manual-resolution",
        json=reason_payload("Needs human review"),
        headers=idempotency_headers("manual-resolution"),
    )
    assert manual.status_code == 200
    assert manual.json()["data"]["status"] == PendingChangeStatus.requires_manual_resolution.value


def test_cancel_stale_older_service_change_cannot_overwrite_newer_intended_state(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.credit_balance = Decimal("10.00")
    organization.service_enforcement_status = ServiceStatus.running
    db_session.commit()

    pause = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("Pause first"),
        headers=idempotency_headers("stale-pause"),
    )
    assert pause.status_code == 200
    pause_change_id = UUID(pause.json()["data"]["pending_product_change_id"])
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    organization.service_enforcement_status = ServiceStatus.disabled
    newer_disable = PendingProductChange(
        action="service.disable",
        payload={
            "organization_id": org["id"],
            "product_deployment_id": str(deployment.id),
            "product_organization_id": "prod-stale",
            "previous_intended_service_status": ServiceStatus.paused.value,
            "requested_intended_service_status": ServiceStatus.disabled.value,
            "previous_manual_continuation_enabled": False,
            "previous_manual_continuation_reason": None,
            "requested_manual_continuation_enabled": False,
            "reason": "Legacy disable",
        },
        organization_id=UUID(org["id"]),
        product_deployment_id=deployment.id,
        status=PendingChangeStatus.saved,
        idempotency_key="legacy-disable",
        retry_count=0,
        reason="Legacy disable",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(newer_disable)
    db_session.commit()

    cancel = client.post(
        f"/api/v1/pending-changes/{pause_change_id}/cancel",
        json=reason_payload("Cancel stale pause"),
        headers=idempotency_headers("cancel-stale-pause"),
    )

    assert cancel.status_code == 409
    organization = db_session.get(Organization, UUID(org["id"]))
    assert organization is not None
    assert organization.service_enforcement_status == ServiceStatus.disabled


def test_sent_confirmed_and_financial_changes_cannot_be_cancelled(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    response = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("Pause"),
        headers=idempotency_headers("unsafe-pause"),
    )
    assert response.status_code == 200
    service_change = db_session.get(PendingProductChange, UUID(response.json()["data"]["pending_product_change_id"]))
    assert service_change is not None
    service_change.status = PendingChangeStatus.sent_to_product
    db_session.commit()
    sent_cancel = client.post(
        f"/api/v1/pending-changes/{service_change.id}/cancel",
        json=reason_payload("Cancel sent"),
        headers=idempotency_headers("cancel-sent"),
    )
    assert sent_cancel.status_code == 409

    client.post(
        f"/api/v1/organizations/{org['id']}/credits/add",
        json=financial_payload("5.00", "Financial change"),
        headers=idempotency_headers("financial-change"),
    )
    financial = db_session.scalar(select(PendingProductChange).where(PendingProductChange.action == "credits.add"))
    assert financial is not None
    financial_cancel = client.post(
        f"/api/v1/pending-changes/{financial.id}/cancel",
        json=reason_payload("Cancel financial"),
        headers=idempotency_headers("cancel-financial"),
    )
    assert financial_cancel.status_code == 409


def test_service_metadata_does_not_expose_product_secret(client: TestClient, db_session: Session) -> None:
    login(client)
    deployment = create_deployment(db_session)
    org = create_org(client, deployment)
    create_mapping(db_session, org["id"], deployment.id)
    response = client.post(
        f"/api/v1/organizations/{org['id']}/service/pause",
        json=reason_payload("Safe metadata"),
        headers=idempotency_headers("secret-service"),
    )
    assert response.status_code == 200
    change = db_session.scalar(select(PendingProductChange).where(PendingProductChange.idempotency_key == "secret-service"))
    audit = db_session.scalar(select(AuditLog).where(AuditLog.idempotency_key == "secret-service"))
    assert change is not None
    assert audit is not None
    combined = f"{response.text} {change.payload} {audit.old_value} {audit.new_value} {audit.failure_message}"
    assert "product-secret" not in combined
