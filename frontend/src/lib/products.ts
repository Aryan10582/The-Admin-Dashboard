import { apiRequest } from "@/lib/api";
import type { ApiResponse, ProductDeployment, ProductHealthCheckResult, ProductPayload } from "@/lib/types";

function cleanPayload(payload: ProductPayload): ProductPayload {
  return {
    ...payload,
    health_check_url: payload.health_check_url || null,
    admin_api_secret: payload.admin_api_secret || undefined
  };
}

export function listProducts() {
  return apiRequest<ApiResponse<ProductDeployment[]>>("/products");
}

export function createProduct(payload: ProductPayload) {
  return apiRequest<ApiResponse<ProductDeployment>>("/products", {
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
