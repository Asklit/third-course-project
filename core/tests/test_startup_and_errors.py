from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from requests import RequestException
from sqlalchemy import select


def _purge_src_modules() -> None:
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]


def test_startup_updates_legacy_records_and_cleans_unsupported(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "startup.db"
    submissions_dir = tmp_path / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SUBMISSIONS_DIR", str(submissions_dir))
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("WIKI_BASE_URL", "http://wiki.test")
    monkeypatch.setenv("CALLBACK_URL", "")

    _purge_src_modules()
    module = importlib.import_module("src.main")
    db_session_module = importlib.import_module("src.infrastructure.db.session")

    module.SUPPORTED_WIKI_LABS = module.SUPPORTED_WIKI_LABS + [
        (f"lr{index:02d}-extra", f"LR{index:02d}: Extra")
        for index in range(15, 20)
    ]

    module.Base.metadata.create_all(bind=module.engine)
    with db_session_module.SessionLocal() as session:
        session.add(
            module.Student(
                email="seed@example.com",
                full_name="Seed Student",
                password_hash=module.hash_password("password123"),
            )
        )
        session.add(
            module.Assignment(
                title="Legacy",
                description="legacy assignment",
                deadline=datetime.now(timezone.utc),
                status="open",
                wiki_slug="lr1-intro",
            )
        )
        session.add(
            module.Assignment(
                title="Old Current",
                description="existing assignment",
                deadline=datetime.now(timezone.utc),
                status="closed",
                wiki_slug="lr02-data-structures",
            )
        )
        unsupported = module.Assignment(
            title="Unsupported",
            description="to remove",
            deadline=datetime.now(timezone.utc),
            status="open",
            wiki_slug="unsupported-slug",
        )
        session.add(unsupported)
        session.flush()
        submission = module.Submission(
            assignment_id=unsupported.id,
            student_id=1,
            comment="x",
            submitted_at=datetime.now(timezone.utc),
            status="accepted",
        )
        session.add(submission)
        session.flush()
        session.add(
            module.SubmissionFile(
                submission_id=submission.id,
                file_name="Program.cs",
                content_type="text/plain",
                size=10,
                storage_path=str(submissions_dir / "Program.cs"),
            )
        )
        session.add(module.SubmissionCodeReference(submission_id=submission.id, url="https://github.com/example/repo"))
        session.commit()

    with TestClient(module.app):
        pass

    with db_session_module.SessionLocal() as session:
        legacy = session.scalar(select(module.Assignment).where(module.Assignment.wiki_slug == "lr01-introduction-and-tooling"))
        assert legacy is not None
        assert legacy.title == "LR01: Introduction and tooling"

        current = session.scalar(select(module.Assignment).where(module.Assignment.wiki_slug == "lr02-data-structures"))
        assert current is not None
        assert current.status == "open"

        unsupported = session.scalar(select(module.Assignment).where(module.Assignment.wiki_slug == "unsupported-slug"))
        assert unsupported is None

        total_assignments = session.scalars(select(module.Assignment.id)).all()
        assert len(total_assignments) >= 14


def test_invalid_access_token_and_missing_entities(client) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    unauthorized = client.get("/assignments", headers={"Authorization": "Bearer bad-token"})
    assert unauthorized.status_code == 401

    not_found = client.get("/assignments/999", headers={"Authorization": "Bearer bad-token"})
    assert not_found.status_code == 401


def test_login_invalid_credentials_and_invalid_refresh_logout(client) -> None:
    login = client.post("/auth/login", json={"email": "student@example.com", "password": "wronggg"})
    assert login.status_code == 401

    refresh = client.post("/auth/refresh", json={"refresh_token": "bad-token"})
    assert refresh.status_code == 401

    logout = client.post("/auth/logout", json={"refresh_token": "bad-token"})
    assert logout.status_code == 401


def test_tokens_for_nonexistent_student_are_rejected(core_module, client) -> None:
    access_token = core_module.create_token("999", "access", 10)
    refresh_token = core_module.create_token("999", "refresh", 10)

    assignments = client.get("/assignments", headers={"Authorization": f"Bearer {access_token}"})
    assert assignments.status_code == 401

    refresh = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 401


def test_second_logout_of_same_token_returns_success(client) -> None:
    tokens = client.post("/auth/login", json={"email": "student@example.com", "password": "student123"}).json()
    first = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    second = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    assert second.status_code == 200


def test_assignment_visibility_and_submission_validation_errors(core_module, client, auth_headers) -> None:
    db_session_module = importlib.import_module("src.infrastructure.db.session")
    with db_session_module.SessionLocal() as session:
        hidden = core_module.Assignment(
            title="Hidden",
            description="future",
            deadline=datetime.now(timezone.utc) + timedelta(days=30),
            status="open",
            wiki_slug="lr-hidden",
        )
        closed = core_module.Assignment(
            title="Closed",
            description="closed",
            deadline=datetime.now(timezone.utc) - timedelta(days=1),
            status="closed",
            wiki_slug="lr-closed",
        )
        session.add_all([hidden, closed])
        session.commit()
        hidden_id = hidden.id
        closed_id = closed.id

    hidden_details = client.get(f"/assignments/{hidden_id}", headers=auth_headers)
    assert hidden_details.status_code == 404

    hidden_status = client.get(f"/assignments/{hidden_id}/submission-status", headers=auth_headers)
    assert hidden_status.status_code == 404

    base_meta = {
        "assignment_id": hidden_id,
        "comment": "demo",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "code_mode": "file",
        "code_link": "",
        "delete_report": False,
        "delete_code": False,
    }
    hidden_submit = client.post(
        f"/assignments/{hidden_id}/submit",
        headers=auth_headers,
        data={"submission_meta": json.dumps(base_meta)},
    )
    assert hidden_submit.status_code == 403

    closed_meta = {**base_meta, "assignment_id": closed_id}
    closed_submit = client.post(
        f"/assignments/{closed_id}/submit",
        headers=auth_headers,
        data={"submission_meta": json.dumps(closed_meta)},
    )
    assert closed_submit.status_code == 403

    missing_assignment = client.post(
        "/assignments/999/submit",
        headers=auth_headers,
        data={"submission_meta": json.dumps({**base_meta, "assignment_id": 999})},
    )
    assert missing_assignment.status_code == 404

    details_missing = client.get("/assignments/999", headers=auth_headers)
    assert details_missing.status_code == 404

    status_missing = client.get("/assignments/999/submission-status", headers=auth_headers)
    assert status_missing.status_code == 404


def test_submission_invalid_payload_branches(client, auth_headers) -> None:
    assignment_id = client.get("/assignments", headers=auth_headers).json()[0]["id"]

    bad_meta = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={"submission_meta": "{not-json"},
    )
    assert bad_meta.status_code == 422

    mismatch = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id + 1,
                    "comment": "",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "file",
                    "code_link": "",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
    )
    assert mismatch.status_code == 422

    wrong_report = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "file",
                    "code_link": "",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
        files=[("report_file", ("report.pdf", b"pdf", "application/pdf"))],
    )
    assert wrong_report.status_code == 422

    wrong_mode = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "archive",
                    "code_link": "",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
    )
    assert wrong_mode.status_code == 422

    missing_parts = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "file",
                    "code_link": "",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
    )
    assert missing_parts.status_code == 422

    initial_link = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "link",
                    "code_link": "https://github.com/example/repo",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
    )
    assert initial_link.status_code == 200


def test_delete_both_parts_is_forbidden_and_callback_paths(core_module, client, auth_headers, monkeypatch) -> None:
    assignment_ids = [item["id"] for item in client.get("/assignments", headers=auth_headers).json()[:2]]
    assignment_id = assignment_ids[0]
    first = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "seed",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "file",
                    "code_link": "",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
        files=[("report_file", ("report.docx", b"docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
    )
    assert first.status_code == 200

    delete_both = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "delete",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "file",
                    "code_link": "",
                    "delete_report": True,
                    "delete_code": True,
                }
            )
        },
    )
    assert delete_both.status_code == 422

    monkeypatch.setattr(core_module.settings, "callback_url", "http://callback.test")
    callback_calls: list[dict] = []

    def fake_post(url: str, json=None, timeout=0):
        callback_calls.append({"url": url, "json": json, "timeout": timeout})
        class Resp:
            status_code = 200
        return Resp()

    monkeypatch.setattr(core_module.requests, "post", fake_post)
    ok = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_id,
                    "comment": "callback",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "link",
                    "code_link": "https://github.com/example/new-repo",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
    )
    assert ok.status_code == 200
    assert callback_calls

    monkeypatch.setattr(core_module.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(RequestException("boom")))
    fail = client.post(
        f"/assignments/{assignment_ids[1]}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    "assignment_id": assignment_ids[1],
                    "comment": "callback fail",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "link",
                    "code_link": "https://gitlab.com/example/repo",
                    "delete_report": False,
                    "delete_code": False,
                }
            )
        },
    )
    assert fail.status_code == 200


def test_wiki_proxy_error_paths(core_module, client, auth_headers, monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, ok: bool, status_code: int):
            self.ok = ok
            self.status_code = status_code
            self.headers = {"Content-Type": "application/json"}
            self.content = b""

        def json(self):
            return {}

    monkeypatch.setattr(core_module.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RequestException("down")))
    unavailable = client.get("/wiki/labs", headers=auth_headers)
    assert unavailable.status_code == 503

    monkeypatch.setattr(core_module.requests, "get", lambda *args, **kwargs: DummyResponse(False, 500))
    bad_labs = client.get("/wiki/labs", headers=auth_headers)
    assert bad_labs.status_code == 502

    monkeypatch.setattr(core_module.requests, "get", lambda *args, **kwargs: DummyResponse(False, 404))
    bad_detail = client.get("/wiki/labs/unknown", headers=auth_headers)
    assert bad_detail.status_code == 404

    bad_asset = client.get("/wiki/assets/missing.png")
    assert bad_asset.status_code == 404

    monkeypatch.setattr(core_module.requests, "get", lambda *args, **kwargs: DummyResponse(False, 500))
    bad_search = client.get("/wiki/search?q=test", headers=auth_headers)
    assert bad_search.status_code == 502

    bad_asset_502 = client.get("/wiki/assets/broken.png")
    assert bad_asset_502.status_code == 502


def test_latest_submission_status_prefers_newest_and_marks_late(core_module, client, auth_headers) -> None:
    db_session_module = importlib.import_module("src.infrastructure.db.session")
    assignment_id = client.get("/assignments", headers=auth_headers).json()[0]["id"]

    with db_session_module.SessionLocal() as session:
        assignment = session.get(core_module.Assignment, assignment_id)
        assignment.deadline = datetime.now(timezone.utc) - timedelta(days=2)
        session.add_all(
            [
                core_module.Submission(
                    assignment_id=assignment_id,
                    student_id=1,
                    comment="old",
                    submitted_at=datetime.now(timezone.utc) - timedelta(days=3),
                    status="accepted",
                ),
                core_module.Submission(
                    assignment_id=assignment_id,
                    student_id=1,
                    comment="new",
                    submitted_at=datetime.now(timezone.utc) - timedelta(days=1),
                    status="accepted",
                ),
            ]
        )
        session.commit()

    assignments = client.get("/assignments", headers=auth_headers)
    assert assignments.status_code == 200
    item = next(row for row in assignments.json() if row["id"] == assignment_id)
    assert item["status"] == "submitted_late"

    details = client.get(f"/assignments/{assignment_id}", headers=auth_headers)
    assert details.status_code == 200
    assert details.json()["status"] == "submitted_late"
