from enum import StrEnum


class Environment(StrEnum):
    production = "production"
    staging = "staging"
    testing = "testing"
    development = "development"


class ProductHealthStatus(StrEnum):
    healthy = "healthy"
    down = "down"
    slow = "slow"
    under_maintenance = "under_maintenance"
    not_responding = "not_responding"


class SyncStatus(StrEnum):
    synced = "synced"
    pending = "pending"
    failed = "failed"
    retrying = "retrying"
    outdated = "outdated"
    mismatch = "mismatch"
    requires_manual_resolution = "requires_manual_resolution"


class OrganizationLifecycleStatus(StrEnum):
    active = "active"
    trial = "trial"
    suspended = "suspended"
    churned = "churned"
    internal_testing = "internal_testing"
    demo = "demo"


class BillingMode(StrEnum):
    prepaid_credits = "prepaid_credits"
    postpaid_manual_settlement = "postpaid_manual_settlement"
    free_internal_testing = "free_internal_testing"


class BillingCalculationStatus(StrEnum):
    active = "active"
    paused = "paused"
    usage_tracking_only = "usage_tracking_only"
    disabled = "disabled"


class CreditStatus(StrEnum):
    healthy_balance = "healthy_balance"
    low_balance = "low_balance"
    zero_balance = "zero_balance"
    balance_exhausted = "balance_exhausted"
    outstanding_dues = "outstanding_dues"
    not_applicable = "not_applicable"


class ServiceStatus(StrEnum):
    running = "running"
    paused = "paused"
    disabled = "disabled"
    pending_sync = "pending_sync"
    product_mismatch = "product_mismatch"
    failed_to_apply = "failed_to_apply"


class MappingStatus(StrEnum):
    active = "active"
    inactive = "inactive"
    missing_product_id = "missing_product_id"
    product_mismatch = "product_mismatch"
    verification_failed = "verification_failed"
    requires_manual_review = "requires_manual_review"


class OrganizationDiscoveryStatus(StrEnum):
    discovered = "discovered"
    already_mapped = "already_mapped"
    imported = "imported"
    ignored = "ignored"
    conflict = "conflict"
    missing_required_data = "missing_required_data"
    requires_manual_review = "requires_manual_review"
    no_longer_returned = "no_longer_returned"


class PendingChangeStatus(StrEnum):
    saved = "saved"
    sent_to_product = "sent_to_product"
    accepted_by_product = "accepted_by_product"
    confirmed_and_synced = "confirmed_and_synced"
    failed = "failed"
    pending_retry = "pending_retry"
    cancelled = "cancelled"
    requires_manual_resolution = "requires_manual_resolution"


class AuditResultStatus(StrEnum):
    success = "success"
    failure = "failure"


class FailureStatus(StrEnum):
    open = "open"
    retrying = "retrying"
    resolved = "resolved"
    ignored = "ignored"


class CompatibilityStatus(StrEnum):
    compatible = "compatible"
    incompatible = "incompatible"
    unknown = "unknown"
    requires_upgrade = "requires_upgrade"


class ProductConfirmationStatus(StrEnum):
    pending = "pending"
    confirmed = "confirmed"
    failed = "failed"
    not_required = "not_required"


class BillingTransactionType(StrEnum):
    credit_grant = "credit_grant"
    credit_deduction = "credit_deduction"
    manual_payment = "manual_payment"
    usage_charge = "usage_charge"
    adjustment = "adjustment"
    correction = "correction"
    reversal = "reversal"


class RevenueType(StrEnum):
    recognized = "recognized"
    collected = "collected"
    outstanding = "outstanding"
    adjustment = "adjustment"


class RevenueSource(StrEnum):
    billing_ledger = "billing_ledger"
    manual_payment = "manual_payment"
    product_sync = "product_sync"
    admin_adjustment = "admin_adjustment"


class MismatchStatus(StrEnum):
    matched = "matched"
    mismatch = "mismatch"
    pending_review = "pending_review"


class IdempotencyRecordStatus(StrEnum):
    started = "started"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class PricingCreatedBy(StrEnum):
    system = "system"
    admin = "admin"
