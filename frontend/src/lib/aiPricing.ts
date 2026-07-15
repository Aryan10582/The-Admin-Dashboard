import { apiRequest } from "@/lib/api";
import type {
  AiPricingCatalog,
  AiPricingCatalogListPayload,
  AiPricingCatalogPayload,
  AiPricingVersion,
  AiPricingVersionPayload,
  AiPriceCheckRun,
  AiPriceCheckRunListPayload,
  ApiResponse
} from "@/lib/types";

export type AiPricingFilters = {
  search?: string;
  provider?: string;
  provider_model_id?: string;
  pricing_scope_code?: string;
  currency?: string;
  is_active?: string;
  has_current_version?: string;
  has_future_version?: string;
  limit?: number;
  offset?: number;
};

function queryString(filters: Record<string, string | number | boolean | undefined> = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

function localDateTimeToUtc(value: string) {
  if (!value) return "";
  return new Date(value).toISOString();
}

export function listAiPricing(filters: AiPricingFilters = {}) {
  return apiRequest<ApiResponse<AiPricingCatalogListPayload>>(`/ai/pricing${queryString(filters)}`);
}

export function createAiPricingCatalog(payload: AiPricingCatalogPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiPricingCatalog>>("/ai/pricing", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: {
      ...payload,
      currency: payload.currency.toUpperCase(),
      description: payload.description || null
    }
  });
}

export function getAiPricingCatalog(pricingId: string) {
  return apiRequest<ApiResponse<AiPricingCatalog>>(`/ai/pricing/${pricingId}`);
}

export function updateAiPricingCatalog(
  pricingId: string,
  payload: Pick<AiPricingCatalogPayload, "display_name" | "description" | "is_active" | "reason">
) {
  return apiRequest<ApiResponse<AiPricingCatalog>>(`/ai/pricing/${pricingId}`, {
    method: "PATCH",
    json: { ...payload, description: payload.description || null }
  });
}

export function listAiPricingVersions(pricingId: string) {
  return apiRequest<ApiResponse<AiPricingVersion[]>>(`/ai/pricing/${pricingId}/versions`);
}

export function createAiPricingVersion(pricingId: string, payload: AiPricingVersionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiPricingVersion>>(`/ai/pricing/${pricingId}/versions`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: {
      ...payload,
      effective_from: localDateTimeToUtc(payload.effective_from),
      effective_to: payload.effective_to ? localDateTimeToUtc(payload.effective_to) : null,
      source_reference: payload.source_reference || null
    }
  });
}

export function runAiPricingCheck(payload: { pricing_catalog_id: string; reason: string; adapter_code?: string; mock_scenario?: string }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiPriceCheckRun>>("/ai/pricing/sync-check", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function listAiPricingCheckRuns(
  filters: {
    pricing_catalog_id?: string;
    provider?: string;
    status?: string;
    reviewed?: string;
    source_fingerprint?: string;
    started_from?: string;
    started_to?: string;
    limit?: number;
    offset?: number;
  } = {}
) {
  return apiRequest<ApiResponse<AiPriceCheckRunListPayload>>(`/ai/pricing/check-runs${queryString(filters)}`);
}

export function getAiPricingCheckRun(checkRunId: string) {
  return apiRequest<ApiResponse<AiPriceCheckRun>>(`/ai/pricing/check-runs/${checkRunId}`);
}

export function approveAiPricingCheckRun(checkRunId: string, payload: { reason: string }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiPriceCheckRun>>(`/ai/pricing/check-runs/${checkRunId}/approve`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}

export function rejectAiPricingCheckRun(checkRunId: string, payload: { reason: string }, idempotencyKey: string) {
  return apiRequest<ApiResponse<AiPriceCheckRun>>(`/ai/pricing/check-runs/${checkRunId}/reject`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}
