import { apiRequest } from "@/lib/api";
import type { ApiResponse, DiscoveryListPayload, DiscoverySummary, ImportOrganizationsResult, ProductDeployment, ProductHealthCheckResult, ProductPayload } from "@/lib/types";

function cleanPayload(payload: ProductPayload): ProductPayload {
  return {
    ...payload,
    health_check_url: payload.health_check_url || null,
    organization_list_path: payload.organization_list_path || null,
    organization_detail_path_template: payload.organization_detail_path_template || null,
    admin_api_secret: payload.admin_api_secret || undefined
  };
}

export function listProducts() {
  return apiRequest<ApiResponse<ProductDeployment[]>>("/products");
}

export function createProduct(payload: ProductPayload) {
  return apiRequest<ApiResponse<ProductDeployment> & { meta?: { organization_discovery?: DiscoverySummary | null } }>("/products", {
    method: "POST",
    json: cleanPayload(payload)
  });
}

export function getProduct(productId: string) {
  return apiRequest<ApiResponse<ProductDeployment>>(`/products/${productId}`);
}

export function updateProduct(productId: string, payload: Partial<ProductPayload>) {
  return apiRequest<ApiResponse<ProductDeployment>>(`/products/${productId}`, {
    method: "PATCH",
    json: cleanPayload(payload as ProductPayload)
  });
}

export function runProductHealthCheck(productId: string) {
  return apiRequest<ApiResponse<ProductHealthCheckResult>>(`/products/${productId}/health-check`, {
    method: "POST"
  });
}

export function discoverProductOrganizations(productId: string) {
  return apiRequest<ApiResponse<DiscoverySummary>>(`/products/${productId}/organizations/discover`, {
    method: "POST"
  });
}

export function listDiscoveredOrganizations(productId: string) {
  return apiRequest<ApiResponse<DiscoveryListPayload>>(`/products/${productId}/organizations/discovered`);
}

export function importProductOrganizations(productId: string, productOrganizationIds: string[]) {
  return apiRequest<ApiResponse<ImportOrganizationsResult>>(`/products/${productId}/organizations/import`, {
    method: "POST",
    json: { product_organization_ids: productOrganizationIds }
  });
}

export function importAllProductOrganizations(productId: string, confirm: string) {
  return apiRequest<ApiResponse<ImportOrganizationsResult>>(`/products/${productId}/organizations/import-all`, {
    method: "POST",
    json: { confirm, limit: 100 }
  });
}

export function deleteProduct(productId: string) {
  return apiRequest<ApiResponse<{ deleted: boolean; dependency_summary: Record<string, number> }>>(`/products/${productId}`, {
    method: "DELETE"
  });
}

export function purgeTestProduct(productId: string, payload: { reason: string; confirmation: string }, idempotencyKey: string) {
  return apiRequest<ApiResponse<{ purged: boolean; dependency_summary: Record<string, number>; remote_product_deleted: boolean }>>(
    `/products/${productId}/purge-test-data`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      json: payload
    }
  );
}

export function getProductPurgePreview(productId: string) {
  return apiRequest<
    ApiResponse<{
      enabled: boolean;
      environment: string;
      remote_product_deleted: boolean;
      dependency_summary: Record<string, number>;
      confirmation_required: string[];
    }>
  >(`/products/${productId}/purge-test-data/preview`);
}
