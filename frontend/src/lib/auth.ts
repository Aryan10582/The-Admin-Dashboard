import { apiRequest } from "@/lib/api";
import type { ApiResponse, AuthPayload } from "@/lib/types";

export function getCurrentAdmin() {
  return apiRequest<ApiResponse<AuthPayload>>("/auth/me");
}

export function login(email: string, password: string) {
  return apiRequest<ApiResponse<AuthPayload>>("/auth/login", {
    method: "POST",
    json: { email, password }
  });
}

export function logout() {
  return apiRequest<ApiResponse<{ logged_out: boolean }>>("/auth/logout", {
    method: "POST"
  });
}
