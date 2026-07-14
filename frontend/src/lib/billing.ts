import { apiRequest } from "@/lib/api";
import type { ApiResponse, BillingSummary, FinancialActionResult, LedgerListPayload } from "@/lib/types";

export type FinancialActionPayload = {
  amount: string;
  currency: string;
  reason: string;
  allow_negative_balance?: boolean;
  payment_date?: string | null;
  payment_method?: string | null;
  payment_reference?: string | null;
};

export type LedgerFilters = {
  limit?: number;
  offset?: number;
  organization_id?: string;
  product_deployment_id?: string;
  product_name?: string;
  region?: string;
  environment?: string;
  currency?: string;
  transaction_type?: string;
  date_from?: string;
  date_to?: string;
};

function queryString(filters: LedgerFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

function writeOptions(payload: FinancialActionPayload, idempotencyKey: string) {
  return {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  };
}

export function getOrganizationBilling(organizationId: string) {
  return apiRequest<ApiResponse<BillingSummary>>(`/organizations/${organizationId}/billing`);
}

export function addCredits(organizationId: string, payload: FinancialActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<FinancialActionResult>>(
    `/organizations/${organizationId}/credits/add`,
    writeOptions(payload, idempotencyKey)
  );
}

export function deductCredits(organizationId: string, payload: FinancialActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<FinancialActionResult>>(
    `/organizations/${organizationId}/credits/deduct`,
    writeOptions(payload, idempotencyKey)
  );
}

export function recordManualPayment(organizationId: string, payload: FinancialActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<FinancialActionResult>>(
    `/organizations/${organizationId}/manual-payment`,
    writeOptions(payload, idempotencyKey)
  );
}

export function getOrganizationLedger(organizationId: string, filters: LedgerFilters = {}) {
  return apiRequest<ApiResponse<LedgerListPayload>>(`/organizations/${organizationId}/ledger${queryString(filters)}`);
}

export function listBillingLedger(filters: LedgerFilters = {}) {
  return apiRequest<ApiResponse<LedgerListPayload>>(`/billing/ledger${queryString(filters)}`);
}
