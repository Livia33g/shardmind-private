"""Stable object IDs and slugs."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return lowered or "untitled"


def note_id(title: str, timestamp: datetime | None = None) -> str:
    now = timestamp or datetime.now(UTC)
    return f"note-{slugify(title)}-{now.strftime('%Y%m%d%H%M%S')}"


def paper_card_id(title: str, existing_ids: set[str] | None = None) -> str:
    base_id = f"paper-{slugify(title)}"
    if not existing_ids or base_id not in existing_ids:
        return base_id
    suffix = 2
    while f"{base_id}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base_id}-{suffix}"
