export type ApiResponse<T> = {
  success: boolean;
  data: T;
};

export type Admin = {
  id: string;
  email: string;
  username: string | null;
};

export type AuthPayload = {
  admin: Admin;
};

export type Environment = "production" | "staging" | "testing" | "development";
export type ProductHealthStatus = "healthy" | "down" | "slow" | "under_maintenance" | "not_responding";
export type SyncStatus =
  | "synced"
  | "pending"
  | "failed"
  | "retrying"
  | "outdated"
  | "mismatch"
  | "requires_manual_resolution";

export type ProductDeployment = {
  id: string;
  product_name: string;
  region: string;
  environment: Environment;
  currency: string;
  api_base_url: string;
  health_check_url: string | null;
  admin_api_version: string;
  organization_list_path: string | null;
  organization_detail_path_template: string | null;
  supported_endpoints: Record<string, unknown> | null;
  compatibility_status: string;
  is_active: boolean;
  is_under_maintenance: boolean;
  health_status: ProductHealthStatus;
  sync_status: SyncStatus;
  last_successful_sync_at: string | null;
  last_failed_sync_at: string | null;
  last_checked_at: string | null;
  last_successful_health_check_at: string | null;
  last_health_response_time_ms: number | null;
  last_error_message: string | null;
  last_organization_discovery_attempt_at: string | null;
  last_successful_organization_discovery_at: string | null;
  last_organization_discovery_error: string | null;
  secret_configured: boolean;
  created_at: string;
  updated_at: string;
};

export type ProductPayload = {
  product_name: string;
  region: string;
  environment: Environment;
  currency: string;
  api_base_url: string;
  health_check_url?: string | null;
  admin_api_version: string;
  organization_list_path?: string | null;
  organization_detail_path_template?: string | null;
  is_active: boolean;
  is_under_maintenance: boolean;
  admin_api_secret?: string | null;
};

export type ProductHealthCheckResult = {
  product: ProductDeployment;
  health_status: ProductHealthStatus;
  response_time_ms: number | null;
  success: boolean;
  error_message: string | null;
  checked_at: string;
};

export type OrganizationLifecycleStatus = "active" | "trial" | "suspended" | "churned" | "internal_testing" | "demo";
export type BillingMode = "prepaid_credits" | "postpaid_manual_settlement" | "free_internal_testing";
export type BillingCalculationStatus = "active" | "paused" | "usage_tracking_only" | "disabled";
export type CreditStatus =
  | "healthy_balance"
  | "low_balance"
  | "zero_balance"
  | "balance_exhausted"
  | "outstanding_dues"
  | "not_applicable";
export type ServiceStatus = "running" | "paused" | "disabled" | "pending_sync" | "product_mismatch" | "failed_to_apply";
export type MappingStatus =
  | "active"
  | "inactive"
  | "missing_product_id"
  | "product_mismatch"
  | "verification_failed"
  | "requires_manual_review";

export type ProductDeploymentSummary = {
  id: string;
  product_name: string;
  region: string;
  environment: Environment;
  currency: string;
  admin_api_version: string;
};

export type OrganizationMapping = {
  id: string;
  organization_id: string;
  product_deployment_id: string;
  product_organization_id: string | null;
  product_api_version: string;
  external_billing_id: string | null;
  external_customer_id: string | null;
  external_plan_id: string | null;
  external_subscription_id: string | null;
  mapping_status: MappingStatus;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Organization = {
  id: string;
  central_organization_id: string;
  name: string;
  product_deployment_id: string;
  currency: string;
  lifecycle_status: OrganizationLifecycleStatus;
  billing_mode: BillingMode;
  billing_calculation_status: BillingCalculationStatus;
  credit_status: CreditStatus;
  service_status: ServiceStatus;
  service_enforcement_status: ServiceStatus;
  credit_balance: string;
  outstanding_dues: string;
  sync_status: SyncStatus;
  last_synced_at: string | null;
  last_active_at: string | null;
  created_at: string;
  updated_at: string;
  product_deployment: ProductDeploymentSummary;
  mapping: OrganizationMapping | null;
};

export type OrganizationPayload = {
  name: string;
  product_deployment_id: string;
  currency: string;
  lifecycle_status: OrganizationLifecycleStatus;
  billing_mode: BillingMode;
  billing_calculation_status: BillingCalculationStatus;
  last_active_at?: string | null;
};

export type ProductOrganizationLookup = {
  product_deployment_id: string;
  product_organization_id: string;
  organization_name: string | null;
  lifecycle_status: OrganizationLifecycleStatus | null;
  billing_mode: BillingMode | null;
  billing_calculation_status: BillingCalculationStatus | null;
  currency: string | null;
  credit_status: CreditStatus | null;
  service_status: ServiceStatus | null;
  credit_balance: string | null;
  outstanding_dues: string | null;
  last_active_at: string | null;
  safe_metadata: Record<string, unknown> | null;
};

export type OrganizationLinkFromProductPayload = {
  product_deployment_id: string;
  product_organization_id: string;
  reason?: string | null;
  manual_name?: string | null;
  manual_currency?: string | null;
  manual_lifecycle_status?: OrganizationLifecycleStatus | null;
  manual_billing_mode?: BillingMode | null;
  manual_billing_calculation_status?: BillingCalculationStatus | null;
};

export type OrganizationListPayload = {
  items: Organization[];
  total: number;
  limit: number;
  offset: number;
};

export type OrganizationMappingPayload = {
  product_deployment_id?: string;
  product_organization_id?: string | null;
  mapping_status?: MappingStatus;
  external_billing_id?: string | null;
  external_customer_id?: string | null;
  external_plan_id?: string | null;
  external_subscription_id?: string | null;
};

export type MappingVerificationResult = {
  mapping: OrganizationMapping;
  success: boolean;
  message: string | null;
};

export type BillingTransactionType =
  | "credit_grant"
  | "credit_deduction"
  | "manual_payment"
  | "usage_charge"
  | "adjustment"
  | "correction"
  | "reversal";

export type BillingSummary = {
  organization_id: string;
  product_deployment_id: string;
  currency: string;
  billing_mode: BillingMode;
  credit_status: CreditStatus;
  credit_balance: string;
  outstanding_dues: string;
};

export type BillingLedgerEntry = {
  id: string;
  organization_id: string;
  product_deployment_id: string;
  currency: string;
  amount: string;
  transaction_type: BillingTransactionType;
  balance_before: string;
  balance_after: string;
  outstanding_dues_before: string;
  outstanding_dues_after: string;
  note: string | null;
  admin_id: string | null;
  idempotency_key: string;
  related_original_transaction_id: string | null;
  related_product_transaction_id: string | null;
  product_sync_status: SyncStatus;
  failure_message: string | null;
  created_at: string;
};

export type ManualPaymentRecord = {
  id: string;
  organization_id: string;
  product_deployment_id: string;
  currency: string;
  payment_amount: string;
  payment_date: string;
  payment_method: string | null;
  payment_reference: string | null;
  note: string | null;
  idempotency_key: string;
  product_sync_status: SyncStatus;
  created_at: string;
  updated_at: string;
};

export type FinancialActionResult = {
  organization: BillingSummary;
  ledger_entry: BillingLedgerEntry;
  pending_product_change_id: string | null;
  manual_payment: ManualPaymentRecord | null;
  idempotency_key: string;
};

export type LedgerListPayload = {
  items: BillingLedgerEntry[];
  total: number;
  limit: number;
  offset: number;
};

export type PendingChangeStatus =
  | "saved"
  | "sent_to_product"
  | "accepted_by_product"
  | "confirmed_and_synced"
  | "failed"
  | "pending_retry"
  | "cancelled"
  | "requires_manual_resolution";

export type PendingChange = {
  id: string;
  action: string;
  organization_id: string | null;
  product_deployment_id: string;
  product_name: string | null;
  region: string | null;
  environment: Environment | null;
  status: PendingChangeStatus;
  retry_count: number;
  last_retry_at: string | null;
  last_error: string | null;
  admin_id: string | null;
  idempotency_key: string | null;
  reason: string | null;
  payload: Record<string, unknown> | null;
  delivery_attempt_id: string | null;
  delivery_started_at: string | null;
  last_delivery_at: string | null;
  product_request_id: string | null;
  product_api_version: string | null;
  safe_confirmation_summary: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  can_cancel: boolean;
  can_retry: boolean;
};

export type PendingChangeListPayload = {
  items: PendingChange[];
  total: number;
  limit: number;
  offset: number;
};

export type ServiceEnforcement = {
  organization_id: string;
  product_deployment_id: string;
  intended_service_status: ServiceStatus;
  evaluated_service_status: ServiceStatus;
  product_confirmation_status: SyncStatus;
  billing_mode: BillingMode;
  credit_balance: string;
  outstanding_dues: string;
  credit_status: CreditStatus;
  manual_continuation_enabled: boolean;
  manual_continuation_reason: string | null;
  latest_pending_change: {
    id: string;
    action: string;
    status: PendingChangeStatus;
    created_at: string;
    reason: string | null;
  } | null;
};

export type ServiceActionResult = {
  organization_id: string;
  intended_service_status: ServiceStatus;
  product_confirmation_status: SyncStatus;
  manual_continuation_enabled: boolean;
  pending_product_change_id: string;
  idempotency_key: string;
};

export type DeliveryActionResult = {
  pending_change_id: string;
  action: string;
  status: PendingChangeStatus | "blocked";
  product_request_id: string | null;
  safe_result: Record<string, unknown> | null;
  error: string | null;
};

export type ProductSyncResult = {
  product_id: string;
  health?: {
    health_status: ProductHealthStatus;
    last_checked_at: string | null;
  } | null;
  examined_count: number;
  confirmed_count?: number;
  pending_retry_count?: number;
  manual_resolution_count?: number;
  blocked_count: number;
  results: DeliveryActionResult[];
};

export type OrganizationSyncResult = {
  organization_id: string;
  results: DeliveryActionResult[];
};

export type MappingSyncResult = {
  product_id: string;
  checked: number;
  failed: number;
};

export type SyncStatusItem = {
  product_id: string;
  product_name: string;
  region: string;
  environment: Environment;
  health_status: ProductHealthStatus;
  compatibility_status: string;
  last_health_check: string | null;
  last_confirmed_delivery: string | null;
  counts: Record<PendingChangeStatus, number>;
  latest_failure: string | null;
  has_ordering_blocker: boolean;
};

export type SyncStatusPayload = {
  items: SyncStatusItem[];
};

export type FailureLogItem = {
  id: string;
  product_deployment_id: string | null;
  organization_id: string | null;
  pending_change_id: string | null;
  action_attempted: string;
  error_code: string | null;
  error_message: string;
  retry_count: number;
  current_status: string;
  product_request_id: string | null;
  created_at: string;
};

export type FailureLogListPayload = {
  items: FailureLogItem[];
  total: number;
  limit: number;
  offset: number;
};

export type OrganizationDiscoveryStatus =
  | "discovered"
  | "already_mapped"
  | "imported"
  | "ignored"
  | "conflict"
  | "missing_required_data"
  | "requires_manual_review"
  | "no_longer_returned";

export type ProductOrganizationDiscovery = {
  id: string;
  product_deployment_id: string;
  product_organization_id: string;
  organization_name: string;
  lifecycle_status_snapshot: OrganizationLifecycleStatus | null;
  billing_mode_snapshot: BillingMode | null;
  billing_calculation_status_snapshot: BillingCalculationStatus | null;
  currency_snapshot: string | null;
  credit_status_snapshot: CreditStatus | null;
  credit_balance_snapshot: string | null;
  outstanding_dues_snapshot: string | null;
  service_status_snapshot: ServiceStatus | null;
  product_active_status: boolean | null;
  product_api_version: string | null;
  product_request_id: string | null;
  product_updated_at: string | null;
  last_active_at: string | null;
  last_seen_at: string | null;
  discovery_status: OrganizationDiscoveryStatus;
  central_organization_id: string | null;
  safe_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type DiscoveryListPayload = {
  items: ProductOrganizationDiscovery[];
  total: number;
  limit: number;
  offset: number;
};

export type DiscoverySummary = {
  discovered_count: number;
  newly_discovered_count: number;
  already_mapped_count: number;
  conflict_count: number;
  invalid_count: number;
  pages_fetched: number;
  safe_failures: string[];
};

export type ImportOrganizationsResult = {
  items: Array<{
    product_organization_id: string;
    status: string;
    organization_id: string | null;
    mapping_status: string | null;
    message: string | null;
  }>;
};
