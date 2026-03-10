import { apiClient } from "../../../shared/api/client";
import type { AssignmentSubmissionStatus } from "../model/assignment";

export function fetchSubmissionStatus(assignmentId: string) {
  return apiClient<AssignmentSubmissionStatus>(`/assignments/${assignmentId}/submission-status`, {
    method: "GET",
  });
}
