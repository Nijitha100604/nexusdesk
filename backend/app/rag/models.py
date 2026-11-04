"""Plain data classes used across the RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KB_ARTICLE = "kb_article"
INCIDENT = "incident"
SOURCE_LABELS = {KB_ARTICLE: "KB article", INCIDENT: "Past ticket"}


@dataclass(frozen=True)
class Section:
    heading: str
    text: str


@dataclass
class Document:
    """One knowledge article or resolved incident, cleaned and split into sections."""

    doc_id: str  # the ServiceNow number, e.g. KB0010056 or INC0010123
    source_type: str
    title: str
    category: str
    sections: list[Section]
    updated: str = ""
    sys_id: str = ""
    url: str = ""


@dataclass(frozen=True)
class ChunkDraft:
    section: str
    body: str

    def embed_text(self, title: str) -> str:
        return f"{title}\n{self.section}\n{self.body}"


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]


@dataclass
class StoredChunk:
    id: str
    text: str
    metadata: dict[str, Any]
    embedding: list[float]


@dataclass
class DocState:
    content_hash: str
    chunk_ids: list[str]
    source_type: str


@dataclass
class Hit:
    chunk_id: str
    text: str
    similarity: float  # cosine similarity of the vectors
    score: float  # similarity plus optional re-ranking bonus
    metadata: dict[str, Any]

    @property
    def number(self) -> str:
        return str(self.metadata.get("number", ""))

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", ""))

    @property
    def source_type(self) -> str:
        return str(self.metadata.get("source_type", ""))

    @property
    def category(self) -> str:
        return str(self.metadata.get("category", ""))


@dataclass(frozen=True)
class Citation:
    number: str
    title: str
    source_type: str
    url: str
    similarity: float


@dataclass
class AnswerResult:
    question: str
    answerable: bool
    answer: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    top_similarity: float = 0.0
    grounding_score: float = 0.0
    reason: str = "ok"
    hits: list[Hit] = field(default_factory=list)
