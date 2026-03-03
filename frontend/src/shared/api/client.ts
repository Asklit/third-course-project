import { env } from "../config/env";
import { storage } from "../lib/storage";

type ApiOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: BodyInit | null;
  isFormData?: boolean;
};

const ACCESS_TOKEN_KEY = "lms_access_token";

export async function apiClient<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const token = storage.getItem(ACCESS_TOKEN_KEY);

  const headers = new Headers();
  if (!options.isFormData) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    method: options.method ?? "GET",
    body: options.body,
    headers,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `API error: ${response.status}`);
  }

  return response.json() as Promise<T>;
}
