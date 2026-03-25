import logging
import re
import uuid

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pymongo import MongoClient, TEXT
from pymongo.errors import PyMongoError

from src.application.services.materials_pipeline import CURATED_DIR, build_curated_labs, _try_convert_vector_to_png
from src.application.services.search_index import (
    normalize_query_token,
    query_tokens,
    query_variants,
    search_meili,
    strip_markdown,
    sync_meili_index,
)
from src.core.config import settings
from src.core.logging import configure_logging
from src.presentation.schemas.schemas import LabDetails, LabSummary, SearchHit, SearchResponse

logger = logging.getLogger(__name__)


def _normalize_lab_document(item: dict) -> dict:
    item.pop("_id", None)
    item["sections_count"] = len(item.get("sections", []))
    return item


def _build_snippet(content: str, query: str, window: int = 180) -> str:
    if not query:
        return content[:window].strip()
    lowered = normalize_query_token(content)
    query_lower = normalize_query_token(query)
    start = lowered.find(query_lower)
    if start < 0:
        return content[:window].strip()
    from_idx = max(0, start - window // 2)
    to_idx = min(len(content), start + len(query) + window // 2)
    return content[from_idx:to_idx].strip()


def _score_hit(doc_title: str, doc_tags: list[str], section_title: str, section_tags: list[str], plain: str, query: str) -> int:
    score = 0
    normalized_query = normalize_query_token(query)
    tokens = query_tokens(query)
    content_lower = normalize_query_token(plain)
    title_lower = normalize_query_token(doc_title)
    section_title_lower = normalize_query_token(section_title)
    tags_lower = [normalize_query_token(tag) for tag in [*doc_tags, *section_tags]]

    if normalized_query:
        if normalized_query in section_title_lower:
            score += 120
        if normalized_query in title_lower:
            score += 80
        if any(normalized_query == tag for tag in tags_lower):
            score += 140
        if normalized_query in content_lower:
            score += 40

    for token in tokens:
        for variant in query_variants(token):
            if variant in section_title_lower:
                score += 40
            if variant in title_lower:
                score += 20
            if any(variant == tag for tag in tags_lower):
                score += 50
            if variant in content_lower:
                score += 10

    return score


def _matches_query(text: str, query: str) -> bool:
    stripped_query = query.strip()
    if not stripped_query:
        return True

    haystack = normalize_query_token(text)
    tokens = query_tokens(stripped_query)
    if not tokens:
        return normalize_query_token(stripped_query) in haystack

    for token in tokens:
        variants = query_variants(token)
        if not any(variant in haystack for variant in variants):
            return False
    return True


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name)

    client = MongoClient(settings.mongo_url)
    collection = client[settings.mongo_db][settings.mongo_collection]

    @app.middleware("http")
    async def request_trace_middleware(request: Request, call_next):
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        logger.info(
            f"{request.method} {request.url.path}",
            extra={"trace_id": trace_id, "action": "http.request", "status": response.status_code},
        )
        return response

    @app.on_event("startup")
    def startup() -> None:
        try:
            collection.create_index("slug", unique=True)
            collection.create_index([("title", TEXT), ("search_text", TEXT), ("sections.title", TEXT), ("sections.content_md", TEXT)])
            collection.create_index("tags")
            collection.create_index("sections.kind")

            labs = build_curated_labs()
            for item in labs:
                collection.update_one({"slug": item["slug"]}, {"$set": item}, upsert=True)
            valid_slugs = [item["slug"] for item in labs]
            if valid_slugs:
                collection.delete_many({"slug": {"$nin": valid_slugs}})
            sync_meili_index(labs)

            logger.info(
                "wiki materials synced",
                extra={"action": "wiki.materials.sync", "status": "success", "count": len(labs)},
            )
        except PyMongoError as exc:
            logger.error("wiki startup failed", extra={"action": "wiki.startup", "status": "failed"})
            logger.debug(str(exc))
            raise

    @app.get("/assets/{asset_path:path}")
    def asset(asset_path: str):
        source_path = (CURATED_DIR / Path(asset_path)).resolve()
        curated_root = CURATED_DIR.resolve()
        if curated_root not in source_path.parents and source_path != curated_root:
            raise HTTPException(status_code=404, detail="Asset not found")
        if not source_path.exists() or not source_path.is_file():
            raise HTTPException(status_code=404, detail="Asset not found")

        ext = source_path.suffix.lower()
        if ext in {".wmf", ".emf"}:
            converted_path = source_path.with_suffix(".png")
            if not converted_path.exists():
                _try_convert_vector_to_png(source_path, converted_path)
            if converted_path.exists():
                return FileResponse(converted_path, media_type="image/png")

        media_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".wmf": "application/octet-stream",
            ".emf": "application/octet-stream",
        }
        return FileResponse(source_path, media_type=media_map.get(ext, "application/octet-stream"))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/labs", response_model=list[LabSummary])
    def labs(
        tag: str | None = Query(default=None),
        kind: str | None = Query(default=None),
    ) -> list[LabSummary]:
        mongo_filter: dict = {}
        if tag:
            mongo_filter["tags"] = tag
        if kind:
            mongo_filter["sections.kind"] = kind

        items = list(
            collection.find(
                mongo_filter,
                {"_id": 0, "lab_id": 1, "slug": 1, "title": 1, "tags": 1, "sections": 1},
            ).sort("lab_id", 1)
        )

        return [LabSummary(**_normalize_lab_document(item)) for item in items]

    @app.get("/labs/{slug}", response_model=LabDetails)
    def lab_details(slug: str) -> LabDetails:
        item = collection.find_one({"slug": slug}, {"_id": 0})
        if not item:
            raise HTTPException(status_code=404, detail="Lab not found")

        logger.info("lab returned", extra={"action": "lab.read", "status": "success"})
        return LabDetails(**_normalize_lab_document(item))

    @app.get("/search", response_model=SearchResponse)
    def search(
        q: str = Query(default="", min_length=0),
        tag: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        lab_slug: str | None = Query(default=None),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> SearchResponse:
        meili_response = search_meili(q=q, tag=tag, kind=kind, lab_slug=lab_slug, limit=limit)
        if meili_response is not None:
            hits = [
                SearchHit(
                    lab_slug=item.get("lab_slug", ""),
                    lab_title=item.get("lab_title", ""),
                    section_id=item.get("section_id", ""),
                    section_title=item.get("section_title", ""),
                    kind=item.get("kind", "content"),
                    snippet=(item.get("_formatted", {}).get("content_plain") or item.get("content_plain", "")).strip(),
                    tags=item.get("tags", []),
                )
                for item in meili_response.get("hits", [])
            ]
            total = int(meili_response.get("estimatedTotalHits", len(hits)))
            return SearchResponse(total=total, items=hits)

        mongo_filter: dict = {}
        if tag:
            mongo_filter["tags"] = tag
        if kind:
            mongo_filter["sections.kind"] = kind
        if lab_slug:
            mongo_filter["slug"] = lab_slug

        docs = list(
            collection.find(
                mongo_filter,
                {"_id": 0, "slug": 1, "title": 1, "tags": 1, "sections": 1},
            ).limit(300)
        )

        scored_hits: list[tuple[int, SearchHit]] = []
        query = q.strip()

        for doc in docs:
            doc_title = doc.get("title", "")
            doc_tags = " ".join(doc.get("tags", []))
            doc_hits_before = len(scored_hits)
            for section in doc.get("sections", []):
                if kind and section.get("kind") != kind:
                    continue
                section_text = section.get("content_md", "")
                plain = strip_markdown(section_text)
                section_title = section.get("title", "")
                section_tags = " ".join(section.get("tags", []))
                searchable = " ".join([doc_title, section_title, section_tags, plain])

                if not _matches_query(searchable, query):
                    continue

                hit = SearchHit(
                    lab_slug=doc["slug"],
                    lab_title=doc_title,
                    section_id=section.get("id", ""),
                    section_title=section_title,
                    kind=section.get("kind", "content"),
                    snippet=_build_snippet(plain, query),
                    tags=section.get("tags", []),
                )
                scored_hits.append(
                    (
                        _score_hit(doc_title, doc.get("tags", []), section_title, section.get("tags", []), plain, query),
                        hit,
                    )
                )

            if query and len(scored_hits) == doc_hits_before and _matches_query(" ".join([doc_title, doc_tags]), query):
                preferred_order = {"theory": 0, "goal": 1, "task": 2, "variants": 3, "content": 4}
                fallback_sections = sorted(
                    doc.get("sections", []),
                    key=lambda section: (
                        preferred_order.get(section.get("kind", "content"), 9),
                        section.get("order", 999),
                    ),
                )
                if fallback_sections:
                    section = fallback_sections[0]
                    plain = strip_markdown(section.get("content_md", ""))
                    hit = SearchHit(
                        lab_slug=doc["slug"],
                        lab_title=doc_title,
                        section_id=section.get("id", ""),
                        section_title=section.get("title", ""),
                        kind=section.get("kind", "content"),
                        snippet=_build_snippet(plain, query),
                        tags=section.get("tags", []),
                    )
                    scored_hits.append((90, hit))

        scored_hits.sort(key=lambda item: (-item[0], item[1].lab_title, item[1].section_title))
        total = len(scored_hits)
        hits = [item[1] for item in scored_hits[:limit]]
        return SearchResponse(total=total, items=hits)

    return app


app = create_app()
