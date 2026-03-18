"""Shared paper-card metadata used across vault, index, and MCP layers."""

from __future__ import annotations

PAPER_CARD_SECTION_LABELS = {
    "summary": "Summary",
    "main_claims": "Main claims",
    "why_relevant": "Why relevant",
    "limitations": "Limitations",
    "notes": "Notes",
    "user_notes": "User notes",
    "related_links": "Related links",
}

PAPER_CARD_SECTION_HEADINGS = {label: field for field, label in PAPER_CARD_SECTION_LABELS.items()}
PAPER_CARD_SECTION_TITLES = {field: label for field, label in PAPER_CARD_SECTION_LABELS.items()}

ENRICHABLE_PAPER_CARD_SECTIONS = frozenset(
    {"summary", "notes", "main_claims", "why_relevant", "limitations", "related_links"}
)
