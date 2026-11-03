"""Minimal LLM helper for the seed scripts (Groq, Gemini or Ollama).

Phase 7 replaces this with the full LLM gateway. This one only needs: one JSON answer per call,
validation with retries, and patience with free-tier rate limits.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from seed_common import env

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class DailyLimitError(RuntimeError):
    """The provider's daily quota is used up; resume later or switch provider."""


def settings() -> tuple[str, str]:
    provider = (env("SEED_LLM_PROVIDER") or env("LLM_PROVIDER") or "groq").lower()
    model = env("SEED_LLM_MODEL")
    if not model:
        raise SystemExit(
            "Set SEED_LLM_MODEL in .env to a current model of your provider "
            "(for Groq, for example llama-3.3-70b-versatile; check the provider's model list)."
        )
    if provider not in ("groq", "gemini", "ollama"):
        raise SystemExit("SEED_LLM_PROVIDER must be groq, gemini or ollama")
    return provider, model


def _http_post(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> httpx.Response:
    return httpx.post(url, headers=headers, json=body, timeout=120)


def _wait_seconds(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 90.0) + 1
        except ValueError:
            pass
    match = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)s", response.text)
    if match:
        return min(int(match.group(1) or 0) * 60 + float(match.group(2)), 90.0) + 1
    return min(5.0 * 2**attempt, 60.0)


def _request(
    provider: str, model: str, system: str, user: str, temperature: float
) -> str:
    if provider == "gemini":
        key = env("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY is not set")
        url = GEMINI_URL.format(model=model)
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
    else:
        if provider == "groq":
            key = env("GROQ_API_KEY")
            if not key:
                raise SystemExit("GROQ_API_KEY is not set")
            url = GROQ_URL
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
        else:
            base = env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
            url = f"{base}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
        body = {
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    for attempt in range(6):
        try:
            response = _http_post(url, headers, body)
        except httpx.TransportError as exc:
            print(f"  network problem ({type(exc).__name__}); waiting before retry")
            time.sleep(min(5.0 * 2**attempt, 60.0))
            continue
        if response.status_code == 429:
            text = response.text.lower()
            if "per day" in text or "daily" in text:
                raise DailyLimitError(response.text[:300])
            wait = _wait_seconds(response, attempt)
            print(f"  rate limited; waiting {wait:.0f}s")
            time.sleep(wait)
            continue
        if response.status_code >= 500:
            time.sleep(min(5.0 * 2**attempt, 60.0))
            continue
        if response.status_code >= 400:
            raise RuntimeError(
                f"{provider} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        if provider == "gemini":
            return data["candidates"][0]["content"]["parts"][0]["text"]
        return data["choices"][0]["message"]["content"]
    raise RuntimeError(f"{provider} kept failing after several retries")


def parse_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def complete_json(
    system: str,
    user: str,
    *,
    provider: str,
    model: str,
    check: Callable[[Any], tuple[Any, list[str]]],
    temperature: float = 0.7,
    attempts: int = 3,
) -> Any:
    """Ask for JSON; `check` returns (normalized_object, errors). Retries with feedback."""
    prompt = user
    last_errors: list[str] = []
    for _ in range(attempts):
        text = _request(provider, model, system, prompt, temperature)
        try:
            obj, errors = check(parse_json(text))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            obj, errors = None, [f"not valid JSON in the requested shape ({exc})"]
        if not errors:
            return obj
        last_errors = errors
        prompt = (
            f"{user}\n\nYour previous answer was rejected for these reasons:\n- "
            + "\n- ".join(errors[:8])
            + "\nReturn corrected JSON only."
        )
    raise ValueError("; ".join(last_errors[:6]))
