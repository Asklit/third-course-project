from pydantic import BaseModel


class LabSummary(BaseModel):
    slug: str
    title: str


class LabDetails(LabSummary):
    content_md: str
    prerequisites: list[str] = []
