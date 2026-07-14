from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import (
    AuditResultStatus,
    BillingCalculationStatus,
    BillingMode,
    BillingTransactionType,
    Environment,
    IdempotencyRecordStatus,
    MappingStatus,
    OrganizationLifecycleStatus,
    PricingCreatedBy,
    ProductHealthStatus,
    SyncStatus,
)
from app.models import (
    AiModelPricingVersion,
    AuditLog,
    BillingLedgerEntry,
    BillingPlan,
    BillingPlanVersion,
    IdempotencyRecord,
    Organization,
    OrganizationMapping,
    ProductDeployment,
)


def test_phase_2_core_schema_records_can_be_created(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    product_deployment = ProductDeployment(
        product_name="Lead CRM",
        region="IN",
        environment=Environment.development,
        currency="INR",
        api_base_url="http://product.local",
        health_check_url="http://product.local/health",
        admin_api_version="v1",
        supported_endpoints={"health": "/health", "billing": "/admin/billing"},
        health_status=ProductHealthStatus.healthy,
        sync_status=SyncStatus.pending,
    )
    db_session.add(product_deployment)
    db_session.commit()

    organization = Organization(
        central_organization_id="org_phase_2",
        name="Phase 2 Org",
        product_deployment_id=product_deployment.id,
        currency="INR",
        lifecycle_status=OrganizationLifecycleStatus.trial,
        billing_mode=BillingMode.prepaid_credits,
        billing_calculation_status=BillingCalculationStatus.active,
        credit_balance=Decimal("1000.00"),
        outstanding_dues=Decimal("0.00"),
        selected_ai_provider="openai",
        selected_ai_model="gpt-test",
    )
    db_session.add(organization)
    db_session.commit()

    mapping = OrganizationMapping(
        organization_id=organization.id,
        product_deployment_id=product_deployment.id,
        product_organization_id="product_org_1",
        product_api_version="v1",
        mapping_status=MappingStatus.active,
    )
    db_session.add(mapping)
    db_session.commit()

    plan = BillingPlan(
        plan_code="starter",
        name="Starter",
        product_deployment_id=product_deployment.id,
        currency="INR",
    )
    db_session.add(plan)
    db_session.commit()

    plan_version = BillingPlanVersion(
        billing_plan_id=plan.id,
        version_number=1,
        currency="INR",
        billing_mode_compatibility=BillingMode.prepaid_credits,
        pricing_structure={"type": "flat"},
        price=Decimal("499.00"),
        limits={"users": 5},
        included_tokens=10000,
        included_leads=100,
        overage_pricing={"lead": "5.00"},
        effective_from=now,
    )
    db_session.add(plan_version)
    db_session.commit()

    ledger_entry = BillingLedgerEntry(
        organization_id=organization.id,
        product_deployment_id=product_deployment.id,
        currency="INR",
        amount=Decimal("499.00"),
        transaction_type=BillingTransactionType.credit_grant,
        balance_before=Decimal("0.00"),
        balance_after=Decimal("499.00"),
        outstanding_dues_before=Decimal("0.00"),
        outstanding_dues_after=Decimal("0.00"),
        idempotency_key="phase-2-ledger-key",
        product_sync_status=SyncStatus.pending,
        created_at=now,
    )
    db_session.add(ledger_entry)
    db_session.commit()

    idempotency_record = IdempotencyRecord(
        idempotency_key="phase-2-action-key",
        action_type="billing.credit_grant",
        request_hash="hash",
        response_json={"ledger_entry_id": str(ledger_entry.id)},
        status=IdempotencyRecordStatus.completed,
        organization_id=organization.id,
        created_at=now,
    )
    db_session.add(idempotency_record)
    db_session.commit()

    audit_log = AuditLog(
        action="phase_2.schema_test",
        organization_id=organization.id,
        product_deployment_id=product_deployment.id,
        result_status=AuditResultStatus.success,
        new_value={"ledger_entry_id": str(ledger_entry.id)},
        created_at=now,
    )
    db_session.add(audit_log)
    db_session.commit()

    pricing_version = AiModelPricingVersion(
        provider="openai",
        model_name="gpt-test",
        input_token_cost=Decimal("0.00000100"),
        output_token_cost=Decimal("0.00000200"),
        currency="USD",
        pricing_source="manual-test",
        version_number=1,
        effective_from=now,
        created_by=PricingCreatedBy.admin,
        audit_log_id=audit_log.id,
    )
    db_session.add(pricing_version)
    db_session.commit()

    assert product_deployment.id is not None
    assert organization.id is not None
    assert mapping.id is not None
    assert plan.id is not None
    assert plan_version.id is not None
    assert ledger_entry.id is not None
    assert idempotency_record.id is not None
    assert audit_log.id is not None
    assert pricing_version.id is not None
