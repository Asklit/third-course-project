import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchAssignmentById } from "../../entities/assignment/api/fetchAssignmentById";
import { fetchSubmissionStatus } from "../../entities/assignment/api/fetchSubmissionStatus";
import type {
  AssignmentDetails,
  AssignmentStatus,
  AssignmentSubmissionStatus,
} from "../../entities/assignment/model/assignment";
import { submitAssignment } from "../../features/submission/api/submitAssignment";

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

function humanizeSubmissionError(message: string): string {
  const normalized = message.toLowerCase();

  if (normalized.includes("отчет должен быть в формате .docx")) {
    return "Отчет нужно загрузить в формате .docx.";
  }
  if (normalized.includes("нужно приложить отчет, код или обе части")) {
    return "Выберите, что хотите отправить: отчет, код или обе части.";
  }
  if (normalized.includes("не приложен файл с кодом")) {
    return "Добавьте хотя бы один файл с кодом или переключитесь на отправку ссылкой.";
  }
  if (normalized.includes("ссылка на код должна вести на github/gitlab/google drive")) {
    return "Проверьте ссылку на код. Поддерживаются GitHub, GitLab и Google Drive.";
  }
  if (normalized.includes("нет изменений для сохранения")) {
    return "Вы пока ничего не изменили. Выберите файл, ссылку или удаление текущей части.";
  }
  if (normalized.includes("нельзя удалить отчет и код одновременно")) {
    return "Нужно оставить хотя бы одну часть работы: отчет или код.";
  }
  if (normalized.includes("assignment_id не совпадает с url")) {
    return "Не удалось сохранить работу из-за несовпадения параметров запроса.";
  }
  if (normalized.includes("задание не найдено")) {
    return "Не удалось найти это задание.";
  }
  if (normalized.includes("сдача по этому заданию закрыта")) {
    return "Срок сдачи уже закрыт. Изменить отправку сейчас нельзя.";
  }
  if (normalized.includes("задание пока недоступно")) {
    return "Это задание еще недоступно для сдачи.";
  }
  return message;
}

function statusLabel(status: AssignmentStatus): string {
  if (status === "open") return "Открыта";
  if (status === "submitted") return "Сдана";
  if (status === "submitted_late") return "Сдана с опозданием";
  if (status === "deadline_passed") return "Дедлайн прошел";
  return "Закрыта";
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function reportStatusLabel(status: AssignmentSubmissionStatus | null): string {
  if (!status?.report_submitted) return "не загружен";
  return status.report_file_name ?? "загружен";
}

function codeStatusLabel(status: AssignmentSubmissionStatus | null): string {
  if (!status?.code_submitted) return "не загружен";
  if (status.code_link) return "ссылка сохранена";
  if (status.code_file_names?.length) return status.code_file_names.join(", ");
  return "загружен";
}

export function AssignmentDetailsPage() {
  const { assignmentId } = useParams();
  const [assignment, setAssignment] = useState<AssignmentDetails | null>(null);
  const [submissionStatus, setSubmissionStatus] = useState<AssignmentSubmissionStatus | null>(null);
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [codeFiles, setCodeFiles] = useState<File[]>([]);
  const [codeMode, setCodeMode] = useState<"file" | "link">("file");
  const [codeLink, setCodeLink] = useState("");
  const [removeReport, setRemoveReport] = useState(false);
  const [removeCode, setRemoveCode] = useState(false);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const reportInputRef = useRef<HTMLInputElement | null>(null);
  const codeInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!assignmentId) {
      setError("Не передан идентификатор задания");
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
        setRemoveReport(false);
        setRemoveCode(false);
      } catch (loadError) {
        setError(extractErrorMessage(loadError, "Не удалось загрузить задание"));
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [assignmentId]);

  const hasReportChange = Boolean(reportFile || removeReport);
  const hasCodeLinkChange =
    codeMode === "link" &&
    codeLink.trim().length > 0 &&
    codeLink.trim() !== (submissionStatus?.code_link ?? "");
  const hasCodeChange = Boolean(codeFiles.length > 0 || removeCode || hasCodeLinkChange);

  const isSubmitDisabled = submitting || !submissionStatus?.can_submit || (!hasReportChange && !hasCodeChange);

  function onSelectReport(fileList: FileList | null) {
    setRemoveReport(false);
    setReportFile(fileList?.[0] ?? null);
  }

  function onSelectCodeFiles(fileList: FileList | null) {
    const selected = Array.from(fileList ?? []);
    if (selected.length === 0) return;
    setRemoveCode(false);
    setCodeFiles((current) => [...current, ...selected]);
    if (codeInputRef.current) codeInputRef.current.value = "";
  }

  function removeCodeFile(index: number) {
    setCodeFiles((current) => current.filter((_, currentIndex) => currentIndex !== index));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignmentId || !submissionStatus?.can_submit) return;

    setSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      await submitAssignment(assignmentId, {
        reportFile,
        codeFiles,
        meta: {
          assignment_id: assignmentId,
          comment,
          submitted_at: new Date().toISOString(),
          code_mode: codeMode,
          code_link: codeMode === "link" ? codeLink : "",
          delete_report: removeReport,
          delete_code: removeCode,
        },
      });

      const isUpdate = submissionStatus?.submitted;
      const assignmentLabel = assignment ? `LR${String(assignment.id).padStart(2, "0")}` : `#${assignmentId}`;
      setSuccess(
        isUpdate
          ? `${assignmentLabel}: изменения сохранены. Обновленная версия работы успешно загружена.`
          : `${assignmentLabel}: работа успешно отправлена. Можно переходить к следующему заданию или проверить wiki.`,
      );

      setReportFile(null);
      setCodeFiles([]);
      setRemoveReport(false);
      setRemoveCode(false);
      setComment("");
      if (reportInputRef.current) reportInputRef.current.value = "";
      if (codeInputRef.current) codeInputRef.current.value = "";

      const freshStatus = await fetchSubmissionStatus(assignmentId);
      setSubmissionStatus(freshStatus);
    } catch (submitError) {
      setError(humanizeSubmissionError(extractErrorMessage(submitError, "Не удалось отправить работу")));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <p>Загрузка задания...</p>;
  if (!assignment) return <p className="error-text">{error ?? "Задание не найдено"}</p>;

  const wikiSlug = assignment.wiki_url.split("/").pop() ?? "";

  return (
    <section className="stack">
      <article className="panel assignment-hero">
        <div className="assignment-hero__head">
          <Link to="/assignments" className="link-muted">
            Назад к заданиям
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
              Отправлено {submissionStatus.submitted_at ? new Date(submissionStatus.submitted_at).toLocaleString() : ""}
            </p>
            {submissionStatus.submitted_late ? <p className="warning-text">Отправлено после дедлайна</p> : null}
            <p className="meta">Отчет: {reportStatusLabel(submissionStatus)}</p>
            <p className="meta">Код: {codeStatusLabel(submissionStatus)}</p>
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
          <p className="meta">Еще не отправлено</p>
        )}
      </article>

      <form className="panel form form--rich" onSubmit={onSubmit}>
        <div className="assignment-form-head">
          <h2>{submissionStatus?.submitted ? "Обновить отправку" : "Сдать работу"}</h2>
          <Link className="btn btn--ghost" to={`/wiki/${wikiSlug}`}>
            Открыть wiki материал
          </Link>
        </div>

        <section className="submission-block">
          <h3>1. Отчет</h3>
          <p className="meta">Можно отправить только отчет, только код или обе части. Формат отчета: `.docx`.</p>
          <p className="meta">Текущий отчет: {reportStatusLabel(submissionStatus)}</p>
          {submissionStatus?.report_submitted ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setRemoveReport((current) => !current)}
              disabled={!submissionStatus?.can_submit}
            >
              {removeReport ? "Не удалять текущий отчет" : "Удалить текущий отчет"}
            </button>
          ) : null}
          {removeReport ? <p className="warning-text">Текущий отчет будет удален при сохранении.</p> : null}

          <div className="input-file-row">
            <label className="input-file">
              <input
                ref={reportInputRef}
                type="file"
                accept=".docx"
                onChange={(event) => onSelectReport(event.target.files)}
                disabled={!submissionStatus?.can_submit}
              />
              <span>Выбрать файл</span>
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
                      if (reportInputRef.current) reportInputRef.current.value = "";
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
          <p className="meta">Текущий код: {codeStatusLabel(submissionStatus)}</p>
          {submissionStatus?.code_submitted ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setRemoveCode((current) => !current)}
              disabled={!submissionStatus?.can_submit}
            >
              {removeCode ? "Не удалять текущий код" : "Удалить текущий код"}
            </button>
          ) : null}
          {removeCode ? <p className="warning-text">Текущий код будет удален при сохранении.</p> : null}
          <div className="mode-selector" role="radiogroup" aria-label="Режим отправки кода">
            <label className={`mode-option ${codeMode === "file" ? "mode-option--active" : ""}`}>
              <input
                className="mode-option__input"
                type="radio"
                name="codeMode"
                checked={codeMode === "file"}
                onChange={() => setCodeMode("file")}
                disabled={!submissionStatus?.can_submit}
              />
              <span className="mode-option__title">Файлы кода</span>
              <span className="mode-option__desc">Загрузите исходники или архив</span>
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
                <span>Выбрать файлы</span>
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
                onChange={(event) => {
                  setRemoveCode(false);
                  setCodeLink(event.target.value);
                }}
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
          {submitting ? "Отправка..." : submissionStatus?.submitted ? "Обновить выбранную часть" : "Отправить работу"}
        </button>
      </form>
    </section>
  );
}

