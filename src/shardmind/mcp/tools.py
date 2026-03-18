"""Tool implementations with MCP-style response envelopes."""

from __future__ import annotations

from typing import Any

from shardmind.errors import InvalidInputError, ShardMindError
from shardmind.index.service import IndexService
from shardmind.vault.service import VaultService


class KnowledgeTools:
    def __init__(self, vault: VaultService, index: IndexService):
        self.vault = vault
        self.index = index

    def create_note(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_non_empty_string(payload.get("content"), "content")
        note, path = self.vault.create_note(
            title=payload.get("title"),
            content=payload["content"],
            destination=payload.get("destination"),
            tags=payload.get("tags"),
        )
        self.index.reindex_note(note, path)
        return {
            "ok": True,
            "result": {
                "id": note.id,
                "type": note.type,
                "path": path,
                "title": note.title,
                "created_at": note.created_at,
            },
        }

    def append_to_note(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_non_empty_string(payload.get("id"), "id")
        self._require_non_empty_string(payload.get("content"), "content")
        note, path = self.vault.append_to_note(
            note_id_value=payload["id"],
            content=payload["content"],
            section=payload.get("section"),
        )
        self.index.reindex_note(note, path)
        return {
            "ok": True,
            "result": {
                "id": note.id,
                "type": note.type,
                "path": path,
                "updated_at": note.updated_at,
            },
        }

    def get_object(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_non_empty_string(payload.get("id"), "id")
        note, path = self.vault.read_note(payload["id"])
        return {"ok": True, "result": note.to_document(path)}

    def list_objects(self, payload: dict[str, Any]) -> dict[str, object]:
        object_type = payload.get("object_type")
        if object_type not in (None, "note", "paper-card"):
            raise InvalidInputError("object_type must be one of: note, paper-card, null.")
        limit = int(payload.get("limit") or 50)
        objects = self.index.list_objects(
            object_type=object_type,
            path_scope=payload.get("path_scope"),
            limit=limit,
        )
        return {"ok": True, "result": {"objects": objects}}

    def search(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_non_empty_string(payload.get("query"), "query")
        top_k = int(payload.get("top_k") or 10)
        object_types = payload.get("object_types")
        results = self.index.search(
            query=payload["query"],
            object_types=object_types,
            path_scope=payload.get("path_scope"),
            top_k=top_k,
        )
        return {
            "ok": True,
            "result": {
                "query": payload["query"],
                "results": [result.to_dict() for result in results],
                "top_k": top_k,
            },
        }

    def invoke(self, tool_name: str, payload: dict[str, Any]) -> dict[str, object]:
        try:
            method_name = tool_name.split(".", 1)[-1]
            method = getattr(self, method_name)
            return method(payload)
        except ShardMindError as exc:
            return exc.to_response()

    def _require_non_empty_string(self, value: object, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise InvalidInputError(f"{field_name} must be a non-empty string.")
