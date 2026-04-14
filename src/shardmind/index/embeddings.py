"""Local embedding backends for hybrid retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass


class EmbeddingBackend:
    name: str = "none"
    enabled: bool = False

    def embed_text(self, text: str) -> list[float] | None:
        raise NotImplementedError

    def serialize(self, vector: list[float]) -> bytes:
        return json.dumps(vector, separators=(",", ":")).encode("utf-8")

    def deserialize(self, raw: bytes | str | None) -> list[float] | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return [float(value) for value in json.loads(raw)]

    def similarity(self, left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=False))


class NullEmbeddingBackend(EmbeddingBackend):
    name = "none"
    enabled = False

    def embed_text(self, text: str) -> list[float] | None:  # noqa: ARG002
        return None


@dataclass(slots=True)
class HashEmbeddingBackend(EmbeddingBackend):
    """Cheap local embedding backend using hashed normalized tokens and char n-grams.

    This is not a foundation-model embedding, but it gives us:
    - zero per-query API cost
    - deterministic local vectors
    - better fuzzy retrieval than plain keyword matching
    """

    dimensions: int = 192
    char_ngram_weight: float = 0.15
    name: str = "hash"
    enabled: bool = True

    def embed_text(self, text: str) -> list[float] | None:
        normalized = text.strip().lower()
        if not normalized:
            return None

        vector = [0.0] * self.dimensions
        word_tokens = [_normalize_word(token) for token in re.findall(r"[a-z0-9]+", normalized)]
        word_tokens = [token for token in word_tokens if token]
        if not word_tokens:
            return None

        for token in word_tokens:
            self._add(vector, f"w:{token}", 1.0)

        compact_text = " ".join(word_tokens)
        if len(compact_text) >= 3:
            for index in range(len(compact_text) - 2):
                gram = compact_text[index : index + 3]
                self._add(vector, f"c:{gram}", self.char_ngram_weight)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return None
        return [value / norm for value in vector]

    def _add(self, vector: list[float], token: str, weight: float) -> None:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % self.dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += weight * sign


def create_embedding_backend(name: str) -> EmbeddingBackend:
    normalized = name.strip().lower()
    if normalized in {"", "none", "off", "disabled"}:
        return NullEmbeddingBackend()
    if normalized in {"stub", "hash", "local"}:
        return HashEmbeddingBackend()
    raise ValueError(
        f"Unsupported embedding backend '{name}'. Supported backends: none, hash/local, stub."
    )


def content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def _normalize_word(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token
