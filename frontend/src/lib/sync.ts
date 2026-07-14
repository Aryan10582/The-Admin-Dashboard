import { apiRequest } from "@/lib/api";
import type {
  ApiResponse,
  FailureLogListPayload,
  MappingSyncResult,
  OrganizationSyncResult,
  ProductDeployment,
  ProductSyncResult,
  SyncStatusPayload
} from "@/lib/types";

export type FailureFilters = {
  limit?: number;
  offset?: number;
  product_deployment_id?: string;
  organization_id?: string;
  pending_change_id?: string;
  action?: string;
  failure_category?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
};

function queryString(filters: FailureFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function getSyncStatus() {
  return apiRequest<ApiResponse<SyncStatusPayload>>("/sync/status");
}

export function syncProduct(productId: string) {
  return apiRequest<ApiResponse<ProductSyncResult>>(`/products/${productId}/sync`, {
    method: "POST"
  });
}

export function syncProductHealth(productId: string) {
  return apiRequest<ApiResponse<ProductDeployment>>(`/products/${productId}/sync/health`, {
    method: "POST"
  });
}

export function syncProductOrganizations(productId: string) {
  return apiRequest<ApiResponse<MappingSyncResult>>(`/products/${productId}/sync/organizations`, {
    method: "POST"
  });
}

export function syncOrganization(organizationId: string) {
  return apiRequest<ApiResponse<OrganizationSyncResult>>(`/organizations/${organizationId}/sync`, {
    method: "POST"
  });
}

export function listFailures(filters: FailureFilters = {}) {
  return apiRequest<ApiResponse<FailureLogListPayload>>(`/failures${queryString(filters)}`);
}
