"""Stable note IDs and slugs."""

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
