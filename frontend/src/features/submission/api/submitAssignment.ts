import { apiClient } from "../../../shared/api/client";

export type SubmissionMeta = {
  assignment_id: string;
  comment?: string;
  submitted_at: string;
  code_mode: "file" | "link";
  code_link?: string;
};

export function submitAssignment(
  assignmentId: string,
  payload: {
    reportFile: File | null;
    codeFiles: File[];
    meta: SubmissionMeta;
  },
) {
  const formData = new FormData();

  if (payload.reportFile) {
    formData.append("report_file", payload.reportFile);
  }

  payload.codeFiles.forEach((file) => formData.append("code_files[]", file));
  formData.append("submission_meta", JSON.stringify(payload.meta));

  return apiClient<{ status: string; submission_id: number }>(
    `/assignments/${assignmentId}/submit`,
    {
      method: "POST",
      body: formData,
      isFormData: true,
    },
  );
}

