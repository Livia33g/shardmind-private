"""Schema loading and lightweight validation."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shardmind.errors import SchemaValidationError
from shardmind.models import Note, PaperCard


class SchemaStore:
    def __init__(self, shared_path: Path):
        self.shared_path = shared_path
        self._schemas: dict[str, dict[str, Any]] = {}

    def load(self, name: str) -> dict[str, Any]:
        if name not in self._schemas:
            schema_path = self.shared_path / "schemas" / f"{name}.schema.json"
            self._schemas[name] = json.loads(schema_path.read_text(encoding="utf-8"))
        return self._schemas[name]

    def validate_note(self, note: Note) -> None:
        self.load("note")
        if not note.id.startswith("note-"):
            raise SchemaValidationError("Note id must start with 'note-'.")
        if note.type != "note":
            raise SchemaValidationError("Note type must be 'note'.")
        if not isinstance(note.tags, list) or any(not isinstance(tag, str) for tag in note.tags):
            raise SchemaValidationError("Note tags must be a list of strings.")
        if not note.created_at or not note.updated_at:
            raise SchemaValidationError("Note timestamps are required.")
        if not isinstance(note.sections.content, str):
            raise SchemaValidationError("Note content must be a string.")
        provenance = asdict(note.provenance)
        if set(provenance) != {"created_from"}:
            raise SchemaValidationError("Note provenance may only contain 'created_from'.")

    def validate_paper_card(self, paper_card: PaperCard) -> None:
        self.load("paper_card")
        if not paper_card.id.startswith("paper-"):
            raise SchemaValidationError("Paper card id must start with 'paper-'.")
        if paper_card.type != "paper-card":
            raise SchemaValidationError("Paper card type must be 'paper-card'.")
        if not paper_card.title.strip():
            raise SchemaValidationError("Paper card title is required.")
        if not isinstance(paper_card.authors, list) or any(
            not isinstance(author, str) for author in paper_card.authors
        ):
            raise SchemaValidationError("Paper card authors must be a list of strings.")
        if paper_card.year is not None and not isinstance(paper_card.year, int):
            raise SchemaValidationError("Paper card year must be an integer when provided.")
        if not isinstance(paper_card.tags, list) or any(
            not isinstance(tag, str) for tag in paper_card.tags
        ):
            raise SchemaValidationError("Paper card tags must be a list of strings.")
        if not paper_card.created_at or not paper_card.updated_at:
            raise SchemaValidationError("Paper card timestamps are required.")
        if paper_card.status not in {"unread", "queued", "reading", "reviewed", "archived"}:
            raise SchemaValidationError("Paper card status is invalid.")
        sections = asdict(paper_card.sections)
        required_sections = {
            "source_notes",
            "llm_summary",
            "main_claims",
            "why_relevant",
            "limitations",
            "user_notes",
            "related_links",
        }
        if set(sections) != required_sections:
            raise SchemaValidationError("Paper card sections must match the canonical schema.")
        if any(not isinstance(value, str) for value in sections.values()):
            raise SchemaValidationError("Paper card sections must be strings.")
