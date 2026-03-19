from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _purge_src_modules() -> None:
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]


@pytest.fixture()
def core_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "core-test.db"
    submissions_dir = tmp_path / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SUBMISSIONS_DIR", str(submissions_dir))
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("WIKI_BASE_URL", "http://wiki.test")
    monkeypatch.setenv("CALLBACK_URL", "")

    _purge_src_modules()
    module = importlib.import_module("src.main")
    return module


@pytest.fixture()
def client(core_module) -> Iterator[TestClient]:
    with TestClient(core_module.app) as test_client:
        yield test_client


@pytest.fixture()
def auth_tokens(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "student123"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def auth_headers(auth_tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}
