import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from pymongo import MongoClient

from src.core.config import settings
from src.core.logging import configure_logging
from src.presentation.schemas.schemas import LabDetails, LabSummary

logger = logging.getLogger(__name__)


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
        collection.create_index("slug", unique=True)

        if collection.count_documents({}) == 0:
            collection.insert_many(
                [
                    {
                        "slug": "lr1-intro",
                        "title": "LR1: Intro",
                        "content_md": "# LR1 Intro\n\n- Setup project\n- Implement first endpoint\n- Prepare report",
                        "prerequisites": [],
                    },
                    {
                        "slug": "lr2-data-structures",
                        "title": "LR2: Data Structures",
                        "content_md": "# LR2 Data Structures\n\n- Lists and dicts\n- Complexity basics\n- Practical tasks",
                        "prerequisites": ["lr1-intro"],
                    },
                ]
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/labs", response_model=list[LabSummary])
    def labs() -> list[LabSummary]:
        items = list(collection.find({}, {"_id": 0, "slug": 1, "title": 1}).sort("slug", 1))
        return [LabSummary(**item) for item in items]

    @app.get("/labs/{slug}", response_model=LabDetails)
    def lab_details(slug: str) -> LabDetails:
        item = collection.find_one({"slug": slug}, {"_id": 0})
        if not item:
            raise HTTPException(status_code=404, detail="Lab not found")

        logger.info("lab returned", extra={"action": "lab.read", "status": "success"})
        return LabDetails(**item)

    return app


app = create_app()
