"""Turn ServiceNow HTML into clean text sections."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

from .models import Section

_SKIP = {"script", "style", "head", "noscript", "template"}
_BLOCK = {
    "p", "div", "section", "article", "header", "footer", "blockquote", "pre", "table",
    "tr", "dl", "dt", "dd", "figure", "li",
}  # fmt: skip
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []  # (kind, text), kind is "heading" or "text"
        self._buf: list[str] = []
        self._kind = "text"
        self._skip = 0
        self._lists: list[list] = []  # stack of [tag, counter]

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text:
            self.blocks.append((self._kind, text))
        self._kind = "text"

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _HEADINGS:
            self._flush()
            self._kind = "heading"
        elif tag in ("ul", "ol"):
            self._flush()
            self._lists.append([tag, 0])
        elif tag == "li":
            self._flush()
            if self._lists:
                top = self._lists[-1]
                top[1] += 1
                self._buf.append(f"{top[1]}. " if top[0] == "ol" else "- ")
            else:
                self._buf.append("- ")
        elif tag in ("td", "th"):
            if "".join(self._buf).strip():
                self._buf.append(" | ")
        elif tag in ("br", "hr"):
            self._flush()
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in _HEADINGS or tag in _BLOCK:
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            if self._lists:
                self._lists.pop()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def html_to_sections(html_text: str) -> list[Section]:
    """Split HTML into sections at headings. Text before the first heading has an empty heading."""
    parser = _Extractor()
    parser.feed(html_text or "")
    parser.close()
    sections: list[Section] = []
    heading, lines = "", []

    def close_section() -> None:
        if lines:
            sections.append(Section(heading, "\n".join(lines)))

    for kind, text in parser.blocks:
        if kind == "heading":
            close_section()
            heading, lines = text, []
        else:
            lines.append(text)
    close_section()
    return sections


def normalize_text(text: str) -> str:
    """Plain-text field cleanup (incident descriptions and notes)."""
    return " ".join(_CONTROL.sub(" ", text or "").split())


def content_hash(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
