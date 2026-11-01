"""Run on demand:  pytest -m live -s"""

import uuid

import pytest

from app.core.config import get_settings
from app.servicenow import LiveServiceNowClient, ServiceNowValidationError
from app.servicenow.instance import load_instance_config

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live():
    s = get_settings()
    if not (s.sn_instance and s.sn_user and s.sn_password):
        pytest.skip("SN_INSTANCE, SN_USER and SN_PASSWORD are not set")
    try:
        config = load_instance_config(s.sn_config_path or None)
    except ServiceNowValidationError as exc:
        pytest.skip(str(exc))
    if config.has_placeholders:
        pytest.skip("servicenow.json still has placeholder sys_ids")
    client = LiveServiceNowClient(
        s.sn_instance, s.sn_user, s.sn_password, instance_config=config, kb_sys_id=s.sn_kb_sys_id
    )
    yield client
    client.close()


def test_ping(live):
    assert live.ping() is True


def test_search_returns_a_list(live):
    assert isinstance(live.search_incidents(limit=3), list)


def test_knowledge_is_readable(live):
    articles = live.fetch_knowledge_articles(limit=5)
    assert articles, "no article returned; check user criteria and SN_KB_SYS_ID"
    assert articles[0].text


def test_ticket_lifecycle_and_idempotency(live):
    key = f"pytest-{uuid.uuid4().hex[:16]}"
    args = dict(
        short_description="[NexusDesk test] integration check",
        description="Created by the live test; safe to ignore.",
        category="inquiry",
        urgency="3",
        impact="3",
        idempotency_key=key,
    )
    first = live.create_incident(**args)
    second = live.create_incident(**args)
    assert first.sys_id == second.sys_id  # no duplicate

    assert live.get_incident(first.number).sys_id == first.sys_id
    live.add_work_note(first.sys_id, "live test note")
    live.add_comment(first.sys_id, "live test comment")
    assert live.reassign_incident(first.sys_id, "Service Desk", note="live test").assignment_group
    done = live.resolve_incident(first.sys_id, "Resolved by caller", "Closed by live test")
    assert done.state == "6"
