import re
from collections.abc import Iterable, Mapping

from .constants import CLOSE_CODES, IMPACT_VALUES, SN_CATEGORIES, URGENCY_VALUES
from .errors import ServiceNowValidationError

SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
NUMBER_RE = re.compile(r"^INC\d{7,}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")
_UNSAFE_QUERY_CHARS = re.compile(r"[\^\r\n\t]")

UPDATABLE_FIELDS = ("short_description", "description", "category", "urgency", "impact")


def require_sys_id(value: str, field: str = "sys_id") -> str:
    if not isinstance(value, str) or not SYS_ID_RE.match(value):
        raise ServiceNowValidationError(f"{field} must be a 32-character lowercase hex sys_id")
    return value


def require_choice(value: str, allowed: Iterable[str], field: str) -> str:
    options = tuple(allowed)
    if value not in options:
        raise ServiceNowValidationError(f"{field} must be one of {list(options)}, got {value!r}")
    return value


def clean_text(value: str, field: str, *, max_len: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceNowValidationError(f"{field} must not be empty")
    text = value.strip()
    if len(text) > max_len:
        raise ServiceNowValidationError(f"{field} is longer than {max_len} characters")
    return text


def safe_query_value(value: str, max_len: int = 100) -> str:
    """Stop user text from adding conditions to an encoded query (the ^ operator)."""
    cleaned = _UNSAFE_QUERY_CHARS.sub(" ", value).strip()
    if not cleaned:
        raise ServiceNowValidationError("search text must not be empty")
    return cleaned[:max_len]


def require_idempotency_key(key: str) -> str:
    if not KEY_RE.match(key):
        raise ServiceNowValidationError("idempotency_key must be 8-64 chars of A-Z a-z 0-9 _ . : -")
    return key


def prepare_create(
    short_description: str,
    description: str,
    category: str,
    urgency: str,
    impact: str,
    caller_id: str | None,
) -> dict[str, str]:
    body = {
        "short_description": clean_text(short_description, "short_description", max_len=160),
        "description": clean_text(description, "description"),
        "category": require_choice(category, SN_CATEGORIES, "category"),
        "urgency": require_choice(urgency, URGENCY_VALUES, "urgency"),
        "impact": require_choice(impact, IMPACT_VALUES, "impact"),
    }
    if caller_id:
        body["caller_id"] = require_sys_id(caller_id, "caller_id")
    return body


def prepare_update(fields: Mapping[str, str]) -> dict[str, str]:
    if not fields:
        raise ServiceNowValidationError("no fields to update")
    unknown = set(fields) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ServiceNowValidationError(
            f"fields not allowed in update: {sorted(unknown)}; allowed: {list(UPDATABLE_FIELDS)}"
        )
    out: dict[str, str] = {}
    for name, value in fields.items():
        if name == "short_description":
            out[name] = clean_text(value, name, max_len=160)
        elif name == "description":
            out[name] = clean_text(value, name)
        elif name == "category":
            out[name] = require_choice(value, SN_CATEGORIES, name)
        elif name == "urgency":
            out[name] = require_choice(value, URGENCY_VALUES, name)
        else:
            out[name] = require_choice(value, IMPACT_VALUES, name)
    return out


def prepare_resolve(close_code: str, close_notes: str) -> dict[str, str]:
    return {
        "state": "6",
        "close_code": require_choice(close_code, CLOSE_CODES, "close_code"),
        "close_notes": clean_text(close_notes, "close_notes"),
    }
