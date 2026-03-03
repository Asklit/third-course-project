import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../app/providers/AuthProvider";
import { fetchAssignments } from "../../entities/assignment/api/fetchAssignments";
import type { AssignmentSummary } from "../../entities/assignment/model/assignment";

export function AssignmentsPage() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [assignments, setAssignments] = useState<AssignmentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchAssignments();
        setAssignments(data);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load assignments");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  return (
    <div className="page">
      <div className="header-row">
        <h1>Assignments</h1>
        <button
          type="button"
          onClick={() => {
            logout();
            navigate("/login");
          }}
        >
          Logout
        </button>
      </div>

      {loading ? <p>Loading assignments...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <ul className="list">
        {assignments.map((assignment) => (
          <li className="card" key={assignment.id}>
            <h2>{assignment.title}</h2>
            <p>Deadline: {new Date(assignment.deadline).toLocaleString()}</p>
            <p>Status: {assignment.status}</p>
            <Link to={`/assignments/${assignment.id}`}>Open</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
