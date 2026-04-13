from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shardmind.cloud.main import CloudStore
from shardmind.cloud.mcp import CloudMCPTools


class CloudMCPToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store_path = Path(self.tempdir.name) / "cloud-store.json"
        self.store = CloudStore(self.store_path)
        self.store.write_bundle(
            {
                "account_email": "livia@example.com",
                "sync_scope": "selected-projects",
            },
            [
                {
                    "id": "note-1",
                    "type": "note",
                    "path": "notes/projects/shardmind.md",
                    "note_title": "ShardMind",
                    "wikilink": "shardmind",
                    "frontmatter": {"tags": ["memory", "startup"]},
                    "sections": {"content": "memory systems and startup notes"},
                },
                {
                    "id": "paper-1",
                    "type": "paper-card",
                    "path": "library/papers/ml/paper.md",
                    "paper_title": "Memory Paper",
                    "wikilink": "memory-paper",
                    "frontmatter": {"tags": ["memory", "ml"]},
                    "sections": {"summary": "retrieval memory systems"},
                },
            ],
        )
        self.tools = CloudMCPTools(cloud_store=self.store, account_email="livia@example.com")

    def test_search_fetch_and_list_tools_use_cloud_store(self) -> None:
        searched = self.tools.search(query="memory", top_k=5)
        self.assertTrue(searched["ok"])
        self.assertEqual(len(searched["result"]["results"]), 2)

        fetched = self.tools.fetch(id="note-1")
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["note_title"], "ShardMind")

        listed = self.tools.list_objects(limit=10)
        self.assertTrue(listed["ok"])
        self.assertEqual(len(listed["result"]["objects"]), 2)

        tags = self.tools.list_tags(limit=10)
        self.assertTrue(tags["ok"])
        self.assertEqual(tags["result"]["tags"], ["memory", "ml", "startup"])

    def test_search_respects_path_scope(self) -> None:
        searched = self.tools.search(query="memory", path_scope="library/papers", top_k=5)
        self.assertTrue(searched["ok"])
        self.assertEqual(searched["result"]["results"][0]["id"], "paper-1")
