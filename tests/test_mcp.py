from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shardmind.bootstrap import build_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MCPToolsTest(unittest.TestCase):
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

    def test_create_and_get_note_via_mcp_envelope(self) -> None:
        created = self.runtime.tools.create_note(
            {
                "title": "Memory Architecture Idea",
                "content": "Typed long-term memory",
                "destination": "inbox",
                "tags": ["memory"],
            }
        )
        self.assertTrue(created["ok"])
        note_id = created["result"]["id"]

        fetched = self.runtime.tools.get_object({"id": note_id})
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["id"], note_id)
        self.assertEqual(fetched["result"]["sections"]["content"], "Typed long-term memory")

    def test_append_and_search_note_via_mcp_envelope(self) -> None:
        created = self.runtime.tools.create_note(
            {
                "title": "Search Target",
                "content": "Original body",
            }
        )
        note_id = created["result"]["id"]
        appended = self.runtime.tools.append_to_note({"id": note_id, "content": "Semantic memory"})
        self.assertTrue(appended["ok"])

        searched = self.runtime.tools.search(
            {"query": "memory", "object_types": ["note"], "top_k": 5}
        )
        self.assertTrue(searched["ok"])
        self.assertEqual(searched["result"]["results"][0]["id"], note_id)

    def test_invalid_payload_returns_structured_error(self) -> None:
        response = self.runtime.tools.invoke("knowledge.create_note", {"content": ""})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_INPUT")

    def test_claude_safe_tool_aliases_resolve(self) -> None:
        response = self.runtime.tools.invoke(
            "knowledge_create_note",
            {"title": "Alias note", "content": "hello from Claude"},
        )
        self.assertTrue(response["ok"])
        note_id = response["result"]["id"]

        fetched = self.runtime.tools.invoke("knowledge_get_object", {"id": note_id})
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["id"], note_id)
