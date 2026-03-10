import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchAssignments } from "../../entities/assignment/api/fetchAssignments";
import type { AssignmentStatus, AssignmentSummary } from "../../entities/assignment/model/assignment";

function statusLabel(status: AssignmentStatus): string {
  if (status === "open") {
    return "Открыта";
  }
  if (status === "submitted") {
    return "Сдана";
  }
  if (status === "submitted_late") {
    return "Сдана с опозданием";
  }
  if (status === "deadline_passed") {
    return "Дедлайн прошел";
  }
  return "Закрыта";
}

export function AssignmentsPage() {
  const navigate = useNavigate();
  const [assignments, setAssignments] = useState<AssignmentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchAssignments();
        setAssignments(data);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить задания");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  return (
    <section className="stack">
      <div className="panel dashboard-hero">
        <div>
          <p className="eyebrow">Личный кабинет студента</p>
          <h1>Лабораторные работы</h1>
          <p className="meta">
            Список обновляется автоматически: открытые работы, завершенные, с просрочкой и закрытые.
          </p>
        </div>
      </div>

      {loading ? <p>Загружаем задания...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}

      {!loading && !error ? (
        <div className="assignments-list">
          {assignments.map((assignment, index) => (
            <article
              key={assignment.id}
              className="assignment-row-card"
              style={{ animationDelay: `${index * 70}ms` }}
              role="link"
              tabIndex={0}
              onClick={() => navigate(`/assignments/${assignment.id}`)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  navigate(`/assignments/${assignment.id}`);
                }
              }}
            >
              <div className="assignment-row-card__top">
                <span className={`status-chip status-chip--${assignment.status}`}>{statusLabel(assignment.status)}</span>
                <p className="assignment-row-card__id">LR {String(assignment.id).padStart(2, "0")}</p>
              </div>

              <h3>{assignment.title}</h3>
              <p className="meta">Дедлайн: {new Date(assignment.deadline).toLocaleString()}</p>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
