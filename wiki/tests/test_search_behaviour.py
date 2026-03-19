from __future__ import annotations

import io
import json
import urllib.error

import pytest


def test_main_helper_functions_cover_scoring_and_snippets(wiki_module) -> None:
    assert wiki_module._build_snippet("console application basics", "") == "console application basics"
    assert "application" in wiki_module._build_snippet("console application basics", "application")

    score = wiki_module._score_hit(
        doc_title="Console Lab",
        doc_tags=["console"],
        section_title="Introduction to console",
        section_tags=["goal"],
        plain="This console application uses loops",
        query="console",
    )
    assert score > 0

    assert wiki_module._matches_query("oop console application", "") is True
    assert wiki_module._matches_query("oop console application", "console oop") is True
    assert wiki_module._matches_query("oop console application", "missing") is False
    assert wiki_module._matches_query("oop console application", "!!!") is False


def test_search_fallback_without_query_uses_preferred_section_order(wiki_module, client, monkeypatch) -> None:
    monkeypatch.setattr(wiki_module, "search_meili", lambda **kwargs: None)

    response = client.get("/search")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 2
    assert payload["items"][0]["kind"] in {"theory", "goal", "task", "variants", "content"}


def test_search_with_filters_and_asset_conversion_branch(wiki_module, client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(wiki_module, "search_meili", lambda **kwargs: None)

    filtered = client.get("/search", params={"tag": "arrays", "kind": "theory", "lab_slug": "lr02-data-structures"})
    assert filtered.status_code == 200
    assert filtered.json()["items"][0]["lab_slug"] == "lr02-data-structures"

    curated_dir = tmp_path / "curated"
    assets_dir = curated_dir / "lr01" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    wmf_path = assets_dir / "image.wmf"
    png_path = assets_dir / "image.png"
    wmf_path.write_bytes(b"wmf")

    monkeypatch.setattr(wiki_module, "CURATED_DIR", curated_dir)
    monkeypatch.setattr(wiki_module, "_try_convert_vector_to_png", lambda source, dest: dest.write_bytes(b"png") or True)

    response = client.get("/assets/lr01/assets/image.wmf")
    assert response.status_code == 200
    assert png_path.exists()


def test_api_not_found_and_kind_filter_branches(wiki_module, client, monkeypatch) -> None:
    labs = client.get("/labs", params={"kind": "goal"})
    assert labs.status_code == 200
    assert labs.json()[0]["slug"] == "lr01-introduction-and-tooling"

    monkeypatch.setattr(wiki_module, "search_meili", lambda **kwargs: None)
    missing = client.get("/assets/unknown/path.png")
    assert missing.status_code == 404

    traversal = client.get("/assets/../oops")
    assert traversal.status_code == 404


def test_fallback_search_without_matches_uses_default_section(wiki_module, client, monkeypatch) -> None:
    monkeypatch.setattr(wiki_module, "search_meili", lambda **kwargs: None)
    response = client.get("/search", params={"q": ""})
    assert response.status_code == 200
    assert response.json()["items"]


def test_startup_failure_branch_with_pymongo_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    import sys
    import mongomock
    import pymongo
    from pymongo.errors import PyMongoError
    from fastapi.testclient import TestClient

    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]

    monkeypatch.setenv("MONGO_URL", "mongodb://mocked")
    monkeypatch.setenv("MONGO_DB", "wiki_test")
    monkeypatch.setenv("MONGO_COLLECTION", "labs")
    monkeypatch.setenv("MEILI_ENABLED", "false")
    monkeypatch.setattr(pymongo, "MongoClient", mongomock.MongoClient)

    module = importlib.import_module("src.main")
    collection = module.app.router.on_startup  # keep module imported
    assert collection is not None

    original_client = module.MongoClient(module.settings.mongo_url)
    broken_collection = original_client[module.settings.mongo_db][module.settings.mongo_collection]
    monkeypatch.setattr(module, "MongoClient", lambda url: original_client)
    monkeypatch.setattr(broken_collection, "create_index", lambda *args, **kwargs: (_ for _ in ()).throw(PyMongoError("boom")))
    monkeypatch.setattr(module, "build_curated_labs", lambda: [])

    app = module.create_app()
    with pytest.raises(PyMongoError):
        with TestClient(app):
            pass
