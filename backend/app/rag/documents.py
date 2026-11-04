"""Convert ServiceNow records into Documents and Documents into indexable chunks."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .categories import category_from_label
from .chunking import CHUNKER_VERSION, chunk_sections
from .cleaning import content_hash, html_to_sections, normalize_text
from .models import INCIDENT, KB_ARTICLE, Chunk, Document, Section

if TYPE_CHECKING:
    from app.servicenow.models import Incident, KnowledgeArticle

CATEGORY_LINE = re.compile(r"^\s*category:\s*(.+?)\s*$", re.IGNORECASE)
BOILERPLATE = re.compile(r"^\s*synthetic demo article", re.IGNORECASE)
TEST_TICKET_PREFIX = "[NexusDesk"  # tickets made by the connectivity and live tests


def article_to_document(article: KnowledgeArticle, instance_url: str) -> Document | None:
    category = "unknown"
    sections: list[Section] = []
    for section in html_to_sections(article.text):
        kept: list[str] = []
        for line in section.text.split("\n"):
            match = CATEGORY_LINE.match(line)
            if match and category == "unknown":
                category = category_from_label(match.group(1))
            elif not BOILERPLATE.match(line):
                kept.append(line)
        if kept:
            sections.append(Section(section.heading, "\n".join(kept)))
    title = normalize_text(article.short_description)
    if not sections or not title:
        return None
    base = instance_url.rstrip("/")
    return Document(
        doc_id=article.number,
        source_type=KB_ARTICLE,
        title=title,
        category=category,
        sections=sections,
        updated=article.sys_updated_on,
        sys_id=article.sys_id,
        url=f"{base}/kb_view.do?sysparm_article={article.number}" if base else "",
    )


def incident_to_document(
    incident: Incident,
    group_categories: dict[str, str],
    instance_url: str,
    *,
    only_nexusdesk: bool = True,
) -> Document | None:
    """Tickets made through NexusDesk always carry a correlation_id; ServiceNow's built-in
    demo incidents do not, so they are skipped unless `only_nexusdesk` is False."""
    title = normalize_text(incident.short_description)
    description = normalize_text(incident.description)
    resolution = normalize_text(incident.close_notes)
    if not title or not description or not resolution or title.startswith(TEST_TICKET_PREFIX):
        return None
    if only_nexusdesk and not incident.correlation_id:
        return None
    base = instance_url.rstrip("/")
    return Document(
        doc_id=incident.number,
        source_type=INCIDENT,
        title=title,
        category=group_categories.get(incident.assignment_group, "unknown"),
        sections=[Section("Problem", description), Section("Resolution", resolution)],
        updated=incident.sys_updated_on,
        sys_id=incident.sys_id,
        url=f"{base}/incident.do?sys_id={incident.sys_id}" if base else "",
    )


def document_hash(doc: Document, embedding_model: str) -> str:
    body = "\n".join(f"{s.heading}\n{s.text}" for s in doc.sections)
    return content_hash(doc.title, doc.category, body, CHUNKER_VERSION, embedding_model)


def build_chunks(doc: Document, embedding_model: str) -> list[Chunk]:
    drafts = chunk_sections(doc.sections)
    digest = document_hash(doc, embedding_model)
    chunks: list[Chunk] = []
    for index, draft in enumerate(drafts):
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}:{index:03d}",
                text=draft.embed_text(doc.title),
                metadata={  # Chroma accepts only str, int, float and bool values
                    "doc_id": doc.doc_id,
                    "number": doc.doc_id,
                    "source_type": doc.source_type,
                    "title": doc.title,
                    "category": doc.category,
                    "section": draft.section,
                    "updated": doc.updated,
                    "url": doc.url,
                    "sys_id": doc.sys_id,
                    "content_hash": digest,
                    "chunk_index": index,
                    "chunk_count": len(drafts),
                    "embedding_model": embedding_model,
                },
            )
        )
    return chunks
