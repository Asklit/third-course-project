from __future__ import annotations

import posixpath
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parents[3]
MATERIALS_DIR = ROOT_DIR / "materials"
SOURCES_DIR = MATERIALS_DIR / "sources"
CURATED_DIR = MATERIALS_DIR / "curated"


DOCX_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "v": "urn:schemas-microsoft-com:vml",
}


@dataclass(frozen=True)
class LabSourceConfig:
    lab_id: int
    slug: str
    title: str
    source_file: str
    tags: list[str]


LAB_SOURCE_CONFIG: list[LabSourceConfig] = [
    LabSourceConfig(1, "lr01-introduction-and-tooling", "Лабораторная работа №1", "Практическая работа №1.docx", ["csharp", "console", "math"]),
    LabSourceConfig(2, "lr02-data-structures", "Лабораторная работа №2", "Практическая работа №2.docx", ["operators", "loops", "conditions"]),
    LabSourceConfig(3, "lr03-functions-and-modules", "Лабораторная работа №3", "Практическая работа №3.docx", ["recurrence", "complexity"]),
    LabSourceConfig(4, "lr04-error-handling", "Лабораторная работа №4", "Практическая работа №4.docx", ["arrays", "data-processing"]),
    # Shared source document for labs 5 and 6 is published as a single wiki material.
    LabSourceConfig(5, "lr05-files-and-serialization", "Лабораторная работа №5-6", "Практическая работа №5_6.docx", ["lr5", "lr6", "functions", "arrays", "strings"]),
    LabSourceConfig(9, "lr09-testing-basics", "Лабораторная работа №9", "Практическая работа №9.docx", ["oop", "unit-tests"]),
    LabSourceConfig(10, "lr10-web-fundamentals", "Лабораторная работа №10", "Практическая работа №10.docx", ["inheritance", "virtual-methods"]),
    LabSourceConfig(11, "lr11-rest-api-basics", "Лабораторная работа №11", "Практическая работа №11 new2024.docx", ["collections", "variants"]),
    LabSourceConfig(12, "lr12-databases-and-sql", "Лабораторная работа №12", "Практическая работа №12.docx", ["custom-collections"]),
    LabSourceConfig(13, "lr13-orm-integration", "Лабораторная работа №13", "Практическая работа №13.docx", ["events", "delegates"]),
    LabSourceConfig(14, "lr14-async-programming", "Лабораторная работа №14", "Практическая работа №14.docx", ["linq", "extension-methods"]),
]


STRUCTURE_KEYWORDS = (
    "цель",
    "теорет",
    "постановка",
    "задани",
    "вариант",
    "содержание отчета",
    "контрольные вопросы",
    "методические указания",
    "литература",
    "критерии",
)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9а-яА-Я]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-")
    return cleaned or "section"


def _contains_letters(text: str) -> bool:
    return bool(re.search(r"[a-zA-Zа-яА-Я]", text))


def _normalize_line(text: str) -> str:
    cleaned = text.replace("\u00a0", " ").replace("\xad", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _is_code_like_line(text: str) -> bool:
    stripped = text.strip().lower()
    if not stripped:
        return False
    if stripped.startswith("//") or stripped.startswith("#include"):
        return True
    if any(token in stripped for token in ["{", "}", ";", "=>", "==", "!=", " for(", " while(", "switch("]):
        return True
    if re.match(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)+\s*\(", stripped):
        return True
    return False


def _looks_semantic_heading(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4 or len(stripped) > 150:
        return False
    if not _contains_letters(stripped):
        return False
    if _is_code_like_line(stripped):
        return False
    if re.match(r"^[\d\s.,;:()/%+-]+$", stripped):
        return False

    words = re.findall(r"[a-zA-Zа-яА-Я0-9]+", stripped, flags=re.UNICODE)
    if len(words) > 16:
        return False
    if len(words) >= 2:
        return True

    lowered = stripped.lower()
    return any(keyword in lowered for keyword in STRUCTURE_KEYWORDS)


def _extract_styles(archive: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str], set[str]]:
    styles_path = "word/styles.xml"
    if styles_path not in archive.namelist():
        return {}, {}, set()

    styles_root = ET.fromstring(archive.read(styles_path))
    style_name_by_id: dict[str, str] = {}
    based_on: dict[str, str] = {}

    for style in styles_root.findall(".//w:style", NS):
        style_id = style.attrib.get(f"{{{NS['w']}}}styleId")
        if not style_id:
            continue
        name_node = style.find("./w:name", NS)
        based_node = style.find("./w:basedOn", NS)
        style_name_by_id[style_id] = (name_node.attrib.get(f"{{{NS['w']}}}val", "") if name_node is not None else "").lower()
        if based_node is not None:
            based_id = based_node.attrib.get(f"{{{NS['w']}}}val")
            if based_id:
                based_on[style_id] = based_id

    heading_ids: set[str] = set()

    def is_heading_chain(style_id: str) -> bool:
        seen: set[str] = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            name = style_name_by_id.get(current, "")
            lowered_id = current.lower()
            if "heading" in lowered_id or "заголов" in lowered_id or "heading" in name or "заголов" in name:
                return True
            if re.fullmatch(r"[1-6]", current):
                return True
            current = based_on.get(current, "")
        return False

    for style_id in style_name_by_id:
        if is_heading_chain(style_id):
            heading_ids.add(style_id)

    return style_name_by_id, based_on, heading_ids


def _extract_numbering_kinds(archive: zipfile.ZipFile) -> dict[str, str]:
    numbering_path = "word/numbering.xml"
    if numbering_path not in archive.namelist():
        return {}

    root = ET.fromstring(archive.read(numbering_path))
    abstract_kind_by_id: dict[str, str] = {}
    for abstract in root.findall("./w:abstractNum", NS):
        abstract_id = abstract.attrib.get(f"{{{NS['w']}}}abstractNumId")
        if not abstract_id:
            continue
        kind = "ordered"
        for lvl in abstract.findall("./w:lvl", NS):
            fmt_node = lvl.find("./w:numFmt", NS)
            fmt_val = fmt_node.attrib.get(f"{{{NS['w']}}}val", "") if fmt_node is not None else ""
            if fmt_val == "bullet":
                kind = "bullet"
                break
        abstract_kind_by_id[abstract_id] = kind

    num_kind_by_id: dict[str, str] = {}
    for num in root.findall("./w:num", NS):
        num_id = num.attrib.get(f"{{{NS['w']}}}numId")
        abstract_ref = num.find("./w:abstractNumId", NS)
        abstract_id = abstract_ref.attrib.get(f"{{{NS['w']}}}val") if abstract_ref is not None else None
        if num_id and abstract_id:
            num_kind_by_id[num_id] = abstract_kind_by_id.get(abstract_id, "ordered")
    return num_kind_by_id


def _extract_heading_level(style_id: str | None, style_name: str | None, text: str) -> int | None:
    if style_id and re.fullmatch(r"[1-6]", style_id):
        return int(style_id)

    if style_name:
        match = re.search(r"heading\s*([1-6])", style_name, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match_ru = re.search(r"заголовок\s*([1-6])", style_name, flags=re.IGNORECASE)
        if match_ru:
            return int(match_ru.group(1))

    numbered = re.match(r"^(\d+(?:\.\d+){0,3})[.)]?\s+", text.strip())
    if numbered:
        parts = numbered.group(1).split(".")
        return max(1, min(6, len(parts)))

    return None


def _is_structural_heading(text: str, style_id: str | None, style_name: str | None, heading_ids: set[str]) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    has_keyword = any(keyword in lowered for keyword in STRUCTURE_KEYWORDS)
    word_count = len(re.findall(r"[a-zA-Zа-яА-Я0-9]+", lowered, flags=re.UNICODE))

    def style_heading_allowed(value: str) -> bool:
        if not _looks_semantic_heading(value):
            return False
        if _is_code_like_line(value):
            return False
        if not has_keyword and word_count > 12:
            return False
        if not has_keyword and word_count > 8 and value.strip().endswith("."):
            return False
        return True

    if style_id and style_id in heading_ids:
        return style_heading_allowed(text)

    if style_name and ("heading" in style_name or "заголов" in style_name):
        return style_heading_allowed(text)

    numbered = re.match(r"^(\d+(?:\.\d+){1,2})[.)]?\s+(.+)$", text.strip())
    if numbered:
        tail = numbered.group(2).strip()
        word_count = len(re.findall(r"[a-zA-Zа-яА-Я0-9]+", tail, flags=re.UNICODE))
        if _looks_semantic_heading(tail) and not _is_code_like_line(tail):
            if has_keyword:
                return True
            if word_count <= 8 and not tail.endswith((".", ";", ":")):
                return True

    if has_keyword and _looks_semantic_heading(text):
        return True

    return False


def _normalize_heading(text: str) -> str:
    normalized = re.sub(r"^\d+(?:\.\d+){0,2}[.)]?\s*", "", text).strip()
    normalized = re.sub(r"^[-*]\s+", "", normalized)
    normalized = normalized.strip(" :")
    return normalized or text.strip()


def _classify_section_kind(section_title: str) -> str:
    lowered = section_title.lower()
    if "цель" in lowered:
        return "goal"
    if "теорет" in lowered:
        return "theory"
    if "задани" in lowered or "постановка" in lowered:
        return "task"
    if "вариант" in lowered:
        return "variants"
    if "отчет" in lowered:
        return "report"
    if "вопрос" in lowered:
        return "qa"
    if "методичес" in lowered:
        return "method"
    return "content"


def _extract_tags(text: str) -> list[str]:
    lowered = text.lower()
    patterns = {
        "варианты": "вариант",
        "теория": "теорет",
        "массивы": "массив",
        "функции": "функц",
        "классы": "класс",
        "коллекции": "коллекц",
        "события": "событ",
        "linq": "linq",
        "тесты": "тест",
        "делегаты": "делегат",
    }
    tags = [tag for tag, needle in patterns.items() if needle in lowered]
    return sorted(set(tags))


def _is_noise_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) <= 2 and not _contains_letters(stripped):
        return True
    if len(stripped) < 8 and re.match(r"^[\d\s.,;:()/%+-]+$", stripped):
        return True
    return False


def _is_subheading_candidate(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4 or len(stripped) > 90:
        return False
    if _is_code_like_line(stripped):
        return False
    if re.match(r"^[\d\s.,;:()/%+-]+$", stripped):
        return False
    words = re.findall(r"[a-zA-Zа-яА-Я0-9]+", stripped, flags=re.UNICODE)
    if not words or len(words) > 12:
        return False
    if stripped.endswith(":"):
        return True
    lowered = stripped.lower()
    return any(
        marker in lowered
        for marker in ("постановка задачи", "методические указания", "содержание отчета", "вопросы для защиты", "критерии")
    )


def _extract_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    rels_path = "word/_rels/document.xml.rels"
    if rels_path not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read(rels_path))
    relationships: dict[str, str] = {}
    for rel in root.findall(f".//{{{DOCX_REL_NS}}}Relationship"):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            normalized = posixpath.normpath(target.replace("\\", "/")).lstrip("./")
            if normalized.startswith("../"):
                normalized = normalized[3:]
            relationships[rid] = normalized
    return relationships


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _extract_image_rids(node: ET.Element) -> list[str]:
    image_rids: list[str] = []
    for blip in node.findall(".//a:blip", NS):
        rid = blip.attrib.get(f"{{{NS['r']}}}embed")
        if rid:
            image_rids.append(rid)
    for v_img in node.findall(".//v:imagedata", NS):
        rid = v_img.attrib.get(f"{{{NS['r']}}}id")
        if rid:
            image_rids.append(rid)
    return image_rids


def _parse_paragraph_element(
    paragraph: ET.Element,
    style_name_by_id: dict[str, str],
    heading_style_ids: set[str],
    numbering_kind_by_num_id: dict[str, str],
) -> dict[str, Any] | None:
    text_parts = [(node.text or "") for node in paragraph.findall(".//w:t", NS)]
    text = _normalize_line("".join(text_parts))

    style_node = paragraph.find("./w:pPr/w:pStyle", NS)
    style_id = style_node.attrib.get(f"{{{NS['w']}}}val") if style_node is not None else None
    style_name = style_name_by_id.get(style_id or "", "")
    heading_level = _extract_heading_level(style_id, style_name, text)
    num_id_node = paragraph.find("./w:pPr/w:numPr/w:numId", NS)
    ilvl_node = paragraph.find("./w:pPr/w:numPr/w:ilvl", NS)
    num_id = num_id_node.attrib.get(f"{{{NS['w']}}}val") if num_id_node is not None else None
    list_level = int(ilvl_node.attrib.get(f"{{{NS['w']}}}val", "0")) if ilvl_node is not None else 0
    list_kind = numbering_kind_by_num_id.get(num_id or "", "ordered") if num_id else None
    image_rids = _extract_image_rids(paragraph)

    if not text and not image_rids:
        return None

    return {
        "type": "paragraph",
        "text": text,
        "style_id": style_id,
        "style_name": style_name,
        "is_heading_style": bool(style_id and style_id in heading_style_ids),
        "heading_level": heading_level,
        "is_list_item": bool(num_id),
        "list_level": list_level,
        "list_kind": list_kind,
        "image_rids": image_rids,
    }


def _collect_cell_content(cell: ET.Element) -> tuple[str, list[str]]:
    chunks: list[str] = []
    image_rids: list[str] = []
    for paragraph in cell.findall(".//w:p", NS):
        raw = "".join((node.text or "") for node in paragraph.findall(".//w:t", NS))
        normalized = _normalize_line(raw)
        if normalized:
            chunks.append(normalized)
        for rid in _extract_image_rids(paragraph):
            image_rids.append(rid)
            chunks.append(f"[[IMG:{rid}]]")
    if not chunks:
        return "", image_rids
    return "<br>".join(chunks), image_rids


def _parse_table_element(table: ET.Element) -> dict[str, Any] | None:
    rows: list[list[str]] = []
    table_image_rids: list[str] = []

    for row in table.findall("./w:tr", NS):
        cells: list[str] = []
        for cell in row.findall("./w:tc", NS):
            cell_text, cell_rids = _collect_cell_content(cell)
            table_image_rids.extend(cell_rids)
            value = cell_text.replace("|", r"\|")
            cells.append(value)
        if any(cell.strip() for cell in cells):
            rows.append(cells)

    if not rows:
        image_rids = _extract_image_rids(table)
        if not image_rids:
            return None
        return {"type": "table", "lines": [], "image_rids": image_rids}

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    body_rows = normalized_rows[1:]
    divider = ["---"] * column_count

    lines = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join(divider)} |",
    ]
    for row in body_rows:
        lines.append(f"| {' | '.join(row)} |")

    return {"type": "table", "lines": lines, "image_rids": table_image_rids}


def _extract_document_blocks(
    document_root: ET.Element,
    style_name_by_id: dict[str, str],
    heading_style_ids: set[str],
    numbering_kind_by_num_id: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    blocks: list[dict[str, Any]] = []
    equations_count = len(document_root.findall(".//m:oMath", NS)) + len(document_root.findall(".//m:oMathPara", NS))
    body = document_root.find("./w:body", NS)
    if body is None:
        return blocks, equations_count

    for element in list(body):
        node_type = _local_name(element.tag)
        if node_type == "p":
            parsed = _parse_paragraph_element(element, style_name_by_id, heading_style_ids, numbering_kind_by_num_id)
            if parsed is not None:
                blocks.append(parsed)
            continue
        if node_type == "tbl":
            parsed_table = _parse_table_element(element)
            if parsed_table is not None:
                blocks.append(parsed_table)

    return blocks, equations_count


def _copy_asset(archive: zipfile.ZipFile, target: str, destination: Path, asset_name: str) -> bool:
    normalized_target = target.replace("\\", "/")
    source_name = f"word/{normalized_target}"
    if source_name not in archive.namelist():
        return False
    destination.mkdir(parents=True, exist_ok=True)
    with archive.open(source_name) as src, open(destination / asset_name, "wb") as out:
        out.write(src.read())
    return True


def _try_convert_vector_to_png(source_path: Path, destination_path: Path) -> bool:
    magick = shutil.which("magick")
    if not magick:
        magick = None
    if magick:
        try:
            completed = subprocess.run(
                [magick, str(source_path), str(destination_path)],
                check=False,
                capture_output=True,
            )
            if completed.returncode == 0 and destination_path.exists():
                return True
        except OSError:
            pass

    soffice = shutil.which("soffice")
    if not soffice:
        return False
    try:
        completed = subprocess.run(
            [soffice, "--headless", "--convert-to", "png", "--outdir", str(destination_path.parent), str(source_path)],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            return False
        office_output = destination_path.parent / f"{source_path.stem}.png"
        if office_output.exists():
            if office_output != destination_path:
                office_output.replace(destination_path)
            return True
        return destination_path.exists()
    except OSError:
        return False


def _strip_manual_list_marker(text: str) -> tuple[str, str | None]:
    ordered_match = re.match(r"^\s*(\d+)[\).]\s+(.+)$", text)
    if ordered_match:
        return ordered_match.group(2).strip(), "ordered"
    bullet_match = re.match(r"^\s*[-•–]\s+(.+)$", text)
    if bullet_match:
        return bullet_match.group(1).strip(), "bullet"
    return text, None


def _format_list_item(text: str, list_kind: str, level: int = 0) -> str:
    indent = "  " * max(level, 0)
    marker = "1." if list_kind == "ordered" else "-"
    return f"{indent}{marker} {text.strip()}"


def _is_markdown_list_line(text: str) -> bool:
    return bool(re.match(r"^\s*(?:-|\d+\.)\s+", text))


def _is_probable_code_line(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    if not stripped:
        return False
    has_cyrillic = bool(re.search(r"[а-яА-Я]", stripped))
    if re.match(r"^(//|/\*|\*|#include|using\s+[A-Za-z_]|import\s+[A-Za-z_]|print\()", stripped):
        return True
    if "{" in stripped or "}" in stripped:
        return True
    if re.search(r"\b(class|public|private|protected|static|void|namespace|console|return|new|try|catch)\b", lowered):
        return True
    if has_cyrillic:
        return False
    if re.search(r"\b(if|else|for|while|switch|case|int|string|double|float|bool|var)\b", lowered):
        return True
    if ";" in stripped and re.search(r"[A-Za-z_]", stripped) and any(token in stripped for token in ("(", ")", "=")):
        return True
    return False


def _compose_section_markdown(lines: list[str]) -> str:
    prepared = [line.rstrip() for line in lines if line is not None]
    output: list[str] = []
    idx = 0
    total = len(prepared)

    while idx < total:
        line = prepared[idx]
        if not line.strip():
            if output and output[-1] != "":
                output.append("")
            idx += 1
            continue

        if _is_probable_code_line(line) and not _is_markdown_list_line(line) and not line.startswith(("#", "|", "![", ">")):
            block: list[str] = []
            while idx < total:
                candidate = prepared[idx]
                if not candidate.strip():
                    break
                if not _is_probable_code_line(candidate):
                    break
                block.append(candidate)
                idx += 1
            if block:
                if output and output[-1] != "":
                    output.append("")
                output.append("```csharp")
                output.extend(block)
                output.append("```")
                output.append("")
                continue

        is_list = _is_markdown_list_line(line)
        is_table = line.startswith("|")
        prev = output[-1] if output else ""
        prev_is_list = _is_markdown_list_line(prev)
        prev_is_table = prev.startswith("|")

        if output and prev != "":
            if not ((is_list and prev_is_list) or (is_table and prev_is_table)):
                output.append("")
        output.append(line)
        idx += 1

    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


def _is_fragment_section(section: dict[str, Any]) -> bool:
    section_text_len = sum(len(line) for line in section["lines"])
    if section["kind"] != "content":
        return False
    if section["assets"]:
        return False
    if section_text_len >= 240:
        return False

    title = section["title"].strip()
    if not title:
        return True
    if _is_code_like_line(title):
        return True
    if len(re.findall(r"[a-zA-Zа-яА-Я0-9]+", title, flags=re.UNICODE)) <= 2 and not any(k in title.lower() for k in STRUCTURE_KEYWORDS):
        return True
    return False


def _merge_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for section in sections:
        if merged and _is_fragment_section(section):
            merged[-1]["lines"].append(f"### {section['title']}")
            merged[-1]["lines"].extend(section["lines"])
            merged[-1]["tags"] = sorted(set(merged[-1]["tags"] + section["tags"]))
            merged[-1]["assets"].extend(section["assets"])
            continue
        merged.append(section)

    seen: dict[str, int] = {}
    for section in merged:
        base_id = section["id"] or "section"
        if base_id not in seen:
            seen[base_id] = 1
            continue
        seen[base_id] += 1
        section["id"] = f"{base_id}-{seen[base_id]}"

    return merged


def _render_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_render_yaml(item, indent + 2))
            else:
                if isinstance(item, str):
                    escaped = item.replace('"', '\\"')
                    lines.append(f'{prefix}{key}: "{escaped}"')
                else:
                    lines.append(f"{prefix}{key}: {item}")
        return "\n".join(lines)

    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_render_yaml(item, indent + 2))
            else:
                if isinstance(item, str):
                    escaped = item.replace('"', '\\"')
                    lines.append(f'{prefix}- "{escaped}"')
                else:
                    lines.append(f"{prefix}- {item}")
        return "\n".join(lines)

    return f"{prefix}{value}"


def _new_section(section_id: str, title: str, kind: str) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "kind": kind,
        "lines": [],
        "tags": _extract_tags(title),
        "assets": [],
    }


def _append_asset_to_section(section: dict[str, Any], asset_url: str, caption: str = "Иллюстрация") -> None:
    section["lines"].append(f"![{caption}]({asset_url})")
    section["assets"].append(
        {
            "id": f"asset-{len(section['assets']) + 1:03d}",
            "url": asset_url,
            "type": "image",
            "caption": caption,
        }
    )


def build_curated_labs() -> list[dict[str, Any]]:
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    expected_slugs = {item.slug for item in LAB_SOURCE_CONFIG}
    for child in CURATED_DIR.iterdir():
        if child.is_dir() and child.name not in expected_slugs:
            shutil.rmtree(child)

    labs: list[dict[str, Any]] = []

    for config in LAB_SOURCE_CONFIG:
        source_path = SOURCES_DIR / config.source_file
        if not source_path.exists():
            continue

        lab_dir = CURATED_DIR / config.slug
        if lab_dir.exists():
            shutil.rmtree(lab_dir)
        sections_dir = lab_dir / "sections"
        assets_dir = lab_dir / "assets"
        sections_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(source_path) as archive:
            doc_root = ET.fromstring(archive.read("word/document.xml"))
            relationships = _extract_relationships(archive)
            style_name_by_id, _, heading_style_ids = _extract_styles(archive)
            numbering_kind_by_num_id = _extract_numbering_kinds(archive)
            blocks, equations_count = _extract_document_blocks(
                doc_root,
                style_name_by_id,
                heading_style_ids,
                numbering_kind_by_num_id,
            )

            copied_targets: dict[str, str] = {}
            image_counter = 0

            sections: list[dict[str, Any]] = []
            current = _new_section("overview", "Обзор", "content")

            def resolve_asset_url(rid: str) -> str | None:
                nonlocal image_counter
                target = relationships.get(rid)
                if not target:
                    return None
                if target in copied_targets:
                    return copied_targets[target]

                image_counter += 1
                ext = Path(target).suffix.lower() or ".png"
                asset_name = f"img-{image_counter:03d}{ext}"
                copied = _copy_asset(archive, target, assets_dir, asset_name)
                if not copied:
                    return None
                final_asset_name = asset_name
                if ext in {".wmf", ".emf"}:
                    source_file = assets_dir / asset_name
                    converted_name = f"img-{image_counter:03d}.png"
                    converted_file = assets_dir / converted_name
                    if _try_convert_vector_to_png(source_file, converted_file):
                        final_asset_name = converted_name
                asset_url = f"/assets/{config.slug}/assets/{final_asset_name}"
                copied_targets[target] = asset_url
                return asset_url

            for block in blocks:
                block_type = block.get("type")
                if block_type == "paragraph":
                    text = (block["text"] or "").strip()
                    style_id = block.get("style_id")
                    style_name = block.get("style_name")
                    heading_level = block.get("heading_level")

                    if text and _is_structural_heading(text, style_id, style_name, heading_style_ids):
                        heading = _normalize_heading(text)
                        lowered_heading = heading.lower()
                        heading_kind = _classify_section_kind(heading)
                        is_major_heading = bool(
                            (heading_level is not None and heading_level <= 2)
                            or any(keyword in lowered_heading for keyword in STRUCTURE_KEYWORDS)
                        )

                        keep_under_report = bool(
                            current["kind"] == "report"
                            and heading_kind in {"task", "content", "theory"}
                            and any(
                                marker in lowered_heading
                                for marker in ("постановка задачи", "дано", "даны", "критерии", "примерные вопросы")
                            )
                        )

                        if is_major_heading and not keep_under_report:
                            if current["lines"] or current["assets"]:
                                sections.append(current)
                            current = _new_section(_slugify(heading), heading, heading_kind)
                        else:
                            # Minor headings become subheaders inside current section.
                            current["lines"].append(f"### {heading}")
                        continue

                    if text and not _is_noise_line(text):
                        normalized_text, manual_list_kind = _strip_manual_list_marker(text)
                        if block.get("is_list_item"):
                            list_kind = str(block.get("list_kind") or "ordered")
                            list_level = int(block.get("list_level") or 0)
                            current["lines"].append(_format_list_item(normalized_text, list_kind, list_level))
                        elif manual_list_kind:
                            current["lines"].append(_format_list_item(normalized_text, manual_list_kind, 0))
                        elif _is_subheading_candidate(normalized_text):
                            current["lines"].append(f"### {normalized_text.rstrip(':')}")
                        else:
                            current["lines"].append(normalized_text)
                elif block_type == "table":
                    table_lines = block.get("lines") or []
                    if table_lines:
                        replaced_lines: list[str] = []
                        for line in table_lines:
                            updated_line = line
                            for rid in block.get("image_rids", []):
                                token = f"[[IMG:{rid}]]"
                                if token not in updated_line:
                                    continue
                                asset_url = resolve_asset_url(rid)
                                if not asset_url:
                                    updated_line = updated_line.replace(token, "Иллюстрация")
                                    continue
                                updated_line = updated_line.replace(token, f"![Иллюстрация]({asset_url})")
                            replaced_lines.append(updated_line)
                        table_block = "\n".join(replaced_lines)
                        current["lines"].append(table_block)
                    continue
                for rid in block["image_rids"]:
                    asset_url = resolve_asset_url(rid)
                    if not asset_url:
                        continue
                    _append_asset_to_section(current, asset_url)

            if current["lines"] or current["assets"]:
                sections.append(current)

            sections = _merge_sections(sections)

            media_files = [name for name in archive.namelist() if name.startswith("word/media/")]
            leftovers = [m for m in media_files if m.replace("word/", "") not in copied_targets]
            if leftovers:
                appendix = _new_section("appendix-images", "Дополнительные иллюстрации", "content")
                appendix["tags"] = ["иллюстрации"]

                for item in leftovers:
                    target = item.replace("word/", "")
                    image_counter += 1
                    ext = Path(target).suffix.lower() or ".png"
                    asset_name = f"img-{image_counter:03d}{ext}"
                    copied = _copy_asset(archive, target, assets_dir, asset_name)
                    if not copied:
                        continue
                    final_asset_name = asset_name
                    if ext in {".wmf", ".emf"}:
                        source_file = assets_dir / asset_name
                        converted_name = f"img-{image_counter:03d}.png"
                        converted_file = assets_dir / converted_name
                        if _try_convert_vector_to_png(source_file, converted_file):
                            final_asset_name = converted_name
                    asset_url = f"/assets/{config.slug}/assets/{final_asset_name}"
                    _append_asset_to_section(appendix, asset_url)

                if appendix["lines"]:
                    sections.append(appendix)

        sections_payload: list[dict[str, Any]] = []
        all_assets: list[dict[str, Any]] = []
        section_meta: list[dict[str, Any]] = []
        search_chunks: list[str] = [config.title, " ".join(config.tags)]

        for index, section in enumerate(sections, start=1):
            section_id = section["id"] or f"section-{index:02d}"
            filename = f"{index:02d}-{section_id}.md"
            content_md = _compose_section_markdown(section["lines"])
            if not content_md:
                continue
            (sections_dir / filename).write_text(content_md + "\n", encoding="utf-8")
            section_tags = sorted(set(section["tags"] + _extract_tags(content_md)))

            payload = {
                "id": section_id,
                "title": section["title"],
                "kind": section["kind"],
                "order": index,
                "content_md": content_md,
                "tags": section_tags,
                "assets": section["assets"],
            }
            sections_payload.append(payload)
            section_meta.append(
                {
                    "id": section_id,
                    "file": f"sections/{filename}",
                    "kind": section["kind"],
                    "title": section["title"],
                    "order": index,
                    "tags": section_tags,
                }
            )
            all_assets.extend(section["assets"])
            search_chunks.extend([section["title"], content_md])

        metadata = {
            "lab_id": config.lab_id,
            "slug": config.slug,
            "title": config.title,
            "tags": sorted(set(config.tags + _extract_tags(" ".join(search_chunks)))),
            "source": {"file": config.source_file},
            "stats": {"equations_detected": equations_count, "assets_detected": len(all_assets)},
            "sections": section_meta,
            "assets": all_assets,
        }
        (lab_dir / "meta.yaml").write_text(_render_yaml(metadata) + "\n", encoding="utf-8")

        labs.append(
            {
                "lab_id": config.lab_id,
                "slug": config.slug,
                "title": config.title,
                "source_file": config.source_file,
                "tags": metadata["tags"],
                "sections": sections_payload,
                "assets": all_assets,
                "stats": metadata["stats"],
                "search_text": " ".join(search_chunks),
                "updated_at": datetime.now(timezone.utc),
            }
        )

    return labs
