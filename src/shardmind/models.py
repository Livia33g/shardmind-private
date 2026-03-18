"""Core domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class Provenance:
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
    provenance: Provenance = field(default_factory=Provenance)
    created_at: str = ""
    updated_at: str = ""
    sections: NoteSections = field(default_factory=NoteSections)

    def to_document(self, path: str) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "path": path,
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
        return asdict(self)
