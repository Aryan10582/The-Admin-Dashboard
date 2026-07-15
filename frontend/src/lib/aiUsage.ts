import { apiRequest } from "@/lib/api";
import type {
  AiUsageBatchResolutionResponse,
  AiUsageConflictDetail,
  AiUsageListPayload,
  AiUsageRecord,
  AiUsageSummary,
  AiUsageSyncRun,
  AiUsageSyncRunListPayload,
  AiUsageSyncState,
  ApiResponse
} from "@/lib/types";

export type AiUsageFilters = {
  limit?: number;
  offset?: number;
  product_deployment_id?: string;
  organization_id?: string;
  product_organization_id?: string;
  provider?: string;
  product_model_id?: string;
  usage_from?: string;
  usage_to?: string;
  pricing_catalog_id?: string;
  pricing_version_id?: string;
  cost_currency?: string;
  pricing_resolution_status?: string;
  mapping_resolution_status?: string;
  conflict_status?: string;
  finalization_status?: string;
  product_usage_id?: string;
};

function queryString(filters: AiUsageFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listAiUsage(filters: AiUsageFilters = {}) {
  return apiRequest<ApiResponse<AiUsageListPayload>>(`/ai/usage${queryString(filters)}`);
}

export function summarizeAiUsage(filters: AiUsageFilters = {}) {
  return apiRequest<ApiResponse<AiUsageSummary>>(`/ai/usage/summary${queryString(filters)}`);
}

export function resolveAiUsagePricing(usageId: string, payload: { reason: string; pricing_version_id?: string | null }, idempotencyKey: string) {
  return apiRequest<ApiResponse<{ outcome: string; message: string | null; usage: AiUsageRecord | null }>>(`/ai/usage/${usageId}/resolve-pricing`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function resolveMissingPricing(payload: { reason: string; product_deployment_id?: string | null; limit?: number }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiUsageBatchResolutionResponse>>("/ai/usage/resolve-missing-pricing", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function resolveMappings(payload: { reason: string; product_deployment_id?: string | null; limit?: number }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiUsageBatchResolutionResponse>>("/ai/usage/resolve-mappings", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function getAiUsageConflict(usageId: string) {
  return apiRequest<ApiResponse<AiUsageConflictDetail>>(`/ai/usage/${usageId}/conflict`);
}

export function markAiUsageConflictReviewed(usageId: string, payload: { reason: string }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiUsageConflictDetail>>(`/ai/usage/${usageId}/conflict/mark-reviewed`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function syncProductAiUsage(productId: string, payload: { reason: string; limit?: number; max_pages?: number }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiUsageSyncRun>>(`/products/${productId}/sync/token-usage`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function getProductAiUsageSyncState(productId: string) {
  return apiRequest<ApiResponse<AiUsageSyncState | null>>(`/products/${productId}/ai-usage-sync-state`);
}

export function listProductAiUsageSyncRuns(productId: string, filters: { limit?: number; offset?: number } = {}) {
  return apiRequest<ApiResponse<AiUsageSyncRunListPayload>>(`/products/${productId}/ai-usage-sync-runs${queryString(filters)}`);
}
