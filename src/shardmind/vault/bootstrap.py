"""Vault bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

VAULT_DIRS = (
    "library/papers",
    "notes/inbox",
    "notes/scratch",
    "notes/daily",
    "assets/images",
    "assets/attachments",
    "archive",
    "system/cache",
    "system/indexes",
    "system/logs",
)


def bootstrap_vault(vault_path: Path) -> None:
    for relative in VAULT_DIRS:
        (vault_path / relative).mkdir(parents=True, exist_ok=True)
