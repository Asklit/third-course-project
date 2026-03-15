import { apiClient } from "../../../shared/api/client";
import type { WikiLabDetails } from "../model/wiki";

export function fetchWikiLabBySlug(slug: string) {
  return apiClient<WikiLabDetails>(`/wiki/labs/${slug}`);
}
