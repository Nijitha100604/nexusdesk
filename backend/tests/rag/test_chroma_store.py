"""Smoke test of the real ChromaDB store (skipped when chromadb is not installed)."""

import pytest

from app.rag.documents import article_to_document, build_chunks
from tests.rag.fakes import PASSWORD, PRINTER, VPN, FakeEmbedder


def test_chroma_roundtrip(tmp_path):
    pytest.importorskip("chromadb")
    from app.rag.store import ChromaStore

    embedder = FakeEmbedder()
    store = ChromaStore(tmp_path / "chroma", "test_collection")
    for article in (VPN, PRINTER, PASSWORD):
        chunks = build_chunks(article_to_document(article, "https://x"), embedder.name)
        store.upsert(chunks, embedder.embed_passages([c.text for c in chunks]))

    assert store.count() == 3
    assert set(store.doc_states()) == {"KB0000001", "KB0000002", "KB0000003"}

    query = embedder.embed_query("vpn connection timeout")
    best = store.query(query, 3)
    assert best[0].metadata["number"] == "KB0000001"
    assert len(best[0].embedding) == len(query)

    only_hardware = store.query(query, 3, categories=["hardware"])
    assert [c.metadata["number"] for c in only_hardware] == ["KB0000002"]
    both = store.query(query, 3, categories=["hardware"], source_types=["kb_article"])
    assert len(both) == 1

    store.delete(["KB0000002:000"])
    assert store.count() == 2
    store.reset()
    assert store.count() == 0
