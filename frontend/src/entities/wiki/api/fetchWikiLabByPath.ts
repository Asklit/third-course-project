import { apiClient } from "../../../shared/api/client";
import type { WikiLabDetails } from "../model/wiki";

export function fetchWikiLabByPath(path: string) {
  return apiClient<WikiLabDetails>(path, { method: "GET" });
}
