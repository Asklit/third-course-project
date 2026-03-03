from datetime import datetime
from typing import Any

import requests
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
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
from src.infrastructure.db.models import Assignment, Student, Submission, SubmissionFile
from src.infrastructure.db.session import Base, engine, get_db_session
from src.presentation.schemas.schemas import (
    AssignmentDetailsOut,
    AssignmentOut,
    CallbackPayload,
    LoginRequest,
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
                student = Student(
                    email="student@example.com",
                    full_name="Demo Student",
                    password_hash=hash_password("student123"),
                )
                session.add(student)

            if session.scalar(select(Assignment.id).limit(1)) is None:
                session.add_all(
                    [
                        Assignment(
                            title="LR1: Intro",
                            description="Basic Python tasks and report.",
                            deadline=datetime.fromisoformat("2026-03-20T21:00:00+00:00"),
                            status="open",
                            wiki_slug="lr1-intro",
                        ),
                        Assignment(
                            title="LR2: Data structures",
                            description="Collections, complexity, report.",
                            deadline=datetime.fromisoformat("2026-04-01T21:00:00+00:00"),
                            status="open",
                            wiki_slug="lr2-data-structures",
                        ),
                    ]
                )

            session.commit()

    def get_current_student(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db_session),
    ) -> Student:
        try:
            payload = decode_token(credentials.credentials, expected_type="access")
            student_id = int(payload["sub"])
        except (TokenError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

        student = db.get(Student, student_id)
        if not student:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student not found")

        return student

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
        student = db.scalar(select(Student).where(Student.email == payload.email))
        if not student or not verify_password(payload.password, student.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        return TokenResponse(
            access_token=create_token(str(student.id), "access", settings.access_token_minutes),
            refresh_token=create_token(str(student.id), "refresh", settings.refresh_token_minutes),
        )

    @app.post("/auth/refresh", response_model=TokenResponse)
    def refresh(payload: RefreshRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
        try:
            token_payload = decode_token(payload.refresh_token, expected_type="refresh")
            student_id = int(token_payload["sub"])
        except (TokenError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        student = db.get(Student, student_id)
        if not student:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student not found")

        return TokenResponse(
            access_token=create_token(str(student.id), "access", settings.access_token_minutes),
            refresh_token=create_token(str(student.id), "refresh", settings.refresh_token_minutes),
        )

    @app.get("/assignments", response_model=list[AssignmentOut])
    def assignments(_: Student = Depends(get_current_student), db: Session = Depends(get_db_session)) -> list[AssignmentOut]:
        records = db.scalars(select(Assignment).order_by(Assignment.deadline)).all()
        return [
            AssignmentOut(id=row.id, title=row.title, deadline=row.deadline, status=row.status)
            for row in records
        ]

    @app.get("/assignments/{assignment_id}", response_model=AssignmentDetailsOut)
    def assignment_details(
        assignment_id: int,
        _: Student = Depends(get_current_student),
        db: Session = Depends(get_db_session),
    ) -> AssignmentDetailsOut:
        record = db.get(Assignment, assignment_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

        return AssignmentDetailsOut(
            id=record.id,
            title=record.title,
            description=record.description,
            deadline=record.deadline,
            status=record.status,
            wiki_url=f"/wiki/labs/{record.wiki_slug}",
        )

    @app.post("/assignments/{assignment_id}/submit", response_model=SubmissionResponse)
    def submit_assignment(
        assignment_id: int,
        files: list[UploadFile] = File(..., alias="files[]"),
        submission_meta: str = Form(...),
        student: Student = Depends(get_current_student),
        db: Session = Depends(get_db_session),
    ) -> SubmissionResponse:
        assignment = db.get(Assignment, assignment_id)
        if not assignment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

        try:
            meta = SubmissionMeta.model_validate_json(submission_meta)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid submission_meta") from exc

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

        for upload in files:
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
                }
            )

        db.commit()

        if settings.callback_url:
            payload = CallbackPayload(
                event_type="submission.created",
                submission_id=submission.id,
                student_id=student.id,
                assignment_id=assignment_id,
                files=saved_files,
                created_at=datetime.utcnow(),
            )
            try:
                requests.post(settings.callback_url, json=payload.model_dump(mode="json"), timeout=3)
            except requests.RequestException as exc:
                logger.error(
                    "callback delivery failed",
                    extra={"action": "submission_callback", "status": "failed", "user_id": student.id},
                )
                logger.debug(str(exc))

        logger.info(
            "submission accepted",
            extra={"action": "submission.create", "status": "success", "user_id": student.id},
        )

        return SubmissionResponse(status="accepted", submission_id=submission.id)

    @app.get("/wiki/labs", response_model=list[WikiLabOut])
    def wiki_labs(_: Student = Depends(get_current_student)) -> list[WikiLabOut]:
        response = requests.get(f"{settings.wiki_base_url}/labs", timeout=5)
        if not response.ok:
            raise HTTPException(status_code=502, detail="Wiki service is unavailable")
        return [WikiLabOut(**item) for item in response.json()]

    @app.get("/wiki/labs/{slug}", response_model=WikiLabDetailsOut)
    def wiki_lab_details(slug: str, _: Student = Depends(get_current_student)) -> WikiLabDetailsOut:
        response = requests.get(f"{settings.wiki_base_url}/labs/{slug}", timeout=5)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Lab material not found")
        if not response.ok:
            raise HTTPException(status_code=502, detail="Wiki service is unavailable")
        return WikiLabDetailsOut(**response.json())

    return app


app = create_app()
