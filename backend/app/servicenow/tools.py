import functools
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .base import ServiceNowClient
from .constants import (
    AUTO_RESOLVE_PRIORITIES,
    CLOSE_CODE_BY_CALLER,
    CLOSE_CODE_PERMANENT_FIX,
    CLOSE_CODE_WORKAROUND,
    INACTIVE_STATES,
    NEXUS_CATEGORIES,
)
from .context import request_id_var
from .errors import ServiceNowError

NexusCategory = Literal[
    "network_vpn",
    "software_access",
    "hardware",
    "email_collaboration",
    "account_password",
    "other",
]
Level = Literal["1", "2", "3"]
GroupName = Literal[
    "Service Desk", "Network Support", "Software Support", "Hardware Support", "Messaging Support"
]
Resolution = Literal["employee_confirmed", "permanent_fix", "workaround"]
SYS_ID = r"^[0-9a-f]{32}$"
IDENTIFIER = r"^(INC\d{7,}|[0-9a-f]{32})$"

RESOLUTION_CODES = {
    "employee_confirmed": CLOSE_CODE_BY_CALLER,
    "permanent_fix": CLOSE_CODE_PERMANENT_FIX,
    "workaround": CLOSE_CODE_WORKAROUND,
}

READ_TOOL_NAMES = frozenset({"get_ticket", "search_tickets"})
WRITE_TOOL_NAMES = frozenset(
    {
        "create_ticket",
        "add_work_note",
        "add_customer_comment",
        "update_ticket",
        "resolve_ticket",
        "escalate_ticket",
    }
)
SYNC_TOOL_NAMES = frozenset({"list_knowledge_articles"})  # for workers, not for agents


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateTicketArgs(_Args):
    short_description: str = Field(min_length=5, max_length=160, description="One-line summary.")
    description: str = Field(min_length=5, max_length=4000, description="Details of the problem.")
    category: NexusCategory = Field(description="Best matching category.")
    urgency: Level = Field(
        description="1 = work blocked, no workaround; 2 = workaround exists; 3 = minor."
    )
    impact: Level = Field(
        description="1 = company or department; 2 = team or several users; 3 = one user."
    )
    caller_id: str | None = Field(
        default=None, pattern=SYS_ID, description="sys_id of the employee."
    )


class GetTicketArgs(_Args):
    identifier: str = Field(pattern=IDENTIFIER, description="Ticket number (INC0010001) or sys_id.")


class SearchTicketsArgs(_Args):
    text: str | None = Field(
        default=None, min_length=2, max_length=100, description="Words in the summary."
    )
    caller_id: str | None = Field(
        default=None, pattern=SYS_ID, description="Only this employee's tickets."
    )
    active_only: bool = Field(default=True, description="Hide resolved and closed tickets.")
    limit: int = Field(default=10, ge=1, le=25)


class AddNoteArgs(_Args):
    sys_id: str = Field(pattern=SYS_ID)
    note: str = Field(
        min_length=3, max_length=4000, description="Internal note, not visible to the employee."
    )


class AddCommentArgs(_Args):
    sys_id: str = Field(pattern=SYS_ID)
    comment: str = Field(
        min_length=3, max_length=4000, description="Message the employee will see."
    )


class UpdateTicketArgs(_Args):
    sys_id: str = Field(pattern=SYS_ID)
    short_description: str | None = Field(default=None, min_length=5, max_length=160)
    description: str | None = Field(default=None, min_length=5, max_length=4000)
    category: NexusCategory | None = None
    urgency: Level | None = None
    impact: Level | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "UpdateTicketArgs":
        changes = (
            self.short_description,
            self.description,
            self.category,
            self.urgency,
            self.impact,
        )
        if all(v is None for v in changes):
            raise ValueError("provide at least one field to change")
        return self


class ResolveTicketArgs(_Args):
    sys_id: str = Field(pattern=SYS_ID)
    resolution: Resolution = Field(description="How it was resolved.")
    close_notes: str = Field(min_length=5, max_length=4000, description="What fixed it.")


class EscalateTicketArgs(_Args):
    sys_id: str = Field(pattern=SYS_ID)
    group_name: GroupName
    reason: str = Field(min_length=10, max_length=500, description="Why a human is needed.")


class ListArticlesArgs(_Args):
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


def _ok(**payload: Any) -> dict[str, Any]:
    return {"ok": True, **payload}


def _fail(error: str, message: str, *, detail: str = "", retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "message": message,
        "detail": detail,
        "retryable": retryable,
    }


def _safe(func):
    """Turn ServiceNow errors into data the agent can reason about."""

    @functools.wraps(func)
    def wrapper(**kwargs: Any) -> dict[str, Any]:
        try:
            return func(**kwargs)
        except ServiceNowError as exc:
            return _fail(
                type(exc).__name__, exc.message, detail=exc.detail, retryable=exc.retryable
            )

    return wrapper


def _ticket(incident) -> dict[str, str]:
    return {k: v for k, v in incident.model_dump().items() if v}


def _format_validation_error(exc: ValidationError) -> str:
    problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return "Invalid tool input - " + "; ".join(problems)


def build_tools(client: ServiceNowClient) -> dict[str, StructuredTool]:
    """Create the tool set bound to one client (mock or live)."""

    @_safe
    def create_ticket(**kw: Any) -> dict[str, Any]:
        sn_category, _group = NEXUS_CATEGORIES[kw["category"]]
        run_id = request_id_var.get()
        incident = client.create_incident(
            short_description=kw["short_description"],
            description=kw["description"],
            category=sn_category,
            urgency=kw["urgency"],
            impact=kw["impact"],
            caller_id=kw.get("caller_id"),
            idempotency_key=f"{run_id}:create" if run_id else None,
        )
        return _ok(ticket=_ticket(incident))

    @_safe
    def get_ticket(identifier: str) -> dict[str, Any]:
        return _ok(ticket=_ticket(client.get_incident(identifier)))

    @_safe
    def search_tickets(**kw: Any) -> dict[str, Any]:
        found = client.search_incidents(**kw)
        return _ok(count=len(found), tickets=[_ticket(i) for i in found])

    @_safe
    def add_work_note(sys_id: str, note: str) -> dict[str, Any]:
        return _ok(ticket=_ticket(client.add_work_note(sys_id, note)))

    @_safe
    def add_customer_comment(sys_id: str, comment: str) -> dict[str, Any]:
        return _ok(ticket=_ticket(client.add_comment(sys_id, comment)))

    @_safe
    def update_ticket(sys_id: str, **kw: Any) -> dict[str, Any]:
        fields = {k: v for k, v in kw.items() if v is not None}
        if "category" in fields:
            fields["category"] = NEXUS_CATEGORIES[fields["category"]][0]
        return _ok(ticket=_ticket(client.update_incident(sys_id, fields)))

    @_safe
    def resolve_ticket(sys_id: str, resolution: str, close_notes: str) -> dict[str, Any]:
        incident = client.get_incident(sys_id)
        if incident.state in INACTIVE_STATES:
            return _fail("AlreadyResolved", f"{incident.number} is already resolved or closed.")
        if incident.priority not in AUTO_RESOLVE_PRIORITIES:
            return _fail(
                "ApprovalRequired",
                f"{incident.number} has priority {incident.priority or 'unknown'}; "
                "only P3 to P5 can be resolved automatically. Propose it for human approval.",
            )
        resolved = client.resolve_incident(sys_id, RESOLUTION_CODES[resolution], close_notes)
        return _ok(ticket=_ticket(resolved))

    @_safe
    def escalate_ticket(sys_id: str, group_name: str, reason: str) -> dict[str, Any]:
        updated = client.reassign_incident(
            sys_id, group_name, note=f"Escalated by NexusDesk: {reason}"
        )
        return _ok(ticket=_ticket(updated))

    @_safe
    def list_knowledge_articles(limit: int = 10, offset: int = 0) -> dict[str, Any]:
        articles = client.fetch_knowledge_articles(limit=limit, offset=offset)
        return _ok(
            articles=[
                {
                    "number": a.number,
                    "short_description": a.short_description,
                    "text_preview": a.text[:500],
                    "updated": a.sys_updated_on,
                }
                for a in articles
            ]
        )

    specs = [
        (
            create_ticket,
            "create_ticket",
            CreateTicketArgs,
            "Create a new IT ticket in ServiceNow. Call once per employee issue, after triage. "
            "Returns the ticket number and sys_id; use the sys_id in later calls.",
        ),
        (
            get_ticket,
            "get_ticket",
            GetTicketArgs,
            "Read one ticket by number (INC0010001) or sys_id.",
        ),
        (
            search_tickets,
            "search_tickets",
            SearchTicketsArgs,
            "Search existing tickets by words in the summary and/or caller."
            "Use it to spot duplicates.",
        ),
        (
            add_work_note,
            "add_work_note",
            AddNoteArgs,
            "Add an INTERNAL note to a ticket (reasoning, sources, decisions)."
            "The employee cannot see it.",
        ),
        (
            add_customer_comment,
            "add_customer_comment",
            AddCommentArgs,
            "Send a message the EMPLOYEE WILL SEE on the ticket. Keep it clear and polite.",
        ),
        (
            update_ticket,
            "update_ticket",
            UpdateTicketArgs,
            "Correct a ticket's summary, description, category, urgency or impact. "
            "It cannot change state, priority or assignment.",
        ),
        (
            resolve_ticket,
            "resolve_ticket",
            ResolveTicketArgs,
            "Resolve a low-priority (P3 to P5) ticket after the employee confirmed the fix. "
            "Refuses P1 and P2 tickets, which need human approval.",
        ),
        (
            escalate_ticket,
            "escalate_ticket",
            EscalateTicketArgs,
            "Hand the ticket to a human support group with a reason."
            "Use when unsure, when the issue "
            "is critical or security-related, or after two failed attempts.",
        ),
        (
            list_knowledge_articles,
            "list_knowledge_articles",
            ListArticlesArgs,
            "List published knowledge articles (for sync jobs; "
            "agents should use the RAG search instead).",
        ),
    ]
    return {
        name: StructuredTool.from_function(
            func=func,
            name=name,
            description=description,
            args_schema=schema,
            handle_validation_error=_format_validation_error,
        )
        for func, name, schema, description in specs
    }
