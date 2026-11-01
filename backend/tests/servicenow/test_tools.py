import pytest

from app.servicenow import ServiceNowUnavailableError
from app.servicenow.context import request_context
from app.servicenow.tools import (
    READ_TOOL_NAMES,
    SYNC_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    build_tools,
)

CREATE = dict(
    short_description="Cannot connect to VPN",
    description="Timeout error since this morning",
    category="network_vpn",
    urgency="2",
    impact="3",
)


@pytest.fixture
def tools(mock_client):
    return build_tools(mock_client)


def test_tool_names(tools):
    assert set(tools) == READ_TOOL_NAMES | WRITE_TOOL_NAMES | SYNC_TOOL_NAMES


def test_create_maps_category(tools):
    out = tools["create_ticket"].invoke(CREATE)
    assert out["ok"] is True
    assert out["ticket"]["category"] == "network"


def test_create_is_deduplicated_within_one_run(tools):
    with request_context("run-abc12345"):
        a = tools["create_ticket"].invoke(CREATE)
        b = tools["create_ticket"].invoke(CREATE)
    assert a["ticket"]["number"] == b["ticket"]["number"]


def test_invalid_input_gives_a_readable_message(tools):
    out = tools["create_ticket"].invoke({**CREATE, "urgency": "5"})
    assert isinstance(out, str)
    assert "urgency" in out


def test_unknown_arguments_are_rejected(tools):
    ticket = tools["create_ticket"].invoke(CREATE)["ticket"]
    out = tools["add_work_note"].invoke(
        {"sys_id": ticket["sys_id"], "note": "hello there", "state": "6"}
    )
    assert isinstance(out, str)


def test_resolve_refuses_high_priority(tools, mock_client):
    ticket = tools["create_ticket"].invoke({**CREATE, "urgency": "1", "impact": "1"})["ticket"]
    out = tools["resolve_ticket"].invoke(
        {
            "sys_id": ticket["sys_id"],
            "resolution": "permanent_fix",
            "close_notes": "Fixed the tunnel",
        }
    )
    assert out["ok"] is False
    assert out["error"] == "ApprovalRequired"
    assert mock_client.get_incident(ticket["sys_id"]).state == "1"


def test_resolve_allows_low_priority(tools, mock_client):
    ticket = tools["create_ticket"].invoke({**CREATE, "urgency": "3", "impact": "3"})["ticket"]
    out = tools["resolve_ticket"].invoke(
        {
            "sys_id": ticket["sys_id"],
            "resolution": "employee_confirmed",
            "close_notes": "Employee confirmed fix",
        }
    )
    assert out["ok"] is True
    assert mock_client.get_incident(ticket["sys_id"]).state == "6"


def test_escalate(tools, mock_client, instance_config):
    ticket = tools["create_ticket"].invoke(CREATE)["ticket"]
    out = tools["escalate_ticket"].invoke(
        {
            "sys_id": ticket["sys_id"],
            "group_name": "Network Support",
            "reason": "Two attempts failed",
        }
    )
    assert out["ok"] is True
    assert out["ticket"]["assignment_group"] == instance_config.group_id("Network Support")
    assert "Two attempts failed" in mock_client.work_notes(ticket["sys_id"])[0]


def test_update_cannot_change_state(tools):
    ticket = tools["create_ticket"].invoke(CREATE)["ticket"]
    out = tools["update_ticket"].invoke({"sys_id": ticket["sys_id"], "state": "6"})
    assert isinstance(out, str)


def test_not_found_is_structured(tools):
    out = tools["get_ticket"].invoke({"identifier": "INC9999999"})
    assert out["ok"] is False
    assert out["error"] == "ServiceNowNotFoundError"


def test_retryable_errors_are_flagged(tools, mock_client):
    mock_client.fail_next(ServiceNowUnavailableError("down"))
    out = tools["get_ticket"].invoke({"identifier": "INC0001001"})
    assert out["ok"] is False
    assert out["retryable"] is True
