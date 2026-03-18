"""SQLite-backed typed-object index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from shardmind.models import Note, ObjectRecord, SearchResult

PAPER_CARD_SECTION_LABELS = {
    "source_notes": "Source notes",
    "llm_summary": "LLM summary",
    "main_claims": "Main claims",
    "why_relevant": "Why relevant",
    "limitations": "Limitations",
    "user_notes": "User notes",
    "related_links": "Related links",
}


class IndexService:
    def __init__(self, sqlite_path: Path):
        self.sqlite_path = sqlite_path
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    section_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tags (
                    document_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS embeddings (
                    document_id TEXT NOT NULL,
                    section_name TEXT NOT NULL,
                    vector BLOB,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    document_id UNINDEXED,
                    section_name,
                    content
                );
                """
            )

    def reindex_note(self, note: Note, path: str) -> None:
        self.reindex_object(note, path)

    def reindex_object(self, record: ObjectRecord, path: str) -> None:
        tags = list(record.tags)
        chunks = self._chunks_for_object(record)
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (record.id,))
            connection.execute("DELETE FROM chunks_fts WHERE document_id = ?", (record.id,))
            connection.execute("DELETE FROM tags WHERE document_id = ?", (record.id,))
            connection.execute("DELETE FROM embeddings WHERE document_id = ?", (record.id,))
            connection.execute(
                """
                INSERT INTO documents(id, type, title, path, tags, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    title = excluded.title,
                    path = excluded.path,
                    tags = excluded.tags,
                    updated_at = excluded.updated_at
                """,
                (
                    record.id,
                    record.type,
                    record.title,
                    path,
                    self._encode_tags(tags),
                    record.updated_at,
                ),
            )
            for tag in tags:
                connection.execute(
                    "INSERT INTO tags(document_id, tag) VALUES (?, ?)",
                    (record.id, tag),
                )
            for section_name, content in chunks:
                connection.execute(
                    "INSERT INTO chunks(document_id, section_name, content) VALUES (?, ?, ?)",
                    (record.id, section_name, content),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(document_id, section_name, content) VALUES (?, ?, ?)",
                    (record.id, section_name, content),
                )

    def list_objects(
        self,
        object_type: str | None = None,
        path_scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        clauses = []
        params: list[object] = []
        if object_type:
            clauses.append("type = ?")
            params.append(object_type)
        if path_scope:
            clauses.append("path LIKE ?")
            params.append(f"{path_scope}%")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT id, type, title, path, updated_at
            FROM documents
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def search(
        self,
        query: str,
        object_types: list[str] | None = None,
        path_scope: str | None = None,
        top_k: int = 10,
        tags: list[str] | None = None,
    ) -> list[SearchResult]:
        filters = []
        params: list[object] = [query]
        if object_types:
            placeholders = ", ".join(["?"] * len(object_types))
            filters.append(f"d.type IN ({placeholders})")
            params.extend(object_types)
        if path_scope:
            filters.append("d.path LIKE ?")
            params.append(f"{path_scope}%")
        for index, tag in enumerate(tags or []):
            alias = f"t{index}"
            filters.append(
                "EXISTS ("
                f"SELECT 1 FROM tags {alias} "
                f"WHERE {alias}.document_id = d.id AND {alias}.tag = ?"
                ")"
            )
            params.append(tag)
        where_clause = f"AND {' AND '.join(filters)}" if filters else ""
        sql = f"""
            SELECT
                d.id,
                d.type,
                d.title,
                d.path,
                d.tags,
                chunks_fts.section_name AS section_name,
                chunks_fts.content AS content,
                snippet(chunks_fts, 2, '', '', '...', 24) AS snippet,
                bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN documents d ON d.id = chunks_fts.document_id
            WHERE chunks_fts MATCH ?
            {where_clause}
            ORDER BY rank
            LIMIT ?
        """
        params.append(max(top_k * 10, 25))
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return self._collapse_results(rows, top_k)

    def _chunks_for_object(self, record: ObjectRecord) -> list[tuple[str, str]]:
        chunks: list[tuple[str, str]] = [("Title", record.title)]
        if isinstance(record, Note):
            if record.sections.content.strip():
                chunks.append(("Content", record.sections.content.strip()))
            return chunks
        if record.authors:
            chunks.append(("Authors", ", ".join(record.authors)))
        if record.year is not None:
            chunks.append(("Year", str(record.year)))
        if record.source.strip():
            chunks.append(("Source", record.source.strip()))
        if record.url.strip():
            chunks.append(("URL", record.url.strip()))
        for field_name, section_label in PAPER_CARD_SECTION_LABELS.items():
            content = getattr(record.sections, field_name).strip()
            if content:
                chunks.append((section_label, content))
        return chunks

    def _collapse_results(self, rows: list[sqlite3.Row], top_k: int) -> list[SearchResult]:
        collapsed: dict[str, SearchResult] = {}
        best_ranks: dict[str, float] = {}
        for row in rows:
            document_id = row["id"]
            rank = float(row["rank"])
            snippet = row["snippet"] or row["content"][:200]
            if document_id not in collapsed:
                collapsed[document_id] = SearchResult(
                    id=document_id,
                    type=row["type"],
                    title=row["title"],
                    path=row["path"],
                    score=self._score(rank),
                    matched_sections=[row["section_name"]],
                    snippet=snippet,
                    tags=self._decode_tags(row["tags"]),
                )
                best_ranks[document_id] = rank
                continue
            result = collapsed[document_id]
            if row["section_name"] not in result.matched_sections:
                result.matched_sections.append(row["section_name"])
            if rank < best_ranks[document_id]:
                result.score = self._score(rank)
                result.snippet = snippet
                best_ranks[document_id] = rank
        ordered_ids = sorted(best_ranks, key=best_ranks.get)
        return [collapsed[document_id] for document_id in ordered_ids[:top_k]]

    def _encode_tags(self, tags: list[str]) -> str:
        if not tags:
            return ""
        return "|" + "|".join(tags) + "|"

    def _decode_tags(self, encoded: str) -> list[str]:
        return [tag for tag in encoded.strip("|").split("|") if tag]

    def _score(self, rank: float) -> float:
        return 1.0 / (1.0 + abs(rank))
