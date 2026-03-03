import { apiClient } from "../../../shared/api/client";
import type { AuthTokens, LoginRequest } from "../../../shared/types/auth";

export function loginStudent(payload: LoginRequest) {
  return apiClient<AuthTokens>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
