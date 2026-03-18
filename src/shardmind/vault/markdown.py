"""Deterministic frontmatter and Markdown parsing."""

from __future__ import annotations

import ast
from dataclasses import asdict

from shardmind.models import Note, NoteSections, Provenance


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


def parse_note(markdown_text: str) -> Note:
    if not markdown_text.startswith("---\n"):
        raise ValueError("Markdown note is missing frontmatter.")
    _, frontmatter_body = markdown_text.split("---\n", 1)
    frontmatter_raw, body = frontmatter_body.split("\n---\n", 1)
    frontmatter = parse_frontmatter(frontmatter_raw)
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
        provenance=Provenance(created_from=str(provenance.get("created_from", ""))),
        created_at=str(frontmatter.get("created_at", "")),
        updated_at=str(frontmatter.get("updated_at", "")),
        sections=NoteSections(content=content),
    )


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
