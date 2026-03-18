from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)


QUERY_SYNONYMS: dict[str, list[str]] = {
    "ооп": ["ооп", "oop", "object oriented", "объектно"],
    "oop": ["oop", "ооп", "object oriented", "объектно"],
    "console": ["console", "консоль", "консольн"],
    "консоль": ["консоль", "console", "консольн"],
    "c#": ["c#", "csharp", "с#", "шарп"],
    "с#": ["с#", "c#", "csharp", "шарп"],
    "csharp": ["csharp", "c#", "с#", "шарп"],
}


def normalize_query_token(token: str) -> str:
    return token.strip().lower().replace("ё", "е")


def query_variants(token: str) -> list[str]:
    normalized = normalize_query_token(token)
    raw_variants = QUERY_SYNONYMS.get(normalized, [normalized])
    variants: list[str] = []
    for item in raw_variants:
        candidate = normalize_query_token(item)
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


def query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Zа-яА-Я0-9+#]+", query) if token]


def strip_markdown(content: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", content)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
    text = re.sub(r"`{1,3}", " ", text)
    text = re.sub(r"#+\s*", " ", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def section_search_documents(labs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for lab in labs:
        lab_tags = list(lab.get("tags", []))
        for section in lab.get("sections", []):
            section_tags = list(section.get("tags", []))
            combined_tags = sorted(set([*lab_tags, *section_tags]))
            plain = strip_markdown(section.get("content_md", ""))
            documents.append(
                {
                    "id": f"{lab.get('lab_id', 0)}-{int(section.get('order', 0)):03d}",
                    "lab_id": lab.get("lab_id", 0),
                    "lab_slug": lab["slug"],
                    "lab_title": lab.get("title", ""),
                    "section_id": section.get("id", ""),
                    "section_title": section.get("title", ""),
                    "kind": section.get("kind", "content"),
                    "order": section.get("order", 0),
                    "tags": combined_tags,
                    "search_tags": section_tags,
                    "section_tags": section_tags,
                    "lab_tags": lab_tags,
                    "content_md": section.get("content_md", ""),
                    "content_plain": plain,
                }
            )
    return documents


def meili_is_enabled() -> bool:
    return bool(settings.meili_enabled and settings.meili_url)


def _meili_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.meili_api_key:
        headers["Authorization"] = f"Bearer {settings.meili_api_key}"
    return headers


def _meili_request(method: str, path: str, payload: dict[str, Any] | list[dict[str, Any]] | None = None) -> Any:
    if not settings.meili_url:
        raise RuntimeError("Meilisearch URL is not configured")

    url = f"{settings.meili_url.rstrip('/')}{path}"
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(url=url, data=data, method=method.upper(), headers=_meili_headers())
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


def ensure_meili_index() -> None:
    if not meili_is_enabled():
        return

    try:
        _meili_request(
            "POST",
            "/indexes",
            {"uid": settings.meili_index, "primaryKey": "id"},
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise

    _meili_request(
        "PATCH",
        f"/indexes/{settings.meili_index}/settings",
        {
            "searchableAttributes": ["section_title", "content_plain", "lab_title", "search_tags", "kind"],
            "filterableAttributes": ["lab_slug", "kind", "tags", "lab_id"],
            "sortableAttributes": ["lab_id", "order"],
            "displayedAttributes": [
                "id",
                "lab_id",
                "lab_slug",
                "lab_title",
                "section_id",
                "section_title",
                "kind",
                "order",
                "tags",
                "search_tags",
                "content_plain",
            ],
            "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
            "typoTolerance": {"enabled": True},
            "synonyms": QUERY_SYNONYMS,
        },
    )


def sync_meili_index(labs: list[dict[str, Any]]) -> bool:
    if not meili_is_enabled():
        return False

    documents = section_search_documents(labs)
    try:
        ensure_meili_index()
        _meili_request("DELETE", f"/indexes/{settings.meili_index}/documents")
        _meili_request("PUT", f"/indexes/{settings.meili_index}/documents", documents)
        logger.info(
            "meilisearch index synced",
            extra={"action": "wiki.search.sync", "status": "success", "count": len(documents)},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "meilisearch sync failed",
            extra={"action": "wiki.search.sync", "status": "failed", "error": str(exc)},
        )
        return False


def _meili_filter(tag: str | None, kind: str | None, lab_slug: str | None) -> str | None:
    def escape_filter(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    filters: list[str] = []
    if lab_slug:
        filters.append(f'lab_slug = "{escape_filter(lab_slug)}"')
    if kind:
        filters.append(f'kind = "{escape_filter(kind)}"')
    if tag:
        filters.append(f'tags = "{escape_filter(tag)}"')
    if not filters:
        return None
    return " AND ".join(filters)


def search_meili(q: str, tag: str | None, kind: str | None, lab_slug: str | None, limit: int) -> dict[str, Any] | None:
    if not meili_is_enabled():
        return None

    payload: dict[str, Any] = {
        "q": q,
        "limit": limit,
        "attributesToCrop": ["content_plain"],
        "cropLength": 24,
        "attributesToRetrieve": [
            "lab_slug",
            "lab_title",
            "section_id",
            "section_title",
            "kind",
            "tags",
            "content_plain",
        ],
    }
    filter_expr = _meili_filter(tag, kind, lab_slug)
    if filter_expr:
        payload["filter"] = filter_expr
    if not q.strip():
        payload["sort"] = ["lab_id:asc", "order:asc"]

    try:
        return _meili_request("POST", f"/indexes/{settings.meili_index}/search", payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "meilisearch query failed",
            extra={"action": "wiki.search.query", "status": "failed", "error": str(exc)},
        )
        return None
