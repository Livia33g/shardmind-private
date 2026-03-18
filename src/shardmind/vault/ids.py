"""Stable object IDs and slugs."""

from __future__ import annotations

import re
import unicodedata
from uuid import uuid4


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return lowered or "untitled"


def note_id() -> str:
    return _object_id("note")


def paper_card_id() -> str:
    return _object_id("paper")


def short_id(object_id: str, length: int = 8) -> str:
    return object_id.split("-", 1)[-1][:length]


def _object_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
