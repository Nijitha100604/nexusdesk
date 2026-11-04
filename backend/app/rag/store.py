"""Vector store: a small interface, the ChromaDB implementation and an in-memory one for tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .models import Chunk, DocState, StoredChunk


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def delete(self, ids: list[str]) -> None: ...

    def doc_states(self) -> dict[str, DocState]: ...

    def query(
        self,
        embedding: list[float],
        n: int,
        categories: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> list[StoredChunk]: ...

    def count(self) -> int: ...

    def reset(self) -> None: ...

    def metadatas(self) -> list[dict[str, Any]]: ...


def _states(ids: list[str], metadatas: list[dict[str, Any]]) -> dict[str, DocState]:
    states: dict[str, DocState] = {}
    for chunk_id, meta in zip(ids, metadatas, strict=True):
        doc_id = str(meta["doc_id"])
        state = states.setdefault(
            doc_id, DocState(str(meta["content_hash"]), [], str(meta["source_type"]))
        )
        state.chunk_ids.append(chunk_id)
    return states


class ChromaStore:
    def __init__(self, path: Path, collection: str) -> None:
        import chromadb
        from chromadb.config import Settings

        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path), settings=Settings(anonymized_telemetry=False)
        )
        self._name = collection
        self._col = self._client.get_or_create_collection(name=collection, embedding_function=None)

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if chunks:
            self._col.upsert(
                ids=[c.chunk_id for c in chunks],
                embeddings=embeddings,
                documents=[c.text for c in chunks],
                metadatas=[c.metadata for c in chunks],
            )

    def delete(self, ids: list[str]) -> None:
        if ids:
            self._col.delete(ids=ids)

    def doc_states(self) -> dict[str, DocState]:
        result = self._col.get(include=["metadatas"])
        return _states(list(result["ids"]), list(result["metadatas"]))

    def metadatas(self) -> list[dict[str, Any]]:
        return list(self._col.get(include=["metadatas"])["metadatas"])

    def query(
        self,
        embedding: list[float],
        n: int,
        categories: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> list[StoredChunk]:
        total = self._col.count()
        if total == 0:
            return []
        conditions: list[dict[str, Any]] = []
        if categories:
            conditions.append({"category": {"$in": categories}})
        if source_types:
            conditions.append({"source_type": {"$in": source_types}})
        where: dict[str, Any] | None = None
        if len(conditions) == 1:
            where = conditions[0]
        elif conditions:
            where = {"$and": conditions}
        result = self._col.query(
            query_embeddings=[embedding],
            n_results=min(n, total),
            where=where,
            include=["documents", "metadatas", "embeddings"],
        )
        return [
            StoredChunk(chunk_id, text, dict(meta), [float(x) for x in vector])
            for chunk_id, text, meta, vector in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["embeddings"][0],
                strict=True,
            )
        ]

    def count(self) -> int:
        return self._col.count()

    def reset(self) -> None:
        self._client.delete_collection(self._name)
        self._col = self._client.get_or_create_collection(name=self._name, embedding_function=None)


class InMemoryStore:
    """Same behaviour as ChromaStore without persistence; used in unit tests."""

    def __init__(self) -> None:
        self._rows: dict[str, StoredChunk] = {}

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        for chunk, vector in zip(chunks, embeddings, strict=True):
            self._rows[chunk.chunk_id] = StoredChunk(
                chunk.chunk_id, chunk.text, dict(chunk.metadata), list(vector)
            )

    def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self._rows.pop(chunk_id, None)

    def doc_states(self) -> dict[str, DocState]:
        return _states(list(self._rows), [r.metadata for r in self._rows.values()])

    def metadatas(self) -> list[dict[str, Any]]:
        return [r.metadata for r in self._rows.values()]

    def query(
        self,
        embedding: list[float],
        n: int,
        categories: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> list[StoredChunk]:
        rows = [
            r
            for r in self._rows.values()
            if (not categories or r.metadata.get("category") in categories)
            and (not source_types or r.metadata.get("source_type") in source_types)
        ]
        rows.sort(key=lambda r: -sum(a * b for a, b in zip(embedding, r.embedding, strict=True)))
        return rows[:n]

    def count(self) -> int:
        return len(self._rows)

    def reset(self) -> None:
        self._rows.clear()
