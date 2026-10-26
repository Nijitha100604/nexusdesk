"""Check that configured LLM providers are reachable. Run from repo root:
python scripts/check_env.py"""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import get_settings


def check(name: str, url: str, **kwargs) -> None:
    try:
        r = httpx.get(url, timeout=10, **kwargs)
        status = "OK" if r.status_code == 200 else "FAILED"
        print(f"{name:8} {status} (HTTP {r.status_code})")
    except Exception as exc:  # noqa: BLE001
        print(f"{name:8} UNREACHABLE ({type(exc).__name__})")


s = get_settings()

if s.groq_api_key:
    check(
        "Groq",
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {s.groq_api_key}"},
    )
else:
    print("Groq     no key set")

if s.gemini_api_key:
    check(
        "Gemini",
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": s.gemini_api_key},
    )
else:
    print("Gemini   no key set")

check("Ollama", f"{s.ollama_base_url}/api/tags")
