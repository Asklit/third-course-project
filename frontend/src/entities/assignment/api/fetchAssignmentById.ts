import { apiClient } from "../../../shared/api/client";
import type { AssignmentDetails } from "../model/assignment";

export function fetchAssignmentById(assignmentId: string) {
  return apiClient<AssignmentDetails>(`/assignments/${assignmentId}`, {
    method: "GET",
  });
}
