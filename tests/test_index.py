from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shardmind.bootstrap import build_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class IndexServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.env = patch.dict(
            "os.environ",
            {
                "SHARDMIND_VAULT_PATH": str(self.root / "vault"),
                "SHARDMIND_SQLITE_PATH": str(self.root / "var" / "shardmind.sqlite3"),
                "SHARDMIND_SHARED_PATH": str(PROJECT_ROOT / "shared"),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.runtime = build_runtime()

    def test_reindex_and_search_note(self) -> None:
        note, path = self.runtime.vault.create_note(
            title="Memory Architecture Idea",
            content="Typed long-term memory for research agents",
            tags=["memory"],
        )
        self.runtime.index.reindex_note(note, path)

        results = self.runtime.index.search("memory")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, note.id)
        self.assertIn("memory", results[0].snippet.lower())

    def test_list_objects_orders_by_recent_update(self) -> None:
        first, first_path = self.runtime.vault.create_note(title="First", content="alpha")
        self.runtime.index.reindex_note(first, first_path)
        second, second_path = self.runtime.vault.create_note(title="Second", content="beta")
        self.runtime.index.reindex_note(second, second_path)

        objects = self.runtime.index.list_objects(object_type="note", limit=10)
        self.assertEqual(objects[0]["id"], second.id)
        self.assertEqual(objects[1]["id"], first.id)

    def test_reindex_and_search_paper_card_sections(self) -> None:
        paper_card, path = self.runtime.vault.create_paper_card(
            title="Memory Systems for Research Agents",
            source_text="abstract",
            tags=["memory", "agents"],
        )
        paper_card, path = self.runtime.vault.update_paper_card_sections(
            paper_card.id,
            sections={"llm_summary": "Typed long-term memory for research agents"},
            mode="fill-empty",
        )
        self.runtime.index.reindex_object(paper_card, path)

        results = self.runtime.index.search("memory", object_types=["paper-card"], tags=["memory"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, paper_card.id)
        self.assertIn("LLM summary", results[0].matched_sections)

    def test_search_collapses_mixed_object_results(self) -> None:
        note, note_path = self.runtime.vault.create_note(
            title="Memory note",
            content="Memory systems notes",
            tags=["memory"],
        )
        self.runtime.index.reindex_object(note, note_path)
        paper_card, paper_path = self.runtime.vault.create_paper_card(
            title="Memory paper",
            source_text="memory substrate",
            tags=["memory"],
        )
        paper_card, paper_path = self.runtime.vault.update_paper_card_sections(
            paper_card.id,
            sections={
                "llm_summary": "memory summary",
                "why_relevant": "memory relevance",
            },
            mode="fill-empty",
        )
        self.runtime.index.reindex_object(paper_card, paper_path)

        results = self.runtime.index.search("memory", top_k=5)
        self.assertEqual({result.type for result in results}, {"note", "paper-card"})
