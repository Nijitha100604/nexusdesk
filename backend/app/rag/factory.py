"""Shared instances for the app and the scripts."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.llm.simple import SimpleLLM

from .embeddings import FastEmbedEmbedder
from .retriever import Retriever
from .store import ChromaStore


@lru_cache
def get_embedder() -> FastEmbedEmbedder:
    s = get_settings()
    return FastEmbedEmbedder(s.embedding_model, s.embedding_cache)


@lru_cache
def get_store() -> ChromaStore:
    s = get_settings()
    return ChromaStore(s.chroma_dir, s.rag_collection)


def get_retriever(*, rerank: bool | None = None) -> Retriever:
    s = get_settings()
    return Retriever(
        get_store(),
        get_embedder(),
        top_k=s.rag_top_k,
        min_similarity=s.rag_min_similarity,
        rerank=s.rag_rerank if rerank is None else rerank,
    )


def get_llm() -> SimpleLLM:
    s = get_settings()
    return SimpleLLM(
        s.llm_provider,
        s.llm_model,
        groq_api_key=s.groq_api_key,
        gemini_api_key=s.gemini_api_key,
        ollama_base_url=s.ollama_base_url,
    )
