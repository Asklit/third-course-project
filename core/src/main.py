from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
import shutil
import re

import requests
from requests import RequestException
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from src.application.services.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.core.config import settings
from src.core.logging import configure_logging
from src.infrastructure.db.models import (
    Assignment,
    RevokedRefreshToken,
    Student,
    Submission,
    SubmissionCodeReference,
    SubmissionFile,
)
from src.infrastructure.db.session import Base, engine, get_db_session
from src.presentation.schemas.schemas import (
    AssignmentDetailsOut,
    AssignmentOut,
    AssignmentSubmissionStatusOut,
    CallbackPayload,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    SubmissionMeta,
    SubmissionResponse,
    TokenResponse,
    WikiLabDetailsOut,
    WikiLabOut,
)

import logging
import os
import uuid

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=True)


SUPPORTED_WIKI_LABS = [
    ("lr01-introduction-and-tooling", "LR01: Introduction and tooling"),
    ("lr02-data-structures", "LR02: Data structures"),
    ("lr03-functions-and-modules", "LR03: Functions and modules"),
    ("lr04-error-handling", "LR04: Error handling"),
    ("lr05-files-and-serialization", "LR05-06: Files and serialization"),
    ("lr09-testing-basics", "LR09: Testing basics"),
    ("lr10-web-fundamentals", "LR10: Web fundamentals"),
    ("lr11-rest-api-basics", "LR11: REST API basics"),
    ("lr12-databases-and-sql", "LR12: Databases and SQL"),
    ("lr13-orm-integration", "LR13: ORM integration"),
    ("lr14-async-programming", "LR14: Async programming"),
]

LEGACY_WIKI_SLUG_MAP = {
    "lr1-intro": "lr01-introduction-and-tooling",
    "lr2-data-structures": "lr02-data-structures",
    "lr06-oop-basics": "lr05-files-and-serialization",
}

VISIBILITY_WINDOW_DAYS = 14
VISIBLE_ASSIGNMENTS_COUNT = 14
PAST_DEADLINES_COUNT = 5
PAST_DEADLINE_STEP_DAYS = 3
FUTURE_DEADLINE_STEP_DAYS = 1


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalized_slug(raw_slug: str) -> str:
    return LEGACY_WIKI_SLUG_MAP.get(raw_slug, raw_slug)


def assignment_open_at(assignment: Assignment) -> datetime:
    return assignment.deadline - timedelta(days=VISIBILITY_WINDOW_DAYS)


def is_assignment_visible(assignment: Assignment, current_time: datetime) -> bool:
    return current_time >= assignment_open_at(assignment)


def assignment_state(assignment: Assignment, current_time: datetime) -> str:
    if assignment.status == "closed":
        return "closed"
    if current_time > assignment.deadline:
        return "deadline_passed"
    return "open"


def assignment_submission_requirements(_: Assignment) -> dict[str, Any]:
    return {
        "requires_report_docx": True,
        "code_submission_mode": "file_or_link",
    }


def validate_code_link(link: str) -> bool:
    if not link:
        return False
    try:
        parsed = urlparse(link)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.netloc or "").lower()
    allowed_hosts = {"github.com", "gitlab.com", "drive.google.com", "docs.google.com"}
    return any(host == h or host.endswith(f".{h}") for h in allowed_hosts)


def is_refresh_token_revoked(db: Session, token_jti: str) -> bool:
    return db.scalar(
        select(RevokedRefreshToken.id).where(RevokedRefreshToken.jti == token_jti).limit(1)
    ) is not None


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_trace_middleware(request: Request, call_next):
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        logger.info(
            f"{request.method} {request.url.path}",
            extra={"trace_id": trace_id, "action": "http.request", "status": response.status_code},
        )
        return response

    @app.on_event("startup")
    def startup() -> None:
        Base.metadata.create_all(bind=engine)
        os.makedirs(settings.submissions_dir, exist_ok=True)

        with next(get_db_session()) as session:
            if session.scalar(select(Student.id).limit(1)) is None:
                session.add(
                    Student(
                        email="student@example.com",
                        full_name="Demo Student",
                        password_hash=hash_password("student123"),
                    )
                )

            legacy_slug_map = [
                ("lr1-intro", "lr01-introduction-and-tooling", "LR01: Introduction and tooling"),
                ("lr2-data-structures", "lr02-data-structures", "LR02: Data structures"),
                ("lr06-oop-basics", "lr05-files-and-serialization", "LR05-06: Files and serialization"),
            ]
            for old_slug, new_slug, new_title in legacy_slug_map:
                old_id = session.scalar(select(Assignment.id).where(Assignment.wiki_slug == old_slug).limit(1))
                new_id = session.scalar(select(Assignment.id).where(Assignment.wiki_slug == new_slug).limit(1))
                if old_id is not None and new_id is None:
                    session.execute(
                        update(Assignment)
                        .where(Assignment.id == old_id)
                        .values(wiki_slug=new_slug, title=new_title)
                    )

            seed_now = now_utc().replace(microsecond=0)
            for idx, (slug, title) in enumerate(SUPPORTED_WIKI_LABS, start=1):
                if idx <= PAST_DEADLINES_COUNT:
                    days_ago = (PAST_DEADLINES_COUNT - idx + 1) * PAST_DEADLINE_STEP_DAYS
                    deadline = seed_now - timedelta(days=days_ago)
                elif idx <= VISIBLE_ASSIGNMENTS_COUNT:
                    days_ahead = (idx - PAST_DEADLINES_COUNT) * FUTURE_DEADLINE_STEP_DAYS
                    deadline = seed_now + timedelta(days=days_ahead)
                else:
                    deadline = seed_now + timedelta(days=60 + idx)
                description = f"Complete {title.split(':', maxsplit=1)[0]} and upload code + short report."

                existing_id = session.scalar(select(Assignment.id).where(Assignment.wiki_slug == slug).limit(1))
                if existing_id is None:
                    session.add(
                        Assignment(
                            title=title,
                            description=description,
                            deadline=deadline,
                            status="open",
                            wiki_slug=slug,
                        )
                    )
                else:
                    session.execute(
                        update(Assignment)
                        .where(Assignment.id == existing_id)
                        .values(
                            title=title,
                            description=description,
                            deadline=deadline,
                            status="open",
                        )
                    )

            allowed_slugs = {item[0] for item in SUPPORTED_WIKI_LABS}
            unsupported_assignment_ids = session.scalars(
                select(Assignment.id).where(~Assignment.wiki_slug.in_(allowed_slugs))
            ).all()

            if unsupported_assignment_ids:
                unsupported_submission_ids = session.scalars(
                    select(Submission.id).where(Submission.assignment_id.in_(unsupported_assignment_ids))
                ).all()
                if unsupported_submission_ids:
                    session.execute(
                        delete(SubmissionFile).where(SubmissionFile.submission_id.in_(unsupported_submission_ids))
                    )
                    session.execute(
                        delete(SubmissionCodeReference).where(
                            SubmissionCodeReference.submission_id.in_(unsupported_submission_ids)
                        )
                    )
                    session.execute(delete(Submission).where(Submission.id.in_(unsupported_submission_ids)))

                session.execute(delete(Assignment).where(Assignment.id.in_(unsupported_assignment_ids)))

            session.commit()

    def get_current_student(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db_session),
    ) -> Student:
        try:
            payload = decode_token(credentials.credentials, expected_type="access")
            student_id = int(payload["sub"])
        except (TokenError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен") from exc

        student = db.get(Student, student_id)
        if not student:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Студент не найден")

        return student

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
        student = db.scalar(select(Student).where(Student.email == payload.email))
        if not student or not verify_password(payload.password, student.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

        return TokenResponse(
            access_token=create_token(str(student.id), "access", settings.access_token_minutes),
            refresh_token=create_token(str(student.id), "refresh", settings.refresh_token_minutes),
        )

    @app.post("/auth/refresh", response_model=TokenResponse)
    def refresh(payload: RefreshRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
        try:
            token_payload = decode_token(payload.refresh_token, expected_type="refresh")
            student_id = int(token_payload["sub"])
            token_jti = str(token_payload["jti"])
        except (TokenError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        if is_refresh_token_revoked(db, token_jti):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

        student = db.get(Student, student_id)
        if not student:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student not found")

        return TokenResponse(
            access_token=create_token(str(student.id), "access", settings.access_token_minutes),
            refresh_token=create_token(str(student.id), "refresh", settings.refresh_token_minutes),
        )

    @app.post("/auth/logout", response_model=LogoutResponse)
    def logout(payload: LogoutRequest, db: Session = Depends(get_db_session)) -> LogoutResponse:
        try:
            token_payload = decode_token(payload.refresh_token, expected_type="refresh")
            student_id = int(token_payload["sub"])
            token_jti = str(token_payload["jti"])
            token_exp = datetime.fromtimestamp(int(token_payload["exp"]), tz=timezone.utc)
        except (TokenError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        if is_refresh_token_revoked(db, token_jti):
            return LogoutResponse()

        db.add(
            RevokedRefreshToken(
                jti=token_jti,
                student_id=student_id,
                expires_at=token_exp,
            )
        )
        db.commit()
        return LogoutResponse()

    @app.get("/assignments", response_model=list[AssignmentOut])
    def assignments(student: Student = Depends(get_current_student), db: Session = Depends(get_db_session)) -> list[AssignmentOut]:
        current_time = now_utc()
        records = db.scalars(select(Assignment).order_by(Assignment.deadline, Assignment.id)).all()

        unique_records: dict[str, Assignment] = {}
        for record in records:
            slug = normalized_slug(record.wiki_slug)
            if slug not in unique_records:
                unique_records[slug] = record

        visible_records = [
            row for row in unique_records.values() if is_assignment_visible(row, current_time)
        ]

        assignment_ids = [row.id for row in visible_records]
        latest_submission_by_assignment: dict[int, Submission] = {}
        if assignment_ids:
            submissions = db.scalars(
                select(Submission)
                .where(Submission.student_id == student.id, Submission.assignment_id.in_(assignment_ids))
                .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            ).all()
            for row in submissions:
                if row.assignment_id not in latest_submission_by_assignment:
                    latest_submission_by_assignment[row.assignment_id] = row

        response: list[AssignmentOut] = []
        for row in visible_records:
            latest_submission = latest_submission_by_assignment.get(row.id)
            if latest_submission:
                is_late_submission = latest_submission.submitted_at > row.deadline
                status_value = "submitted_late" if is_late_submission else "submitted"
            else:
                status_value = assignment_state(row, current_time)
            response.append(
                AssignmentOut(
                    id=row.id,
                    title=row.title,
                    deadline=row.deadline,
                    status=status_value,
                )
            )

        return response

    @app.get("/assignments/{assignment_id}", response_model=AssignmentDetailsOut)
    def assignment_details(
        assignment_id: int,
        student: Student = Depends(get_current_student),
        db: Session = Depends(get_db_session),
    ) -> AssignmentDetailsOut:
        current_time = now_utc()
        record = db.get(Assignment, assignment_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задание не найдено")

        if not is_assignment_visible(record, current_time):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задание пока недоступно")

        latest_submission = db.scalar(
            select(Submission)
            .where(Submission.assignment_id == assignment_id, Submission.student_id == student.id)
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            .limit(1)
        )

        wiki_slug = normalized_slug(record.wiki_slug)
        if latest_submission:
            is_late_submission = latest_submission.submitted_at > record.deadline
            status_value = "submitted_late" if is_late_submission else "submitted"
        else:
            status_value = assignment_state(record, current_time)
        requirements = assignment_submission_requirements(record)

        return AssignmentDetailsOut(
            id=record.id,
            title=record.title,
            description=record.description,
            deadline=record.deadline,
            status=status_value,
            wiki_url=f"/wiki/labs/{wiki_slug}",
            requires_report_docx=requirements["requires_report_docx"],
            code_submission_mode=requirements["code_submission_mode"],
        )

    @app.get("/assignments/{assignment_id}/submission-status", response_model=AssignmentSubmissionStatusOut)
    def assignment_submission_status(
        assignment_id: int,
        student: Student = Depends(get_current_student),
        db: Session = Depends(get_db_session),
    ) -> AssignmentSubmissionStatusOut:
        current_time = now_utc()
        assignment = db.get(Assignment, assignment_id)
        if not assignment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задание не найдено")

        if not is_assignment_visible(assignment, current_time):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задание пока недоступно")

        latest_submission = db.scalar(
            select(Submission)
            .where(Submission.assignment_id == assignment_id, Submission.student_id == student.id)
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            .limit(1)
        )

        code_link: str | None = None
        if latest_submission:
            code_reference = db.scalar(
                select(SubmissionCodeReference)
                .where(SubmissionCodeReference.submission_id == latest_submission.id)
                .limit(1)
            )
            code_link = code_reference.url if code_reference else None

        assignment_current_state = assignment_state(assignment, current_time)
        can_submit = assignment_current_state != "closed"
        is_late_submission = bool(latest_submission and latest_submission.submitted_at > assignment.deadline)

        return AssignmentSubmissionStatusOut(
            submitted=latest_submission is not None,
            submitted_at=latest_submission.submitted_at if latest_submission else None,
            submission_id=latest_submission.id if latest_submission else None,
            status="submitted" if latest_submission else "not_submitted",
            can_submit=can_submit,
            code_link=code_link,
            submitted_late=is_late_submission,
        )

    @app.post("/assignments/{assignment_id}/submit", response_model=SubmissionResponse)
    def submit_assignment(
        assignment_id: int,
        report_file: UploadFile | None = File(None),
        code_files: list[UploadFile] | None = File(None, alias="code_files[]"),
        submission_meta: str = Form(...),
        student: Student = Depends(get_current_student),
        db: Session = Depends(get_db_session),
    ) -> SubmissionResponse:
        assignment = db.get(Assignment, assignment_id)
        if not assignment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задание не найдено")

        current_time = now_utc()
        if not is_assignment_visible(assignment, current_time):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Задание пока недоступно")

        state = assignment_state(assignment, current_time)
        if state == "closed":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Сдача по этому заданию закрыта")

        try:
            meta = SubmissionMeta.model_validate_json(submission_meta)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Некорректный submission_meta") from exc

        if meta.assignment_id != assignment_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="assignment_id не совпадает с URL")

        computed_late_submission = current_time > assignment.deadline

        requirements = assignment_submission_requirements(assignment)

        if requirements["requires_report_docx"]:
            if report_file is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Не приложен отчет .docx")
            report_name = (report_file.filename or "").lower()
            if not report_name.endswith(".docx"):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Отчет должен быть в формате .docx")

        normalized_code_mode = meta.code_mode.strip().lower()
        if normalized_code_mode not in {"file", "link"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неверный режим сдачи кода")

        code_file_items = code_files or []
        code_link = meta.code_link.strip()
        if normalized_code_mode == "file" and len(code_file_items) == 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Не приложен файл с кодом")
        if normalized_code_mode == "link" and not validate_code_link(code_link):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Ссылка на код должна вести на GitHub/GitLab/Google Drive",
            )

        existing_submission = db.scalar(
            select(Submission)
            .where(Submission.assignment_id == assignment_id, Submission.student_id == student.id)
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            .limit(1)
        )

        is_update = existing_submission is not None
        if is_update:
            submission = existing_submission
            submission.comment = meta.comment
            submission.submitted_at = meta.submitted_at
            submission.status = "accepted"
        else:
            submission = Submission(
                assignment_id=assignment_id,
                student_id=student.id,
                comment=meta.comment,
                submitted_at=meta.submitted_at,
                status="accepted",
            )
            db.add(submission)
            db.flush()

        saved_files: list[dict[str, Any]] = []

        target_dir = os.path.join(settings.submissions_dir, str(student.id), str(submission.id))
        os.makedirs(target_dir, exist_ok=True)

        if is_update:
            old_files = db.scalars(
                select(SubmissionFile).where(SubmissionFile.submission_id == submission.id)
            ).all()
            for old_file in old_files:
                if old_file.storage_path and os.path.exists(old_file.storage_path):
                    try:
                        os.remove(old_file.storage_path)
                    except OSError:
                        logger.warning("failed to remove old file", extra={"action": "submission.update", "status": "warn"})
                db.delete(old_file)

            old_code_ref = db.scalar(
                select(SubmissionCodeReference).where(SubmissionCodeReference.submission_id == submission.id).limit(1)
            )
            if old_code_ref:
                db.delete(old_code_ref)

            shutil.rmtree(target_dir, ignore_errors=True)
            os.makedirs(target_dir, exist_ok=True)

        uploads: list[tuple[UploadFile, str]] = []
        if report_file is not None:
            uploads.append((report_file, "report"))
        for code_file in code_file_items:
            uploads.append((code_file, "code"))

        for upload, file_role in uploads:
            safe_name = f"{uuid.uuid4()}_{upload.filename}"
            path = os.path.join(target_dir, safe_name)
            content = upload.file.read()
            with open(path, "wb") as output:
                output.write(content)

            row = SubmissionFile(
                submission_id=submission.id,
                file_name=upload.filename or "unknown",
                content_type=upload.content_type or "application/octet-stream",
                size=len(content),
                storage_path=path,
            )
            db.add(row)

            saved_files.append(
                {
                    "name": row.file_name,
                    "type": row.content_type,
                    "size": row.size,
                    "storage_path": row.storage_path,
                    "role": file_role,
                }
            )

        if normalized_code_mode == "link":
            db.add(SubmissionCodeReference(submission_id=submission.id, url=code_link))

        db.commit()

        if settings.callback_url:
            payload = CallbackPayload(
                event_type="submission.updated" if is_update else "submission.created",
                submission_id=submission.id,
                student_id=student.id,
                assignment_id=assignment_id,
                files=saved_files,
                created_at=now_utc(),
                message="Работа обновлена" if is_update else "Работа сдана",
                late_submission=computed_late_submission,
            )
            try:
                requests.post(settings.callback_url, json=payload.model_dump(mode="json"), timeout=3)
                logger.info(
                    "submission notification sent",
                    extra={"action": "submission_callback", "status": "success", "user_id": student.id},
                )
            except requests.RequestException as exc:
                logger.error(
                    "callback delivery failed",
                    extra={"action": "submission_callback", "status": "failed", "user_id": student.id},
                )
                logger.debug(str(exc))
        else:
            logger.info(
                "submission notification skipped",
                extra={"action": "submission_callback", "status": "skipped", "user_id": student.id},
            )

        logger.info(
            "submission accepted" if not is_update else "submission updated",
            extra={
                "action": "submission.update" if is_update else "submission.create",
                "status": "success",
                "user_id": student.id,
            },
        )

        return SubmissionResponse(status="accepted", submission_id=submission.id)

    def rewrite_wiki_asset_urls(payload: Any) -> Any:
        def rewrite_text_assets(text: str) -> str:
            rewritten = re.sub(r"^/assets/", "/wiki/assets/", text)
            rewritten = re.sub(r"\(/assets/", "(/wiki/assets/", rewritten)
            rewritten = re.sub(r"\"/assets/", "\"/wiki/assets/", rewritten)
            rewritten = re.sub(r"'/assets/", "'/wiki/assets/", rewritten)
            rewritten = re.sub(r"=/assets/", "=/wiki/assets/", rewritten)
            return rewritten

        if isinstance(payload, dict):
            rewritten: dict[str, Any] = {}
            for key, value in payload.items():
                rewritten[key] = rewrite_wiki_asset_urls(value)
            return rewritten
        if isinstance(payload, list):
            return [rewrite_wiki_asset_urls(item) for item in payload]
        if isinstance(payload, str) and "/assets/" in payload:
            return rewrite_text_assets(payload)
        return payload

    def wiki_get(path: str, *, params: dict[str, Any] | None = None, timeout: int = 10) -> requests.Response:
        try:
            return requests.get(f"{settings.wiki_base_url}{path}", params=params, timeout=timeout)
        except RequestException as exc:
            logger.warning(
                "wiki request failed",
                extra={"action": "wiki.proxy", "status": "failed", "path": path, "error": str(exc)},
            )
            raise HTTPException(status_code=503, detail="Wiki service temporarily unavailable") from exc

    @app.get("/wiki/labs")
    def wiki_labs(
        tag: str | None = None,
        kind: str | None = None,
        _: Student = Depends(get_current_student),
    ) -> Any:
        response = wiki_get("/labs", params={"tag": tag, "kind": kind}, timeout=10)
        if not response.ok:
            raise HTTPException(status_code=502, detail="Wiki service unavailable")
        return rewrite_wiki_asset_urls(response.json())

    @app.get("/wiki/labs/{slug}")
    def wiki_lab_details(slug: str, _: Student = Depends(get_current_student)) -> Any:
        normalized = normalized_slug(slug)
        response = wiki_get(f"/labs/{normalized}", timeout=10)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Wiki material not found")
        if not response.ok:
            raise HTTPException(status_code=502, detail="Wiki service unavailable")
        return rewrite_wiki_asset_urls(response.json())

    @app.get("/wiki/search")
    def wiki_search(
        q: str = "",
        tag: str | None = None,
        kind: str | None = None,
        lab_slug: str | None = None,
        limit: int = 30,
        _: Student = Depends(get_current_student),
    ) -> Any:
        response = wiki_get(
            "/search",
            params={"q": q, "tag": tag, "kind": kind, "lab_slug": lab_slug, "limit": limit},
            timeout=10,
        )
        if not response.ok:
            raise HTTPException(status_code=502, detail="Wiki service unavailable")
        return rewrite_wiki_asset_urls(response.json())

    @app.get("/wiki/assets/{asset_path:path}")
    def wiki_asset(asset_path: str) -> Response:
        response = wiki_get(f"/assets/{asset_path}", timeout=15)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Asset not found")
        if not response.ok:
            raise HTTPException(status_code=502, detail="Wiki service unavailable")
        return Response(content=response.content, media_type=response.headers.get("Content-Type", "application/octet-stream"))
    return app


app = create_app()



