from __future__ import annotations

import posixpath
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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
    replacements = {
        "\u00a0": " ",
        "\xad": "",
        "": "ε",
        "": "|",
        "": "|",
        "": "θ",
        "": "ψ",
        "": "φ",
        "": "→",
        "": "→",
        "": "∈",
        "": "∞",
    }
    cleaned = text
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
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
    if stripped in {"{", "}", ";"}:
        return False
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
    if stripped.endswith("."):
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


def _is_image_only_line(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and bool(re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", stripped))


def _is_inline_continuation_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _is_markdown_list_line(stripped) or stripped.startswith(("#", "|", "```", "![", ">")):
        return False
    if _should_treat_as_code(stripped):
        return False
    if stripped[0] in ",.;:)]}" or stripped[0].islower():
        return True
    lowered = stripped.lower()
    return lowered.startswith(("где", "при", "всего", "называется", "или", "и "))


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
    seen: set[str] = set()
    for blip in node.findall(".//a:blip", NS):
        rid = blip.attrib.get(f"{{{NS['r']}}}embed")
        if rid and rid not in seen:
            seen.add(rid)
            image_rids.append(rid)
    for v_img in node.findall(".//v:imagedata", NS):
        rid = v_img.attrib.get(f"{{{NS['r']}}}id")
        if rid and rid not in seen:
            seen.add(rid)
            image_rids.append(rid)
    return image_rids


def _wrap_math_operand(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if re.fullmatch(r"[A-Za-zА-Яа-я0-9_]+", stripped):
        return stripped
    return f"({stripped})"


def _linearize_omml(node: ET.Element) -> str:
    tag = _local_name(node.tag)

    if tag in {"oMath", "oMathPara", "e", "num", "den", "sub", "sup", "deg"}:
        return "".join(_linearize_omml(child) for child in list(node))

    if tag == "r":
        return "".join((child.text or "") for child in node.findall("./m:t", NS))

    if tag == "t":
        return node.text or ""

    if tag == "fName":
        return "".join(_linearize_omml(child) for child in list(node))

    if tag == "func":
        func_name = _linearize_omml(node.find("./m:fName", NS) or ET.Element("m:fName"))
        expr = _linearize_omml(node.find("./m:e", NS) or ET.Element("m:e"))
        if func_name and expr:
            return f"{func_name}{_wrap_math_operand(expr)}"
        return func_name or expr

    if tag == "sSup":
        base = _linearize_omml(node.find("./m:e", NS) or ET.Element("m:e"))
        sup = _linearize_omml(node.find("./m:sup", NS) or ET.Element("m:sup"))
        if base and sup:
            return f"{_wrap_math_operand(base)}^{_wrap_math_operand(sup)}"
        return base or sup

    if tag == "sSub":
        base = _linearize_omml(node.find("./m:e", NS) or ET.Element("m:e"))
        sub = _linearize_omml(node.find("./m:sub", NS) or ET.Element("m:sub"))
        if base and sub:
            return f"{_wrap_math_operand(base)}_{_wrap_math_operand(sub)}"
        return base or sub

    if tag == "f":
        numerator = _linearize_omml(node.find("./m:num", NS) or ET.Element("m:num"))
        denominator = _linearize_omml(node.find("./m:den", NS) or ET.Element("m:den"))
        if numerator and denominator:
            return f"{_wrap_math_operand(numerator)}/{_wrap_math_operand(denominator)}"
        return numerator or denominator

    return "".join(_linearize_omml(child) for child in list(node))


def _extract_math_fragments(node: ET.Element) -> list[str]:
    fragments: list[str] = []
    seen: set[str] = set()
    containers = node.findall(".//m:oMathPara", NS) or node.findall(".//m:oMath", NS)

    for item in containers:
        raw = _linearize_omml(item)
        normalized = _normalize_line(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            fragments.append(normalized)
    return fragments


def _merge_inline_fragments(fragments: list[str]) -> list[str]:
    merged: list[str] = []
    text_buffer: list[str] = []

    def flush_text() -> None:
        if not text_buffer:
            return
        normalized = _normalize_line("".join(text_buffer))
        if normalized:
            merged.append(normalized)
        text_buffer.clear()

    for fragment in fragments:
        if fragment.startswith("[[IMG:") or (fragment.startswith("$") and fragment.endswith("$")):
            flush_text()
            merged.append(fragment)
            continue
        text_buffer.append(fragment)

    flush_text()
    return merged


def _extract_paragraph_fragments(paragraph: ET.Element) -> tuple[list[str], list[str]]:
    fragments: list[str] = []
    image_rids: list[str] = []

    for child in list(paragraph):
        tag = _local_name(child.tag)
        if tag == "pPr":
            continue

        direct_text = "".join((node.text or "") for node in child.findall(".//w:t", NS))
        if direct_text:
            fragments.append(direct_text)

        for formula in _extract_math_fragments(child):
            fragments.append(f"${formula}$")

        for rid in _extract_image_rids(child):
            image_rids.append(rid)
            fragments.append(f"[[IMG:{rid}]]")

    return _merge_inline_fragments(fragments), image_rids


def _render_paragraph_fragments(
    fragments: list[str],
    resolve_asset_url: Callable[[str], str | None],
) -> str:
    segments: list[str] = []
    text_buffer: list[str] = []

    def flush_text() -> None:
        if not text_buffer:
            return
        normalized = _normalize_inline_spacing(" ".join(part for part in text_buffer if part))
        if normalized:
            segments.append(normalized)
        text_buffer.clear()

    for fragment in fragments:
        if fragment.startswith("[[IMG:") and fragment.endswith("]]"):
            flush_text()
            rid = fragment[6:-2]
            asset_url = resolve_asset_url(rid)
            if asset_url:
                segments.append(f"![Иллюстрация]({asset_url})")
            else:
                segments.append("Иллюстрация")
            continue
        text_buffer.append(fragment)

    flush_text()
    return "<br>".join(segment for segment in segments if segment)


def _parse_paragraph_element(
    paragraph: ET.Element,
    style_name_by_id: dict[str, str],
    heading_style_ids: set[str],
    numbering_kind_by_num_id: dict[str, str],
) -> dict[str, Any] | None:
    fragments, image_rids = _extract_paragraph_fragments(paragraph)
    text = _normalize_line(" ".join(fragment for fragment in fragments if not fragment.startswith("[[IMG:")))

    style_node = paragraph.find("./w:pPr/w:pStyle", NS)
    style_id = style_node.attrib.get(f"{{{NS['w']}}}val") if style_node is not None else None
    style_name = style_name_by_id.get(style_id or "", "")
    heading_level = _extract_heading_level(style_id, style_name, text)
    num_id_node = paragraph.find("./w:pPr/w:numPr/w:numId", NS)
    ilvl_node = paragraph.find("./w:pPr/w:numPr/w:ilvl", NS)
    num_id = num_id_node.attrib.get(f"{{{NS['w']}}}val") if num_id_node is not None else None
    list_level = int(ilvl_node.attrib.get(f"{{{NS['w']}}}val", "0")) if ilvl_node is not None else 0
    list_kind = numbering_kind_by_num_id.get(num_id or "", "ordered") if num_id else None
    if not text and not image_rids:
        return None

    return {
        "type": "paragraph",
        "text": text,
        "fragments": fragments,
        "style_id": style_id,
        "style_name": style_name,
        "is_heading_style": bool(style_id and style_id in heading_style_ids),
        "heading_level": heading_level,
        "is_list_item": bool(num_id),
        "num_id": num_id,
        "list_level": list_level,
        "list_kind": list_kind,
        "image_rids": image_rids,
    }


def _collect_cell_content(cell: ET.Element) -> tuple[str, list[str]]:
    chunks: list[str] = []
    image_rids: list[str] = []
    for paragraph in cell.findall(".//w:p", NS):
        fragments, paragraph_image_rids = _extract_paragraph_fragments(paragraph)
        chunks.extend(fragments)
        for rid in paragraph_image_rids:
            image_rids.append(rid)
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
                [
                    magick,
                    "-density",
                    "240",
                    str(source_path),
                    "-background",
                    "white",
                    "-alpha",
                    "remove",
                    "-alpha",
                    "off",
                    "-trim",
                    "+repage",
                    str(destination_path),
                ],
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
            _trim_raster_image(destination_path)
            return True
        return destination_path.exists()
    except OSError:
        return False


def _trim_raster_image(image_path: Path) -> None:
    magick = shutil.which("magick")
    if not magick or not image_path.exists():
        return
    temp_path = image_path.with_name(f"{image_path.stem}-trim{image_path.suffix}")
    try:
        completed = subprocess.run(
            [magick, str(image_path), "-trim", "+repage", str(temp_path)],
            check=False,
            capture_output=True,
        )
        if completed.returncode == 0 and temp_path.exists():
            temp_path.replace(image_path)
    except OSError:
        pass
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _strip_manual_list_marker(text: str) -> tuple[str, str | None, int | None]:
    ordered_match = re.match(r"^\s*(\d+)[\).]\s+(.+)$", text)
    if ordered_match:
        return ordered_match.group(2).strip(), "ordered", int(ordered_match.group(1))
    bullet_match = re.match(r"^\s*[-•–]\s+(.+)$", text)
    if bullet_match:
        return bullet_match.group(1).strip(), "bullet", None
    return text, None, None


def _format_list_item(text: str, list_kind: str, level: int = 0, index: int | None = None) -> str:
    indent = "  " * max(level, 0)
    marker = f"{index}." if list_kind == "ordered" and index is not None else ("1." if list_kind == "ordered" else "-")
    return f"{indent}{marker} {text.strip()}"


def _is_markdown_list_line(text: str) -> bool:
    return bool(re.match(r"^\s*(?:-|\d+\.)\s+", text))


def _normalize_inline_spacing(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([(\[{])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([)\]}])", r"\1", cleaned)
    return cleaned


def _is_code_placeholder_line(text: str) -> bool:
    stripped = text.strip().lower()
    if not stripped:
        return False
    if stripped.startswith(("[спецификаторы]", "[ спецификаторы ]")):
        return True
    if stripped.startswith(("тип имя_метода", "тип имя_функции", "имя_функции(", "имя_метода(")):
        return True
    if stripped in {"оператор", "оператор;", "операторы;", "тело_функции", "тело функции"}:
        return True
    if stripped.startswith(("тело метода", "тело_функции")):
        return True
    return False


def _is_probable_code_line(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    if not stripped:
        return False
    if "![" in stripped:
        return False
    if stripped in {"do", "{", "}", "оператор", "оператор;", "операторы;"}:
        return True
    if _is_code_placeholder_line(stripped):
        return True
    if stripped.startswith(";"):
        return True
    if re.fullmatch(r"\.{3,}", stripped):
        return True
    if re.match(r"^(switch\s*\(|case\b|default\b|\[default:|do\b|while\s*\(|for\s*\()", lowered):
        return True
    if re.match(r"^(//|/\*|#include|using\s+[A-Za-z_]|import\s+[A-Za-z_]|print\()", stripped):
        return True
    if "{" in stripped or "}" in stripped:
        return True
    has_cyrillic = bool(re.search(r"[А-Яа-я]", stripped))
    has_api_call = bool(re.search(r"\b(Console|Math)\.[A-Za-z_][A-Za-z0-9_]*\s*\(", stripped))
    has_control = bool(re.match(r"^(if|else|for|foreach|while|switch|case)\b", lowered))
    has_decl = bool(
        re.match(r"^(public|private|protected|internal|static|sealed|abstract|partial|\s)*(class|namespace|void|int|string|double|float|bool|var|char|long|short|decimal|object)\b", lowered)
        or re.match(r"^[A-Za-z_][A-Za-z0-9_<>,\[\]]*\s+[A-Za-z_][A-Za-z0-9_]*\s*(?:[;=({])", stripped)
    )
    has_member_chain = bool(re.search(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+\s*\(", stripped))
    has_assignment = "=" in stripped or any(token in stripped for token in ("++", "--"))
    has_statement_end = ";" in stripped

    if has_cyrillic and len(stripped) > 120 and stripped.endswith(".") and not (has_api_call or has_control or has_decl):
        return False
    if has_cyrillic and not (has_api_call or has_control or has_decl or has_member_chain or has_statement_end):
        return False

    score = 0
    if has_api_call or has_member_chain:
        score += 2
    if has_control or has_decl:
        score += 2
    if has_assignment:
        score += 1
    if has_statement_end:
        score += 1
    if any(token in stripped for token in ("(", ")", "[", "]")) and re.search(r"[A-Za-z_]", stripped):
        score += 1

    return score >= 2


def _should_treat_as_code(line: str) -> bool:
    stripped = line.strip()
    return _is_probable_code_line(stripped) and not _is_markdown_list_line(stripped) and not stripped.startswith(("#", "|", "![", ">"))


def _code_block_has_unclosed_string(lines: list[str]) -> bool:
    quote_count = 0
    for line in lines:
        quote_count += line.count('"')
    return quote_count % 2 == 1


def _has_unclosed_verbatim_string(lines: list[str]) -> bool:
    inside = False

    for line in lines:
        idx = 0
        while idx < len(line):
            if not inside:
                start = line.find('@"', idx)
                if start < 0:
                    break
                inside = True
                idx = start + 2
                continue

            end = line.find('"', idx)
            if end < 0:
                break
            if end + 1 < len(line) and line[end + 1] == '"':
                idx = end + 2
                continue
            inside = False
            idx = end + 1

    return inside


def _should_keep_inside_code_block(line: str) -> bool:
    stripped = line.strip()
    lowered = stripped.lower()
    if _should_treat_as_code(stripped):
        return True
    if _is_code_placeholder_line(stripped):
        return True
    if stripped in {"{", "}", "do", "оператор", "оператор;", "операторы;", "[default: операторы;]"}:
        return True
    if re.match(r"^(case\b|default\b|switch\s*\(|if\s*\(|else\b|for\s*\(|while\s*\()", lowered):
        return True
    if re.fullmatch(r"[. ]{5,}", stripped):
        return True
    if re.match(r"^\[default:\s*операторы;?\]$", lowered):
        return True
    if stripped.endswith(";") and len(stripped) <= 80 and (" " not in stripped or re.search(r"[A-Za-zА-Яа-я_]", stripped)):
        return True
    return False


def _indent_code_block(lines: list[str]) -> list[str]:
    indented: list[str] = []
    level = 0

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            indented.append("")
            continue

        if stripped.startswith("}"):
            level = max(0, level - 1)

        indent = "    " * level
        indented.append(f"{indent}{stripped}")

        open_count = stripped.count("{")
        close_count = stripped.count("}")
        if not stripped.startswith("}") and open_count > close_count:
            level += open_count - close_count
        elif stripped.startswith("}") and open_count > close_count:
            level += open_count - close_count
        elif close_count > open_count and not stripped.startswith("}"):
            level = max(0, level - (close_count - open_count))

    return indented


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

        if _should_treat_as_code(line):
            block: list[str] = []
            while idx < total:
                candidate = prepared[idx]
                if not candidate.strip():
                    next_idx = idx + 1
                    while next_idx < total and not prepared[next_idx].strip():
                        next_idx += 1
                    if next_idx < total and block and (
                        _should_treat_as_code(prepared[next_idx]) or _has_unclosed_verbatim_string(block)
                    ):
                        block.append("")
                        idx = next_idx
                        continue
                    break
                if block and _has_unclosed_verbatim_string(block):
                    block.append(candidate)
                    idx += 1
                    continue
                if not _should_keep_inside_code_block(candidate):
                    if block and _code_block_has_unclosed_string(block) and not candidate.startswith(("###", "|", "![", ">")):
                        block.append(candidate)
                        idx += 1
                        continue
                    break
                block.append(candidate)
                idx += 1
            if block:
                if output and output[-1] != "":
                    output.append("")
                output.append("```csharp")
                output.extend(_indent_code_block(block))
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


def _extract_assets_from_markdown(content_md: str) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", content_md), start=1):
        caption = match.group(1).strip() or "Иллюстрация"
        url = match.group(2).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        assets.append(
            {
                "id": f"asset-{index:03d}",
                "url": url,
                "type": "image",
                "caption": caption,
            }
        )
    return assets


def _normalize_curated_asset_links(lab_slug: str, content_md: str, assets_dir: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        caption = match.group(1)
        asset_url = match.group(2).strip()
        asset_path = assets_dir / Path(asset_url).name
        ext = asset_path.suffix.lower()

        if ext in {".wmf", ".emf"} and asset_path.exists():
            png_path = asset_path.with_suffix(".png")
            if not png_path.exists():
                _try_convert_vector_to_png(asset_path, png_path)
            if png_path.exists():
                return f"![{caption}](/assets/{lab_slug}/assets/{png_path.name})"

        if ext in {".png", ".jpg", ".jpeg"} and asset_path.exists():
            _trim_raster_image(asset_path)

        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\((/assets/[^)]+)\)", replace, content_md)


def _parse_generated_meta(meta_path: Path) -> dict[str, Any]:
    text = meta_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    data: dict[str, Any] = {
        "lab_id": None,
        "slug": "",
        "title": "",
        "tags": [],
        "source_file": "",
        "stats": {"equations_detected": 0, "assets_detected": 0},
        "sections": [],
    }

    current_list: str | None = None
    current_section: dict[str, Any] | None = None
    current_nested: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip(" "))

        if indent == 0:
            current_nested = None
            if stripped == "tags:":
                current_list = "tags"
                current_section = None
                continue
            if stripped == "sections:":
                current_list = "sections"
                current_section = None
                continue
            current_list = None

            if stripped.startswith("lab_id:"):
                data["lab_id"] = int(stripped.split(":", 1)[1].strip())
            elif stripped.startswith("slug:"):
                data["slug"] = stripped.split(":", 1)[1].strip().strip('"')
            elif stripped.startswith("title:"):
                data["title"] = stripped.split(":", 1)[1].strip().strip('"')
            elif stripped == "source:":
                current_nested = "source"
            elif stripped == "stats:":
                current_nested = "stats"
            continue

        if current_list == "tags" and stripped.startswith("- "):
            data["tags"].append(stripped[2:].strip().strip('"'))
            continue

        if current_nested == "source" and stripped.startswith("file:"):
            data["source_file"] = stripped.split(":", 1)[1].strip().strip('"')
            continue

        if current_nested == "stats" and ":" in stripped:
            key, value = stripped.split(":", 1)
            data["stats"][key.strip()] = int(value.strip())
            continue

        if current_list == "sections":
            if stripped == "-":
                current_section = {"tags": []}
                data["sections"].append(current_section)
                current_nested = None
                continue
            if current_section is None:
                continue
            if stripped == "tags:":
                current_nested = "section_tags"
                continue
            if current_nested == "section_tags" and stripped.startswith("- "):
                current_section["tags"].append(stripped[2:].strip().strip('"'))
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                cleaned = value.strip().strip('"')
                if key.strip() == "order":
                    current_section["order"] = int(cleaned)
                else:
                    current_section[key.strip()] = cleaned
                current_nested = None

    return data


def _load_curated_lab(config: LabSourceConfig) -> dict[str, Any] | None:
    lab_dir = CURATED_DIR / config.slug
    meta_path = lab_dir / "meta.yaml"
    sections_dir = lab_dir / "sections"
    if not meta_path.exists() or not sections_dir.exists():
        return None

    parsed_meta = _parse_generated_meta(meta_path)
    sections_payload: list[dict[str, Any]] = []
    all_assets: list[dict[str, Any]] = []
    search_chunks: list[str] = [parsed_meta.get("title") or config.title, " ".join(parsed_meta.get("tags") or config.tags)]

    for section_meta in sorted(parsed_meta.get("sections", []), key=lambda item: int(item.get("order", 999))):
        relative_file = section_meta.get("file", "")
        section_path = lab_dir / relative_file
        if not relative_file or not section_path.exists():
            continue
        content_md = section_path.read_text(encoding="utf-8").strip()
        content_md = _normalize_curated_asset_links(config.slug, content_md, lab_dir / "assets")
        assets = _extract_assets_from_markdown(content_md)
        payload = {
            "id": section_meta.get("id", ""),
            "title": section_meta.get("title", ""),
            "kind": section_meta.get("kind", "content"),
            "order": int(section_meta.get("order", len(sections_payload) + 1)),
            "content_md": content_md,
            "tags": list(section_meta.get("tags", [])),
            "assets": assets,
        }
        sections_payload.append(payload)
        all_assets.extend(assets)
        search_chunks.extend([payload["title"], content_md])

    return {
        "lab_id": parsed_meta.get("lab_id") or config.lab_id,
        "slug": parsed_meta.get("slug") or config.slug,
        "title": parsed_meta.get("title") or config.title,
        "source_file": parsed_meta.get("source_file") or config.source_file,
        "tags": parsed_meta.get("tags") or config.tags,
        "sections": sections_payload,
        "assets": all_assets,
        "stats": parsed_meta.get("stats") or {"equations_detected": 0, "assets_detected": len(all_assets)},
        "search_text": " ".join(search_chunks),
        "updated_at": datetime.now(timezone.utc),
    }


def _curated_lab_exists(config: LabSourceConfig) -> bool:
    lab_dir = CURATED_DIR / config.slug
    meta_path = lab_dir / "meta.yaml"
    sections_dir = lab_dir / "sections"
    return meta_path.exists() and sections_dir.exists() and any(sections_dir.glob("*.md"))


def _normalize_section_lines(lines: list[str], section_kind: str) -> list[str]:
    normalized: list[str] = []
    report_item_markers = (
        "постановка задачи",
        "анализ классов",
        "алгоритм",
        "код программы",
        "тесты",
        "анализ достаточности",
        "объяснение результатов",
    )

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if re.match(r"^Таблица\s+\d+[.]", stripped, flags=re.IGNORECASE):
            normalized.append(f"**{stripped}**")
            continue

        if section_kind == "report":
            lowered = stripped.lower().rstrip(":")
            if lowered == "### для каждой задачи привести":
                normalized.append("**Для каждой задачи привести:**")
                continue
            if stripped.startswith("### "):
                heading_text = stripped[4:].strip()
                lowered_heading = heading_text.lower()
                if any(marker in lowered_heading for marker in report_item_markers):
                    normalized.append(_format_list_item(heading_text, "ordered"))
                    continue

        normalized.append(line)

    merged_images: list[str] = []
    idx = 0
    while idx < len(normalized):
        line = normalized[idx]
        stripped = line.strip()

        if _is_image_only_line(stripped):
            last_content_idx = len(merged_images) - 1
            while last_content_idx >= 0 and not merged_images[last_content_idx].strip():
                last_content_idx -= 1

            next_idx = idx + 1
            while next_idx < len(normalized) and not normalized[next_idx].strip():
                next_idx += 1
            next_line = normalized[next_idx].strip() if next_idx < len(normalized) else ""

            if last_content_idx >= 0 and (
                _is_markdown_list_line(merged_images[last_content_idx])
                or _is_inline_continuation_text(merged_images[last_content_idx])
                or not merged_images[last_content_idx].startswith(("###", "|", "```"))
            ):
                while merged_images and not merged_images[-1].strip():
                    merged_images.pop()
                merged_images[last_content_idx] = f"{merged_images[last_content_idx]}<br>{stripped}"
                if next_line and _is_inline_continuation_text(next_line):
                    merged_images[last_content_idx] = f"{merged_images[last_content_idx]}<br>{next_line}"
                    idx = next_idx
                idx += 1
                continue

            if next_line and _is_inline_continuation_text(next_line):
                merged_images.append(f"{stripped}<br>{next_line}")
                idx = next_idx + 1
                continue

        merged_images.append(line)
        idx += 1

    return merged_images


def _postprocess_lab_markdown(slug: str, section_id: str, content_md: str) -> str:
    content_md = content_md.replace("csharp\nКопировать\n", "```csharp\n")

    if slug == "lr01-introduction-and-tooling" and section_id == "теоретические-сведения":
        content_md = content_md.replace(
            "Console.Write(”y=”+y+”\\n”};\nПри вводе данных с клавиатуры используются методы Console.Read() и Console.ReadLine().\n```",
            "Console.Write(”y=”+y+”\\n”};\n```\n\nПри вводе данных с клавиатуры используются методы `Console.Read()` и `Console.ReadLine()`.",
        )
        content_md = content_md.replace(
            "Таблица 4 Основные поля и методы класса Math",
            "**Таблица 4. Основные поля и методы класса Math**",
        )

    if slug == "lr01-introduction-and-tooling" and section_id == "варианты":
        content_md = content_md.replace("$sin(()x)+x^3++1/(x^2-1)$", "$sin(x) + x^3 + 1/(x^2 - 1)$")
        content_md = re.sub(
            r"(\| 21 \| .*? \| .*? \| а=1000, b=0\.0001<br>!\[Иллюстрация\]\(/assets/lr01-introduction-and-tooling/assets/img-008\.wmf\))<br>!\[Иллюстрация\]\(/assets/lr01-introduction-and-tooling/assets/img-009\.wmf\) \|",
            r"\1 |",
            content_md,
        )

    if slug == "lr01-introduction-and-tooling" and section_id == "вывод-результатов-для-задания-а-организовать-в-виде":
        content_md = content_md.replace(
            "Console.WriteLine(\"m++ +n={0}, m={1},n={2}\", k, m, n);\n```",
            "Console.WriteLine(\"m++ +n={0}, m={1},n={2}\", k, m, n);\n}\n```",
        )

    if slug == "lr02-data-structures" and section_id == "оператор-выражение":
        content_md = content_md.replace(
            "```csharp\ni++; //инкремент\nx+=y+x;//аддитивное присваивание\nt=a>b;// присваивание результата отношения\n```\n\n; //пустой оператор",
            "```csharp\ni++; //инкремент\nx+=y+x;//аддитивное присваивание\nt=a>b;// присваивание результата отношения\n; //пустой оператор\n```",
        )

    if slug == "lr02-data-structures" and section_id == "операторы-выбора":
        content_md = content_md.replace(
            "```csharp\nОператоры выбора – это условный оператор и переключатель.\n1. Условный оператор имеет полную и сокращенную форму.\nif (выражение-условие) оператор;//сокращенная форма\n```",
            "Операторы выбора – это условный оператор и переключатель.\n\n1. Условный оператор имеет полную и сокращенную форму.\n\n```csharp\nif (выражение-условие) оператор; // сокращенная форма\n```",
        )
        content_md = re.sub(
            r"```csharp\nswitch \(выражение\)\n\{\n\s*case константа1: оператор1;\n\s*case константа2: оператор2;\n```\n\n\.{5,}\n\n```csharp\n\[default: операторы;\]\n\}\n```",
            "```csharp\nswitch (выражение)\n{\n    case константа1: оператор1;\n    case константа2: оператор2;\n    ...........\n    [default: операторы;]\n}\n```",
            content_md,
        )

    if slug == "lr02-data-structures" and section_id == "операторы-циклов":
        content_md = content_md.replace(
            "do\n\nоператор\n\n```csharp\nwhile (выражение-условие);\n```",
            "```csharp\ndo\nоператор\nwhile (выражение-условие);\n```",
        )
        content_md = content_md.replace(
            "Тело цикла выполняется до тех пор, пока выражение-условие истинно.\n\ndo\n\n```csharp\n{\nConsole.Write(\"? \");",
            "Тело цикла выполняется до тех пор, пока выражение-условие истинно.\n\n```csharp\ndo\n{\nConsole.Write(\"? \");",
        )
        content_md = content_md.replace(
            "```csharp\nfor (выражение_1;выражение-условие;выражение_3)\nоператор;\nВыражение_1 и выражение_3 могут состоять из нескольких выражений, разделенных запятыми. Выражение_1 – задает начальные условия для цикла (инициализация). Выражение-условие определяет условие выполнения цикла, если оно не равно 0, цикл выполняется, а затем вычисляется значение выражения_3. Выражение_3 – задает изменение параметра цикла или других переменных (коррекция). Цикл продолжается до тех пор, пока выражение-условие не станет равно 0. Любое выражение может отсутствовать, но разделяющие их « ; » должны быть обязательно.\nfor (int i = 0; i < n; i++)",
            "```csharp\nfor (выражение_1;выражение-условие;выражение_3)\nоператор;\n```\n\nВыражение_1 и выражение_3 могут состоять из нескольких выражений, разделенных запятыми. Выражение_1 – задает начальные условия для цикла (инициализация). Выражение-условие определяет условие выполнения цикла, если оно не равно 0, цикл выполняется, а затем вычисляется значение выражения_3. Выражение_3 – задает изменение параметра цикла или других переменных (коррекция). Цикл продолжается до тех пор, пока выражение-условие не станет равно 0. Любое выражение может отсутствовать, но разделяющие их « ; » должны быть обязательно.\n\n```csharp\nfor (int i = 0; i < n; i++)",
        )

    if slug == "lr03-functions-and-modules" and section_id == "теоретические-сведения":
        content_md = content_md.replace("Sn+1-Sn< или an<.", "|Sn+1-Sn|<ε или an<ε.")
        content_md = content_md.replace("Rn<.", "|Rn|<ε.")
        content_md = content_md.replace("R→0 при n→.", "R→0 при n→∞.")

    if slug == "lr03-functions-and-modules" and section_id == "выполнение-задания":
        content_md = content_md.replace(
            "```csharp\nа)<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-007.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-008.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-009.wmf)<br>;\nб)<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-010.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-011.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-012.wmf)<br>;\n```",
            "а)<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-007.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-008.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-009.wmf)<br>;\n\nб)<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-010.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-011.wmf)<br>;<br>![Иллюстрация](/assets/lr03-functions-and-modules/assets/img-012.wmf)<br>;",
        )

    if slug == "lr05-files-and-serialization" and section_id == "теоретические-сведения":
        content_md = content_md.replace(
            "```csharp\nConsole.WriteLine(@\"1. Создать массив.\n```\n\n2. Печать массива.\n3. Удалить элементы из массива.\n4. Добавить элементы в массив.\n5. Поиск элемента в массиве.\n6. Сортировака массива.\n7. Выход.\");",
            "```csharp\nConsole.WriteLine(@\"1. Создать массив.\n2. Печать массива.\n3. Удалить элементы из массива.\n4. Добавить элементы в массив.\n5. Поиск элемента в массиве.\n6. Сортировка массива.\n7. Выход.\");\n```",
        )
        content_md = content_md.replace(
            "7. Выход.\");<br>![Иллюстрация](/assets/lr05-files-and-serialization/assets/img-001.png)\n```",
            "7. Выход.\");\n```\n\n![Иллюстрация](/assets/lr05-files-and-serialization/assets/img-001.png)",
        )

    if slug == "lr05-files-and-serialization" and section_id == "понятие-функции":
        content_md = content_md.replace(
            "тип имя_функции([список_формальных параметров])\n\n```csharp\n{\n```\n\nтело_функции\n\n```csharp\n}\n```",
            "```csharp\nтип имя_функции([список_формальных параметров])\n{\n    тело_функции\n}\n```",
        )
        content_md = content_md.replace(
            "```csharp\nтип имя_функции([список_формальных параметров])\n{\n    тело_функции\n}\nТело_функции – это блок или составной оператор. Внутри функции нельзя определить другую функцию.\n```",
            "```csharp\nтип имя_функции([список_формальных параметров])\n{\n    тело_функции\n}\n```\n\nТело_функции – это блок или составной оператор. Внутри функции нельзя определить другую функцию.",
        )
        content_md = content_md.replace(
            "```csharp\nПервая форма используется для возврата результата, поэтому выражение должно иметь тот же тип, что и тип функции в определении. Вторая форма используется, если функция не возвращает значения, т. е. имеет тип void. Программист может не использовать этот оператор в теле функции явно, компилятор добавит его автоматически в конец функции перед}. Это может быть любой допустимый тип, включая типы классов, создаваемые программистом.\n```",
            "Первая форма используется для возврата результата, поэтому выражение должно иметь тот же тип, что и тип функции в определении. Вторая форма используется, если функция не возвращает значения, т. е. имеет тип `void`. Программист может не использовать этот оператор в теле функции явно, компилятор добавит его автоматически в конец функции перед `}`. Это может быть любой допустимый тип, включая типы классов, создаваемые программистом.",
        )

    return content_md


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

        if _curated_lab_exists(config):
            existing_lab = _load_curated_lab(config)
            if existing_lab:
                labs.append(existing_lab)
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
            ordered_list_counters: dict[tuple[str, int], int] = {}

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
                elif ext in {".png", ".jpg", ".jpeg"}:
                    _trim_raster_image(assets_dir / asset_name)
                asset_url = f"/assets/{config.slug}/assets/{final_asset_name}"
                copied_targets[target] = asset_url
                return asset_url

            for block in blocks:
                block_type = block.get("type")
                if block_type == "paragraph":
                    text = (block["text"] or "").strip()
                    rendered_text = _render_paragraph_fragments(block.get("fragments") or [], resolve_asset_url).strip()
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

                    if rendered_text and (text and not _is_noise_line(text) or "![" in rendered_text or rendered_text == "Иллюстрация"):
                        normalized_text, manual_list_kind, manual_index = _strip_manual_list_marker(text or rendered_text)
                        if manual_list_kind and rendered_text.startswith(f"{manual_index}. "):
                            rendered_payload = rendered_text[len(f"{manual_index}. ") :].strip()
                        elif manual_list_kind and rendered_text.startswith("1. "):
                            rendered_payload = rendered_text[3:].strip()
                        else:
                            rendered_payload = rendered_text
                        if block.get("is_list_item"):
                            list_kind = str(block.get("list_kind") or "ordered")
                            list_level = int(block.get("list_level") or 0)
                            if list_kind == "ordered":
                                num_id = str(block.get("num_id") or "default")
                                counter_key = (num_id, list_level)
                                ordered_list_counters[counter_key] = ordered_list_counters.get(counter_key, 0) + 1
                                current["lines"].append(
                                    _format_list_item(rendered_payload or normalized_text or "![Иллюстрация]", list_kind, list_level, ordered_list_counters[counter_key])
                                )
                            else:
                                current["lines"].append(_format_list_item(rendered_payload or normalized_text or "![Иллюстрация]", list_kind, list_level))
                        elif manual_list_kind:
                            current["lines"].append(_format_list_item(rendered_payload or normalized_text or "![Иллюстрация]", manual_list_kind, 0, manual_index))
                        elif _is_subheading_candidate(normalized_text):
                            current["lines"].append(f"### {normalized_text.rstrip(':')}")
                        else:
                            current["lines"].append(rendered_payload or normalized_text)
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
                if block_type != "paragraph":
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
                    elif ext in {".png", ".jpg", ".jpeg"}:
                        _trim_raster_image(assets_dir / asset_name)
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
            normalized_lines = _normalize_section_lines(section["lines"], section["kind"])
            content_md = _compose_section_markdown(normalized_lines)
            content_md = _postprocess_lab_markdown(config.slug, section_id, content_md)
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
