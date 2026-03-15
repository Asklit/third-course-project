import { apiClient } from "../../../shared/api/client";
import type { WikiSearchResponse } from "../model/wiki";

export type WikiSearchParams = {
  q?: string;
  tag?: string;
  kind?: string;
  lab_slug?: string;
  limit?: number;
};

export function searchWiki(params: WikiSearchParams) {
  const query = new URLSearchParams();
  if (params.q) {
    query.set("q", params.q);
  }
  if (params.tag) {
    query.set("tag", params.tag);
  }
  if (params.kind) {
    query.set("kind", params.kind);
  }
  if (params.lab_slug) {
    query.set("lab_slug", params.lab_slug);
  }
  query.set("limit", String(params.limit ?? 30));

  return apiClient<WikiSearchResponse>(`/wiki/search?${query.toString()}`);
}
