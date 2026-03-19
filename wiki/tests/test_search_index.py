from __future__ import annotations

import json
import urllib.error

import pytest


def test_query_normalization_and_synonyms() -> None:
    from src.application.services import search_index

    assert search_index.normalize_query_token(" Ёлка ") == "елка"
    assert "oop" in search_index.query_variants("ООП")
    assert "ооп" in search_index.query_variants("oop")
    assert search_index.query_tokens("C# и console app")[:2] == ["C#", "и"]


def test_strip_markdown_and_section_documents() -> None:
    from src.application.services import search_index

    markdown = "# Заголовок\n![img](/a.png) [ссылка](https://x) `code`"
    plain = search_index.strip_markdown(markdown)
    assert "Заголовок" in plain
    assert "img" not in plain

    docs = search_index.section_search_documents(
        [
            {
                "lab_id": 1,
                "slug": "lr01",
                "title": "LR01",
                "tags": ["console"],
                "sections": [
                    {
                        "id": "intro",
                        "order": 1,
                        "title": "Введение",
                        "kind": "goal",
                        "tags": ["intro"],
                        "content_md": "Console application",
                    }
                ],
            }
        ]
    )
    assert len(docs) == 1
    assert docs[0]["id"] == "1-001"
    assert docs[0]["tags"] == ["console", "intro"]


def test_meili_filter_search_and_sync(monkeypatch) -> None:
    from src.application.services import search_index

    assert search_index._meili_filter("console", "goal", "lr01") == 'lab_slug = "lr01" AND kind = "goal" AND tags = "console"'

    monkeypatch.setattr(search_index.settings, "meili_enabled", True)
    monkeypatch.setattr(search_index.settings, "meili_url", "http://meili.test")
    monkeypatch.setattr(search_index.settings, "meili_index", "wiki_sections")

    calls: list[tuple[str, str, object]] = []

    def fake_meili_request(method: str, path: str, payload=None):
        calls.append((method, path, payload))
        if path.endswith("/search"):
            return {"hits": [], "estimatedTotalHits": 0}
        return {}

    monkeypatch.setattr(search_index, "_meili_request", fake_meili_request)

    synced = search_index.sync_meili_index(
        [
            {
                "lab_id": 1,
                "slug": "lr01",
                "title": "LR01",
                "tags": [],
                "sections": [{"id": "goal", "order": 1, "title": "Цель", "kind": "goal", "tags": [], "content_md": "text"}],
            }
        ]
    )
    assert synced is True
    assert any(path == "/indexes" for _, path, _ in calls)
    assert any(path.endswith("/documents") for _, path, _ in calls)

    response = search_index.search_meili("oop", tag="console", kind="goal", lab_slug="lr01", limit=5)
    assert response == {"hits": [], "estimatedTotalHits": 0}


def test_search_meili_returns_none_on_failure(monkeypatch) -> None:
    from src.application.services import search_index

    monkeypatch.setattr(search_index.settings, "meili_enabled", True)
    monkeypatch.setattr(search_index.settings, "meili_url", "http://meili.test")
    monkeypatch.setattr(search_index, "_meili_request", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    assert search_index.search_meili("oop", None, None, None, 10) is None
    assert search_index.sync_meili_index([]) is False


def test_meili_helpers_and_raw_request(monkeypatch) -> None:
    from src.application.services import search_index

    monkeypatch.setattr(search_index.settings, "meili_enabled", False)
    monkeypatch.setattr(search_index.settings, "meili_url", "")
    assert search_index.meili_is_enabled() is False
    assert search_index.ensure_meili_index() is None

    monkeypatch.setattr(search_index.settings, "meili_api_key", "secret")
    headers = search_index._meili_headers()
    assert headers["Authorization"] == "Bearer secret"

    monkeypatch.setattr(search_index.settings, "meili_url", "http://meili.test")

    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(search_index.urllib.request, "urlopen", lambda request, timeout=10: FakeResponse(b""))
    assert search_index._meili_request("GET", "/indexes") == {}

    monkeypatch.setattr(
        search_index.urllib.request,
        "urlopen",
        lambda request, timeout=10: FakeResponse(json.dumps({"ok": True}).encode("utf-8")),
    )
    assert search_index._meili_request("POST", "/indexes", {"x": 1}) == {"ok": True}


def test_ensure_meili_index_raises_for_unexpected_http_error(monkeypatch) -> None:
    from src.application.services import search_index

    monkeypatch.setattr(search_index.settings, "meili_enabled", True)
    monkeypatch.setattr(search_index.settings, "meili_url", "http://meili.test")

    def fake_request(method: str, path: str, payload=None):
        if path == "/indexes":
            raise urllib.error.HTTPError(path, 500, "boom", hdrs=None, fp=None)
        return {}

    monkeypatch.setattr(search_index, "_meili_request", fake_request)
    with pytest.raises(urllib.error.HTTPError):
        search_index.ensure_meili_index()


def test_disabled_meili_and_blank_query_sort(monkeypatch) -> None:
    from src.application.services import search_index

    monkeypatch.setattr(search_index.settings, "meili_enabled", False)
    monkeypatch.setattr(search_index.settings, "meili_url", "")
    assert search_index.sync_meili_index([]) is False
    assert search_index.search_meili("", None, None, None, 10) is None

    monkeypatch.setattr(search_index.settings, "meili_enabled", True)
    monkeypatch.setattr(search_index.settings, "meili_url", "")
    with pytest.raises(RuntimeError):
        search_index._meili_request("GET", "/indexes")

    monkeypatch.setattr(search_index.settings, "meili_url", "http://meili.test")
    payloads: list[dict] = []

    def fake_request(method: str, path: str, payload=None):
        payloads.append(payload)
        return {"hits": [], "estimatedTotalHits": 0}

    monkeypatch.setattr(search_index, "_meili_request", fake_request)
    search_index.search_meili("", None, None, None, 10)
    assert payloads[-1]["sort"] == ["lab_id:asc", "order:asc"]
