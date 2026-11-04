"""Local embedding model (no API key, no cost)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    name: str

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, query: str) -> list[float]: ...


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class FastEmbedEmbedder:
    """BGE-small through fastembed (ONNX): small install, no PyTorch, runs on CPU."""

    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        from fastembed import TextEmbedding  # imported here so tests do not need it

        cache_dir.mkdir(parents=True, exist_ok=True)
        self.name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize([float(x) for x in vector]) for vector in self._model.embed(texts)]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._embed([self.QUERY_PREFIX + query])[0]
