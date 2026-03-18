"""Configuration and project path helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Could not locate project root from pyproject.toml.")


@dataclass(slots=True)
class Settings:
    project_root: Path
    vault_path: Path
    sqlite_path: Path
    shared_path: Path
    default_note_destination: str = "inbox"
    embedding_backend: str = "stub"

    @classmethod
    def load(cls) -> Settings:
        project_root = find_project_root()
        vault_path = Path(os.environ.get("SHARDMIND_VAULT_PATH", project_root / "vault"))
        sqlite_path = Path(
            os.environ.get(
                "SHARDMIND_SQLITE_PATH",
                project_root / "var" / "shardmind.sqlite3",
            )
        )
        shared_path = Path(os.environ.get("SHARDMIND_SHARED_PATH", project_root / "shared"))
        default_note_destination = os.environ.get("SHARDMIND_DEFAULT_NOTE_DESTINATION", "inbox")
        embedding_backend = os.environ.get("SHARDMIND_EMBEDDING_BACKEND", "stub")
        return cls(
            project_root=project_root,
            vault_path=vault_path,
            sqlite_path=sqlite_path,
            shared_path=shared_path,
            default_note_destination=default_note_destination,
            embedding_backend=embedding_backend,
        )
