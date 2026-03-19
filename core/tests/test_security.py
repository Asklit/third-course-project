from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def test_password_hash_and_verify(core_module) -> None:
    security = core_module
    password_hash = security.hash_password("secret123")

    assert password_hash != "secret123"
    assert security.verify_password("secret123", password_hash) is True
    assert security.verify_password("wrong", password_hash) is False


def test_create_and_decode_token(core_module) -> None:
    token = core_module.create_token("42", "access", 10)
    payload = core_module.decode_token(token, expected_type="access")

    assert payload["sub"] == "42"
    assert payload["token_type"] == "access"
    assert "jti" in payload


def test_decode_token_with_wrong_type_raises(core_module) -> None:
    token = core_module.create_token("42", "refresh", 10)

    with pytest.raises(core_module.TokenError):
        core_module.decode_token(token, expected_type="access")


def test_assignment_helpers_and_visibility(core_module) -> None:
    assignment = core_module.Assignment(
        id=1,
        title="LR01",
        description="desc",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
        status="open",
        wiki_slug="lr1-intro",
    )
    current_time = datetime.now(timezone.utc)

    assert core_module.normalized_slug("lr1-intro") == "lr01-introduction-and-tooling"
    assert core_module.assignment_open_at(assignment) == assignment.deadline - timedelta(days=14)
    assert core_module.is_assignment_visible(assignment, current_time) is True
    assert core_module.assignment_state(assignment, current_time) == "open"

    assignment.status = "closed"
    assert core_module.assignment_state(assignment, current_time) == "closed"


def test_link_validation_and_storage_helpers(core_module, tmp_path) -> None:
    assert core_module.validate_code_link("") is False
    assert core_module.validate_code_link("https://github.com/example/repo") is True
    assert core_module.validate_code_link("https://sub.gitlab.com/example/repo") is True
    assert core_module.validate_code_link("ftp://github.com/example/repo") is False
    assert core_module.validate_code_link("https://example.com/repo") is False
    assert core_module.validate_code_link("http://[invalid") is False
    assert core_module.infer_submission_file_role("report.docx") == "report"
    assert core_module.infer_submission_file_role("program.cs", "text/plain") == "code"
    assert core_module.sanitize_storage_component('bad<>:"/\\\\|?*name.') == "bad-name"

    assignment = core_module.Assignment(
        id=7,
        title="LR07",
        description="desc",
        deadline=datetime.now(timezone.utc),
        status="open",
        wiki_slug="lr1-intro",
    )
    storage_dir = core_module.assignment_storage_dir(5, assignment)
    assert "student-5" in storage_dir
    assert "assignment-7-lr01-introduction-and-tooling" in storage_dir


def test_write_submission_manifest(core_module, tmp_path) -> None:
    student = core_module.Student(id=1, email="student@example.com", full_name="Test", password_hash="hash")
    assignment = core_module.Assignment(
        id=3,
        title="LR03",
        description="desc",
        deadline=datetime.now(timezone.utc),
        status="open",
        wiki_slug="lr03-functions-and-modules",
    )
    submission = core_module.Submission(
        id=11,
        assignment_id=3,
        student_id=1,
        comment="ok",
        submitted_at=datetime.now(timezone.utc),
        status="accepted",
    )

    core_module.write_submission_manifest(
        str(tmp_path),
        student=student,
        assignment=assignment,
        submission=submission,
        report_file_name="report.docx",
        code_file_names=["Program.cs"],
        code_link="https://github.com/example/repo",
    )

    manifest_path = tmp_path / "submission.json"
    assert manifest_path.exists()
    content = manifest_path.read_text(encoding="utf-8")
    assert '"assignment_id": 3' in content
    assert '"report_file_name": "report.docx"' in content
