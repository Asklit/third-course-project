from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AssignmentOut(BaseModel):
    id: int
    title: str
    deadline: datetime
    status: str


class AssignmentDetailsOut(AssignmentOut):
    description: str
    wiki_url: str


class SubmissionMeta(BaseModel):
    assignment_id: int
    comment: str = ""
    submitted_at: datetime


class SubmissionResponse(BaseModel):
    status: str
    submission_id: int


class WikiLabOut(BaseModel):
    slug: str
    title: str


class WikiLabDetailsOut(BaseModel):
    slug: str
    title: str
    content_md: str
    prerequisites: list[str] = []


class CallbackPayload(BaseModel):
    event_type: str
    submission_id: int
    student_id: int
    assignment_id: int
    files: list[dict[str, Any]]
    created_at: datetime
