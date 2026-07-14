import { apiRequest } from "@/lib/api";
import type {
  ApiResponse,
  BillingMode,
  BillingPlan,
  BillingPlanListPayload,
  BillingPlanPayload,
  BillingPlanVersion,
  BillingPlanVersionPayload,
  OrganizationPlanAssignmentState,
  PlanAssignment,
  PlanAssignmentResult
} from "@/lib/types";

export type PlanFilters = {
  search?: string;
  product_deployment_id?: string;
  currency?: string;
  is_active?: string;
  limit?: number;
  offset?: number;
};

function queryString(filters: PlanFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

function parseJsonObject(value: string, fallback: Record<string, unknown> | null = {}) {
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON fields must be objects.");
  }
  return parsed as Record<string, unknown>;
}

export function listPlans(filters: PlanFilters = {}) {
  return apiRequest<ApiResponse<BillingPlanListPayload>>(`/plans${queryString(filters)}`);
}

export function createPlan(payload: BillingPlanPayload) {
  return apiRequest<ApiResponse<BillingPlan>>("/plans", {
    method: "POST",
    json: {
      ...payload,
      description: payload.description || null,
      currency: payload.currency.toUpperCase()
    }
  });
}

export function updatePlan(planId: string, payload: Partial<Pick<BillingPlanPayload, "name" | "description" | "is_active">>) {
  return apiRequest<ApiResponse<BillingPlan>>(`/plans/${planId}`, {
    method: "PATCH",
    json: payload
  });
}

export function getPlan(planId: string) {
  return apiRequest<ApiResponse<BillingPlan>>(`/plans/${planId}`);
}

export function listPlanVersions(planId: string) {
  return apiRequest<ApiResponse<BillingPlanVersion[]>>(`/plans/${planId}/versions`);
}

export function createPlanVersion(
  planId: string,
  payload: Omit<BillingPlanVersionPayload, "pricing_structure" | "limits" | "overage_pricing" | "billing_mode_compatibility"> & {
    billing_mode_compatibility: BillingMode;
    pricing_structure: string;
    limits?: string;
    overage_pricing?: string;
  }
) {
  return apiRequest<ApiResponse<BillingPlanVersion>>(`/plans/${planId}/versions`, {
    method: "POST",
    json: {
      ...payload,
      currency: payload.currency.toUpperCase(),
      pricing_structure: parseJsonObject(payload.pricing_structure, {}),
      limits: parseJsonObject(payload.limits || "", null),
      overage_pricing: parseJsonObject(payload.overage_pricing || "", null),
      effective_to: payload.effective_to || null,
      external_product_plan_id: payload.external_product_plan_id || null
    }
  });
}

export function getOrganizationPlanAssignment(organizationId: string) {
  return apiRequest<ApiResponse<OrganizationPlanAssignmentState>>(`/organizations/${organizationId}/plan-assignment`);
}

export function listOrganizationPlanHistory(organizationId: string) {
  return apiRequest<ApiResponse<PlanAssignment[]>>(`/organizations/${organizationId}/plan-assignment-history`);
}

export function assignOrganizationPlan(organizationId: string, payload: { billing_plan_version_id: string; reason: string }, idempotencyKey: string) {
  return apiRequest<ApiResponse<PlanAssignmentResult>>(`/organizations/${organizationId}/plan-assignment`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    json: payload
  });
}
