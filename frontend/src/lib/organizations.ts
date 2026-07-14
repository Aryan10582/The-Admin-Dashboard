import { apiRequest } from "@/lib/api";
import type {
  ApiResponse,
  MappingVerificationResult,
  Organization,
  OrganizationListPayload,
  OrganizationMapping,
  OrganizationMappingPayload,
  OrganizationPayload
} from "@/lib/types";

export type OrganizationFilters = {
  limit?: number;
  offset?: number;
  product_deployment_id?: string;
  product_name?: string;
  region?: string;
  environment?: string;
  currency?: string;
  lifecycle_status?: string;
  billing_mode?: string;
  billing_calculation_status?: string;
  credit_status?: string;
  service_status?: string;
  sync_status?: string;
  mapping_status?: string;
  search?: string;
  last_active_from?: string;
  last_active_to?: string;
};

function queryString(filters: OrganizationFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

function cleanOrganizationPayload(payload: Partial<OrganizationPayload>) {
  return {
    ...payload,
    currency: payload.currency?.toUpperCase(),
    last_active_at: payload.last_active_at || null
  };
}

function cleanMappingPayload(payload: OrganizationMappingPayload) {
  return {
    ...payload,
    product_organization_id: payload.product_organization_id || null,
    external_billing_id: payload.external_billing_id || null,
    external_customer_id: payload.external_customer_id || null,
    external_plan_id: payload.external_plan_id || null,
    external_subscription_id: payload.external_subscription_id || null
  };
}

export function listOrganizations(filters: OrganizationFilters = {}) {
  return apiRequest<ApiResponse<OrganizationListPayload>>(`/organizations${queryString(filters)}`);
}

export function createOrganization(payload: OrganizationPayload) {
  return apiRequest<ApiResponse<Organization>>("/organizations", {
    method: "POST",
    json: cleanOrganizationPayload(payload)
  });
}

export function getOrganization(organizationId: string) {
  return apiRequest<ApiResponse<Organization>>(`/organizations/${organizationId}`);
}

export function updateOrganization(organizationId: string, payload: Partial<OrganizationPayload>) {
  return apiRequest<ApiResponse<Organization>>(`/organizations/${organizationId}`, {
    method: "PATCH",
    json: cleanOrganizationPayload(payload)
  });
}

export function getOrganizationMapping(organizationId: string) {
  return apiRequest<ApiResponse<OrganizationMapping | null>>(`/organizations/${organizationId}/mapping`);
}

export function updateOrganizationMapping(organizationId: string, payload: OrganizationMappingPayload) {
  return apiRequest<ApiResponse<OrganizationMapping>>(`/organizations/${organizationId}/mapping`, {
    method: "PATCH",
    json: cleanMappingPayload(payload)
  });
}

export function verifyOrganizationMapping(organizationId: string) {
  return apiRequest<ApiResponse<MappingVerificationResult>>(`/organizations/${organizationId}/verify-mapping`, {
    method: "POST"
  });
}
