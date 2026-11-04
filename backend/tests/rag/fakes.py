"""Test doubles: a deterministic embedder, a fake ServiceNow client and a scripted LLM."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app.llm.base import LLMError
from app.rag.embeddings import normalize
from app.rag.retriever import content_terms

DIM = 256


class FakeEmbedder:
    """Bag-of-words hashing: texts that share content words get similar vectors."""

    name = "fake-bow"

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIM
        for term in content_terms(text):
            vector[int(hashlib.md5(term.encode()).hexdigest(), 16) % DIM] += 1.0
        return normalize(vector)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._vector(query)


def article_html(category_label: str, symptoms: list[str], steps: list[str], cause: str) -> str:
    sym = "".join(f"<li>{s}</li>" for s in symptoms)
    stp = "".join(f"<li>{s}</li>" for s in steps)
    return (
        f"<p><strong>Category:</strong> {category_label}</p>"
        f"<h2>Symptoms</h2><ul>{sym}</ul><h2>Cause</h2><p>{cause}</p>"
        f"<h2>Resolution</h2><ol>{stp}</ol><h2>When to escalate</h2><p>Contact the Service Desk.</p>"
        "<p><em>Synthetic demo article generated for the NexusDesk portfolio project.</em></p>"
    )


def make_article(number: str, title: str, html: str, updated: str = "2026-10-01 09:00:00"):
    return SimpleNamespace(
        number=number,
        short_description=title,
        text=html,
        sys_updated_on=updated,
        sys_id=number.lower() * 4,
    )


def make_incident(
    number: str, title: str, description: str, notes: str, group: str = "",
    updated="2026-10-02 09:00:00", correlation_id="seed-inc-0001",
):  # fmt: skip
    return SimpleNamespace(
        number=number, short_description=title, description=description, close_notes=notes,
        assignment_group=group, sys_updated_on=updated, sys_id=number.lower() * 3,
        correlation_id=correlation_id,
    )  # fmt: skip


VPN = make_article(
    "KB0000001",
    "VPN client shows a connection timeout",
    article_html(
        "Network and VPN",
        ["The VPN client shows a connection timeout", "You cannot reach internal sites"],
        ["Check your internet connection", "Restart the VPN client", "Reinstall the VPN client"],
        "The client cannot reach the gateway, usually because of a weak connection.",
    ),
)
PRINTER = make_article(
    "KB0000002",
    "Printer shows offline",
    article_html(
        "Hardware",
        ["The printer shows offline", "Documents stay in the print queue"],
        ["Turn the printer off and on", "Check it is on the same network", "Add the printer again"],
        "The printer lost its network connection.",
    ),
)
PASSWORD = make_article(
    "KB0000003",
    "How to reset a forgotten password with self-service",
    article_html(
        "Account and Password",
        ["You forgot your password", "Sign in fails with the wrong password message"],
        ["Open the self-service portal", "Verify your identity with MFA", "Choose a new password"],
        "Passwords are reset through the self-service portal.",
    ),
)


class FakeClient:
    def __init__(self, articles=None, incidents=None):
        self.articles = list(articles if articles is not None else [VPN, PRINTER, PASSWORD])
        self.incidents = list(incidents or [])
        self.fail = False

    def iter_knowledge_articles(self, *, page_size=50, updated_since=None):
        if self.fail:
            raise RuntimeError("ServiceNow unavailable")
        yield from self.articles

    def iter_resolved_incidents(self, *, page_size=50, max_items=1000):
        yield from self.incidents[:max_items]


class ScriptedLLM:
    """Returns queued responses; an Exception in the queue is raised instead."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_user = ""

    def complete(self, system, user, *, json_mode=True, temperature=0.2):
        self.calls += 1
        self.last_user = user
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


__all__ = ["FakeEmbedder", "FakeClient", "ScriptedLLM", "LLMError", "VPN", "PRINTER", "PASSWORD"]
