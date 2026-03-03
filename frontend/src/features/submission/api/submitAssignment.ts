import { apiClient } from "../../../shared/api/client";

export type SubmissionMeta = {
  assignment_id: string;
  comment?: string;
  submitted_at: string;
};

export function submitAssignment(assignmentId: string, files: File[], meta: SubmissionMeta) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files[]", file));
  formData.append("submission_meta", JSON.stringify(meta));

  return apiClient<{ status: string; submission_id: string }>(
    `/assignments/${assignmentId}/submit`,
    {
      method: "POST",
      body: formData,
      isFormData: true,
    },
  );
}
