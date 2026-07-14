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
  central_organization_id?: string;
  name: string;
  product_deployment_id: string;
  currency: string;
  lifecycle_status: OrganizationLifecycleStatus;
  billing_mode: BillingMode;
  billing_calculation_status: BillingCalculationStatus;
  credit_status: CreditStatus;
  service_status: ServiceStatus;
  sync_status: SyncStatus;
  last_active_at?: string | null;
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
