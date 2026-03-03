import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchAssignmentById } from "../../entities/assignment/api/fetchAssignmentById";
import type { AssignmentDetails } from "../../entities/assignment/model/assignment";
import { submitAssignment } from "../../features/submission/api/submitAssignment";

export function AssignmentDetailsPage() {
  const { assignmentId } = useParams();
  const [assignment, setAssignment] = useState<AssignmentDetails | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!assignmentId) {
      setError("Assignment id is missing");
      setLoading(false);
      return;
    }
    const currentAssignmentId = assignmentId;

    async function load() {
      try {
        const data = await fetchAssignmentById(currentAssignmentId);
        setAssignment(data);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load assignment");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [assignmentId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignmentId) {
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await submitAssignment(assignmentId, files, {
        assignment_id: assignmentId,
        comment,
        submitted_at: new Date().toISOString(),
      });
      setSuccess(`Submission accepted: ${result.submission_id}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <p>Loading assignment...</p>
      </div>
    );
  }

  if (!assignment) {
    return (
      <div className="page">
        <p className="error">{error ?? "Assignment not found"}</p>
      </div>
    );
  }

  return (
    <div className="page">
      <Link to="/assignments">Back to assignments</Link>
      <div className="card">
        <h1>{assignment.title}</h1>
        <p>{assignment.description}</p>
        <p>Deadline: {new Date(assignment.deadline).toLocaleString()}</p>
        <p>Status: {assignment.status}</p>
        <a href={assignment.wiki_url} target="_blank" rel="noreferrer">
          Open wiki materials
        </a>
      </div>

      <form className="card" onSubmit={onSubmit}>
        <h2>Submit work</h2>
        <label>
          Files (code and/or doc/docx)
          <input
            type="file"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            required
          />
        </label>

        <label>
          Comment
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            rows={4}
            placeholder="Optional comment"
          />
        </label>

        {error ? <p className="error">{error}</p> : null}
        {success ? <p className="success">{success}</p> : null}

        <button type="submit" disabled={submitting || files.length === 0}>
          {submitting ? "Submitting..." : "Submit"}
        </button>
      </form>
    </div>
  );
}
