from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import mongomock
import pytest
from fastapi.testclient import TestClient


def _purge_src_modules() -> None:
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]


@pytest.fixture()
def sample_labs() -> list[dict]:
    return [
        {
            "lab_id": 1,
            "slug": "lr01-introduction-and-tooling",
            "title": "Лабораторная работа №1",
            "source_file": "Практическая работа №1.docx",
            "updated_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
            "stats": {"sections": 2, "assets": 0},
            "tags": ["console", "csharp"],
            "assets": [],
            "search_text": "console basics",
            "sections": [
                {
                    "id": "goal",
                    "order": 1,
                    "title": "Цель работы",
                    "kind": "goal",
                    "tags": ["goal"],
                    "content_md": "Изучить консольное приложение и основы C#.",
                    "assets": [],
                },
                {
                    "id": "task",
                    "order": 2,
                    "title": "Задание",
                    "kind": "task",
                    "tags": ["task"],
                    "content_md": "Реализовать console app и вывести hello world.",
                    "assets": [],
                },
            ],
        },
        {
            "lab_id": 2,
            "slug": "lr02-data-structures",
            "title": "Лабораторная работа №2",
            "source_file": "Практическая работа №2.docx",
            "updated_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
            "stats": {"sections": 1, "assets": 0},
            "tags": ["arrays"],
            "assets": [],
            "search_text": "arrays and loops",
            "sections": [
                {
                    "id": "theory",
                    "order": 1,
                    "title": "Теория",
                    "kind": "theory",
                    "tags": ["arrays"],
                    "content_md": "Массивы и циклы for.",
                    "assets": [],
                }
            ],
        },
    ]


@pytest.fixture()
def wiki_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://mocked")
    monkeypatch.setenv("MONGO_DB", "wiki_test")
    monkeypatch.setenv("MONGO_COLLECTION", "labs")
    monkeypatch.setenv("MEILI_ENABLED", "true")
    monkeypatch.setenv("MEILI_URL", "http://meili.test")
    monkeypatch.setenv("MEILI_INDEX", "wiki_sections")

    import pymongo

    monkeypatch.setattr(pymongo, "MongoClient", mongomock.MongoClient)
    _purge_src_modules()
    module = importlib.import_module("src.main")
    return module


@pytest.fixture()
def client(wiki_module, sample_labs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(wiki_module, "build_curated_labs", lambda: sample_labs)
    monkeypatch.setattr(wiki_module, "sync_meili_index", lambda labs: True)
    monkeypatch.setattr(wiki_module, "CURATED_DIR", curated_dir)

    with TestClient(wiki_module.app) as test_client:
        yield test_client
