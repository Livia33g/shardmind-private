"""Deterministic frontmatter and Markdown parsing."""

from __future__ import annotations

import ast
from dataclasses import asdict

from shardmind.models import (
    Note,
    NoteProvenance,
    NoteSections,
    ObjectRecord,
    PaperCard,
    PaperCardProvenance,
    PaperCardSections,
)

PAPER_CARD_SECTION_HEADINGS = {
    "Source notes": "source_notes",
    "LLM summary": "llm_summary",
    "Main claims": "main_claims",
    "Why relevant": "why_relevant",
    "Limitations": "limitations",
    "User notes": "user_notes",
    "Related links": "related_links",
}

PAPER_CARD_SECTION_TITLES = {value: key for key, value in PAPER_CARD_SECTION_HEADINGS.items()}


def _parse_scalar(value: str):
    stripped = value.strip()
    if stripped == "[]":
        return []
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    if stripped == "":
        return ""
    if stripped.isdigit():
        return int(stripped)
    if stripped.startswith("[") and stripped.endswith("]"):
        return ast.literal_eval(stripped)
    return stripped


def parse_frontmatter(raw: str) -> dict[str, object]:
    lines = raw.splitlines()
    data: dict[str, object] = {}
    current_map: dict[str, object] | None = None
    current_key: str | None = None
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("  "):
            if current_map is None:
                continue
            nested_key, _, nested_value = line.strip().partition(":")
            current_map[nested_key] = _parse_scalar(nested_value)
            continue
        key, _, value = line.partition(":")
        if value == "":
            current_key = key.strip()
            current_map = {}
            data[current_key] = current_map
        else:
            data[key.strip()] = _parse_scalar(value)
            current_key = None
            current_map = None
    return data


def _split_frontmatter(markdown_text: str) -> tuple[dict[str, object], str]:
    if not markdown_text.startswith("---\n"):
        raise ValueError("Markdown object is missing frontmatter.")
    _, frontmatter_body = markdown_text.split("---\n", 1)
    frontmatter_raw, body = frontmatter_body.split("\n---\n", 1)
    return parse_frontmatter(frontmatter_raw), body


def parse_note(markdown_text: str) -> Note:
    frontmatter, body = _split_frontmatter(markdown_text)
    heading = "# Content\n"
    content = body.lstrip("\n")
    if content.startswith(heading):
        content = content[len(heading) :]
    content = content.lstrip("\n").rstrip()
    provenance = frontmatter.get("provenance") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    return Note(
        id=str(frontmatter.get("id", "")),
        type=str(frontmatter.get("type", "note")),
        title=str(frontmatter.get("title", "")),
        tags=list(frontmatter.get("tags", [])),
        provenance=NoteProvenance(created_from=str(provenance.get("created_from", ""))),
        created_at=str(frontmatter.get("created_at", "")),
        updated_at=str(frontmatter.get("updated_at", "")),
        sections=NoteSections(content=content),
    )


def parse_sections(markdown_body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []
    for raw_line in markdown_body.lstrip("\n").splitlines():
        if raw_line.startswith("# "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = raw_line[2:].strip()
            current_lines = []
        else:
            current_lines.append(raw_line)
    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()
    return sections


def parse_paper_card(markdown_text: str) -> PaperCard:
    frontmatter, body = _split_frontmatter(markdown_text)
    provenance = frontmatter.get("provenance") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    raw_sections = parse_sections(body)
    sections = PaperCardSections(
        **{
            field_name: raw_sections.get(heading, "")
            for heading, field_name in PAPER_CARD_SECTION_HEADINGS.items()
        }
    )
    year = frontmatter.get("year")
    return PaperCard(
        id=str(frontmatter.get("id", "")),
        type=str(frontmatter.get("type", "paper-card")),
        title=str(frontmatter.get("title", "")),
        authors=list(frontmatter.get("authors", [])),
        year=year if isinstance(year, int) else None,
        source=str(frontmatter.get("source", "")),
        url=str(frontmatter.get("url", "")),
        citekey=str(frontmatter.get("citekey", "")),
        tags=list(frontmatter.get("tags", [])),
        status=str(frontmatter.get("status", "unread")),
        provenance=PaperCardProvenance(
            created_from=str(provenance.get("created_from", "")),
            source_type=str(provenance.get("source_type", "")),
            source_ref=str(provenance.get("source_ref", "")),
            llm_enriched=bool(provenance.get("llm_enriched", False)),
        ),
        created_at=str(frontmatter.get("created_at", "")),
        updated_at=str(frontmatter.get("updated_at", "")),
        sections=sections,
    )


def parse_object(markdown_text: str) -> ObjectRecord:
    frontmatter, _ = _split_frontmatter(markdown_text)
    object_type = str(frontmatter.get("type", ""))
    if object_type == "paper-card":
        return parse_paper_card(markdown_text)
    return parse_note(markdown_text)


def render_note(note: Note) -> str:
    frontmatter = asdict(note)
    lines = ["---"]
    lines.append(f"id: {frontmatter['id']}")
    lines.append(f"type: {frontmatter['type']}")
    lines.append(f"title: {frontmatter['title']}")
    lines.append(f"tags: {frontmatter['tags']}")
    lines.append("provenance:")
    lines.append(f"  created_from: {frontmatter['provenance']['created_from']}")
    lines.append(f"created_at: {frontmatter['created_at']}")
    lines.append(f"updated_at: {frontmatter['updated_at']}")
    lines.append("---")
    lines.append("")
    lines.append("# Content")
    content = note.sections.content.rstrip()
    if content:
        lines.append("")
        lines.append(content)
    return "\n".join(lines) + "\n"


def render_paper_card(paper_card: PaperCard) -> str:
    frontmatter = asdict(paper_card)
    lines = ["---"]
    lines.append(f"id: {frontmatter['id']}")
    lines.append(f"type: {frontmatter['type']}")
    lines.append(f"title: {frontmatter['title']}")
    lines.append(f"authors: {frontmatter['authors']}")
    year = frontmatter["year"] if frontmatter["year"] is not None else ""
    lines.append(f"year: {year}")
    lines.append(f"source: {frontmatter['source']}")
    lines.append(f"url: {frontmatter['url']}")
    lines.append(f"citekey: {frontmatter['citekey']}")
    lines.append(f"tags: {frontmatter['tags']}")
    lines.append(f"status: {frontmatter['status']}")
    lines.append("provenance:")
    lines.append(f"  created_from: {frontmatter['provenance']['created_from']}")
    lines.append(f"  source_type: {frontmatter['provenance']['source_type']}")
    lines.append(f"  source_ref: {frontmatter['provenance']['source_ref']}")
    lines.append(f"  llm_enriched: {str(frontmatter['provenance']['llm_enriched']).lower()}")
    lines.append(f"created_at: {frontmatter['created_at']}")
    lines.append(f"updated_at: {frontmatter['updated_at']}")
    lines.append("---")
    lines.append("")
    for field_name, heading in PAPER_CARD_SECTION_TITLES.items():
        lines.append(f"# {heading}")
        content = getattr(paper_card.sections, field_name).rstrip()
        if content:
            lines.append("")
            lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
