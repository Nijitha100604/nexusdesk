import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from .base import ServiceNowClient
from .constants import INACTIVE_STATES, calculate_priority
from .errors import ServiceNowError, ServiceNowNotFoundError, ServiceNowValidationError
from .instance import InstanceConfig
from .models import Incident, KnowledgeArticle
from .validation import (
    NUMBER_RE,
    SYS_ID_RE,
    clean_text,
    prepare_create,
    prepare_resolve,
    prepare_update,
    require_idempotency_key,
    require_sys_id,
)

_FMT = "%Y-%m-%d %H:%M:%S"
_KB_NS = uuid.UUID("5a1c0d0e-0000-4000-8000-000000000001")


def _now() -> str:
    return datetime.now(UTC).strftime(_FMT)


def _article(number: str, title: str, body: str, updated: str) -> KnowledgeArticle:
    return KnowledgeArticle(
        sys_id=uuid.uuid5(_KB_NS, number).hex,
        number=number,
        short_description=title,
        text=f"<h2>{title}</h2>{body}",
        kb_knowledge_base="b" * 32,
        workflow_state="published",
        valid_to="2100-01-01",
        sys_updated_on=updated,
    )


def default_articles() -> list[KnowledgeArticle]:
    return [
        _article(
            "KB0900001",
            "VPN connection times out",
            "<p>Symptoms: client shows a timeout.</p><ol><li>Check your internet.</li>"
            "<li>Restart the VPN client.</li><li>Reinstall the client if it persists.</li></ol>",
            "2026-10-01 09:00:00",
        ),
        _article(
            "KB0900002",
            "Reset a forgotten password",
            "<p>Use the self-service portal and verify with MFA. Locked accounts unlock "
            "after 30 minutes or via the Service Desk.</p>",
            "2026-10-02 09:00:00",
        ),
        _article(
            "KB0900003",
            "Outlook keeps asking for a password",
            "<ol><li>Close Outlook.</li><li>Remove saved credentials in Credential Manager."
            "</li><li>Reopen Outlook and sign in again.</li></ol>",
            "2026-10-03 09:00:00",
        ),
        _article(
            "KB0900004",
            "Printer shows offline",
            "<p>Power-cycle the printer, check it is on the same network, then re-add it "
            "from Settings.</p>",
            "2026-10-04 09:00:00",
        ),
    ]


class MockServiceNowClient(ServiceNowClient):
    """In-memory stand-in with the same rules as the live client."""

    def __init__(
        self,
        instance_config: InstanceConfig,
        *,
        kb_articles: list[KnowledgeArticle] | None = None,
    ) -> None:
        self._config = instance_config
        self._records: dict[str, dict[str, str]] = {}
        self._work_notes: dict[str, list[str]] = {}
        self._comments: dict[str, list[str]] = {}
        self._counter = 1000
        self._articles = list(default_articles() if kb_articles is None else kb_articles)
        self._failures: list[ServiceNowError] = []
        self.calls: list[str] = []

    # --- test helpers -------------------------------------------------
    def fail_next(self, error: ServiceNowError, times: int = 1) -> None:
        self._failures.extend([error] * times)

    def work_notes(self, sys_id: str) -> list[str]:
        return list(self._work_notes.get(sys_id, []))

    def comments(self, sys_id: str) -> list[str]:
        return list(self._comments.get(sys_id, []))

    # --- internals ----------------------------------------------------
    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if self._failures:
            raise self._failures.pop(0)

    def _record(self, sys_id: str) -> dict[str, str]:
        require_sys_id(sys_id)
        try:
            return self._records[sys_id]
        except KeyError:
            raise ServiceNowNotFoundError(f"No incident with sys_id {sys_id}") from None

    # --- interface ----------------------------------------------------
    def ping(self) -> bool:
        self._enter("ping")
        return True

    def create_incident(
        self,
        *,
        short_description: str,
        description: str,
        category: str,
        urgency: str,
        impact: str,
        caller_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Incident:
        self._enter("create_incident")
        body = prepare_create(short_description, description, category, urgency, impact, caller_id)
        if idempotency_key is not None:
            require_idempotency_key(idempotency_key)
            for rec in self._records.values():
                if rec["correlation_id"] == idempotency_key:
                    return Incident(**rec)
        self._counter += 1
        now = _now()
        rec = {
            "sys_id": uuid.uuid4().hex,
            "number": f"INC{self._counter:07d}",
            "short_description": body["short_description"],
            "description": body["description"],
            "category": body["category"],
            "urgency": body["urgency"],
            "impact": body["impact"],
            "priority": calculate_priority(body["impact"], body["urgency"]),
            "state": "1",
            "assignment_group": "",
            "caller_id": body.get("caller_id", ""),
            "close_code": "",
            "close_notes": "",
            "correlation_id": idempotency_key or uuid.uuid4().hex,
            "opened_at": now,
            "sys_updated_on": now,
        }
        self._records[rec["sys_id"]] = rec
        return Incident(**rec)

    def get_incident(self, identifier: str) -> Incident:
        self._enter("get_incident")
        if NUMBER_RE.match(identifier):
            for rec in self._records.values():
                if rec["number"] == identifier:
                    return Incident(**rec)
            raise ServiceNowNotFoundError(f"No incident {identifier}")
        if SYS_ID_RE.match(identifier):
            return Incident(**self._record(identifier))
        raise ServiceNowValidationError("identifier must be an INC number or a sys_id")

    def search_incidents(
        self,
        *,
        active_only: bool = True,
        category: str | None = None,
        state: str | None = None,
        caller_id: str | None = None,
        group_name: str | None = None,
        text: str | None = None,
        limit: int = 10,
    ) -> list[Incident]:
        self._enter("search_incidents")
        group_id = self._config.group_id(group_name) if group_name else None
        found = []
        for rec in reversed(list(self._records.values())):  # newest first
            if active_only and rec["state"] in INACTIVE_STATES:
                continue
            if category and rec["category"] != category:
                continue
            if state and rec["state"] != state:
                continue
            if caller_id and rec["caller_id"] != caller_id:
                continue
            if group_id and rec["assignment_group"] != group_id:
                continue
            if text and text.lower() not in rec["short_description"].lower():
                continue
            found.append(Incident(**rec))
        return found[: max(1, min(limit, 50))]

    def _touch(self, rec: dict[str, str]) -> Incident:
        rec["sys_updated_on"] = _now()
        return Incident(**rec)

    def add_work_note(self, sys_id: str, note: str) -> Incident:
        self._enter("add_work_note")
        rec = self._record(sys_id)
        self._work_notes.setdefault(sys_id, []).append(clean_text(note, "note"))
        return self._touch(rec)

    def add_comment(self, sys_id: str, comment: str) -> Incident:
        self._enter("add_comment")
        rec = self._record(sys_id)
        self._comments.setdefault(sys_id, []).append(clean_text(comment, "comment"))
        return self._touch(rec)

    def update_incident(self, sys_id: str, fields: Mapping[str, str]) -> Incident:
        self._enter("update_incident")
        changes = prepare_update(fields)
        rec = self._record(sys_id)
        rec.update(changes)
        rec["priority"] = calculate_priority(rec["impact"], rec["urgency"])
        return self._touch(rec)

    def resolve_incident(self, sys_id: str, close_code: str, close_notes: str) -> Incident:
        self._enter("resolve_incident")
        changes = prepare_resolve(close_code, close_notes)
        rec = self._record(sys_id)
        rec.update(changes)
        return self._touch(rec)

    def reassign_incident(self, sys_id: str, group_name: str, note: str | None = None) -> Incident:
        self._enter("reassign_incident")
        group_id = self._config.group_id(group_name)
        rec = self._record(sys_id)
        if note:
            self._work_notes.setdefault(sys_id, []).append(clean_text(note, "note"))
        rec["assignment_group"] = group_id
        return self._touch(rec)

    def fetch_knowledge_articles(
        self, *, limit: int = 50, offset: int = 0, updated_since: datetime | None = None
    ) -> list[KnowledgeArticle]:
        self._enter("fetch_knowledge_articles")
        items = [a for a in self._articles if a.workflow_state == "published"]
        if updated_since:
            cutoff = updated_since.strftime(_FMT)
            items = [a for a in items if a.sys_updated_on > cutoff]
        items.sort(key=lambda a: a.sys_updated_on)
        return items[offset : offset + limit]
