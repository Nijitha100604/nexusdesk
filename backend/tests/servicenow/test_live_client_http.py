import json

import httpx
import pytest

from app.servicenow import (
    ServiceNowAuthError,
    ServiceNowDataPolicyError,
    ServiceNowForbiddenError,
    ServiceNowUnavailableError,
    ServiceNowValidationError,
)
from app.servicenow.live import LiveServiceNowClient, build_incident_query

KB_ID = "b" * 32
CREATE = dict(
    short_description="VPN not connecting",
    description="Timeout on VPN client",
    category="network",
    urgency="2",
    impact="3",
)


def record(**over):
    base = {
        "sys_id": "a" * 32,
        "number": "INC0010001",
        "short_description": "VPN not connecting",
        "state": "1",
        "urgency": "2",
        "impact": "3",
        "priority": "4",
        "category": "network",
        "assignment_group": "",
        "caller_id": {"link": "https://x/api/now/table/sys_user/c", "value": "c" * 32},
        "correlation_id": "",
    }
    return {**base, **over}


def make_client(handler, instance_config, kb_sys_id=KB_ID, **kw):
    sleeps: list[float] = []
    client = LiveServiceNowClient(
        "https://dev00000.service-now.com",
        "svc",
        "secret",
        instance_config=instance_config,
        kb_sys_id=kb_sys_id,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    return client, sleeps


def test_retries_503_then_succeeds(instance_config):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"result": [record()]})

    client, sleeps = make_client(handler, instance_config)
    assert client.search_incidents()[0].number == "INC0010001"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_gives_up_after_max_retries(instance_config):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, json={"error": {"message": "down"}})

    client, _ = make_client(handler, instance_config, max_retries=2)
    with pytest.raises(ServiceNowUnavailableError):
        client.search_incidents()
    assert calls["n"] == 3


def test_timeouts_are_retried(instance_config):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectTimeout("slow")

    client, _ = make_client(handler, instance_config, max_retries=2)
    with pytest.raises(ServiceNowUnavailableError):
        client.search_incidents()
    assert calls["n"] == 3


def test_rate_limit_honours_retry_after(instance_config):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"Retry-After": "2"}, json={"error": {"message": "slow down"}}
            )
        return httpx.Response(200, json={"result": []})

    client, sleeps = make_client(handler, instance_config)
    assert client.search_incidents() == []
    assert sleeps == [2.0]


def test_non_json_means_hibernating(instance_config):
    def handler(request):
        return httpx.Response(
            200, text="<html>Instance Hibernating</html>", headers={"content-type": "text/html"}
        )

    client, _ = make_client(handler, instance_config, max_retries=0)
    with pytest.raises(ServiceNowUnavailableError, match="hibernating"):
        client.search_incidents()


def test_auth_error_is_not_retried(instance_config):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "User Not Authenticated"}})

    client, _ = make_client(handler, instance_config)
    with pytest.raises(ServiceNowAuthError):
        client.search_incidents()
    assert calls["n"] == 1


def test_data_policy_and_forbidden_are_different(instance_config):
    policy = {
        "error": {"message": "Operation Failed", "detail": "Data Policy Exception: mandatory"}
    }
    acl = {
        "error": {"message": "Operation Failed", "detail": "ACL Exception: security constraints"}
    }
    responses = iter([httpx.Response(403, json=policy), httpx.Response(403, json=acl)])
    client, _ = make_client(lambda request: next(responses), instance_config)
    with pytest.raises(ServiceNowDataPolicyError):
        client.resolve_incident("a" * 32, "Resolved by caller", "done")
    with pytest.raises(ServiceNowForbiddenError):
        client.resolve_incident("a" * 32, "Resolved by caller", "done")


def test_basic_auth_header_is_sent(instance_config):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"result": []})

    client, _ = make_client(handler, instance_config)
    client.search_incidents()
    assert seen["auth"].startswith("Basic ")


def test_create_survives_a_lost_response_without_duplicating(instance_config):
    """The server creates the ticket, but the response is lost (timeout)."""
    store = []
    posts = {"n": 0}

    def handler(request):
        if request.method == "POST":
            posts["n"] += 1
            body = json.loads(request.content)
            store.append(record(number="INC0010099", correlation_id=body["correlation_id"]))
            raise httpx.ReadTimeout("response lost")
        wanted = request.url.params["sysparm_query"].split("=", 1)[1]
        return httpx.Response(
            200, json={"result": [r for r in store if r["correlation_id"] == wanted]}
        )

    client, _ = make_client(handler, instance_config)
    ticket = client.create_incident(**CREATE)
    assert ticket.number == "INC0010099"
    assert posts["n"] == 1


def test_create_with_caller_key_checks_before_posting(instance_config):
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"result": [record(correlation_id="run-0001:create")]})

    client, _ = make_client(handler, instance_config)
    ticket = client.create_incident(**CREATE, idempotency_key="run-0001:create")
    assert ticket.number == "INC0010001"
    assert methods == ["GET"]


def test_create_sends_correlation_id(instance_config):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"result": record()})

    client, _ = make_client(handler, instance_config)
    client.create_incident(**CREATE)
    assert len(seen["body"]["correlation_id"]) >= 8


def test_resolve_sends_state_and_code(instance_config):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": record(state="6")})

    client, _ = make_client(handler, instance_config)
    client.resolve_incident("a" * 32, "Resolved by caller", "Restarted client")
    assert seen["body"] == {
        "state": "6",
        "close_code": "Resolved by caller",
        "close_notes": "Restarted client",
    }


def test_query_builder_blocks_injection():
    query = build_incident_query(
        active_only=True,
        category=None,
        state=None,
        caller_id=None,
        group_id=None,
        text="vpn^active=false",
    )
    assert "active=false" not in query.split("^")


def test_knowledge_is_scoped_to_one_base(instance_config):
    seen = {}

    def handler(request):
        seen["query"] = request.url.params["sysparm_query"]
        return httpx.Response(200, json={"result": []})

    client, _ = make_client(handler, instance_config)
    client.fetch_knowledge_articles()
    assert "workflow_state=published" in seen["query"]
    assert f"kb_knowledge_base={KB_ID}" in seen["query"]


def test_knowledge_refuses_without_base_id(instance_config):
    client, _ = make_client(
        lambda r: httpx.Response(200, json={"result": []}), instance_config, kb_sys_id=""
    )
    with pytest.raises(ServiceNowValidationError):
        client.fetch_knowledge_articles()
