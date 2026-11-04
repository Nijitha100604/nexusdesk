"""Minimal LLM client (Groq, Gemini or Ollama). Phase 7 replaces it with the full gateway."""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .base import LLMError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class SimpleLLM:
    def __init__(
        self,
        provider: str,
        model: str,
        *,
        groq_api_key: str = "",
        gemini_api_key: str = "",
        ollama_base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        max_attempts: int = 4,
    ) -> None:
        if provider not in ("groq", "gemini", "ollama"):
            raise ValueError("LLM_PROVIDER must be groq, gemini or ollama")
        if not model:
            raise ValueError("LLM_MODEL is not set in .env")
        self.provider, self.model = provider, model
        self._keys = {"groq": groq_api_key, "gemini": gemini_api_key}
        self._ollama = ollama_base_url.rstrip("/")
        self._timeout = timeout
        self._attempts = max_attempts

    def _build(
        self, system: str, user: str, json_mode: bool, temperature: float
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        if self.provider == "gemini":
            config: dict[str, Any] = {"temperature": temperature}
            if json_mode:
                config["responseMimeType"] = "application/json"
            return (
                GEMINI_URL.format(model=self.model),
                {"x-goog-api-key": self._keys["gemini"], "Content-Type": "application/json"},
                {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": config,
                },
            )
        url = GROQ_URL if self.provider == "groq" else f"{self._ollama}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.provider == "groq":
            headers["Authorization"] = f"Bearer {self._keys['groq']}"
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return url, headers, body

    @staticmethod
    def _wait(response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("retry-after")
        try:
            if header:
                return min(float(header), 60.0) + 1
        except ValueError:
            pass
        match = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)s", response.text)
        if match:
            return min(int(match.group(1) or 0) * 60 + float(match.group(2)), 60.0) + 1
        return min(2.0 * 2**attempt, 30.0)

    def complete(
        self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.2
    ) -> str:
        url, headers, body = self._build(system, user, json_mode, temperature)
        last = "no response"
        for attempt in range(self._attempts):
            try:
                response = httpx.post(url, headers=headers, json=body, timeout=self._timeout)
            except httpx.TransportError as exc:
                last = type(exc).__name__
                time.sleep(min(2.0 * 2**attempt, 30.0))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last = f"HTTP {response.status_code}"
                if "per day" in response.text.lower():
                    raise LLMError("daily quota used up; try later or switch model or provider")
                time.sleep(self._wait(response, attempt))
                continue
            if response.status_code >= 400:
                detail = response.text[:200]
                raise LLMError(f"{self.provider} returned HTTP {response.status_code}: {detail}")
            data = response.json()
            if self.provider == "gemini":
                return data["candidates"][0]["content"]["parts"][0]["text"]
            return data["choices"][0]["message"]["content"]
        raise LLMError(f"{self.provider} kept failing ({last})")
