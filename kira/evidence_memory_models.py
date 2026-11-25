"""Typed domain models for Kira's evidence-backed memory and embedding indexes."""
from __future__ import annotations
import array
import math
from dataclasses import dataclass
from typing import Any

def _row_value(row: Any, key: str, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None and default is not None else value

def _optional_float(value):
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None

@dataclass(frozen=True, slots=True)
class EvidenceFact:
    """Canonical persisted fact shape; provenance remains a separate EvidenceQuote."""
    id: str
    subject: str
    predicate: str
    value: str
    text: str
    category: str
    status: str
    source_kind: str
    valid_from: float | None
    valid_to: float | None
    supersedes: str
    legacy: bool
    persona_id: str | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: Any) -> "EvidenceFact":
        return cls(
            id=str(_row_value(row, "id", "")),
            subject=str(_row_value(row, "subject", "")),
            predicate=str(_row_value(row, "predicate", "")),
            value=str(_row_value(row, "value", "")),
            text=str(_row_value(row, "text", "")),
            category=str(_row_value(row, "category", "unverified")),
            status=str(_row_value(row, "status", "active")),
            source_kind=str(_row_value(row, "source_kind", "unknown")),
            valid_from=_optional_float(_row_value(row, "valid_from")),
            valid_to=_optional_float(_row_value(row, "valid_to")),
            supersedes=str(_row_value(row, "supersedes", "[]")),
            legacy=bool(_row_value(row, "legacy", 0)),
            persona_id=_row_value(row, "persona_id"),
            created_at=_optional_float(_row_value(row, "created_at")) or 0.0,
            updated_at=_optional_float(_row_value(row, "updated_at")) or 0.0,
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "id": self.id, "subject": self.subject, "predicate": self.predicate, "value": self.value,
            "text": self.text, "category": self.category, "status": self.status, "source_kind": self.source_kind,
            "valid_from": self.valid_from, "valid_to": self.valid_to, "supersedes": self.supersedes,
            "legacy": self.legacy, "persona_id": self.persona_id, "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def retrieval_item(self, *, pinned: bool, earlier: str | None) -> dict[str, Any]:
        return {
            "id": self.id, "text": self.text, "predicate": self.predicate, "category": self.category,
            "status": self.status, "created_at": self.created_at, "pinned": pinned, "earlier": earlier,
        }

@dataclass(frozen=True, slots=True)
class EvidenceQuote:
    """A source citation attached to a fact."""
    fact_id: str
    message_id: int | None
    speaker: str
    quote: str
    created_at: float

    @classmethod
    def from_row(cls, row: Any) -> "EvidenceQuote":
        message_id = _row_value(row, "message_id")
        return cls(
            fact_id=str(_row_value(row, "fact_id", "")),
            message_id=int(message_id) if message_id is not None else None,
            speaker=str(_row_value(row, "speaker", "")),
            quote=str(_row_value(row, "quote", "")),
            created_at=_optional_float(_row_value(row, "created_at")) or 0.0,
        )

@dataclass(frozen=True, slots=True)
class EmbeddingIndex:
    """Identity and compatibility contract for one independently rebuildable vector index."""
    backend: str
    provider: str
    model: str
    tag: str
    index_version: int

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "EmbeddingIndex":
        return cls(
            backend=str(config.get("kind") or "unknown"),
            provider=str(config.get("provider") or config.get("pid") or "unknown"),
            model=str(config.get("model") or "unknown"),
            tag=str(config.get("tag") or ""),
            index_version=int(config.get("index_version") or 1),
        )

    def __post_init__(self):
        if not self.tag or self.index_version < 1:
            raise ValueError("embedding index identity is incomplete")

@dataclass(frozen=True, slots=True)
class EvidenceVector:
    """Validated vector payload; malformed or incompatible vectors are never ranked."""
    fact_id: str
    model_tag: str
    dimension: int
    values: tuple[float, ...]

    def __post_init__(self):
        if not self.fact_id or not self.model_tag:
            raise ValueError("vector identity is incomplete")
        if self.dimension <= 0 or len(self.values) != self.dimension:
            raise ValueError("vector dimension does not match its payload")
        if any(not math.isfinite(float(value)) for value in self.values):
            raise ValueError("vector contains a non-finite value")

    @classmethod
    def create(cls, fact_id: str, model_tag: str, values) -> "EvidenceVector":
        vector = tuple(float(value) for value in values)
        return cls(fact_id, model_tag, len(vector), vector)

    def to_blob(self) -> bytes:
        return array.array("f", self.values).tobytes()

    @classmethod
    def from_row(cls, row: Any, model_tag: str) -> "EvidenceVector":
        dimension = int(_row_value(row, "dim", 0))
        blob = bytes(_row_value(row, "blob", b""))
        if dimension <= 0 or len(blob) != dimension * array.array("f").itemsize:
            raise ValueError("stored vector payload is incompatible with its dimension")
        values = array.array("f")
        values.frombytes(blob)
        return cls(str(_row_value(row, "fact_id", "")), model_tag, dimension, tuple(values))
