"""Shared helpers for the Phase 5 seed scripts.

The scripts import only from this module, so the sys.path setup below always runs first.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from app.servicenow.constants import (
    CLOSE_CODE_BY_CALLER,
    CLOSE_CODE_PERMANENT_FIX,
    CLOSE_CODE_WORKAROUND,
    NEXUS_CATEGORIES,
    calculate_priority,
)
from app.servicenow.errors import ServiceNowError  # noqa: F401

DATA_DIR = ROOT / "data" / "synthetic"
EVAL_DIR = ROOT / "data" / "eval"
ARTICLES_FILE = DATA_DIR / "articles.jsonl"
INCIDENTS_FILE = DATA_DIR / "incidents.jsonl"
MANIFEST_FILE = DATA_DIR / "seed_manifest.json"
REVIEW_FILE = DATA_DIR / "REVIEW.md"
EVAL_FILE = EVAL_DIR / "test_tickets.jsonl"

CATEGORIES = tuple(NEXUS_CATEGORIES)
CATEGORY_CODES = {
    "network_vpn": "NET",
    "software_access": "SFT",
    "hardware": "HWR",
    "email_collaboration": "EML",
    "account_password": "ACC",
    "other": "OTH",
}
CATEGORY_LABELS = {
    "network_vpn": "Network and VPN",
    "software_access": "Software and Access",
    "hardware": "Hardware",
    "email_collaboration": "Email and Collaboration",
    "account_password": "Account and Password",
    "other": "Other",
}
INCIDENT_PLAN = {
    "network_vpn": 24,
    "software_access": 24,
    "hardware": 20,
    "email_collaboration": 20,
    "account_password": 20,
    "other": 12,
}
RESOLUTION_TYPES = {
    "employee_fixed": CLOSE_CODE_BY_CALLER,
    "permanent_fix": CLOSE_CODE_PERMANENT_FIX,
    "workaround": CLOSE_CODE_WORKAROUND,
}
ROUTES = ("answer", "clarify", "approval", "escalate", "refuse")


# ---------------------------------------------------------------- files
def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------- validation
def _text(errors: list[str], d: dict, field: str, lo: int, hi: int) -> str:
    value = d.get(field)
    if not isinstance(value, str):
        errors.append(f"{field}: must be text")
        return ""
    value = value.strip()
    if not lo <= len(value) <= hi:
        errors.append(f"{field}: length {len(value)} not in {lo}-{hi}")
    if "<" in value or ">" in value:
        errors.append(f"{field}: must not contain < or >")
    return value


def _list(
    errors: list[str], d: dict, field: str, n_lo: int, n_hi: int, lo: int, hi: int
) -> None:
    value = d.get(field)
    if not isinstance(value, list) or not n_lo <= len(value) <= n_hi:
        errors.append(f"{field}: must be a list of {n_lo}-{n_hi} items")
        return
    for i, item in enumerate(value):
        if not isinstance(item, str) or not lo <= len(item.strip()) <= hi:
            errors.append(f"{field}[{i}]: must be text of {lo}-{hi} characters")
        elif "<" in item or ">" in item:
            errors.append(f"{field}[{i}]: must not contain < or >")


def clean_item(text: str) -> str:
    """Remove list numbering or bullets that models like to add."""
    return re.sub(r"^\s*(?:\d+[.)]|[-*\u2022])\s*", "", str(text)).strip()


def normalize_article_body(obj: dict[str, Any]) -> dict[str, Any]:
    out = dict(obj)
    for key in ("symptoms", "resolution_steps", "keywords"):
        if isinstance(out.get(key), list):
            out[key] = [clean_item(x) for x in out[key]]
    for key in ("title", "cause", "escalate_if"):
        if isinstance(out.get(key), str):
            out[key] = " ".join(out[key].split())
    return out


def validate_article_body(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return ["response must be a JSON object"]
    errors: list[str] = []
    title = _text(errors, obj, "title", 15, 120)
    if "^" in title:
        errors.append("title: must not contain ^")
    _list(errors, obj, "symptoms", 2, 5, 10, 220)
    _text(errors, obj, "cause", 20, 450)
    _list(errors, obj, "resolution_steps", 3, 9, 10, 320)
    _text(errors, obj, "escalate_if", 20, 320)
    _list(errors, obj, "keywords", 3, 8, 2, 40)
    return errors


def validate_article(d: dict[str, Any]) -> list[str]:
    errors = validate_article_body(d)
    if not re.fullmatch(r"ART-[A-Z]{3}-\d{3}", str(d.get("art_id", ""))):
        errors.append("art_id: bad format")
    if d.get("category") not in CATEGORIES:
        errors.append(f"category: must be one of {list(CATEGORIES)}")
    return errors


def normalize_ticket(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t)
    for key in ("urgency", "impact"):
        if key in out:
            out[key] = str(out[key]).strip()
    for key in ("short_description", "description", "close_notes"):
        if isinstance(out.get(key), str):
            out[key] = " ".join(out[key].split())
    return out


def validate_ticket_body(t: Any) -> list[str]:
    if not isinstance(t, dict):
        return ["ticket must be a JSON object"]
    errors: list[str] = []
    _text(errors, t, "short_description", 10, 120)
    _text(errors, t, "description", 30, 700)
    _text(errors, t, "close_notes", 20, 500)
    for key in ("urgency", "impact"):
        if t.get(key) not in ("1", "2", "3"):
            errors.append(f"{key}: must be 1, 2 or 3")
    if t.get("resolution_type") not in RESOLUTION_TYPES:
        errors.append(f"resolution_type: must be one of {list(RESOLUTION_TYPES)}")
    return errors


def validate_incident(d: dict[str, Any]) -> list[str]:
    errors = validate_ticket_body(d)
    if not re.fullmatch(r"INC-SEED-\d{4}", str(d.get("inc_id", ""))):
        errors.append("inc_id: bad format")
    if d.get("category") not in CATEGORIES:
        errors.append("category: invalid")
    if d.get("close_code") != RESOLUTION_TYPES.get(d.get("resolution_type")):
        errors.append("close_code: does not match resolution_type")
    return errors


def validate_eval(d: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not re.fullmatch(r"EV-\d{3}", str(d.get("eval_id", ""))):
        errors.append("eval_id: bad format")
    if d.get("split") not in ("dev", "test"):
        errors.append("split: must be dev or test")
    message = d.get("message")
    if not isinstance(message, str) or not 5 <= len(message.strip()) <= 800:
        errors.append("message: must be 5-800 characters")
    if d.get("expected_category") not in CATEGORIES:
        errors.append("expected_category: invalid")
    for key in ("expected_urgency", "expected_impact"):
        if d.get(key) not in ("1", "2", "3"):
            errors.append(f"{key}: must be 1, 2 or 3")
    labels_ok = d.get("expected_urgency") in ("1", "2", "3") and d.get(
        "expected_impact"
    ) in ("1", "2", "3")
    if labels_ok and d.get("expected_priority") != calculate_priority(
        d["expected_impact"], d["expected_urgency"]
    ):
        errors.append("expected_priority: does not match urgency and impact")
    if d.get("expected_route") not in ROUTES:
        errors.append(f"expected_route: must be one of {list(ROUTES)}")
    return errors


# ---------------------------------------------------------------- rendering
def render_article_html(a: dict[str, Any]) -> str:
    esc = html.escape
    symptoms = "".join(f"<li>{esc(s)}</li>" for s in a["symptoms"])
    steps = "".join(f"<li>{esc(s)}</li>" for s in a["resolution_steps"])
    return (
        f"<p><strong>Category:</strong> {esc(CATEGORY_LABELS[a['category']])}</p>"
        f"<h2>Symptoms</h2><ul>{symptoms}</ul>"
        f"<h2>Cause</h2><p>{esc(a['cause'])}</p>"
        f"<h2>Resolution</h2><ol>{steps}</ol>"
        f"<h2>When to escalate</h2><p>{esc(a['escalate_if'])}</p>"
        "<p><em>Synthetic demo article generated for the NexusDesk portfolio project.</em></p>"
    )


def article_text(a: dict[str, Any]) -> str:
    parts = [
        a["title"],
        *a["symptoms"],
        a["cause"],
        *a["resolution_steps"],
        a["escalate_if"],
    ]
    return " ".join(parts)


def trigrams(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + 3]) for i in range(len(words) - 2)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ---------------------------------------------------------------- ServiceNow (imported lazily)
def build_service_client():
    """The runtime service user (itil). Used to create and resolve the seed incidents."""
    from app.core.config import get_settings
    from app.servicenow import LiveServiceNowClient
    from app.servicenow.instance import load_instance_config

    s = get_settings()
    if not (s.sn_instance and s.sn_user and s.sn_password):
        raise SystemExit("SN_INSTANCE, SN_USER and SN_PASSWORD must be set in .env")
    config = load_instance_config(s.sn_config_path or None)
    if config.has_placeholders:
        raise SystemExit("backend/config/servicenow.json still has placeholder sys_ids")
    client = LiveServiceNowClient(
        s.sn_instance,
        s.sn_user,
        s.sn_password,
        instance_config=config,
        kb_sys_id=s.sn_kb_sys_id,
    )
    return client, config
