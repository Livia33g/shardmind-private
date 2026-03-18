from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shardmind.bootstrap import build_runtime
from shardmind.vault.ids import slugify
from shardmind.vault.markdown import parse_note, render_note

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VaultServiceTest(unittest.TestCase):
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

    def test_slugify_normalizes_human_titles(self) -> None:
        self.assertEqual(slugify("Memory Architecture Idea!"), "memory-architecture-idea")

    def test_create_note_writes_canonical_markdown_and_log(self) -> None:
        note, relative_path = self.runtime.vault.create_note(
            title="Memory Architecture Idea",
            content="First line\nSecond line",
            tags=["memory", "agents"],
        )

        note_path = self.runtime.settings.vault_path / relative_path
        self.assertTrue(note_path.exists())
        saved_note = parse_note(note_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_note.id, note.id)
        self.assertEqual(saved_note.sections.content, "First line\nSecond line")
        self.assertEqual(saved_note.tags, ["memory", "agents"])

        log_path = self.runtime.settings.vault_path / "system" / "logs" / "operations.log"
        event = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(event["tool_name"], "knowledge.create_note")

    def test_append_to_note_updates_content(self) -> None:
        note, _ = self.runtime.vault.create_note(content="Original", title="Scratch note")
        updated_note, _ = self.runtime.vault.append_to_note(note.id, "More context")
        self.assertEqual(updated_note.sections.content, "Original\n\nMore context")

    def test_render_and_parse_round_trip(self) -> None:
        note, _ = self.runtime.vault.create_note(content="Round trip", title="Round trip")
        rendered = render_note(note)
        parsed = parse_note(rendered)
        self.assertEqual(parsed.id, note.id)
        self.assertEqual(parsed.title, note.title)
        self.assertEqual(parsed.sections.content, note.sections.content)
