import { apiClient } from "../../../shared/api/client";
import type { AssignmentSummary } from "../model/assignment";

export function fetchAssignments() {
  return apiClient<AssignmentSummary[]>("/assignments", {
    method: "GET",
  });
}
