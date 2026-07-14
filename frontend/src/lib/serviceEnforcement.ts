import { apiRequest } from "@/lib/api";
import type { ApiResponse, ServiceActionResult, ServiceEnforcement } from "@/lib/types";

export type ServiceActionPayload = {
  reason: string;
};

function writeOptions(payload: ServiceActionPayload, idempotencyKey: string) {
  return {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  };
}

export function getServiceEnforcement(organizationId: string) {
  return apiRequest<ApiResponse<ServiceEnforcement>>(`/organizations/${organizationId}/service-enforcement`);
}

export function pauseService(organizationId: string, payload: ServiceActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<ServiceActionResult>>(
    `/organizations/${organizationId}/service/pause`,
    writeOptions(payload, idempotencyKey)
  );
}

export function resumeService(organizationId: string, payload: ServiceActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<ServiceActionResult>>(
    `/organizations/${organizationId}/service/resume`,
    writeOptions(payload, idempotencyKey)
  );
}

export function disableService(organizationId: string, payload: ServiceActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<ServiceActionResult>>(
    `/organizations/${organizationId}/service/disable`,
    writeOptions(payload, idempotencyKey)
  );
}

export function applyManualContinuation(organizationId: string, payload: ServiceActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<ServiceActionResult>>(
    `/organizations/${organizationId}/manual-continuation/apply`,
    writeOptions(payload, idempotencyKey)
  );
}

export function removeManualContinuation(organizationId: string, payload: ServiceActionPayload, idempotencyKey: string) {
  return apiRequest<ApiResponse<ServiceActionResult>>(
    `/organizations/${organizationId}/manual-continuation/remove`,
    writeOptions(payload, idempotencyKey)
  );
}
