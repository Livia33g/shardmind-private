"""Tool implementations with MCP-style response envelopes."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from shardmind.errors import InternalError, InvalidInputError, ShardMindError
from shardmind.index.service import IndexService
from shardmind.mcp.registry import invoke_registered_tool, tool_spec
from shardmind.models import Note, PaperCard, SearchResult, path_reference_fields, titled_fields
from shardmind.paper_cards import PAPER_CARD_SECTION_LABELS
from shardmind.vault.service import VaultService

WIKILINK_GUIDANCE = (
    "When another vault file is relevant or mentioned, reference it inline with an Obsidian "
    "wikilink using the file stem returned by retrieval, for example "
    "[[memory-architecture-idea--1a2b3c4d]]. Do not use frontmatter title as the link target."
)
OBJECT_ID_GUIDANCE = (
    "Object id returned by create, list, search, or get tools. Use note-... for notes and "
    "paper-... for paper cards."
)
OBJECT_PATH_GUIDANCE = (
    "Vault-relative Markdown path. Notes may live under notes/, archive/, or library/ except "
    "library/papers/. Paper cards must stay under library/papers/. Paths under assets/ and "
    "system/ are rejected."
)
NOTE_CONTENT_GUIDANCE = (
    "Main note body for the # Content section. Use complete prose or bullets that should live "
    "in the note. "
    f"{WIKILINK_GUIDANCE}"
)
TAG_CREATION_GUIDANCE = (
    "Prefer existing tags and existing casing when known instead of inventing near-duplicate "
    "spellings. If you need to inspect the current tag vocabulary first, call shardmind.list_tags."
)
PAPER_CARD_SECTION_PATCH_GUIDANCE = (
    "Section patch object keyed by any of: summary, main_claims, why_relevant, limitations, "
    "notes, related_links. Intended use: summary=high-level takeaway in 2-4 sentences, "
    "main_claims=distinct core claims or findings, why_relevant=why this matters to your work, "
    "limitations=known caveats or missing evidence, notes=raw source snippets only, "
    "related_links=wikilinks or URLs. Use these structured sections for synthesized content "
    "instead of dumping everything into notes."
)
PAPER_CARD_CREATE_SECTIONS_GUIDANCE = (
    "Optional initial section object for create_paper_card using the same keys as "
    "shardmind_edit_paper_card: summary, main_claims, why_relevant, limitations, notes, "
    "related_links. Prefer putting synthesized content here during creation so the card is "
    "usable in one tool call. Use sections.notes for raw source capture only, such as abstract "
    "text, direct excerpts, bibliographic scraps, or stray observations. Do not put a "
    "synthesized paper summary, claim list, relevance rationale, limitations list, or a second "
    "mini-card in sections.notes. Do not include duplicate headings such as # Summary or ## Main "
    "Claims inside sections.notes. " + PAPER_CARD_SECTION_PATCH_GUIDANCE
)
PAPER_CARD_METADATA_PATCH_GUIDANCE = (
    "Metadata patch object using: authors (list[str]), year (int or null), source (str), "
    "url (str), citekey (str), tags (list[str]), status (str). If citekey is provided, use "
    "lowercase authorYearTitleword format such as mottes2026gradient."
)
NOTE_SECTION_PATCH_GUIDANCE = (
    "Section patch object for notes. Supported key: content. Use this to replace or seed the "
    "main # Content section."
)
NOTE_METADATA_PATCH_GUIDANCE = (
    "Metadata patch object for notes. Supported keys: title (str), tags (list[str])."
)
EDIT_MODE_GUIDANCE = (
    "Patch mode. fill-empty only writes into empty fields and preserves existing non-empty "
    "values. refresh replaces existing values."
)
LOGGER = logging.getLogger(__name__)
CORRECTION_CUES = {
    "correction",
    "corrected",
    "correct",
    "wrong",
    "mistake",
    "missed",
    "fix",
    "fixed",
    "revise",
    "revised",
    "update",
    "updated",
}
ALTERNATIVE_CUES = {
    "alternative",
    "alternatively",
    "instead",
    "different",
    "another",
    "better",
    "option",
    "approach",
    "method",
    "variant",
}


class KnowledgeTools:
    def __init__(self, vault: VaultService, index: IndexService):
        self.vault = vault
        self.index = index

    @tool_spec("shardmind_create_note", "shardmind.create_note")
    def create_note(
        self,
        content: Annotated[str, Field(description=NOTE_CONTENT_GUIDANCE)],
        title: Annotated[
            str | None,
            Field(
                description=(
                    "Optional note title. If omitted, the server derives one from the first "
                    "non-empty content line."
                )
            ),
        ] = None,
        destination: Annotated[
            Literal["inbox", "scratch", "daily"] | None,
            Field(
                description=(
                    "Optional note folder under notes/. Use inbox for captured ideas, scratch "
                    "for temporary work, and daily for day-specific notes."
                )
            ),
        ] = None,
        relative_path: Annotated[
            str | None,
            Field(
                description=(
                    "Optional vault-relative Markdown path for the new note, such as "
                    "notes/projects/ideas/memory.md, library/references/topic.md, or "
                    "archive/2026/retrospective.md. Must not be used together with destination. "
                    "Notes may live under notes/, archive/, or library/ except library/papers/. "
                    "Paths under assets/ and system/ are rejected."
                )
            ),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(
                description=(
                    f"Optional note tags for filtering and retrieval. {TAG_CREATION_GUIDANCE}"
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        """Create a deterministic note from freeform text."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(content, "content")
            note, path = self.vault.create_note(
                title=title,
                content=content,
                destination=destination,
                relative_path=relative_path,
                tags=tags,
            )
            return {
                "ok": True,
                "result": {
                    "id": note.id,
                    "type": note.type,
                    "path": path,
                    "note_title": note.title,
                    "created_at": note.created_at,
                },
            }

        return self._execute_tool("shardmind.create_note", run)

    @tool_spec("shardmind_create_paper_card", "shardmind.create_paper_card")
    def create_paper_card(
        self,
        title: Annotated[
            str | None,
            Field(
                description=(
                    "Optional human-readable paper title. Prefer the canonical published title "
                    "when available."
                )
            ),
        ] = None,
        authors: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional ordered author list from first author to last author, preserving "
                    "publication order."
                )
            ),
        ] = None,
        year: Annotated[
            int | None,
            Field(description="Optional publication year as a four-digit integer."),
        ] = None,
        source: Annotated[
            str | None,
            Field(description="Optional source label such as arxiv, doi, conference, or journal."),
        ] = None,
        url: Annotated[
            str | None,
            Field(
                description=(
                    "Optional canonical URL (publisher, DOI resolver, or stable preprint URL)."
                )
            ),
        ] = None,
        citekey: Annotated[
            str | None,
            Field(
                description=(
                    "Optional Better BibTeX-style citekey in lowercase authorYearTitleword "
                    "format, for example mottes2026gradient."
                )
            ),
        ] = None,
        sections: Annotated[
            dict[str, str] | None,
            Field(description=PAPER_CARD_CREATE_SECTIONS_GUIDANCE),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional paper tags for thematic grouping, e.g. memory, planning, or "
                    f"evaluation. {TAG_CREATION_GUIDANCE}"
                )
            ),
        ] = None,
        status: Annotated[
            str | None,
            Field(
                description=(
                    "Optional reading status such as unread, queued, reading, reviewed, "
                    "or archived."
                )
            ),
        ] = None,
        relative_path: Annotated[
            str | None,
            Field(
                description=(
                    "Optional vault-relative Markdown path for the new paper card, such as "
                    "library/papers/ml/transformers/attention-card.md. Must stay under "
                    "library/papers/ and end in .md."
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        """Create a paper card with metadata plus optional canonical sections in one request."""

        def run() -> dict[str, object]:
            next_sections = self._optional_dict(sections, "sections")
            if not any((title, url, next_sections)):
                raise InvalidInputError("At least one of title, url, or sections must be provided.")
            paper_card, path = self.vault.create_paper_card(
                title=title,
                authors=authors,
                year=year,
                source=source,
                url=url,
                citekey=citekey,
                sections=next_sections,
                tags=tags,
                status=status,
                relative_path=relative_path,
            )
            return {
                "ok": True,
                "result": {
                    "id": paper_card.id,
                    "type": paper_card.type,
                    "path": path,
                    "paper_title": paper_card.title,
                    "created_at": paper_card.created_at,
                    "duplicate_of": None,
                },
            }

        return self._execute_tool("shardmind.create_paper_card", run)

    @tool_spec("shardmind_append_to_note", "shardmind.append_to_note")
    def append_to_note(
        self,
        id: Annotated[str, Field(description=OBJECT_ID_GUIDANCE)],  # noqa: A002
        content: Annotated[
            str,
            Field(
                description=(
                    "Content to append to the existing # Content section without replacing "
                    "current text. "
                    f"{WIKILINK_GUIDANCE}"
                )
            ),
        ],
        section: Annotated[
            str | None,
            Field(
                description=(
                    "Optional section selector. Milestone 2 supports only Content/content."
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        """Append content to the canonical Content section of an existing note."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(id, "id")
            self._require_non_empty_string(content, "content")
            note, path = self.vault.append_to_note(
                note_id_value=id,
                content=content,
                section=section,
            )
            return {
                "ok": True,
                "result": {
                    "id": note.id,
                    "type": note.type,
                    "path": path,
                    "updated_at": note.updated_at,
                },
            }

        return self._execute_tool("shardmind.append_to_note", run)

    @tool_spec("shardmind_edit_note", "shardmind.edit_note")
    def edit_note(
        self,
        id: Annotated[str, Field(description=OBJECT_ID_GUIDANCE)],  # noqa: A002
        sections: Annotated[
            dict[str, str] | None,
            Field(description=NOTE_SECTION_PATCH_GUIDANCE),
        ] = None,
        metadata: Annotated[
            dict[str, object] | None,
            Field(description=NOTE_METADATA_PATCH_GUIDANCE),
        ] = None,
        mode: Annotated[
            Literal["fill-empty", "refresh"] | None,
            Field(description=EDIT_MODE_GUIDANCE),
        ] = None,
    ) -> dict[str, object]:
        """Edit supported sections and metadata on an existing note."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(id, "id")
            next_mode = mode or "refresh"
            next_sections = self._optional_dict(sections, "sections")
            next_metadata = self._optional_dict(metadata, "metadata")
            if not next_sections and not next_metadata:
                raise InvalidInputError("At least one of sections or metadata must be provided.")
            note, path = self.vault.update_note(
                id,
                sections=next_sections,
                metadata=next_metadata,
                mode=next_mode,
            )
            return {
                "ok": True,
                "result": {
                    "id": note.id,
                    "type": note.type,
                    "path": path,
                    "updated_at": note.updated_at,
                    "mode": next_mode,
                },
            }

        return self._execute_tool("shardmind.edit_note", run)

    @tool_spec("shardmind_edit_paper_card", "shardmind.edit_paper_card")
    def edit_paper_card(
        self,
        id: Annotated[str, Field(description=OBJECT_ID_GUIDANCE)],  # noqa: A002
        sections: Annotated[
            dict[str, str] | None,
            Field(description=PAPER_CARD_SECTION_PATCH_GUIDANCE),
        ] = None,
        metadata: Annotated[
            dict[str, object] | None,
            Field(description=PAPER_CARD_METADATA_PATCH_GUIDANCE),
        ] = None,
        mode: Annotated[
            Literal["fill-empty", "refresh"] | None,
            Field(description=EDIT_MODE_GUIDANCE),
        ] = None,
    ) -> dict[str, object]:
        """Populate or replace the canonical structured sections on an existing paper card."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(id, "id")
            next_mode = mode or "fill-empty"
            next_sections = self._optional_dict(sections, "sections")
            next_metadata = self._optional_dict(metadata, "metadata")
            if not next_sections and not next_metadata:
                raise InvalidInputError("At least one of sections or metadata must be provided.")
            paper_card, path = self.vault.update_paper_card_sections(
                id,
                sections=next_sections,
                metadata=next_metadata,
                mode=next_mode,
            )
            return {
                "ok": True,
                "result": {
                    "id": paper_card.id,
                    "type": paper_card.type,
                    "path": path,
                    "updated_at": paper_card.updated_at,
                    "mode": next_mode,
                },
            }

        return self._execute_tool("shardmind.edit_paper_card", run)

    @tool_spec("shardmind_get_object", "shardmind.get_object", "fetch")
    def get_object(
        self,
        id: Annotated[str, Field(description=OBJECT_ID_GUIDANCE)],  # noqa: A002
    ) -> dict[str, object]:
        def run() -> dict[str, object]:
            self._require_non_empty_string(id, "id")
            record, path = self.vault.read_object(id)
            return {"ok": True, "result": record.to_document(path)}

        return self._execute_tool("shardmind.get_object", run)

    @tool_spec("shardmind_move_object", "shardmind.move_object")
    def move_object(
        self,
        id: Annotated[str, Field(description=OBJECT_ID_GUIDANCE)],  # noqa: A002
        relative_path: Annotated[
            str,
            Field(
                description=(
                    "New vault-relative Markdown path for the existing object. "
                    f"{OBJECT_PATH_GUIDANCE}"
                )
            ),
        ],
    ) -> dict[str, object]:
        """Move an existing object to a new allowed path without changing its id."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(id, "id")
            self._require_non_empty_string(relative_path, "relative_path")
            record, path = self.vault.move_object(id, relative_path)
            return {
                "ok": True,
                "result": {
                    "id": record.id,
                    "type": record.type,
                    "path": path,
                    **titled_fields(record.type, record.title),
                    **path_reference_fields(path),
                },
            }

        return self._execute_tool("shardmind.move_object", run)

    @tool_spec("shardmind_delete_object", "shardmind.delete_object")
    def delete_object(
        self,
        id: Annotated[str, Field(description=OBJECT_ID_GUIDANCE)],  # noqa: A002
    ) -> dict[str, object]:
        """Delete an existing object by id and remove it from the derived index."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(id, "id")
            record, path = self.vault.delete_object(id)
            return {
                "ok": True,
                "result": {
                    "id": record.id,
                    "type": record.type,
                    "path": path,
                    "deleted": True,
                    **titled_fields(record.type, record.title),
                    **path_reference_fields(path),
                },
            }

        return self._execute_tool("shardmind.delete_object", run)

    @tool_spec("shardmind_reindex_all", "shardmind.reindex_all")
    def reindex_all(self) -> dict[str, object]:
        """Rebuild the derived SQLite index from the current vault contents."""

        def run() -> dict[str, object]:
            records, skipped_paths = self.vault.list_indexable_objects()
            self.index.rebuild(records)
            return {
                "ok": True,
                "result": {
                    "indexed_count": len(records),
                    "skipped_paths": skipped_paths,
                    "skipped_count": len(skipped_paths),
                },
            }

        return self._execute_tool("shardmind.reindex_all", run)

    @tool_spec("shardmind_list_objects", "shardmind.list_objects")
    def list_objects(
        self,
        object_type: Annotated[
            Literal["note", "paper-card"] | None,
            Field(description="Optional type filter. Omit to include both object types."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(
                description=("Optional path prefix filter such as notes/inbox or library/papers.")
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(ge=1, le=200, description="Maximum number of objects to return."),
        ] = 50,
    ) -> dict[str, object]:
        def run() -> dict[str, object]:
            objects = self._list_live_objects(
                object_type=object_type,
                path_scope=path_scope,
                limit=limit,
            )
            return {"ok": True, "result": {"objects": objects}}

        return self._execute_tool("shardmind.list_objects", run)

    @tool_spec("shardmind_list_tags", "shardmind.list_tags")
    def list_tags(
        self,
        object_type: Annotated[
            Literal["note", "paper-card"] | None,
            Field(description="Optional type filter. Omit to include tags from both object types."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(
                description=(
                    "Optional path prefix filter such as notes/inbox or library/papers; "
                    "limits tags to documents under that path."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=200,
                description="Maximum number of distinct tag strings to return (index-backed).",
            ),
        ] = 200,
    ) -> dict[str, object]:
        def run() -> dict[str, object]:
            tags = self._list_live_tags(
                object_type=object_type,
                path_scope=path_scope,
                limit=limit,
            )
            return {"ok": True, "result": {"tags": tags}}

        return self._execute_tool("shardmind.list_tags", run)

    @tool_spec("shardmind_search", "shardmind.search", "search")
    def search(
        self,
        query: Annotated[
            str,
            Field(description="Lexical search query string."),
        ],
        object_types: Annotated[
            list[Literal["note", "paper-card"]] | None,
            Field(description="Optional object-type filter list."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(description="Optional path prefix filter."),
        ] = None,
        top_k: Annotated[
            int,
            Field(ge=1, le=50, description="Maximum number of ranked results to return."),
        ] = 10,
        tags: Annotated[
            list[str] | None,
            Field(
                description=("Optional tag filter; only objects matching these tags are returned.")
            ),
        ] = None,
    ) -> dict[str, object]:
        def run() -> dict[str, object]:
            self._require_non_empty_string(query, "query")
            results = self._search_live_results(
                query=query,
                object_types=object_types,
                path_scope=path_scope,
                top_k=top_k,
                tags=tags,
            )
            return {
                "ok": True,
                "result": {
                    "query": query,
                    "results": [result.to_dict() for result in results],
                    "top_k": top_k,
                },
            }

        return self._execute_tool("shardmind.search", run)

    @tool_spec(
        "shardmind_retrieve_context",
        "shardmind.retrieve_context",
        "retrieve_context",
        "gather_context",
    )
    def retrieve_context(
        self,
        query: Annotated[
            str,
            Field(
                description=(
                    "Retrieve a compact evidence bundle for a query using ShardMind's hybrid "
                    "retrieval. Use this when you want model-ready context instead of raw search "
                    "results."
                )
            ),
        ],
        object_types: Annotated[
            list[Literal["note", "paper-card"]] | None,
            Field(description="Optional object-type filter list."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(description="Optional path prefix filter."),
        ] = None,
        top_k: Annotated[
            int,
            Field(
                ge=1,
                le=20,
                description="Maximum number of documents to include in the evidence bundle.",
            ),
        ] = 6,
        tags: Annotated[
            list[str] | None,
            Field(
                description=("Optional tag filter; only objects matching these tags are returned.")
            ),
        ] = None,
        max_sections_per_object: Annotated[
            int,
            Field(
                ge=1,
                le=6,
                description="Maximum number of matched sections/snippets to include per object.",
            ),
        ] = 3,
        snippet_chars: Annotated[
            int,
            Field(
                ge=80,
                le=800,
                description="Maximum character length for each evidence snippet.",
            ),
        ] = 320,
        max_total_chars: Annotated[
            int,
            Field(
                ge=200,
                le=12000,
                description=(
                    "Hard budget for the total evidence text returned across all snippets. "
                    "Use this to control downstream model token cost."
                ),
            ),
        ] = 1800,
    ) -> dict[str, object]:
        """Retrieve compact, model-ready evidence bundles instead of raw search results."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(query, "query")
            results = self._search_live_results(
                query=query,
                object_types=object_types,
                path_scope=path_scope,
                top_k=top_k,
                tags=tags,
            )
            evidence = [
                self._build_evidence_bundle(
                    result,
                    max_sections=max_sections_per_object,
                    snippet_chars=snippet_chars,
                )
                for result in results
            ]
            evidence = self._apply_evidence_budget(evidence, max_total_chars=max_total_chars)
            return {
                "ok": True,
                "result": {
                    "query": query,
                    "evidence": evidence,
                    "retrieval_mode": "hybrid-local-rag",
                    "evidence_count": len(evidence),
                    "max_total_chars": max_total_chars,
                    "returned_chars": self._evidence_char_count(evidence),
                    "recommended_citation_style": "cite ShardMind path and wikilink when summarizing evidence",
                },
            }

        return self._execute_tool("shardmind.retrieve_context", run)

    @tool_spec(
        "shardmind_suggest_recall",
        "shardmind.suggest_recall",
        "suggest_recall",
        "resurface_memories",
        "bring_back_up",
    )
    def suggest_recall(
        self,
        topic: Annotated[
            str,
            Field(
                description=(
                    "Suggest previously captured ShardMind memories that are worth bringing "
                    "back into the current conversation. Use this when you want the system to "
                    "proactively surface older relevant notes or paper cards instead of only "
                    "running plain search."
                )
            ),
        ],
        object_types: Annotated[
            list[Literal["note", "paper-card"]] | None,
            Field(description="Optional object-type filter list."),
        ] = None,
        path_scope: Annotated[
            str | None,
            Field(description="Optional path prefix filter."),
        ] = None,
        max_suggestions: Annotated[
            int,
            Field(
                ge=1,
                le=10,
                description="Maximum number of resurfaced memories to return.",
            ),
        ] = 4,
        tags: Annotated[
            list[str] | None,
            Field(
                description=("Optional tag filter; only objects matching these tags are returned.")
            ),
        ] = None,
        exclude_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional list of object ids to exclude, for example memories already "
                    "mentioned in the current session."
                )
            ),
        ] = None,
        snippet_chars: Annotated[
            int,
            Field(
                ge=80,
                le=700,
                description="Maximum character length for each resurfaced snippet.",
            ),
        ] = 280,
        max_total_chars: Annotated[
            int,
            Field(
                ge=200,
                le=12000,
                description=(
                    "Hard budget for the total resurfaced evidence text returned across all "
                    "suggestions. Use this to control downstream model token cost."
                ),
            ),
        ] = 1600,
    ) -> dict[str, object]:
        """Suggest prior memories worth resurfacing for the current topic."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(topic, "topic")
            search_depth = min(max(max_suggestions * 3, 8), 20)
            excluded = {candidate for candidate in exclude_ids or [] if isinstance(candidate, str)}
            query_terms = self._query_terms(topic)
            results = self._search_live_results(
                query=topic,
                object_types=object_types,
                path_scope=path_scope,
                top_k=search_depth,
                tags=tags,
            )
            suggestions = []
            for result in results:
                if result.id in excluded:
                    continue
                suggestion = self._build_recall_suggestion(
                    topic=topic,
                    query_terms=query_terms,
                    result=result,
                    snippet_chars=snippet_chars,
                )
                suggestions.append(suggestion)
            suggestions.sort(
                key=lambda candidate: (
                    float(candidate["resurfacing_score"]),
                    float(candidate["score"]),
                ),
                reverse=True,
            )
            suggestions = suggestions[:max_suggestions]
            suggestions = self._apply_evidence_budget(suggestions, max_total_chars=max_total_chars)
            return {
                "ok": True,
                "result": {
                    "topic": topic,
                    "suggestions": suggestions,
                    "retrieval_mode": "hybrid-local-rag+resurfacing",
                    "suggestion_count": len(suggestions),
                    "excluded_ids": sorted(excluded),
                    "max_total_chars": max_total_chars,
                    "returned_chars": self._evidence_char_count(suggestions),
                },
            }

        return self._execute_tool("shardmind.suggest_recall", run)

    @tool_spec(
        "shardmind_capture_this",
        "shardmind.capture_this",
        "capture_this",
        "take_note",
        "save_insight",
    )
    def capture_this(
        self,
        content: Annotated[
            str,
            Field(
                description=(
                    "Compact content to capture from the current conversation. Prefer the key "
                    "insight, decision, troubleshooting lesson, or theory update rather than a "
                    "full transcript."
                )
            ),
        ],
        title: Annotated[
            str | None,
            Field(
                description=(
                    "Optional note title. If omitted, ShardMind derives one from the captured content."
                )
            ),
        ] = None,
        mode: Annotated[
            Literal["quick-note", "theory", "decision", "troubleshooting"],
            Field(
                description=(
                    "Capture mode. Use theory for conceptual ideas, decision for choices made, "
                    "and troubleshooting for debugging or methodology lessons."
                )
            ),
        ] = "quick-note",
        destination: Annotated[
            Literal["inbox", "scratch", "daily"] | None,
            Field(
                description=(
                    "Optional note folder under notes/. Use inbox for captured ideas, scratch "
                    "for temporary work, and daily for day-specific notes."
                )
            ),
        ] = "inbox",
        path_scope: Annotated[
            str | None,
            Field(
                description=(
                    "Optional path prefix used when looking for earlier related notes or cards."
                )
            ),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional note tags for filtering and retrieval. These are merged with "
                    "lightweight suggested tags inferred from the capture mode."
                )
            ),
        ] = None,
        preserve_history: Annotated[
            bool,
            Field(
                description=(
                    "When true, corrections or alternatives will preserve the earlier note "
                    "instead of silently overwriting it."
                )
            ),
        ] = True,
        apply: Annotated[
            bool,
            Field(
                description=(
                    "When true, save the capture immediately. When false, only return a preview "
                    "of the recommended action and formatted note content."
                )
            ),
        ] = True,
    ) -> dict[str, object]:
        """Capture a lightweight conversation insight and relate it to prior ShardMind memory."""

        def run() -> dict[str, object]:
            self._require_non_empty_string(content, "content")
            clean_content = content.strip()
            capture_title = (title or self._derive_capture_title(clean_content)).strip()
            inferred_tags = self._merge_capture_tags(tags, mode)
            relation = self._analyze_capture_relation(
                content=clean_content,
                path_scope=path_scope,
            )
            formatted_body = self._format_capture_body(
                content=clean_content,
                mode=mode,
                relation=relation,
            )
            saved_result: dict[str, object] | None = None
            applied_action = relation["recommended_action"]
            if apply:
                saved_result, applied_action = self._apply_capture_relation(
                    title=capture_title,
                    body=formatted_body,
                    destination=destination,
                    tags=inferred_tags,
                    relation=relation,
                    preserve_history=preserve_history,
                )
            return {
                "ok": True,
                "result": {
                    "title": capture_title,
                    "mode": mode,
                    "relation": relation["relation"],
                    "recommended_action": relation["recommended_action"],
                    "applied_action": applied_action if apply else None,
                    "rationale": relation["rationale"],
                    "related_object": relation["related_object"],
                    "preserve_history": preserve_history,
                    "apply": apply,
                    "suggested_tags": inferred_tags,
                    "preview_content": formatted_body,
                    "saved": saved_result,
                },
            }

        return self._execute_tool("shardmind.capture_this", run)

    def invoke(self, tool_name: str, payload: dict[str, Any]) -> dict[str, object]:
        def run() -> dict[str, object]:
            return invoke_registered_tool(self, tool_name, payload)

        return self._execute_tool(tool_name, run)

    def _execute_tool(
        self,
        tool_name: str,
        operation: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        try:
            return operation()
        except ShardMindError as exc:
            return exc.to_response()
        except Exception:
            LOGGER.exception("Unexpected error while executing %s", tool_name)
            return InternalError().to_response()

    def _require_non_empty_string(self, value: object, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise InvalidInputError(f"{field_name} must be a non-empty string.")

    def _optional_dict(self, value: object, field_name: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise InvalidInputError(f"{field_name} must be an object.")
        return value

    def _list_live_objects(
        self,
        *,
        object_type: Literal["note", "paper-card"] | None,
        path_scope: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        while True:
            stale_found = False
            live_objects: list[dict[str, object]] = []
            indexed_objects = self.index.list_objects(
                object_type=object_type,
                path_scope=path_scope,
                limit=limit,
            )
            for candidate in indexed_objects:
                resolved = self.vault.reconcile_index_entry(
                    str(candidate["id"]),
                    str(candidate["path"]),
                )
                if resolved is None:
                    stale_found = True
                    continue
                record, path = resolved
                live_objects.append(
                    {
                        "id": record.id,
                        "type": record.type,
                        "path": path,
                        "updated_at": record.updated_at,
                        **titled_fields(record.type, record.title),
                        **path_reference_fields(path),
                    }
                )
            if len(live_objects) >= limit or not stale_found:
                return live_objects[:limit]

    def _search_live_results(
        self,
        *,
        query: str,
        object_types: list[Literal["note", "paper-card"]] | None,
        path_scope: str | None,
        top_k: int,
        tags: list[str] | None,
    ) -> list[SearchResult]:
        waited_for_embeddings = False
        while True:
            stale_found = False
            live_results: list[SearchResult] = []
            indexed_results = self.index.search(
                query=query,
                object_types=object_types,
                path_scope=path_scope,
                top_k=top_k,
                tags=tags,
            )
            if (
                not indexed_results
                and not waited_for_embeddings
                and self.index.pending_embedding_jobs() > 0
            ):
                self.index.wait_for_embeddings(timeout=0.5)
                waited_for_embeddings = True
                continue
            for candidate in indexed_results:
                resolved = self.vault.reconcile_index_entry(candidate.id, candidate.path)
                if resolved is None:
                    stale_found = True
                    continue
                record, path = resolved
                candidate.path = path
                candidate.title = record.title
                candidate.type = record.type
                live_results.append(candidate)
            if len(live_results) >= top_k or not stale_found:
                return live_results[:top_k]

    def _list_live_tags(
        self,
        *,
        object_type: Literal["note", "paper-card"] | None,
        path_scope: str | None,
        limit: int,
    ) -> list[str]:
        stale_found = False
        live_tags: list[str] = []
        seen_tags: set[str] = set()
        tag_references = self.index.list_tag_references(
            object_type=object_type,
            path_scope=path_scope,
        )
        for candidate in tag_references:
            if len(live_tags) >= limit:
                break
            tag = str(candidate["tag"])
            if tag in seen_tags:
                continue
            resolved = self.vault.reconcile_index_entry(
                str(candidate["id"]),
                str(candidate["path"]),
            )
            if resolved is None:
                stale_found = True
                continue
            seen_tags.add(tag)
            live_tags.append(tag)
        if stale_found:
            return self.index.list_tags(
                object_type=object_type,
                path_scope=path_scope,
                limit=limit,
            )
        return live_tags

    def _build_evidence_bundle(
        self,
        result: SearchResult,
        *,
        max_sections: int,
        snippet_chars: int,
    ) -> dict[str, object]:
        record, path = self.vault.read_object(result.id)
        section_snippets = self._matched_section_snippets(
            record,
            result.matched_sections[:max_sections],
            snippet_chars=snippet_chars,
        )
        return {
            "id": record.id,
            "type": record.type,
            "path": path,
            "score": result.score,
            "matched_sections": list(result.matched_sections[:max_sections]),
            "primary_snippet": self._truncate_snippet(result.snippet, snippet_chars),
            "section_snippets": section_snippets,
            "tags": list(result.tags),
            **titled_fields(record.type, record.title),
            **path_reference_fields(path),
        }

    def _build_recall_suggestion(
        self,
        *,
        topic: str,
        query_terms: set[str],
        result: SearchResult,
        snippet_chars: int,
    ) -> dict[str, object]:
        record, path = self.vault.read_object(result.id)
        evidence = self._build_evidence_bundle(
            result,
            max_sections=3,
            snippet_chars=snippet_chars,
        )
        reason_bits: list[str] = []
        resurfacing_score = float(result.score)
        matched_sections = set(result.matched_sections)

        section_priority = {
            "Why Relevant": 0.16,
            "Limitations": 0.12,
            "Main Claims": 0.1,
            "Summary": 0.08,
            "Notes": 0.06,
            "Content": 0.05,
            "Title": 0.04,
        }
        for section_name, boost in section_priority.items():
            if section_name in matched_sections:
                resurfacing_score += boost
                if section_name == "Why Relevant":
                    reason_bits.append("It already includes an explicit why-relevant rationale.")
                elif section_name == "Limitations":
                    reason_bits.append("It carries caveats or troubleshooting context worth reusing.")
                elif section_name in {"Main Claims", "Summary"}:
                    reason_bits.append("It captures a compact conceptual summary for this topic.")

        overlap_terms = self._overlap_terms(
            query_terms=query_terms,
            text_parts=[
                record.title,
                path,
                " ".join(result.tags),
                result.snippet,
                " ".join(result.matched_sections),
            ],
        )
        if overlap_terms:
            resurfacing_score += min(0.18, 0.05 * len(overlap_terms))
            preview = ", ".join(sorted(overlap_terms)[:3])
            reason_bits.append(f"It overlaps strongly with the current topic terms: {preview}.")

        age_days = self._age_in_days(record.updated_at)
        if age_days is not None:
            if age_days >= 30:
                resurfacing_score += 0.08
                reason_bits.append("It is older and therefore easier to forget, but still relevant now.")
            elif age_days <= 2:
                resurfacing_score -= 0.04

        if not reason_bits:
            reason_bits.append(
                f"It matched the current topic '{topic}' across {len(result.matched_sections)} indexed sections."
            )

        evidence["resurfacing_score"] = round(resurfacing_score, 4)
        evidence["why_now"] = " ".join(reason_bits[:2])
        evidence["updated_at"] = record.updated_at
        return evidence

    def _analyze_capture_relation(
        self,
        *,
        content: str,
        path_scope: str | None,
    ) -> dict[str, object]:
        query_terms = self._query_terms(content)
        candidates = self._search_live_results(
            query=content,
            object_types=None,
            path_scope=path_scope,
            top_k=5,
            tags=None,
        )
        best_match: SearchResult | None = None
        overlap_terms: set[str] = set()
        for candidate in candidates:
            candidate_overlap = self._overlap_terms(
                query_terms=query_terms,
                text_parts=[
                    candidate.title,
                    candidate.path,
                    " ".join(candidate.tags),
                    candidate.snippet,
                    " ".join(candidate.matched_sections),
                ],
            )
            if len(candidate_overlap) >= 2 or (
                candidate.score >= 0.012 and len(candidate_overlap) >= 1
            ):
                best_match = candidate
                overlap_terms = candidate_overlap
                break

        cue_terms = self._query_terms(content)
        relation = "standalone"
        recommended_action = "create_new"
        rationale = "No strong prior memory match was found, so this capture should stand on its own."

        if best_match is not None:
            if cue_terms & CORRECTION_CUES:
                relation = "correction"
                recommended_action = "preserve_both"
                rationale = "This looks like a correction to an earlier memory, so keeping both versions preserves the reasoning trail."
            elif cue_terms & ALTERNATIVE_CUES:
                relation = "alternative"
                recommended_action = "preserve_both"
                rationale = "This looks like an alternative path or improved method, so preserving both versions keeps the design space visible."
            else:
                relation = "build_on"
                recommended_action = (
                    "append_existing" if best_match.type == "note" else "preserve_both"
                )
                rationale = (
                    "This appears to build directly on a prior memory, so appending or linking is clearer than creating an isolated duplicate."
                )

            if overlap_terms:
                rationale += f" Shared topic terms: {', '.join(sorted(overlap_terms)[:4])}."

        related_object = None
        if best_match is not None:
            related_object = {
                "id": best_match.id,
                "type": best_match.type,
                "path": best_match.path,
                "score": best_match.score,
                "matched_sections": list(best_match.matched_sections),
                "snippet": best_match.snippet,
                "tags": list(best_match.tags),
                **titled_fields(best_match.type, best_match.title),
                **path_reference_fields(best_match.path),
            }

        return {
            "relation": relation,
            "recommended_action": recommended_action,
            "rationale": rationale,
            "related_object": related_object,
        }

    def _apply_capture_relation(
        self,
        *,
        title: str,
        body: str,
        destination: Literal["inbox", "scratch", "daily"] | None,
        tags: list[str],
        relation: dict[str, object],
        preserve_history: bool,
    ) -> tuple[dict[str, object], str]:
        related_object = relation["related_object"]
        relation_name = str(relation["relation"])
        recommended_action = str(relation["recommended_action"])

        if (
            recommended_action == "append_existing"
            and not preserve_history
            and isinstance(related_object, dict)
            and str(related_object.get("type")) == "note"
        ):
            appended_content = self._format_capture_append(
                body=body,
                relation_name=relation_name,
                related_title=str(related_object.get("note_title") or related_object.get("paper_title") or ""),
            )
            note, path = self.vault.append_to_note(str(related_object["id"]), appended_content)
            return (
                {
                    "id": note.id,
                    "type": note.type,
                    "path": path,
                    "updated_at": note.updated_at,
                    **titled_fields(note.type, note.title),
                    **path_reference_fields(path),
                },
                "append_existing",
            )

        if recommended_action == "append_existing" and isinstance(related_object, dict):
            appended_content = self._format_capture_append(
                body=body,
                relation_name=relation_name,
                related_title=str(related_object.get("note_title") or related_object.get("paper_title") or ""),
            )
            note, path = self.vault.append_to_note(str(related_object["id"]), appended_content)
            return (
                {
                    "id": note.id,
                    "type": note.type,
                    "path": path,
                    "updated_at": note.updated_at,
                    **titled_fields(note.type, note.title),
                    **path_reference_fields(path),
                },
                "append_existing",
            )

        linked_body = self._link_capture_to_related(body=body, relation=relation)
        note, path = self.vault.create_note(
            title=title,
            content=linked_body,
            destination=destination,
            tags=tags,
            created_from="capture-this",
        )
        return (
            {
                "id": note.id,
                "type": note.type,
                "path": path,
                "created_at": note.created_at,
                **titled_fields(note.type, note.title),
                **path_reference_fields(path),
            },
            "create_new" if relation_name == "standalone" else "preserve_both",
        )

    def _format_capture_body(
        self,
        *,
        content: str,
        mode: str,
        relation: dict[str, object],
    ) -> str:
        lines = [content.strip()]
        if mode != "quick-note":
            lines.append("")
            lines.append(f"Capture mode: {mode}")
        lines.append("")
        lines.append(f"Capture rationale: {relation['rationale']}")
        return "\n".join(lines).strip()

    def _format_capture_append(
        self,
        *,
        body: str,
        relation_name: str,
        related_title: str,
    ) -> str:
        heading = relation_name.replace("_", " ").title()
        label = related_title or "prior memory"
        return (
            f"## {heading} Update\n"
            f"Relation: {heading.lower()} to {label}\n\n"
            f"{body.strip()}"
        )

    def _link_capture_to_related(
        self,
        *,
        body: str,
        relation: dict[str, object],
    ) -> str:
        related_object = relation["related_object"]
        if not isinstance(related_object, dict):
            return body
        title = str(related_object.get("note_title") or related_object.get("paper_title") or "")
        wikilink = str(related_object.get("wikilink") or "")
        relation_name = str(relation["relation"]).replace("_", " ")
        prefix = [
            f"Related prior memory: [[{wikilink}]]",
            f"Relation: {relation_name}",
        ]
        if title:
            prefix.insert(1, f"Related title: {title}")
        return "\n".join(prefix + ["", body.strip()]).strip()

    def _derive_capture_title(self, content: str) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return "Captured insight"
        first_line = re.split(r"[.!?]", lines[0], maxsplit=1)[0].strip()
        if len(first_line) <= 72:
            return first_line
        return first_line[:69].rstrip() + "..."

    def _merge_capture_tags(self, tags: list[str] | None, mode: str) -> list[str]:
        merged = list(tags or [])
        mode_tag_map = {
            "quick-note": "capture",
            "theory": "theory",
            "decision": "decision",
            "troubleshooting": "troubleshooting",
        }
        mode_tag = mode_tag_map.get(mode)
        if mode_tag and mode_tag not in merged:
            merged.append(mode_tag)
        return merged

    def _matched_section_snippets(
        self,
        record: Note | PaperCard,
        matched_sections: list[str],
        *,
        snippet_chars: int,
    ) -> list[dict[str, str]]:
        snippets: list[dict[str, str]] = []
        for section_name, content in self._section_pairs_for_record(record):
            if section_name not in matched_sections:
                continue
            trimmed = self._truncate_snippet(content, snippet_chars)
            if not trimmed:
                continue
            snippets.append({"section": section_name, "snippet": trimmed})
        return snippets

    def _section_pairs_for_record(self, record: Note | PaperCard) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = [("Title", record.title.strip())]
        if isinstance(record, Note):
            pairs.append(("Content", record.sections.content.strip()))
            return [(name, content) for name, content in pairs if content]
        if record.authors:
            pairs.append(("Authors", ", ".join(record.authors)))
        if record.year is not None:
            pairs.append(("Year", str(record.year)))
        if record.source.strip():
            pairs.append(("Source", record.source.strip()))
        if record.url.strip():
            pairs.append(("URL", record.url.strip()))
        for field_name, section_label in PAPER_CARD_SECTION_LABELS.items():
            content = getattr(record.sections, field_name).strip()
            if content:
                pairs.append((section_label, content))
        return [(name, content) for name, content in pairs if content]

    def _truncate_snippet(self, content: str, snippet_chars: int) -> str:
        trimmed = " ".join(content.split())
        if len(trimmed) <= snippet_chars:
            return trimmed
        return trimmed[: snippet_chars - 3] + "..."

    def _query_terms(self, query: str) -> set[str]:
        terms = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) >= 3}
        return {self._normalize_term(term) for term in terms if self._normalize_term(term)}

    def _overlap_terms(self, *, query_terms: set[str], text_parts: list[str]) -> set[str]:
        haystack_terms: set[str] = set()
        for part in text_parts:
            for token in re.findall(r"[a-z0-9]+", part.lower()):
                if len(token) < 3:
                    continue
                normalized = self._normalize_term(token)
                if normalized:
                    haystack_terms.add(normalized)
        return query_terms & haystack_terms

    def _normalize_term(self, token: str) -> str:
        if len(token) > 5 and token.endswith("ing"):
            return token[:-3]
        if len(token) > 4 and token.endswith("ed"):
            return token[:-2]
        if len(token) > 4 and token.endswith("es"):
            return token[:-2]
        if len(token) > 3 and token.endswith("s"):
            return token[:-1]
        return token

    def _age_in_days(self, value: str) -> float | None:
        candidate = value.strip()
        if not candidate:
            return None
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() / 86400.0)

    def _apply_evidence_budget(
        self,
        evidence: list[dict[str, object]],
        *,
        max_total_chars: int,
    ) -> list[dict[str, object]]:
        remaining = max_total_chars
        budgeted: list[dict[str, object]] = []
        for candidate in evidence:
            primary = str(candidate.get("primary_snippet", ""))
            if not primary:
                continue
            if len(primary) > remaining and not budgeted:
                candidate = {**candidate, "primary_snippet": primary[: max(0, remaining - 3)] + "..."}
                budgeted.append(candidate)
                break
            if len(primary) > remaining:
                break

            section_snippets = []
            used = len(primary)
            for section in candidate.get("section_snippets", []):
                if not isinstance(section, dict):
                    continue
                snippet = str(section.get("snippet", ""))
                if not snippet:
                    continue
                additional = len(snippet)
                if used + additional > remaining:
                    break
                section_snippets.append(section)
                used += additional

            next_candidate = dict(candidate)
            next_candidate["section_snippets"] = section_snippets
            budgeted.append(next_candidate)
            remaining -= used
            if remaining <= 0:
                break
        return budgeted

    def _evidence_char_count(self, evidence: list[dict[str, object]]) -> int:
        total = 0
        for item in evidence:
            total += len(str(item.get("primary_snippet", "")))
            for section in item.get("section_snippets", []):
                if isinstance(section, dict):
                    total += len(str(section.get("snippet", "")))
        return total
