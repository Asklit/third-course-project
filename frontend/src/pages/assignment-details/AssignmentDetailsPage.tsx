import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchAssignmentById } from "../../entities/assignment/api/fetchAssignmentById";
import { fetchSubmissionStatus } from "../../entities/assignment/api/fetchSubmissionStatus";
import type {
  AssignmentDetails,
  AssignmentStatus,
  AssignmentSubmissionStatus,
} from "../../entities/assignment/model/assignment";
import { fetchWikiLabByPath } from "../../entities/wiki/api/fetchWikiLabByPath";
import type { WikiLabDetails } from "../../entities/wiki/model/wiki";
import { submitAssignment } from "../../features/submission/api/submitAssignment";
import { markdownToHtml } from "../../shared/lib/markdown";

function extractErrorMessage(raw: unknown, fallback: string): string {
  if (!(raw instanceof Error)) {
    return fallback;
  }

  try {
    const payload = JSON.parse(raw.message) as { detail?: string };
    return payload.detail ?? raw.message;
  } catch {
    return raw.message || fallback;
  }
}

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

function formatFileSize(size: number): string {
  if (size < 1024) {
    return `${size} Б`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} КБ`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

export function AssignmentDetailsPage() {
  const { assignmentId } = useParams();
  const [assignment, setAssignment] = useState<AssignmentDetails | null>(null);
  const [submissionStatus, setSubmissionStatus] = useState<AssignmentSubmissionStatus | null>(null);
  const [wikiLab, setWikiLab] = useState<WikiLabDetails | null>(null);
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [codeFiles, setCodeFiles] = useState<File[]>([]);
  const [codeMode, setCodeMode] = useState<"file" | "link">("file");
  const [codeLink, setCodeLink] = useState("");
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [wikiLoading, setWikiLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wikiError, setWikiError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const reportInputRef = useRef<HTMLInputElement | null>(null);
  const codeInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!assignmentId) {
      setError("Не указан идентификатор задания");
      setLoading(false);
      return;
    }

    const currentAssignmentId = assignmentId;

    async function load() {
      try {
        const [assignmentData, statusData] = await Promise.all([
          fetchAssignmentById(currentAssignmentId),
          fetchSubmissionStatus(currentAssignmentId),
        ]);

        setAssignment(assignmentData);
        setSubmissionStatus(statusData);

        if (statusData.code_link) {
          setCodeMode("link");
          setCodeLink(statusData.code_link);
        }

        try {
          const wikiData = await fetchWikiLabByPath(assignmentData.wiki_url);
          setWikiLab(wikiData);
        } catch (loadWikiError) {
          setWikiError(extractErrorMessage(loadWikiError, "Не удалось загрузить материал wiki"));
        }
      } catch (loadError) {
        setError(extractErrorMessage(loadError, "Не удалось загрузить задание"));
      } finally {
        setLoading(false);
        setWikiLoading(false);
      }
    }

    void load();
  }, [assignmentId]);

  const wikiHtml = useMemo(() => markdownToHtml(wikiLab?.content_md ?? ""), [wikiLab?.content_md]);

  const isSubmitDisabled =
    submitting ||
    !submissionStatus?.can_submit ||
    (assignment?.requires_report_docx && !reportFile) ||
    (codeMode === "file" ? codeFiles.length === 0 : codeLink.trim().length === 0);

  function onSelectReport(fileList: FileList | null) {
    setReportFile(fileList?.[0] ?? null);
  }

  function onSelectCodeFiles(fileList: FileList | null) {
    const selected = Array.from(fileList ?? []);
    if (selected.length === 0) {
      return;
    }
    setCodeFiles((current) => [...current, ...selected]);
    if (codeInputRef.current) {
      codeInputRef.current.value = "";
    }
  }

  function removeCodeFile(index: number) {
    setCodeFiles((current) => current.filter((_, currentIndex) => currentIndex !== index));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignmentId || !submissionStatus?.can_submit) {
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await submitAssignment(assignmentId, {
        reportFile,
        codeFiles,
        meta: {
          assignment_id: assignmentId,
          comment,
          submitted_at: new Date().toISOString(),
          code_mode: codeMode,
          code_link: codeMode === "link" ? codeLink : "",
        },
      });

      const isUpdate = submissionStatus?.submitted;
      const assignmentLabel = assignment ? `LR${String(assignment.id).padStart(2, "0")}` : `#${assignmentId}`;
      setSuccess(
        isUpdate
          ? `${assignmentLabel}: сдача обновлена (ID сдачи ${result.submission_id})`
          : `${assignmentLabel}: работа принята (ID сдачи ${result.submission_id})`,
      );
      setReportFile(null);
      setCodeFiles([]);
      setComment("");
      if (reportInputRef.current) {
        reportInputRef.current.value = "";
      }
      if (codeInputRef.current) {
        codeInputRef.current.value = "";
      }

      const freshStatus = await fetchSubmissionStatus(assignmentId);
      setSubmissionStatus(freshStatus);
    } catch (submitError) {
      setError(extractErrorMessage(submitError, "Не удалось отправить работу"));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <p>Загружаем задание...</p>;
  }

  if (!assignment) {
    return <p className="error-text">{error ?? "Задание не найдено"}</p>;
  }

  return (
    <section className="page-grid page-grid--details">
      <div className="stack">
        <article className="panel assignment-hero">
          <div className="assignment-hero__head">
            <Link to="/assignments" className="link-muted">
              Назад к списку
            </Link>
            <span className={`status-chip status-chip--${assignment.status}`}>{statusLabel(assignment.status)}</span>
          </div>
          <h1>{assignment.title}</h1>
          <p className="meta">Дедлайн: {new Date(assignment.deadline).toLocaleString()}</p>
          <p>{assignment.description}</p>
        </article>

        <article className="panel submit-status-card submit-status-card--rich">
          <h3>Статус сдачи</h3>
          {submissionStatus?.submitted ? (
            <>
              <p className="success-text">
                Сдано {submissionStatus.submitted_at ? new Date(submissionStatus.submitted_at).toLocaleString() : ""}
              </p>
              {submissionStatus.submitted_late ? <p className="warning-text">Сдано после дедлайна</p> : null}
              {submissionStatus.code_link ? (
                <p>
                  Ссылка на код:{" "}
                  <a href={submissionStatus.code_link} target="_blank" rel="noreferrer">
                    {submissionStatus.code_link}
                  </a>
                </p>
              ) : null}
            </>
          ) : (
            <p className="meta">Работа еще не сдана</p>
          )}
        </article>

        <form className="panel form form--rich" onSubmit={onSubmit}>
          <h2>{submissionStatus?.submitted ? "Обновить сдачу" : "Сдача работы"}</h2>

          <section className="submission-block">
            <h3>1. Отчет</h3>
            <p className="meta">Только файл формата .docx</p>

            <div className="input-file-row">
              <label className="input-file">
                <input
                  ref={reportInputRef}
                  type="file"
                  accept=".docx"
                  onChange={(event) => onSelectReport(event.target.files)}
                  disabled={!submissionStatus?.can_submit}
                  required={assignment.requires_report_docx}
                />
                <span>Выберите файл</span>
              </label>

              <div className="input-file-list">
                {reportFile ? (
                  <div className="input-file-list-item">
                    <span className="input-file-list-name">{reportFile.name}</span>
                    <span className="input-file-list-meta">{formatFileSize(reportFile.size)}</span>
                    <button
                      type="button"
                      className="input-file-list-remove"
                      onClick={() => {
                        setReportFile(null);
                        if (reportInputRef.current) {
                          reportInputRef.current.value = "";
                        }
                      }}
                      aria-label="Удалить файл"
                    >
                      x
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          <section className="submission-block">
            <h3>2. Код</h3>
            <div className="mode-selector" role="radiogroup" aria-label="Режим сдачи кода">
              <label className={`mode-option ${codeMode === "file" ? "mode-option--active" : ""}`}>
                <input
                  className="mode-option__input"
                  type="radio"
                  name="codeMode"
                  checked={codeMode === "file"}
                  onChange={() => setCodeMode("file")}
                  disabled={!submissionStatus?.can_submit}
                />
                <span className="mode-option__title">Файлы с кодом</span>
                <span className="mode-option__desc">Загрузите исходники архивом или отдельными файлами</span>
              </label>
              <label className={`mode-option ${codeMode === "link" ? "mode-option--active" : ""}`}>
                <input
                  className="mode-option__input"
                  type="radio"
                  name="codeMode"
                  checked={codeMode === "link"}
                  onChange={() => setCodeMode("link")}
                  disabled={!submissionStatus?.can_submit}
                />
                <span className="mode-option__title">Ссылка на репозиторий</span>
                <span className="mode-option__desc">GitHub, GitLab или Google Drive</span>
              </label>
            </div>

            {codeMode === "file" ? (
              <div className="input-file-row">
                <label className="input-file">
                  <input
                    ref={codeInputRef}
                    type="file"
                    multiple
                    onChange={(event) => onSelectCodeFiles(event.target.files)}
                    disabled={!submissionStatus?.can_submit}
                  />
                  <span>Выберите файлы</span>
                </label>

                <div className="input-file-list">
                  {codeFiles.map((file, index) => (
                    <div className="input-file-list-item" key={`${file.name}-${file.size}-${index}`}>
                      <span className="input-file-list-name">{file.name}</span>
                      <span className="input-file-list-meta">{formatFileSize(file.size)}</span>
                      <button
                        type="button"
                        className="input-file-list-remove"
                        onClick={() => removeCodeFile(index)}
                        aria-label="Удалить файл"
                      >
                        x
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <label className="field">
                <span className="field__label">Ссылка на код</span>
                <input
                  type="url"
                  placeholder="https://github.com/..."
                  value={codeLink}
                  onChange={(event) => setCodeLink(event.target.value)}
                  disabled={!submissionStatus?.can_submit}
                />
              </label>
            )}
          </section>

          <label className="field">
            <span className="field__label">Комментарий</span>
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={4}
              placeholder="Необязательный комментарий"
              disabled={!submissionStatus?.can_submit}
            />
          </label>

          {error ? <p className="error-text">{error}</p> : null}
          {success ? <p className="success-text">{success}</p> : null}

          <button className="btn btn--primary" type="submit" disabled={isSubmitDisabled}>
            {submitting ? "Отправляем..." : submissionStatus?.submitted ? "Обновить файлы" : "Отправить работу"}
          </button>
        </form>
      </div>

      <aside className="panel panel--wiki">
        <h2>Материалы Wiki</h2>
        {wikiLoading ? <p>Загружаем материалы...</p> : null}
        {wikiError ? <p className="error-text">{wikiError}</p> : null}

        {!wikiLoading && !wikiError && wikiLab ? (
          <article className="markdown" dangerouslySetInnerHTML={{ __html: wikiHtml }} />
        ) : null}
      </aside>
    </section>
  );
}
