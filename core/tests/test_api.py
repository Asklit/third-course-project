from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select


def test_auth_flow_login_refresh_logout(client) -> None:
    login_response = client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "student123"},
    )
    assert login_response.status_code == 200
    tokens = login_response.json()
    assert tokens["token_type"] == "bearer"

    refresh_response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_response.status_code == 200

    logout_response = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout_response.status_code == 200
    assert logout_response.json()["status"] == "logged_out"

    revoked_refresh = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert revoked_refresh.status_code == 401


def test_assignments_and_assignment_details(client, auth_headers) -> None:
    assignments_response = client.get("/assignments", headers=auth_headers)
    assert assignments_response.status_code == 200
    assignments = assignments_response.json()
    assert len(assignments) == 11
    assert assignments[0]["status"] in {"open", "deadline_passed", "submitted", "submitted_late"}

    assignment_id = assignments[0]["id"]
    details_response = client.get(f"/assignments/{assignment_id}", headers=auth_headers)
    assert details_response.status_code == 200
    details = details_response.json()
    assert details["id"] == assignment_id
    assert details["wiki_url"].startswith("/wiki/labs/")
    assert details["requires_report_docx"] is True

    status_response = client.get(f"/assignments/{assignment_id}/submission-status", headers=auth_headers)
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["submitted"] is False
    assert status_payload["can_submit"] is True


def test_submission_with_report_and_code_file(core_module, client, auth_headers, tmp_path: Path) -> None:
    assignment_id = client.get("/assignments", headers=auth_headers).json()[0]["id"]
    submission_meta = {
        "assignment_id": assignment_id,
        "comment": "first submit",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "code_mode": "file",
        "code_link": "",
        "delete_report": False,
        "delete_code": False,
    }

    response = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={"submission_meta": json.dumps(submission_meta)},
        files=[
            ("report_file", ("report.docx", b"docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ("code_files[]", ("Program.cs", b"class Program {}", "text/plain")),
        ],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "accepted"

    status_response = client.get(f"/assignments/{assignment_id}/submission-status", headers=auth_headers)
    status_payload = status_response.json()
    assert status_payload["submitted"] is True
    assert status_payload["report_file_name"] == "report.docx"
    assert "Program.cs" in status_payload["code_file_names"]

    submissions_root = Path(core_module.settings.submissions_dir)
    manifests = list(submissions_root.rglob("submission.json"))
    assert manifests, "submission manifest was not created"
    manifest_content = manifests[0].read_text(encoding="utf-8")
    assert '"code_file_names": [' in manifest_content
    assert '"report_file_name": "report.docx"' in manifest_content


def test_submission_update_with_code_link_and_invalid_cases(client, auth_headers) -> None:
    assignment_id = client.get("/assignments", headers=auth_headers).json()[0]["id"]
    base_meta = {
        "assignment_id": assignment_id,
        "comment": "initial submit",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "code_mode": "file",
        "code_link": "",
        "delete_report": False,
        "delete_code": False,
    }

    first_response = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={"submission_meta": json.dumps(base_meta)},
        files=[("report_file", ("report.docx", b"docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
    )
    assert first_response.status_code == 200

    no_changes = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    **base_meta,
                    "comment": "still same",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        },
    )
    assert no_changes.status_code == 422

    invalid_link = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    **base_meta,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "link",
                    "code_link": "https://example.com/bad",
                }
            )
        },
    )
    assert invalid_link.status_code == 422

    valid_link = client.post(
        f"/assignments/{assignment_id}/submit",
        headers=auth_headers,
        data={
            "submission_meta": json.dumps(
                {
                    **base_meta,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "code_mode": "link",
                    "code_link": "https://github.com/example/repo",
                }
            )
        },
    )
    assert valid_link.status_code == 200

    status_response = client.get(f"/assignments/{assignment_id}/submission-status", headers=auth_headers)
    status_payload = status_response.json()
    assert status_payload["code_link"] == "https://github.com/example/repo"


def test_wiki_proxy_endpoints(core_module, client, auth_headers, monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, *, ok: bool = True, status_code: int = 200, json_payload=None, content: bytes = b"", headers=None):
            self.ok = ok
            self.status_code = status_code
            self._json_payload = json_payload if json_payload is not None else {}
            self.content = content
            self.headers = headers or {"Content-Type": "application/json"}

        def json(self):
            return self._json_payload

    def fake_requests_get(url: str, *, params=None, timeout=10):
        if url.endswith("/labs"):
            return DummyResponse(json_payload=[{"slug": "lr01", "title": "LR01"}])
        if url.endswith("/labs/lr01-introduction-and-tooling"):
            return DummyResponse(json_payload={"slug": "lr01-introduction-and-tooling", "title": "LR01"})
        if url.endswith("/search"):
            return DummyResponse(json_payload={"total": 1, "items": [{"section_id": "intro"}]})
        if url.endswith("/assets/sample.png"):
            return DummyResponse(
                content=b"png",
                headers={"Content-Type": "image/png", "Content-Length": "3"},
            )
        return DummyResponse(ok=False, status_code=404)

    monkeypatch.setattr(core_module.requests, "get", fake_requests_get)

    labs = client.get("/wiki/labs", headers=auth_headers)
    assert labs.status_code == 200
    assert labs.json()[0]["slug"] == "lr01"

    lab_details = client.get("/wiki/labs/lr1-intro", headers=auth_headers)
    assert lab_details.status_code == 200
    assert lab_details.json()["slug"] == "lr01-introduction-and-tooling"

    search = client.get("/wiki/search?q=intro", headers=auth_headers)
    assert search.status_code == 200
    assert search.json()["total"] == 1

    asset = client.get("/wiki/assets/sample.png")
    assert asset.status_code == 200
    assert asset.content == b"png"
