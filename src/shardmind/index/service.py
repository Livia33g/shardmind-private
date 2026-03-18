"""SQLite-backed note index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from shardmind.models import Note, SearchResult


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

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    document_id UNINDEXED,
                    section_name,
                    content
                );
                """
            )

    def reindex_note(self, note: Note, path: str) -> None:
        tags = ",".join(note.tags)
        content = note.sections.content.strip()
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (note.id,))
            connection.execute("DELETE FROM chunks_fts WHERE document_id = ?", (note.id,))
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
                (note.id, note.type, note.title, path, tags, note.updated_at),
            )
            connection.execute(
                "INSERT INTO chunks(document_id, section_name, content) VALUES (?, ?, ?)",
                (note.id, "Content", content),
            )
            connection.execute(
                "INSERT INTO chunks_fts(document_id, section_name, content) VALUES (?, ?, ?)",
                (note.id, "Content", content),
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
        where_clause = f"AND {' AND '.join(filters)}" if filters else ""
        sql = f"""
            SELECT
                d.id,
                d.type,
                d.title,
                d.path,
                d.tags,
                f.section_name,
                snippet(chunks_fts, 2, '', '', '...', 24) AS snippet,
                bm25(chunks_fts) AS rank
            FROM chunks_fts f
            JOIN documents d ON d.id = f.document_id
            WHERE chunks_fts MATCH ?
            {where_clause}
            ORDER BY rank
            LIMIT ?
        """
        params.append(top_k)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            SearchResult(
                id=row["id"],
                type=row["type"],
                title=row["title"],
                path=row["path"],
                score=1.0 / (1.0 + abs(row["rank"])),
                matched_sections=[row["section_name"]],
                snippet=row["snippet"],
                tags=[tag for tag in row["tags"].split(",") if tag],
            )
            for row in rows
        ]
