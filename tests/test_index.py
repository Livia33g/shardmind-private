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
