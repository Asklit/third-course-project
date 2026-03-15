from datetime import datetime

from pydantic import BaseModel


class MaterialAsset(BaseModel):
    id: str
    url: str
    type: str
    caption: str


class LabSection(BaseModel):
    id: str
    title: str
    kind: str
    order: int
    content_md: str
    tags: list[str] = []
    assets: list[MaterialAsset] = []


class LabSummary(BaseModel):
    lab_id: int
    slug: str
    title: str
    tags: list[str] = []
    sections_count: int


class LabDetails(LabSummary):
    source_file: str
    updated_at: datetime
    stats: dict[str, int]
    sections: list[LabSection] = []
    assets: list[MaterialAsset] = []


class SearchHit(BaseModel):
    lab_slug: str
    lab_title: str
    section_id: str
    section_title: str
    kind: str
    snippet: str
    tags: list[str] = []


class SearchResponse(BaseModel):
    total: int
    items: list[SearchHit]
