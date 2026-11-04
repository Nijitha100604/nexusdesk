"""Section-aware chunking: keep sections intact, split only what is too long."""

from __future__ import annotations

import re

from .models import ChunkDraft, Section

CHUNKER_VERSION = "1"  # bump when the rules below change, so documents are re-indexed
SINGLE_MAX = 1800  # an article this short stays one chunk
MAX_CHARS = 1200
MIN_CHARS = 250
OVERLAP = 150


def _render(section: Section) -> str:
    return f"{section.heading}\n{section.text}" if section.heading else section.text


def _render_group(group: list[Section]) -> str:
    return "\n\n".join(_render(s) for s in group)


def _wrap(line: str, max_chars: int) -> list[str]:
    """Break one very long line at sentence or word boundaries."""
    if len(line) <= max_chars:
        return [line]
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", line):
        for word in sentence.split(" "):
            if len(word) > max_chars:  # no spaces at all: hard cut
                if current:
                    pieces.append(current)
                    current = ""
                pieces.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
                continue
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars and current:
                pieces.append(current)
                current = word
            else:
                current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_long(body: str, max_chars: int, overlap: int) -> list[str]:
    lines: list[str] = []
    for raw in body.split("\n"):
        lines.extend(_wrap(raw, max_chars))
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            tail: list[str] = []
            tail_size = 0
            for previous in reversed(current):
                if tail_size + len(previous) + 1 > overlap:
                    break
                tail.insert(0, previous)
                tail_size += len(previous) + 1
            if tail_size + len(line) + 1 > max_chars:
                tail, tail_size = [], 0
            current, size = tail, tail_size
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def chunk_sections(
    sections: list[Section],
    *,
    single_max: int = SINGLE_MAX,
    max_chars: int = MAX_CHARS,
    min_chars: int = MIN_CHARS,
    overlap: int = OVERLAP,
) -> list[ChunkDraft]:
    sections = [s for s in sections if s.text.strip()]
    if not sections:
        return []
    full = _render_group(sections)
    if len(full) <= single_max:
        return [ChunkDraft("", full)]

    groups: list[list[Section]] = []
    for section in sections:
        previous = groups[-1] if groups else None
        if (
            previous is not None
            and len(_render_group(previous)) < min_chars
            and len(_render_group([*previous, section])) <= max_chars
        ):
            previous.append(section)  # the previous group is too small to stand alone
        else:
            groups.append([section])
    if len(groups) > 1 and len(_render_group(groups[-1])) < min_chars:
        merged = [*groups[-2], *groups[-1]]
        if len(_render_group(merged)) <= max_chars:
            groups[-2:] = [merged]

    drafts: list[ChunkDraft] = []
    for group in groups:
        name = " / ".join(s.heading for s in group if s.heading)
        body = _render_group(group)
        if len(body) <= max_chars:
            drafts.append(ChunkDraft(name, body))
        else:
            drafts.extend(ChunkDraft(name, part) for part in _split_long(body, max_chars, overlap))
    return drafts
