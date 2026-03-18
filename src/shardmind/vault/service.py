"""Canonical note storage service."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from shardmind.errors import InvalidInputError, NotFoundError, WriteFailedError
from shardmind.models import Note, NoteSections, Provenance
from shardmind.schemas import SchemaStore
from shardmind.vault.bootstrap import bootstrap_vault
from shardmind.vault.ids import note_id, slugify
from shardmind.vault.markdown import parse_note, render_note

DESTINATIONS = {"inbox", "scratch", "daily"}


class VaultService:
    def __init__(self, vault_path: Path, schema_store: SchemaStore):
        self.vault_path = vault_path
        self.schema_store = schema_store
        bootstrap_vault(vault_path)

    def create_note(
        self,
        content: str,
        title: str | None = None,
        destination: str | None = None,
        tags: list[str] | None = None,
        created_from: str = "mcp",
    ) -> tuple[Note, str]:
        if not content.strip():
            raise InvalidInputError("Note content must not be empty.")
        destination_name = self._normalize_destination(destination)
        now = self._now()
        normalized_title = (title or self._title_from_content(content)).strip()
        note = Note(
            id=note_id(normalized_title, timestamp=now),
            title=normalized_title,
            tags=tags or [],
            provenance=Provenance(created_from=created_from),
            created_at=now.isoformat().replace("+00:00", "Z"),
            updated_at=now.isoformat().replace("+00:00", "Z"),
            sections=NoteSections(content=content.strip()),
        )
        self.schema_store.validate_note(note)
        relative_path = f"notes/{destination_name}/{slugify(normalized_title)}.md"
        self._write_markdown(relative_path, render_note(note))
        self.log_write("knowledge.create_note", note.id, "create", True, relative_path)
        return note, relative_path

    def append_to_note(
        self,
        note_id_value: str,
        content: str,
        section: str | None = None,
    ) -> tuple[Note, str]:
        if section not in (None, "", "content", "Content"):
            raise InvalidInputError("Milestone 1 only supports appending to the Content section.")
        note, relative_path = self.read_note(note_id_value)
        appended = content.strip()
        if not appended:
            raise InvalidInputError("Append content must not be empty.")
        existing = note.sections.content.rstrip()
        note.sections.content = f"{existing}\n\n{appended}".strip()
        note.updated_at = self._now().isoformat().replace("+00:00", "Z")
        self.schema_store.validate_note(note)
        self._write_markdown(relative_path, render_note(note))
        self.log_write("knowledge.append_to_note", note.id, "append", True, relative_path)
        return note, relative_path

    def read_note(self, note_id_value: str) -> tuple[Note, str]:
        for path in self._note_paths():
            note = parse_note(path.read_text(encoding="utf-8"))
            if note.id == note_id_value:
                return note, path.relative_to(self.vault_path).as_posix()
        raise NotFoundError(f"No object found for id '{note_id_value}'.")

    def list_notes(self, path_scope: str | None = None) -> list[tuple[Note, str]]:
        results: list[tuple[Note, str]] = []
        for path in self._note_paths():
            relative_path = path.relative_to(self.vault_path).as_posix()
            if path_scope and not relative_path.startswith(path_scope):
                continue
            results.append((parse_note(path.read_text(encoding="utf-8")), relative_path))
        results.sort(key=lambda item: item[0].updated_at, reverse=True)
        return results

    def log_write(
        self,
        tool_name: str,
        object_id: str,
        operation: str,
        success: bool,
        path: str,
    ) -> None:
        log_path = self.vault_path / "system" / "logs" / "operations.log"
        event = {
            "timestamp": self._now().isoformat().replace("+00:00", "Z"),
            "tool_name": tool_name,
            "object_id": object_id,
            "operation": operation,
            "success": success,
            "path": path,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _note_paths(self) -> list[Path]:
        return sorted((self.vault_path / "notes").glob("*/*.md"))

    def _normalize_destination(self, destination: str | None) -> str:
        candidate = (destination or "inbox").strip().lower()
        if candidate not in DESTINATIONS:
            raise InvalidInputError(f"Unsupported note destination '{candidate}'.")
        return candidate

    def _title_from_content(self, content: str) -> str:
        first_line = next(
            (line.strip() for line in content.splitlines() if line.strip()), "Untitled note"
        )
        return first_line[:80]

    def _write_markdown(self, relative_path: str, payload: str) -> None:
        target = self.vault_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)
            tmp_path.replace(target)
        except OSError as exc:
            raise WriteFailedError(f"Could not write note to '{relative_path}'.") from exc

    def _now(self) -> datetime:
        return datetime.now(UTC)
