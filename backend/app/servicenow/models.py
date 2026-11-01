from typing import Any, Self

from pydantic import BaseModel, ConfigDict


def _plain(value: Any) -> str:
    """Reference fields arrive as {"link": ..., "value": ...}; empty ones as ''."""
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return "" if value is None else str(value)


class _ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> Self:
        return cls(**{name: _plain(record.get(name)) for name in cls.model_fields})


class Incident(_ApiModel):
    sys_id: str
    number: str
    short_description: str = ""
    description: str = ""
    category: str = ""
    urgency: str = ""
    impact: str = ""
    priority: str = ""
    state: str = ""
    assignment_group: str = ""  # sys_id
    caller_id: str = ""  # sys_id
    close_code: str = ""
    close_notes: str = ""
    correlation_id: str = ""
    opened_at: str = ""
    sys_updated_on: str = ""


class KnowledgeArticle(_ApiModel):
    sys_id: str
    number: str
    short_description: str = ""
    text: str = ""  # HTML body, cleaned in Phase 6
    kb_knowledge_base: str = ""
    workflow_state: str = ""
    valid_to: str = ""
    sys_updated_on: str = ""


INCIDENT_FIELDS = ",".join(Incident.model_fields)
KB_FIELDS = ",".join(KnowledgeArticle.model_fields)
