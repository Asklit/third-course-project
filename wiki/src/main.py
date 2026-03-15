import logging
import re
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient, TEXT
from pymongo.errors import PyMongoError

from src.application.services.materials_pipeline import CURATED_DIR, build_curated_labs
from src.core.config import settings
from src.core.logging import configure_logging
from src.presentation.schemas.schemas import LabDetails, LabSummary, SearchHit, SearchResponse

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


def _normalize_query_token(token: str) -> str:
    value = token.strip().lower()
    value = value.replace("ё", "е")
    return value


def _query_variants(token: str) -> list[str]:
    normalized = _normalize_query_token(token)
    variants = QUERY_SYNONYMS.get(normalized, [normalized])
    deduped: list[str] = []
    for item in variants:
        candidate = _normalize_query_token(item)
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Zа-яА-Я0-9+#]+", query) if token]


def _normalize_lab_document(item: dict) -> dict:
    item.pop("_id", None)
    item["sections_count"] = len(item.get("sections", []))
    return item


def _build_snippet(content: str, query: str, window: int = 180) -> str:
    if not query:
        return content[:window].strip()
    lowered = content.lower()
    query_lower = query.lower()
    start = lowered.find(query_lower)
    if start < 0:
        return content[:window].strip()
    from_idx = max(0, start - window // 2)
    to_idx = min(len(content), start + len(query) + window // 2)
    return content[from_idx:to_idx].strip()


def _matches_query(text: str, query: str) -> bool:
    stripped_query = query.strip()
    if not stripped_query:
        return True

    haystack = text.lower().replace("ё", "е")
    tokens = _query_tokens(stripped_query)
    if not tokens:
        return stripped_query.lower() in haystack

    for token in tokens:
        variants = _query_variants(token)
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

            logger.info(
                "wiki materials synced",
                extra={"action": "wiki.materials.sync", "status": "success", "count": len(labs)},
            )
        except PyMongoError as exc:
            logger.error("wiki startup failed", extra={"action": "wiki.startup", "status": "failed"})
            logger.debug(str(exc))
            raise

    app.mount("/assets", StaticFiles(directory=str(CURATED_DIR), html=False), name="assets")

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

        hits: list[SearchHit] = []
        query = q.strip()

        for doc in docs:
            doc_title = doc.get("title", "")
            doc_tags = " ".join(doc.get("tags", []))
            for section in doc.get("sections", []):
                if kind and section.get("kind") != kind:
                    continue
                section_text = section.get("content_md", "")
                plain = re.sub(r"\s+", " ", section_text)
                section_title = section.get("title", "")
                section_tags = " ".join(section.get("tags", []))
                searchable = " ".join([doc_title, doc_tags, section_title, section_tags, plain])

                if not _matches_query(searchable, query):
                    continue

                hits.append(
                    SearchHit(
                        lab_slug=doc["slug"],
                        lab_title=doc_title,
                        section_id=section.get("id", ""),
                        section_title=section_title,
                        kind=section.get("kind", "content"),
                        snippet=_build_snippet(plain, query),
                        tags=section.get("tags", []),
                    )
                )

        hits = hits[:limit]
        return SearchResponse(total=len(hits), items=hits)

    return app


app = create_app()
