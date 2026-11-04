"""LLM interface. The Phase 7 gateway implements the same interface."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol


class LLMError(RuntimeError):
    """The model could not be reached or kept failing."""


class LLM(Protocol):
    def complete(
        self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.2
    ) -> str: ...


def parse_json(text: str) -> Any:
    """Parse a JSON answer, tolerating code fences and text around the object."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])
