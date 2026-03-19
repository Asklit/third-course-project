from __future__ import annotations


def test_pipeline_helper_functions() -> None:
    from src.application.services import materials_pipeline as pipeline

    assert pipeline._slugify("Практическая работа №1") == "практическая-работа-1"
    assert pipeline._normalize_line("  a\u00a0b  ") == "a b"
    assert pipeline._is_code_like_line("for(i=0; i<10; i++) {") is True
    assert pipeline._looks_semantic_heading("Цель работы") is True
    assert pipeline._extract_heading_level("2", None, "Title") == 2
    assert pipeline._normalize_heading("1. Цель работы") == "Цель работы"
    assert pipeline._classify_section_kind("Контрольные вопросы") == "qa"
    assert "массивы" in pipeline._extract_tags("Изучить массив и функции")
    assert pipeline._is_noise_line("...") is True
    assert pipeline._is_subheading_candidate("Методические указания:") is True
    assert pipeline._is_image_only_line("![Иллюстрация](/assets/img.png)") is True
    assert pipeline._should_treat_as_code("Console.WriteLine(value);") is True


def test_markdown_related_helpers(tmp_path) -> None:
    from src.application.services import materials_pipeline as pipeline

    section = {"assets": [], "lines": []}
    pipeline._append_asset_to_section(section, "/assets/img.png", "Схема")
    assert section["assets"][0]["url"] == "/assets/img.png"
    assert section["lines"][0] == "![Схема](/assets/img.png)"

    assets = pipeline._extract_assets_from_markdown("Text ![A](/assets/a.png) and ![B](/assets/b.png)")
    assert len(assets) == 2

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "a.png").write_bytes(b"png")
    normalized = pipeline._normalize_curated_asset_links("lr01", "![A](/assets/a.png)", assets_dir)
    assert normalized == "![A](/assets/a.png)"

    yaml_text = pipeline._render_yaml({"slug": "lr01", "tags": ["console", "csharp"]})
    assert 'slug: "lr01"' in yaml_text


def test_parse_generated_meta_and_load_curated_lab(tmp_path, monkeypatch) -> None:
    from src.application.services import materials_pipeline as pipeline

    lab_slug = "lr01-introduction-and-tooling"
    lab_dir = tmp_path / lab_slug
    sections_dir = lab_dir / "sections"
    assets_dir = lab_dir / "assets"
    sections_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    meta_text = """lab_id: 1
slug: "lr01-introduction-and-tooling"
title: "Лабораторная работа №1"
tags:
  - "console"
  - "csharp"
source:
  file: "Практическая работа №1.docx"
stats:
  equations_detected: 0
  assets_detected: 1
sections:
  -
    id: "goal"
    file: "sections/01-goal.md"
    kind: "goal"
    title: "Цель работы"
    order: 1
    tags:
      - "intro"
"""
    (lab_dir / "meta.yaml").write_text(meta_text, encoding="utf-8")
    (sections_dir / "01-goal.md").write_text("![A](/assets/a.png)\nИзучить console app.", encoding="utf-8")
    (assets_dir / "a.png").write_bytes(b"png")

    parsed = pipeline._parse_generated_meta(lab_dir / "meta.yaml")
    assert parsed["lab_id"] == 1
    assert parsed["slug"] == lab_slug
    assert parsed["sections"][0]["id"] == "goal"
    assert parsed["sections"][0]["tags"] == ["intro"]

    monkeypatch.setattr(pipeline, "CURATED_DIR", tmp_path)
    config = pipeline.LabSourceConfig(
        lab_id=1,
        slug=lab_slug,
        title="Лабораторная работа №1",
        source_file="Практическая работа №1.docx",
        tags=["console", "csharp"],
    )

    assert pipeline._curated_lab_exists(config) is True
    loaded = pipeline._load_curated_lab(config)
    assert loaded is not None
    assert loaded["slug"] == lab_slug
    assert loaded["sections"][0]["title"] == "Цель работы"
    assert loaded["assets"][0]["url"] == "/assets/a.png"


def test_build_curated_labs_uses_existing_curated_data(tmp_path, monkeypatch) -> None:
    from src.application.services import materials_pipeline as pipeline

    curated_dir = tmp_path / "curated"
    sources_dir = tmp_path / "sources"
    curated_dir.mkdir()
    sources_dir.mkdir()

    source_file = sources_dir / "Практическая работа №1.docx"
    source_file.write_bytes(b"fake-docx")

    config = pipeline.LabSourceConfig(
        lab_id=1,
        slug="lr01-introduction-and-tooling",
        title="Лабораторная работа №1",
        source_file=source_file.name,
        tags=["console"],
    )

    monkeypatch.setattr(pipeline, "CURATED_DIR", curated_dir)
    monkeypatch.setattr(pipeline, "SOURCES_DIR", sources_dir)
    monkeypatch.setattr(pipeline, "LAB_SOURCE_CONFIG", [config])
    monkeypatch.setattr(pipeline, "_curated_lab_exists", lambda current: current.slug == config.slug)
    monkeypatch.setattr(
        pipeline,
        "_load_curated_lab",
        lambda current: {
            "lab_id": current.lab_id,
            "slug": current.slug,
            "title": current.title,
            "source_file": current.source_file,
            "tags": current.tags,
            "sections": [{"id": "goal", "title": "Цель", "kind": "goal", "order": 1, "content_md": "text", "tags": [], "assets": []}],
            "assets": [],
            "stats": {"equations_detected": 0, "assets_detected": 0},
            "search_text": "text",
        },
    )

    labs = pipeline.build_curated_labs()
    assert len(labs) == 1
    assert labs[0]["slug"] == "lr01-introduction-and-tooling"
    assert labs[0]["sections"][0]["id"] == "goal"
