from __future__ import annotations

from pathlib import Path


def test_health_and_labs_endpoints(client) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    labs = client.get("/labs")
    assert labs.status_code == 200
    payload = labs.json()
    assert len(payload) == 2
    assert payload[0]["sections_count"] == 2

    filtered = client.get("/labs", params={"tag": "arrays"})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1


def test_lab_details_and_search_via_meili(wiki_module, client, monkeypatch) -> None:
    details = client.get("/labs/lr01-introduction-and-tooling")
    assert details.status_code == 200
    assert details.json()["slug"] == "lr01-introduction-and-tooling"

    monkeypatch.setattr(
        wiki_module,
        "search_meili",
        lambda **kwargs: {
            "hits": [
                {
                    "lab_slug": "lr01-introduction-and-tooling",
                    "lab_title": "Лабораторная работа №1",
                    "section_id": "goal",
                    "section_title": "Цель работы",
                    "kind": "goal",
                    "tags": ["goal"],
                    "content_plain": "Изучить консольное приложение",
                    "_formatted": {"content_plain": "Изучить <em>консольное</em> приложение"},
                }
            ],
            "estimatedTotalHits": 1,
        },
    )

    response = client.get("/search", params={"q": "консоль"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["section_id"] == "goal"


def test_search_fallback_and_not_found(client, wiki_module, monkeypatch) -> None:
    monkeypatch.setattr(wiki_module, "search_meili", lambda **kwargs: None)

    response = client.get("/search", params={"q": "console"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["lab_slug"] == "lr01-introduction-and-tooling"

    missing = client.get("/labs/unknown")
    assert missing.status_code == 404


def test_assets_endpoint_and_path_traversal(client, wiki_module, tmp_path: Path, monkeypatch) -> None:
    asset_root = tmp_path / "curated" / "lr01" / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)
    asset_path = asset_root / "sample.png"
    asset_path.write_bytes(b"png")

    monkeypatch.setattr(wiki_module, "CURATED_DIR", tmp_path / "curated")

    ok = client.get("/assets/lr01/assets/sample.png")
    assert ok.status_code == 200
    assert ok.content == b"png"

    traversal = client.get("/assets/../secret.txt")
    assert traversal.status_code == 404
