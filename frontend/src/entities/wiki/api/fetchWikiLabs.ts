import { apiClient } from "../../../shared/api/client";
import type { WikiLabSummary } from "../model/wiki";

export function fetchWikiLabs(params?: { tag?: string; kind?: string }) {
  const query = new URLSearchParams();
  if (params?.tag) {
    query.set("tag", params.tag);
  }
  if (params?.kind) {
    query.set("kind", params.kind);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiClient<WikiLabSummary[]>(`/wiki/labs${suffix}`);
}
