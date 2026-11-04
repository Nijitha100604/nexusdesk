"""Similarity search with optional category filter and light re-ranking."""

from __future__ import annotations

import re

from .categories import filter_values
from .embeddings import Embedder
from .models import Hit
from .store import VectorStore

STOPWORDS = frozenset(
    "the a an and or but if then of to in on at for from with without by is are was were be been "
    "it its this that these those i me my we our you your they their can could would should will "
    "do does did not no yes how what why when where which who whom have has had get got just "
    "please help need want like also very been being into about after before again".split()
)
RERANK_WEIGHT = 0.15


def content_terms(text: str) -> set[str]:
    """Lower-case content words with a very light stemmer; used for re-ranking and grounding."""
    terms: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if len(word) < 3 or word in STOPWORDS:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word = word[: -len(suffix)]
                break
        terms.add(word)
    return terms


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        *,
        top_k: int = 5,
        min_similarity: float = 0.45,
        rerank: bool = False,
        candidates: int = 20,
        max_per_doc: int = 2,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.min_similarity = min_similarity
        self.rerank = rerank
        self.candidates = candidates
        self.max_per_doc = max_per_doc

    def _run(
        self,
        vector: list[float],
        query: str,
        categories: list[str] | None,
        source_types: list[str] | None,
        top_k: int,
        min_similarity: float,
        rerank: bool,
    ) -> list[Hit]:
        stored = self.store.query(vector, max(self.candidates, top_k), categories, source_types)
        query_terms = content_terms(query) if rerank else set()
        hits: list[Hit] = []
        for chunk in stored:
            similarity = cosine(vector, chunk.embedding)
            if similarity < min_similarity:
                continue
            score = similarity
            if rerank and query_terms:
                overlap = len(query_terms & content_terms(chunk.text)) / len(query_terms)
                score += RERANK_WEIGHT * overlap
            hits.append(Hit(chunk.id, chunk.text, similarity, score, chunk.metadata))
        hits.sort(key=lambda h: h.score, reverse=True)
        kept: list[Hit] = []
        per_doc: dict[str, int] = {}
        for hit in hits:
            doc = str(hit.metadata.get("doc_id", hit.chunk_id))
            if per_doc.get(doc, 0) >= self.max_per_doc:
                continue
            per_doc[doc] = per_doc.get(doc, 0) + 1
            kept.append(hit)
            if len(kept) >= top_k:
                break
        return kept

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        source_types: list[str] | None = None,
        top_k: int | None = None,
        min_similarity: float | None = None,
        rerank: bool | None = None,
        fallback_unfiltered: bool = True,
    ) -> list[Hit]:
        """Best chunks for the query. With a category filter, falls back to an unfiltered search
        when the filter finds nothing relevant (the triage category can be wrong)."""
        if not query.strip():
            return []
        vector = self.embedder.embed_query(query)
        k = top_k or self.top_k
        floor = self.min_similarity if min_similarity is None else min_similarity
        use_rerank = self.rerank if rerank is None else rerank
        categories = filter_values(category) if category else None
        hits = self._run(vector, query, categories, source_types, k, floor, use_rerank)
        if not hits and categories and fallback_unfiltered:
            hits = self._run(vector, query, None, source_types, k, floor, use_rerank)
        return hits
