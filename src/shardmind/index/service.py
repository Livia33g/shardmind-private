"""SQLite-backed typed-object index."""

from __future__ import annotations

import sqlite3
import threading
import time
import re
from pathlib import Path

from shardmind.index.embeddings import content_hash, create_embedding_backend
from shardmind.models import Note, ObjectRecord, PaperCard, SearchResult
from shardmind.paper_cards import PAPER_CARD_SECTION_LABELS
from shardmind.vault.ids import slugify


class IndexService:
    def __init__(self, sqlite_path: Path, embedding_backend: str = "stub"):
        self.sqlite_path = sqlite_path
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_backend = create_embedding_backend(embedding_backend)
        self.connection: sqlite3.Connection | None = self._connect()
        self._write_lock = threading.RLock()
        self._worker_stop = threading.Event()
        self._worker_wakeup = threading.Event()
        self._worker_connection: sqlite3.Connection | None = None
        self._worker_thread: threading.Thread | None = None
        self._initialize()
        self._start_embedding_worker()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def close(self) -> None:
        self._worker_stop.set()
        self._worker_wakeup.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None
        if self._worker_connection is not None:
            self._worker_connection.close()
            self._worker_connection = None
        if self.connection is None:
            return
        self.connection.close()
        self.connection = None

    def _initialize(self) -> None:
        connection = self._require_connection()
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    normalized_title TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    citekey TEXT NOT NULL DEFAULT ''
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
                    chunk_id INTEGER,
                    section_name TEXT NOT NULL,
                    vector BLOB,
                    content_hash TEXT NOT NULL DEFAULT '',
                    embedding_model TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    document_id UNINDEXED,
                    section_name,
                    content
                );

                CREATE TABLE IF NOT EXISTS embedding_jobs (
                    chunk_id INTEGER PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    section_name TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                """
            )
            self._ensure_document_columns()
            self._ensure_embedding_columns()
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS documents_paper_citekey_unique
                ON documents(citekey)
                WHERE type = 'paper-card' AND citekey != ''
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS embeddings_document_id_idx ON embeddings(document_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS embeddings_chunk_id_idx ON embeddings(chunk_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS embedding_jobs_document_id_idx ON embedding_jobs(document_id)"
            )

    def _ensure_document_columns(self) -> None:
        connection = self._require_connection()
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        missing = {
            "normalized_title": (
                "ALTER TABLE documents ADD COLUMN normalized_title TEXT NOT NULL DEFAULT ''"
            ),
            "url": "ALTER TABLE documents ADD COLUMN url TEXT NOT NULL DEFAULT ''",
            "citekey": "ALTER TABLE documents ADD COLUMN citekey TEXT NOT NULL DEFAULT ''",
        }
        for column, statement in missing.items():
            if column not in columns:
                connection.execute(statement)

    def _ensure_embedding_columns(self) -> None:
        connection = self._require_connection()
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(embeddings)").fetchall()
        }
        missing = {
            "chunk_id": "ALTER TABLE embeddings ADD COLUMN chunk_id INTEGER",
            "content_hash": "ALTER TABLE embeddings ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''",
            "embedding_model": (
                "ALTER TABLE embeddings ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''"
            ),
            "updated_at": "ALTER TABLE embeddings ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
        }
        for column, statement in missing.items():
            if column not in columns:
                connection.execute(statement)

    def reindex_note(self, note: Note, path: str) -> None:
        self.reindex_object(note, path)

    def reindex_object(self, record: ObjectRecord, path: str) -> None:
        tags = list(record.tags)
        chunks = self._chunks_for_object(record)
        metadata = self._document_metadata(record)
        connection = self._require_connection()
        with self._write_lock, connection:
            self._upsert_object(connection, record, path, tags, chunks, metadata)
        self._worker_wakeup.set()

    def rebuild(self, records: list[tuple[ObjectRecord, str]]) -> None:
        connection = self._require_connection()
        with self._write_lock, connection:
            connection.execute("DELETE FROM chunks_fts")
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM embedding_jobs")
            for record, path in records:
                tags = list(record.tags)
                chunks = self._chunks_for_object(record)
                metadata = self._document_metadata(record)
                self._upsert_object(connection, record, path, tags, chunks, metadata)
        self._worker_wakeup.set()

    def remove_object(self, document_id: str) -> None:
        connection = self._require_connection()
        with self._write_lock, connection:
            self._delete_object_rows(connection, document_id)
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def get_path(self, document_id: str) -> str | None:
        row = (
            self._require_connection()
            .execute(
                "SELECT path FROM documents WHERE id = ?",
                (document_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return str(row["path"])

    def find_duplicate_paper_card(
        self,
        *,
        normalized_title: str = "",
        url: str = "",
        citekey: str = "",
    ) -> str | None:
        clauses: list[str] = []
        params: list[object] = []
        if normalized_title:
            clauses.append("normalized_title = ?")
            params.append(normalized_title)
        if url:
            clauses.append("url = ?")
            params.append(url)
        if citekey:
            clauses.append("citekey = ?")
            params.append(citekey)
        if not clauses:
            return None
        row = (
            self._require_connection()
            .execute(
                f"""
            SELECT id
            FROM documents
            WHERE type = 'paper-card' AND ({" OR ".join(clauses)})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
                params,
            )
            .fetchone()
        )
        if row is None:
            return None
        return str(row["id"])

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
        rows = self._require_connection().execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_tags(
        self,
        object_type: str | None = None,
        path_scope: str | None = None,
        limit: int = 200,
    ) -> list[str]:
        clauses: list[str] = []
        params: list[object] = []
        if object_type:
            clauses.append("d.type = ?")
            params.append(object_type)
        if path_scope:
            clauses.append("d.path LIKE ?")
            params.append(f"{path_scope}%")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT DISTINCT t.tag AS tag
            FROM tags t
            JOIN documents d ON d.id = t.document_id
            {where_clause}
            ORDER BY t.tag COLLATE NOCASE
            LIMIT ?
        """
        params.append(limit)
        rows = self._require_connection().execute(query, params).fetchall()
        return [str(row["tag"]) for row in rows]

    def list_tag_references(
        self,
        object_type: str | None = None,
        path_scope: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if object_type:
            clauses.append("d.type = ?")
            params.append(object_type)
        if path_scope:
            clauses.append("d.path LIKE ?")
            params.append(f"{path_scope}%")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT t.tag AS tag, d.id AS id, d.path AS path
            FROM tags t
            JOIN documents d ON d.id = t.document_id
            {where_clause}
            ORDER BY t.tag COLLATE NOCASE, d.updated_at DESC
        """
        rows = self._require_connection().execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def search(
        self,
        query: str,
        object_types: list[str] | None = None,
        path_scope: str | None = None,
        top_k: int = 10,
        tags: list[str] | None = None,
    ) -> list[SearchResult]:
        lexical_results = self._lexical_search(
            query=query,
            object_types=object_types,
            path_scope=path_scope,
            top_k=top_k,
            tags=tags,
        )
        vector_results = self._vector_search(
            query=query,
            object_types=object_types,
            path_scope=path_scope,
            top_k=top_k,
            tags=tags,
        )
        return self._merge_search_results(lexical_results, vector_results, top_k)

    def _lexical_search(
        self,
        *,
        query: str,
        object_types: list[str] | None = None,
        path_scope: str | None = None,
        top_k: int = 10,
        tags: list[str] | None = None,
    ) -> list[SearchResult]:
        fts_query = self._fts_query(query)
        if not fts_query:
            return []
        filters = []
        params: list[object] = [fts_query]
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
                f"WHERE {alias}.document_id = d.id "
                f"AND LOWER({alias}.tag) = LOWER(?)"
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
        rows = self._require_connection().execute(sql, params).fetchall()
        return self._collapse_results(rows, top_k)

    def _vector_search(
        self,
        *,
        query: str,
        object_types: list[str] | None = None,
        path_scope: str | None = None,
        top_k: int = 10,
        tags: list[str] | None = None,
    ) -> list[SearchResult]:
        if not self.embedding_backend.enabled:
            return []
        query_vector = self.embedding_backend.embed_text(query)
        if query_vector is None:
            return []

        filters = []
        params: list[object] = []
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
                f"WHERE {alias}.document_id = d.id "
                f"AND LOWER({alias}.tag) = LOWER(?)"
                ")"
            )
            params.append(tag)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        sql = f"""
            SELECT
                d.id,
                d.type,
                d.title,
                d.path,
                d.tags,
                c.section_name AS section_name,
                c.content AS content,
                e.vector AS vector
            FROM embeddings e
            JOIN documents d ON d.id = e.document_id
            LEFT JOIN chunks c ON c.chunk_id = e.chunk_id
            {where_clause}
        """
        rows = self._require_connection().execute(sql, params).fetchall()
        scored_rows: list[dict[str, object]] = []
        for row in rows:
            vector = self.embedding_backend.deserialize(row["vector"])
            if vector is None:
                continue
            similarity = self.embedding_backend.similarity(query_vector, vector)
            if similarity <= 0:
                continue
            content = str(row["content"] or "")
            scored_rows.append(
                {
                    "id": row["id"],
                    "type": row["type"],
                    "title": row["title"],
                    "path": row["path"],
                    "tags": row["tags"],
                    "section_name": row["section_name"] or "Content",
                    "content": content,
                    "snippet": self._snippet_from_content(content),
                    "similarity": similarity,
                }
            )
        scored_rows.sort(key=lambda candidate: float(candidate["similarity"]), reverse=True)
        return self._collapse_vector_results(scored_rows[: max(top_k * 10, 25)], top_k)

    def _delete_object_rows(self, connection: sqlite3.Connection, document_id: str) -> None:
        connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM tags WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM embeddings WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM embedding_jobs WHERE document_id = ?", (document_id,))

    def _upsert_object(
        self,
        connection: sqlite3.Connection,
        record: ObjectRecord,
        path: str,
        tags: list[str],
        chunks: list[tuple[str, str]],
        metadata: dict[str, str],
    ) -> None:
        connection.execute(
            """
            INSERT INTO documents(
                id, type, title, path, tags, updated_at, normalized_title, url, citekey
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                title = excluded.title,
                path = excluded.path,
                tags = excluded.tags,
                updated_at = excluded.updated_at,
                normalized_title = excluded.normalized_title,
                url = excluded.url,
                citekey = excluded.citekey
            """,
            (
                record.id,
                record.type,
                record.title,
                path,
                self._encode_tags(tags),
                record.updated_at,
                metadata["normalized_title"],
                metadata["url"],
                metadata["citekey"],
            ),
        )
        existing_chunks = {
            (str(row["section_name"]), str(row["content"])): int(row["chunk_id"])
            for row in connection.execute(
                """
                SELECT chunk_id, section_name, content
                FROM chunks
                WHERE document_id = ?
                """,
                (record.id,),
            ).fetchall()
        }
        desired_pairs = {(section_name, content) for section_name, content in chunks}
        connection.execute("DELETE FROM tags WHERE document_id = ?", (record.id,))
        connection.execute("DELETE FROM chunks_fts WHERE document_id = ?", (record.id,))
        for (section_name, content), chunk_id in existing_chunks.items():
            if (section_name, content) in desired_pairs:
                continue
            connection.execute("DELETE FROM embeddings WHERE chunk_id = ?", (chunk_id,))
            connection.execute("DELETE FROM embedding_jobs WHERE chunk_id = ?", (chunk_id,))
            connection.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
        for tag in tags:
            connection.execute(
                "INSERT INTO tags(document_id, tag) VALUES (?, ?)",
                (record.id, tag),
            )
        for section_name, content in chunks:
            chunk_id = existing_chunks.get((section_name, content))
            if chunk_id is None:
                chunk_cursor = connection.execute(
                    "INSERT INTO chunks(document_id, section_name, content) VALUES (?, ?, ?)",
                    (record.id, section_name, content),
                )
                chunk_id = int(chunk_cursor.lastrowid)
                self._enqueue_embedding_job(
                    connection=connection,
                    document_id=record.id,
                    chunk_id=chunk_id,
                    section_name=section_name,
                    content=content,
                )
            else:
                self._refresh_embedding_job_if_needed(
                    connection=connection,
                    document_id=record.id,
                    chunk_id=chunk_id,
                    section_name=section_name,
                    content=content,
                )
            connection.execute(
                "INSERT INTO chunks_fts(document_id, section_name, content) VALUES (?, ?, ?)",
                (record.id, section_name, content),
            )

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("IndexService connection is closed.")
        return self.connection

    def _document_metadata(self, record: ObjectRecord) -> dict[str, str]:
        if isinstance(record, PaperCard):
            return {
                "normalized_title": slugify(record.title),
                "url": record.url,
                "citekey": record.citekey,
            }
        return {"normalized_title": "", "url": "", "citekey": ""}

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

    def _collapse_vector_results(
        self,
        rows: list[dict[str, object]],
        top_k: int,
    ) -> list[SearchResult]:
        collapsed: dict[str, SearchResult] = {}
        best_similarities: dict[str, float] = {}
        for row in rows:
            document_id = str(row["id"])
            similarity = float(row["similarity"])
            if document_id not in collapsed:
                collapsed[document_id] = SearchResult(
                    id=document_id,
                    type=str(row["type"]),
                    title=str(row["title"]),
                    path=str(row["path"]),
                    score=similarity,
                    matched_sections=[str(row["section_name"])],
                    snippet=str(row["snippet"]),
                    tags=self._decode_tags(str(row["tags"])),
                )
                best_similarities[document_id] = similarity
                continue
            result = collapsed[document_id]
            section_name = str(row["section_name"])
            if section_name not in result.matched_sections:
                result.matched_sections.append(section_name)
            if similarity > best_similarities[document_id]:
                result.score = similarity
                result.snippet = str(row["snippet"])
                best_similarities[document_id] = similarity
        ordered_ids = sorted(best_similarities, key=best_similarities.get, reverse=True)
        return [collapsed[document_id] for document_id in ordered_ids[:top_k]]

    def _merge_search_results(
        self,
        lexical_results: list[SearchResult],
        vector_results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        if not vector_results:
            return lexical_results[:top_k]
        if not lexical_results:
            return vector_results[:top_k]

        fused_scores: dict[str, float] = {}
        merged: dict[str, SearchResult] = {}
        best_component_scores: dict[str, float] = {}

        for weight, results in ((1.0, lexical_results), (0.85, vector_results)):
            for rank, result in enumerate(results, start=1):
                fused_scores[result.id] = fused_scores.get(result.id, 0.0) + weight / (60 + rank)
                current = merged.get(result.id)
                if current is None:
                    merged[result.id] = SearchResult(
                        id=result.id,
                        type=result.type,
                        title=result.title,
                        path=result.path,
                        score=result.score,
                        matched_sections=list(result.matched_sections),
                        snippet=result.snippet,
                        tags=list(result.tags),
                    )
                    best_component_scores[result.id] = result.score
                    continue
                for section_name in result.matched_sections:
                    if section_name not in current.matched_sections:
                        current.matched_sections.append(section_name)
                if result.score > best_component_scores[result.id]:
                    current.snippet = result.snippet
                    best_component_scores[result.id] = result.score

        ordered_ids = sorted(
            fused_scores,
            key=lambda document_id: (fused_scores[document_id], best_component_scores[document_id]),
            reverse=True,
        )
        merged_results: list[SearchResult] = []
        for document_id in ordered_ids[:top_k]:
            result = merged[document_id]
            result.score = fused_scores[document_id]
            merged_results.append(result)
        return merged_results

    def _store_embedding(
        self,
        *,
        connection: sqlite3.Connection,
        document_id: str,
        chunk_id: int,
        section_name: str,
        content: str,
        updated_at: str,
    ) -> None:
        vector = self.embedding_backend.embed_text(content)
        if vector is None:
            return
        connection.execute("DELETE FROM embeddings WHERE chunk_id = ?", (chunk_id,))
        connection.execute(
            """
            INSERT INTO embeddings(
                document_id,
                chunk_id,
                section_name,
                vector,
                content_hash,
                embedding_model,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                chunk_id,
                section_name,
                self.embedding_backend.serialize(vector),
                content_hash(content),
                self.embedding_backend.name,
                updated_at,
            ),
        )

    def _encode_tags(self, tags: list[str]) -> str:
        if not tags:
            return ""
        return "|" + "|".join(tags) + "|"

    def _decode_tags(self, encoded: str) -> list[str]:
        return [tag for tag in encoded.strip("|").split("|") if tag]

    def _score(self, rank: float) -> float:
        return 1.0 / (1.0 + abs(rank))

    def _snippet_from_content(self, content: str, width: int = 220) -> str:
        trimmed = " ".join(content.split())
        if len(trimmed) <= width:
            return trimmed
        return trimmed[: width - 3] + "..."

    def _fts_query(self, query: str) -> str:
        terms = [token for token in re.findall(r"[a-z0-9]+", query.lower()) if token]
        if not terms:
            return ""
        unique_terms = list(dict.fromkeys(terms))
        return " OR ".join(f'"{term}"' for term in unique_terms)

    def process_pending_embeddings(self, batch_size: int = 32) -> int:
        if not self.embedding_backend.enabled:
            return 0
        connection = self._worker_connection or self._require_connection()
        jobs = connection.execute(
            """
            SELECT chunk_id, document_id, section_name, content_hash
            FROM embedding_jobs
            ORDER BY queued_at
            LIMIT ?
            """,
            (batch_size,),
        ).fetchall()
        processed = 0
        with self._write_lock, connection:
            for job in jobs:
                chunk = connection.execute(
                    """
                    SELECT c.content AS content, d.updated_at AS updated_at
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.chunk_id = ?
                    """,
                    (job["chunk_id"],),
                ).fetchone()
                if chunk is None:
                    connection.execute(
                        "DELETE FROM embedding_jobs WHERE chunk_id = ?",
                        (job["chunk_id"],),
                    )
                    continue
                content = str(chunk["content"])
                current_hash = content_hash(content)
                if current_hash != str(job["content_hash"]):
                    connection.execute(
                        """
                        UPDATE embedding_jobs
                        SET content_hash = ?, queued_at = CURRENT_TIMESTAMP
                        WHERE chunk_id = ?
                        """,
                        (current_hash, job["chunk_id"]),
                    )
                    continue
                self._store_embedding(
                    connection=connection,
                    document_id=str(job["document_id"]),
                    chunk_id=int(job["chunk_id"]),
                    section_name=str(job["section_name"]),
                    content=content,
                    updated_at=str(chunk["updated_at"]),
                )
                connection.execute(
                    "DELETE FROM embedding_jobs WHERE chunk_id = ?",
                    (job["chunk_id"],),
                )
                processed += 1
        return processed

    def wait_for_embeddings(self, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = self.pending_embedding_jobs()
            if remaining == 0:
                return
            processed = self.process_pending_embeddings(batch_size=remaining)
            if processed == 0:
                time.sleep(0.02)
        if self.pending_embedding_jobs() != 0:
            raise TimeoutError("Timed out waiting for background embedding jobs to finish.")

    def pending_embedding_jobs(self) -> int:
        return int(
            self._require_connection()
            .execute("SELECT COUNT(*) FROM embedding_jobs")
            .fetchone()[0]
        )

    def _start_embedding_worker(self) -> None:
        if not self.embedding_backend.enabled:
            return
        self._worker_connection = self._connect()
        self._worker_thread = threading.Thread(
            target=self._embedding_worker_loop,
            name="shardmind-embedding-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _embedding_worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            self._worker_wakeup.wait(timeout=0.5)
            self._worker_wakeup.clear()
            while not self._worker_stop.is_set():
                processed = self.process_pending_embeddings(batch_size=32)
                if processed == 0:
                    break

    def _enqueue_embedding_job(
        self,
        *,
        connection: sqlite3.Connection,
        document_id: str,
        chunk_id: int,
        section_name: str,
        content: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO embedding_jobs(chunk_id, document_id, section_name, content_hash, queued_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chunk_id) DO UPDATE SET
                document_id = excluded.document_id,
                section_name = excluded.section_name,
                content_hash = excluded.content_hash,
                queued_at = CURRENT_TIMESTAMP
            """,
            (
                chunk_id,
                document_id,
                section_name,
                content_hash(content),
            ),
        )

    def _refresh_embedding_job_if_needed(
        self,
        *,
        connection: sqlite3.Connection,
        document_id: str,
        chunk_id: int,
        section_name: str,
        content: str,
    ) -> None:
        desired_hash = content_hash(content)
        row = connection.execute(
            """
            SELECT content_hash, embedding_model
            FROM embeddings
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchone()
        if row is None:
            self._enqueue_embedding_job(
                connection=connection,
                document_id=document_id,
                chunk_id=chunk_id,
                section_name=section_name,
                content=content,
            )
            return
        if str(row["content_hash"]) != desired_hash or str(row["embedding_model"]) != self.embedding_backend.name:
            self._enqueue_embedding_job(
                connection=connection,
                document_id=document_id,
                chunk_id=chunk_id,
                section_name=section_name,
                content=content,
            )
