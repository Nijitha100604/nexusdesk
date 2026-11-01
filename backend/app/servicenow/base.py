from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from datetime import datetime

from .models import Incident, KnowledgeArticle


class ServiceNowClient(ABC):
    """Everything NexusDesk needs from ServiceNow. Live and mock both implement this."""

    @abstractmethod
    def ping(self) -> bool: ...

    @abstractmethod
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
        """Same idempotency_key twice returns the same ticket, never a duplicate."""

    @abstractmethod
    def get_incident(self, identifier: str) -> Incident:
        """identifier is an INC number or a sys_id."""

    @abstractmethod
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
    ) -> list[Incident]: ...

    @abstractmethod
    def add_work_note(self, sys_id: str, note: str) -> Incident:
        """Internal note (not visible to the employee)."""

    @abstractmethod
    def add_comment(self, sys_id: str, comment: str) -> Incident:
        """Customer-visible comment."""

    @abstractmethod
    def update_incident(self, sys_id: str, fields: Mapping[str, str]) -> Incident: ...

    @abstractmethod
    def resolve_incident(self, sys_id: str, close_code: str, close_notes: str) -> Incident: ...

    @abstractmethod
    def reassign_incident(
        self, sys_id: str, group_name: str, note: str | None = None
    ) -> Incident: ...

    @abstractmethod
    def fetch_knowledge_articles(
        self, *, limit: int = 50, offset: int = 0, updated_since: datetime | None = None
    ) -> list[KnowledgeArticle]: ...

    def iter_knowledge_articles(
        self, *, page_size: int = 50, updated_since: datetime | None = None
    ) -> Iterator[KnowledgeArticle]:
        """Page through all published articles (used by the Phase 6 sync worker)."""
        offset = 0
        while True:
            page = self.fetch_knowledge_articles(
                limit=page_size, offset=offset, updated_since=updated_since
            )
            yield from page
            if len(page) < page_size:
                return
            offset += page_size
