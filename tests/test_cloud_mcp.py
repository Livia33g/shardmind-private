from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from shardmind.cloud.main import CloudStore
from shardmind.cloud.mcp import CloudMCPTools, build_cloud_mcp_server


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

    def test_build_cloud_mcp_server_can_resolve_account_from_link_token(self) -> None:
        linked = self.store.issue_link_token("livia@example.com", label="chatgpt")
        server = build_cloud_mcp_server(
            store_path=self.store_path,
            link_token=linked["link_token"],
            host="127.0.0.1",
            port=8899,
        )
        tool_manager = getattr(server, "_tool_manager")
        search_tool = tool_manager.get_tool("search")
        self.assertIsNotNone(search_tool)

    def test_unified_cloud_mcp_server_exposes_bridge_routes(self) -> None:
        server = build_cloud_mcp_server(
            store_path=self.store_path,
            account_email="livia@example.com",
            bearer_token="bridge-secret",
            host="127.0.0.1",
            port=8898,
        )
        app = server.streamable_http_app()
        with TestClient(app) as client:
            health = client.get("/health", headers={"Authorization": "Bearer bridge-secret"})
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["ok"])

            session = client.post(
                "/v1/account/session",
                json={"account_email": "livia@example.com"},
                headers={"Authorization": "Bearer bridge-secret"},
            )
            self.assertEqual(session.status_code, 200)
            session_token = session.json()["result"]["session_token"]

            upload = client.post(
                "/v1/sync/bundle",
                json={
                    "manifest": {
                        "account_email": "livia@example.com",
                        "sync_scope": "selected-projects",
                    },
                    "documents": [
                        {
                            "id": "note-sync-1",
                            "type": "note",
                            "path": "notes/projects/synced.md",
                            "note_title": "Synced Note",
                            "wikilink": "synced-note",
                            "frontmatter": {"tags": ["memory", "sync"]},
                            "sections": {"content": "synced memory content"},
                        }
                    ],
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(upload.status_code, 200)

            searched = client.post(
                "/v1/search",
                json={"query": "synced memory", "top_k": 5},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(searched.status_code, 200)
            self.assertEqual(searched.json()["result"]["results"][0]["id"], "note-sync-1")
