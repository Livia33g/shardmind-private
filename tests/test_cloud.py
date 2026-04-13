from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from shardmind.bootstrap import build_runtime
from shardmind.cloud.main import build_cloud_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CloudBridgeTest(unittest.TestCase):
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

    def test_health_search_and_fetch_routes(self) -> None:
        runtime = build_runtime()
        created = runtime.tools.create_note(title="Cloud note", content="hello memory systems")
        self.assertTrue(created["ok"])
        note_id = created["result"]["id"]

        server, _ = self._start_server(runtime, port=8789)

        health = self._request("GET", "/health", port=8789)
        self.assertTrue(health["ok"])

        searched = self._request(
            "POST",
            "/v1/search",
            payload={"query": "memory", "top_k": 5},
            port=8789,
        )
        self.assertTrue(searched["ok"])
        self.assertEqual(searched["result"]["results"][0]["id"], note_id)

        fetched = self._request("POST", "/v1/fetch", payload={"id": note_id}, port=8789)
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["id"], note_id)
        self.assertIsNotNone(server)

    def test_sync_bundle_upload_powers_hosted_search_and_fetch(self) -> None:
        runtime = build_runtime()
        self._start_server(runtime, port=8791)

        uploaded = self._request(
            "POST",
            "/v1/sync/bundle",
            payload={
                "manifest": {
                    "account_email": "livia@example.com",
                    "sync_scope": "selected-projects",
                },
                "documents": [
                    {
                        "id": "note-cloud-1",
                        "type": "note",
                        "path": "notes/projects/cloud.md",
                        "note_title": "Cloud Synced Note",
                        "wikilink": "cloud",
                        "frontmatter": {"tags": ["memory", "cloud"]},
                        "sections": {"content": "hosted memory systems"},
                    }
                ],
            },
            port=8791,
        )
        self.assertTrue(uploaded["ok"])
        self.assertEqual(uploaded["result"]["stored_documents"], 1)

        searched = self._request(
            "POST",
            "/v1/search",
            payload={"query": "hosted memory", "top_k": 5},
            port=8791,
        )
        self.assertTrue(searched["ok"])
        self.assertEqual(searched["result"]["results"][0]["id"], "note-cloud-1")

        fetched = self._request("POST", "/v1/fetch", payload={"id": "note-cloud-1"}, port=8791)
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["note_title"], "Cloud Synced Note")

    def test_account_session_can_scope_search_and_upload(self) -> None:
        runtime = build_runtime()
        self._start_server(runtime, port=8794)

        session = self._request(
            "POST",
            "/v1/account/session",
            payload={"account_email": "livia@example.com"},
            port=8794,
        )
        self.assertTrue(session["ok"])
        session_token = session["result"]["session_token"]

        uploaded = self._request(
            "POST",
            "/v1/sync/bundle",
            payload={
                "manifest": {
                    "account_email": "livia@example.com",
                    "sync_scope": "selected-projects",
                },
                "documents": [
                    {
                        "id": "note-cloud-session",
                        "type": "note",
                        "path": "notes/projects/session.md",
                        "note_title": "Session Note",
                        "wikilink": "session-note",
                        "frontmatter": {"tags": ["session", "memory"]},
                        "sections": {"content": "session scoped memory"},
                    }
                ],
            },
            port=8794,
            token=session_token,
        )
        self.assertTrue(uploaded["ok"])

        searched = self._request(
            "POST",
            "/v1/search",
            payload={"query": "session scoped", "top_k": 5},
            port=8794,
            token=session_token,
        )
        self.assertTrue(searched["ok"])
        self.assertEqual(searched["result"]["results"][0]["id"], "note-cloud-session")

        fetched = self._request(
            "POST",
            "/v1/fetch",
            payload={"id": "note-cloud-session"},
            port=8794,
            token=session_token,
        )
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["result"]["note_title"], "Session Note")

    def test_synced_documents_are_scoped_per_account(self) -> None:
        runtime = build_runtime()
        self._start_server(runtime, port=8792)

        first_upload = self._request(
            "POST",
            "/v1/sync/bundle",
            payload={
                "manifest": {
                    "account_email": "livia@example.com",
                    "sync_scope": "selected-projects",
                },
                "documents": [
                    {
                        "id": "note-cloud-livia",
                        "type": "note",
                        "path": "notes/projects/livia.md",
                        "note_title": "Livia Note",
                        "wikilink": "livia-note",
                        "frontmatter": {"tags": ["memory"]},
                        "sections": {"content": "livia private memory"},
                    }
                ],
            },
            port=8792,
        )
        self.assertTrue(first_upload["ok"])

        second_upload = self._request(
            "POST",
            "/v1/sync/bundle",
            payload={
                "manifest": {
                    "account_email": "team@example.com",
                    "sync_scope": "selected-projects",
                },
                "documents": [
                    {
                        "id": "note-cloud-team",
                        "type": "note",
                        "path": "notes/projects/team.md",
                        "note_title": "Team Note",
                        "wikilink": "team-note",
                        "frontmatter": {"tags": ["labs"]},
                        "sections": {"content": "team research continuity"},
                    }
                ],
            },
            port=8792,
        )
        self.assertTrue(second_upload["ok"])

        livia_search = self._request(
            "POST",
            "/v1/search",
            payload={"account_email": "livia@example.com", "query": "private memory", "top_k": 5},
            port=8792,
        )
        self.assertTrue(livia_search["ok"])
        self.assertEqual(livia_search["result"]["results"][0]["id"], "note-cloud-livia")

        team_search = self._request(
            "POST",
            "/v1/search",
            payload={"account_email": "team@example.com", "query": "research continuity", "top_k": 5},
            port=8792,
        )
        self.assertTrue(team_search["ok"])
        self.assertEqual(team_search["result"]["results"][0]["id"], "note-cloud-team")

        missing_account = self._request(
            "POST",
            "/v1/search",
            payload={"query": "research continuity", "top_k": 5},
            port=8792,
            expect_error=True,
        )
        self.assertFalse(missing_account["ok"])
        self.assertEqual(missing_account["error"]["code"], "ACCOUNT_NOT_SYNCED")

        wrong_account_fetch = self._request(
            "POST",
            "/v1/fetch",
            payload={"account_email": "livia@example.com", "id": "note-cloud-team"},
            port=8792,
            expect_error=True,
        )
        self.assertFalse(wrong_account_fetch["ok"])
        self.assertEqual(wrong_account_fetch["error"]["code"], "OBJECT_NOT_FOUND")

    def test_sync_bundle_requires_account_email(self) -> None:
        runtime = build_runtime()
        self._start_server(runtime, port=8793)

        invalid = self._request(
            "POST",
            "/v1/sync/bundle",
            payload={"manifest": {"sync_scope": "selected-projects"}, "documents": []},
            port=8793,
            expect_error=True,
        )
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"]["code"], "INVALID_INPUT")

    def test_bearer_token_is_required_when_configured(self) -> None:
        runtime = build_runtime()
        self._start_server(runtime, port=8790)

        with self.assertRaises(urllib.error.HTTPError) as exc:
            self._request("GET", "/health", include_token=False, port=8790)
        self.assertEqual(exc.exception.code, 401)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        include_token: bool = True,
        token: str = "test-token",
        port: int,
        expect_error: bool = False,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            method=method,
        )
        request.add_header("Content-Type", "application/json")
        if include_token:
            request.add_header("Authorization", f"Bearer {token}")
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        try:
            with urllib.request.urlopen(request, data=data, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if not expect_error:
                raise
            return json.loads(error.read().decode("utf-8"))

    def _start_server(self, runtime, *, port: int):
        server = build_cloud_server(runtime, host="127.0.0.1", port=port, bearer_token="test-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(runtime.close)
        self._wait_for_server(port)
        return server, thread

    def _wait_for_server(self, port: int) -> None:
        for _ in range(50):
            try:
                self._request("GET", "/health", port=port)
                return
            except Exception:
                time.sleep(0.05)
        self.fail(f"Timed out waiting for test server on port {port}")
