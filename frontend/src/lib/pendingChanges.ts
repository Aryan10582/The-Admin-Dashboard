import { apiRequest } from "@/lib/api";
import type { ApiResponse, PendingChange, PendingChangeListPayload } from "@/lib/types";

export type PendingChangeFilters = {
  limit?: number;
  offset?: number;
  status?: string;
  action?: string;
  organization_id?: string;
  product_deployment_id?: string;
  product_name?: string;
  region?: string;
  environment?: string;
  admin_id?: string;
  date_from?: string;
  date_to?: string;
};

export type PendingChangeActionPayload = {
  reason: string;
};

function queryString(filters: PendingChangeFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

function writeOptions(payload: PendingChangeActionPayload, idempotencyKey: string) {
  return {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  };
}

export function listPendingChanges(filters: PendingChangeFilters = {}) {
  return apiRequest<ApiResponse<PendingChangeListPayload>>(`/pending-changes${queryString(filters)}`);
}

export function getPendingChange(pendingChangeId: string) {
  return apiRequest<ApiResponse<PendingChange>>(`/pending-changes/${pendingChangeId}`);
}

export function cancelPendingChange(pendingChangeId: string, payload: PendingChangeActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<PendingChange>>(
    `/pending-changes/${pendingChangeId}/cancel`,
    writeOptions(payload, idempotencyKey)
  );
}

export function markPendingChangeManualResolution(pendingChangeId: string, payload: PendingChangeActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<PendingChange>>(
    `/pending-changes/${pendingChangeId}/mark-manual-resolution`,
    writeOptions(payload, idempotencyKey)
  );
}

export function retryPendingChange(pendingChangeId: string, payload: PendingChangeActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<{
    pending_change_id: string;
    action: string;
    status: string;
    product_request_id: string | null;
    safe_result: Record<string, unknown> | null;
    error: string | null;
  }>>(
    `/pending-changes/${pendingChangeId}/retry`,
    writeOptions(payload, idempotencyKey)
  );
}
