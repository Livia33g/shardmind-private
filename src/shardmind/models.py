"""Core domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any


def path_reference_fields(path: str) -> dict[str, str]:
    basename = PurePosixPath(path).stem
    return {"wikilink": basename}


def titled_fields(object_type: str, title: str) -> dict[str, str]:
    if object_type == "paper-card":
        return {"paper_title": title}
    return {"note_title": title}


@dataclass(slots=True)
class NoteProvenance:
    created_from: str = ""


@dataclass(slots=True)
class NoteSections:
    content: str = ""


@dataclass(slots=True)
class Note:
    id: str
    type: str = "note"
    title: str = ""
    tags: list[str] = field(default_factory=list)
    provenance: NoteProvenance = field(default_factory=NoteProvenance)
    created_at: str = ""
    updated_at: str = ""
    sections: NoteSections = field(default_factory=NoteSections)

    def to_document(self, path: str) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "path": path,
            **titled_fields(self.type, self.title),
            **path_reference_fields(path),
            "frontmatter": {
                "title": self.title,
                "tags": list(self.tags),
                "provenance": asdict(self.provenance),
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
            "sections": {"content": self.sections.content},
        }


@dataclass(slots=True)
class PaperCardProvenance:
    created_from: str = ""
    source_type: str = ""
    source_ref: str = ""


@dataclass(slots=True)
class PaperCardSections:
    summary: str = ""
    main_claims: str = ""
    why_relevant: str = ""
    limitations: str = ""
    notes: str = ""
    user_notes: str = ""
    related_links: str = ""


@dataclass(slots=True)
class PaperCard:
    id: str
    title: str
    type: str = "paper-card"
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    source: str = ""
    url: str = ""
    citekey: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "unread"
    provenance: PaperCardProvenance = field(default_factory=PaperCardProvenance)
    created_at: str = ""
    updated_at: str = ""
    sections: PaperCardSections = field(default_factory=PaperCardSections)

    def to_document(self, path: str) -> dict[str, object]:
        frontmatter: dict[str, Any] = {
            "title": self.title,
            "authors": list(self.authors),
            "source": self.source,
            "url": self.url,
            "citekey": self.citekey,
            "tags": list(self.tags),
            "status": self.status,
            "provenance": asdict(self.provenance),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.year is not None:
            frontmatter["year"] = self.year
        return {
            "id": self.id,
            "type": self.type,
            "path": path,
            **titled_fields(self.type, self.title),
            **path_reference_fields(path),
            "frontmatter": frontmatter,
            "sections": asdict(self.sections),
        }


ObjectRecord = Note | PaperCard


@dataclass(slots=True)
class SearchResult:
    id: str
    type: str
    title: str
    path: str
    score: float
    matched_sections: list[str]
    snippet: str
    tags: list[str]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("title")
        payload.update(titled_fields(self.type, self.title))
        payload.update(path_reference_fields(self.path))
        return payload
