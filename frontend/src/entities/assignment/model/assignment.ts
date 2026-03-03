export type AssignmentSummary = {
  id: string;
  title: string;
  deadline: string;
  status: "open" | "submitted" | "closed";
};

export type AssignmentDetails = {
  id: string;
  title: string;
  description: string;
  deadline: string;
  wiki_url: string;
  status: "open" | "submitted" | "closed";
};
