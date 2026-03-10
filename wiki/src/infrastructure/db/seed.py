from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from pymongo.collection import Collection


class LabSeed(TypedDict):
    slug: str
    title: str
    content_md: str
    prerequisites: list[str]


LABS_DIR = Path(__file__).resolve().parents[3] / "materials" / "labs"


def _extract_title(markdown: str, fallback_slug: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return fallback_slug.replace("-", " ").title()


def build_lab_seed() -> list[LabSeed]:
    files = sorted(LABS_DIR.glob("lr*.md"))
    seeds: list[LabSeed] = []

    for file_path in files:
        slug = file_path.stem
        content_md = file_path.read_text(encoding="utf-8").strip()
        title = _extract_title(content_md, slug)
        previous_slug = seeds[-1]["slug"] if seeds else None

        seeds.append(
            {
                "slug": slug,
                "title": title,
                "content_md": content_md,
                "prerequisites": [previous_slug] if previous_slug else [],
            }
        )

    return seeds


def seed_labs(collection: Collection) -> int:
    seeds = build_lab_seed()

    for item in seeds:
        collection.update_one(
            {"slug": item["slug"]},
            {"$set": item},
            upsert=True,
        )

    return len(seeds)

