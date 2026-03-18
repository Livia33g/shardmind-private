"""Schema loading and lightweight validation."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shardmind.errors import SchemaValidationError
from shardmind.models import Note


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
        payload = {
            "id": note.id,
            "type": note.type,
            "title": note.title,
            "tags": note.tags,
            "provenance": asdict(note.provenance),
            "created_at": note.created_at,
            "updated_at": note.updated_at,
            "sections": asdict(note.sections),
        }
        if not note.id.startswith("note-"):
            raise SchemaValidationError("Note id must start with 'note-'.")
        if note.type != "note":
            raise SchemaValidationError("Note type must be 'note'.")
        if not isinstance(note.tags, list) or any(not isinstance(tag, str) for tag in note.tags):
            raise SchemaValidationError("Note tags must be a list of strings.")
        if not payload["created_at"] or not payload["updated_at"]:
            raise SchemaValidationError("Note timestamps are required.")
        if not isinstance(note.sections.content, str):
            raise SchemaValidationError("Note content must be a string.")
