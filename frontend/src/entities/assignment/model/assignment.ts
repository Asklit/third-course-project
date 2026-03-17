export type AssignmentStatus = "open" | "submitted" | "submitted_late" | "closed" | "deadline_passed";

export type AssignmentSummary = {
  id: number;
  title: string;
  deadline: string;
  status: AssignmentStatus;
};

export type AssignmentDetails = {
  id: number;
  title: string;
  description: string;
  deadline: string;
  wiki_url: string;
  status: AssignmentStatus;
  requires_report_docx: boolean;
  code_submission_mode: "file_or_link";
};

export type AssignmentSubmissionStatus = {
  submitted: boolean;
  submitted_at: string | null;
  submission_id: number | null;
  status: "submitted" | "not_submitted";
  can_submit: boolean;
  report_file_name: string | null;
  code_link: string | null;
  code_file_names: string[] | null;
  report_submitted: boolean;
  code_submitted: boolean;
  submitted_late: boolean;
};
