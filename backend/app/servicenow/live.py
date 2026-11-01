import random
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import httpx

from .base import ServiceNowClient
from .constants import SN_CATEGORIES, STATE_VALUES
from .errors import (
    ServiceNowAuthError,
    ServiceNowDataPolicyError,
    ServiceNowError,
    ServiceNowForbiddenError,
    ServiceNowNotFoundError,
    ServiceNowRateLimitError,
    ServiceNowUnavailableError,
    ServiceNowValidationError,
)
from .instance import InstanceConfig
from .models import INCIDENT_FIELDS, KB_FIELDS, Incident, KnowledgeArticle
from .validation import (
    NUMBER_RE,
    SYS_ID_RE,
    clean_text,
    prepare_create,
    prepare_resolve,
    prepare_update,
    require_choice,
    require_idempotency_key,
    require_sys_id,
    safe_query_value,
)

RETRY_STATUS = {429, 502, 503, 504}


def build_incident_query(
    *,
    active_only: bool,
    category: str | None,
    state: str | None,
    caller_id: str | None,
    group_id: str | None,
    text: str | None,
) -> str:
    parts = []
    if active_only:
        parts.append("active=true")
    if category:
        parts.append(f"category={require_choice(category, SN_CATEGORIES, 'category')}")
    if state:
        parts.append(f"state={require_choice(state, STATE_VALUES, 'state')}")
    if caller_id:
        parts.append(f"caller_id={require_sys_id(caller_id, 'caller_id')}")
    if group_id:
        parts.append(f"assignment_group={require_sys_id(group_id, 'group_id')}")
    if text:
        parts.append(f"short_descriptionLIKE{safe_query_value(text)}")
    parts.append("ORDERBYDESCsys_created_on")
    return "^".join(parts)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return min(float(raw), 30.0) if raw else None
    except ValueError:
        return None


class LiveServiceNowClient(ServiceNowClient):
    def __init__(
        self,
        instance_url: str,
        username: str,
        password: str,
        *,
        instance_config: InstanceConfig,
        kb_sys_id: str = "",
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not instance_url.startswith("https://"):
            raise ValueError("instance_url must start with https://")
        self._table_url = f"{instance_url.rstrip('/')}/api/now/table"
        self._config = instance_config
        self._kb_sys_id = kb_sys_id
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._sleep = sleep
        self._http = httpx.Client(
            auth=(username, password),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    # --- transport ----------------------------------------------------
    def _delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return retry_after
        delay = min(self._backoff_max, self._backoff_base * 2**attempt)
        return delay + random.uniform(0, self._backoff_base)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        url = f"{self._table_url}/{path}"
        attempts = self._max_retries + 1 if retry else 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = self._http.request(method, url, params=params, json=json)
            except httpx.TransportError as exc:  # includes timeouts
                if last:
                    raise ServiceNowUnavailableError(
                        f"ServiceNow did not respond ({type(exc).__name__})"
                    ) from exc
                self._sleep(self._delay(attempt))
                continue
            if response.status_code in RETRY_STATUS and not last:
                self._sleep(self._delay(attempt, _retry_after(response)))
                continue
            return self._unwrap(response)
        raise AssertionError("unreachable")

    @staticmethod
    def _unwrap(response: httpx.Response) -> Any:
        code = response.status_code
        if "json" not in response.headers.get("content-type", ""):
            raise ServiceNowUnavailableError(
                "ServiceNow returned a non-JSON response; the instance may be hibernating",
                status_code=code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceNowUnavailableError("ServiceNow returned invalid JSON") from exc
        if code < 400:
            return payload.get("result")

        error = payload.get("error") or {}
        message = str(error.get("message") or f"HTTP {code}")
        detail = str(error.get("detail") or "")
        info = {"status_code": code, "detail": detail}
        if code == 400:
            raise ServiceNowValidationError(message, **info)
        if code == 401:
            raise ServiceNowAuthError(message, **info)
        if code == 403:
            if "data policy" in f"{message} {detail}".lower():
                raise ServiceNowDataPolicyError(message, **info)
            raise ServiceNowForbiddenError(message, **info)
        if code == 404:
            raise ServiceNowNotFoundError(message, **info)
        if code == 429:
            raise ServiceNowRateLimitError(message, **info)
        if code >= 500:
            raise ServiceNowUnavailableError(message, **info)
        raise ServiceNowError(message, **info)

    # --- helpers ------------------------------------------------------
    def _patch(self, sys_id: str, body: Mapping[str, Any]) -> Incident:
        require_sys_id(sys_id)
        record = self._request(
            "PATCH",
            f"incident/{sys_id}",
            params={"sysparm_fields": INCIDENT_FIELDS},
            json=body,
        )
        return Incident.from_api(record)

    def _find_by_correlation_id(self, key: str) -> Incident | None:
        records = self._request(
            "GET",
            "incident",
            params={
                "sysparm_query": f"correlation_id={key}",
                "sysparm_fields": INCIDENT_FIELDS,
                "sysparm_limit": 1,
            },
        )
        return Incident.from_api(records[0]) if records else None

    # --- interface ----------------------------------------------------
    def ping(self) -> bool:
        try:
            self._request(
                "GET", "incident", params={"sysparm_limit": 1, "sysparm_fields": "number"}
            )
        except ServiceNowError:
            return False
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
        body: dict[str, Any] = prepare_create(
            short_description, description, category, urgency, impact, caller_id
        )
        if idempotency_key is not None:
            require_idempotency_key(idempotency_key)
        key = idempotency_key or uuid.uuid4().hex
        body["correlation_id"] = key

        attempts = self._max_retries + 1
        for attempt in range(attempts):
            # A caller-supplied key may already exist; after any failed attempt the
            # ticket may have been created even though the response was lost.
            if idempotency_key is not None or attempt > 0:
                existing = self._find_by_correlation_id(key)
                if existing:
                    return existing
            try:
                record = self._request(
                    "POST",
                    "incident",
                    params={"sysparm_fields": INCIDENT_FIELDS},
                    json=body,
                    retry=False,
                )
                return Incident.from_api(record)
            except (ServiceNowUnavailableError, ServiceNowRateLimitError):
                if attempt == attempts - 1:
                    raise
                self._sleep(self._delay(attempt))
        raise AssertionError("unreachable")

    def get_incident(self, identifier: str) -> Incident:
        if NUMBER_RE.match(identifier):
            records = self._request(
                "GET",
                "incident",
                params={
                    "sysparm_query": f"number={identifier}",
                    "sysparm_fields": INCIDENT_FIELDS,
                    "sysparm_limit": 1,
                },
            )
            if not records:
                raise ServiceNowNotFoundError(f"No incident {identifier}")
            return Incident.from_api(records[0])
        if SYS_ID_RE.match(identifier):
            record = self._request(
                "GET", f"incident/{identifier}", params={"sysparm_fields": INCIDENT_FIELDS}
            )
            return Incident.from_api(record)
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
        query = build_incident_query(
            active_only=active_only,
            category=category,
            state=state,
            caller_id=caller_id,
            group_id=self._config.group_id(group_name) if group_name else None,
            text=text,
        )
        records = self._request(
            "GET",
            "incident",
            params={
                "sysparm_query": query,
                "sysparm_fields": INCIDENT_FIELDS,
                "sysparm_limit": max(1, min(limit, 50)),
            },
        )
        return [Incident.from_api(r) for r in records]

    def add_work_note(self, sys_id: str, note: str) -> Incident:
        return self._patch(sys_id, {"work_notes": clean_text(note, "note")})

    def add_comment(self, sys_id: str, comment: str) -> Incident:
        return self._patch(sys_id, {"comments": clean_text(comment, "comment")})

    def update_incident(self, sys_id: str, fields: Mapping[str, str]) -> Incident:
        return self._patch(sys_id, prepare_update(fields))

    def resolve_incident(self, sys_id: str, close_code: str, close_notes: str) -> Incident:
        return self._patch(sys_id, prepare_resolve(close_code, close_notes))

    def reassign_incident(self, sys_id: str, group_name: str, note: str | None = None) -> Incident:
        body = {"assignment_group": self._config.group_id(group_name)}
        if note:
            body["work_notes"] = clean_text(note, "note")
        return self._patch(sys_id, body)

    def fetch_knowledge_articles(
        self, *, limit: int = 50, offset: int = 0, updated_since: datetime | None = None
    ) -> list[KnowledgeArticle]:
        if not self._kb_sys_id:
            raise ServiceNowValidationError("SN_KB_SYS_ID is not set; refusing to read all bases")
        parts = [
            "workflow_state=published",
            "active=true",
            f"kb_knowledge_base={require_sys_id(self._kb_sys_id, 'SN_KB_SYS_ID')}",
        ]
        if updated_since:
            parts.append(f"sys_updated_on>{updated_since.strftime('%Y-%m-%d %H:%M:%S')}")
        parts.append("ORDERBYsys_updated_on")
        records = self._request(
            "GET",
            "kb_knowledge",
            params={
                "sysparm_query": "^".join(parts),
                "sysparm_fields": KB_FIELDS,
                "sysparm_limit": max(1, min(limit, 100)),
                "sysparm_offset": max(0, offset),
            },
        )
        return [KnowledgeArticle.from_api(r) for r in records]
