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

  let response: Response;
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      method: options.method ?? "GET",
      body: options.body,
      headers,
    });
  } catch {
    throw new Error("Не удалось подключиться к серверу. Проверьте, что backend запущен.");
  }

  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const parsed = JSON.parse(raw) as { detail?: string };
      if (parsed.detail) {
        detail = parsed.detail;
      }
    } catch {
      // keep raw text
    }

    if (response.status === 401) {
      throw new Error("Сессия истекла. Войдите заново.");
    }

    if (response.status >= 500) {
      throw new Error(detail ? `Ошибка сервера (${response.status}): ${detail}` : `Ошибка сервера (${response.status}).`);
    }

    throw new Error(detail || `Ошибка API: ${response.status}`);
  }

  return response.json() as Promise<T>;
}
