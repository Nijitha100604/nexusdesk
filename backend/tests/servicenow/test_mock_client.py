import pytest

from app.servicenow import (
    ServiceNowNotFoundError,
    ServiceNowUnavailableError,
    ServiceNowValidationError,
)

BASE = dict(
    short_description="VPN not connecting",
    description="Timeout error on the VPN client",
    category="network",
    urgency="2",
    impact="3",
)


def make(client, **over):
    return client.create_incident(**{**BASE, **over})


def test_create_calculates_priority(mock_client):
    ticket = make(mock_client)
    assert ticket.state == "1"
    assert ticket.priority == "4"
    assert ticket.number.startswith("INC")


def test_same_idempotency_key_returns_same_ticket(mock_client):
    a = make(mock_client, idempotency_key="run-0001:create")
    b = make(mock_client, idempotency_key="run-0001:create")
    assert a.sys_id == b.sys_id
    assert len(mock_client.search_incidents(active_only=False)) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"urgency": "5"},
        {"category": "printer"},
        {"caller_id": "not-a-sys-id"},
        {"short_description": "  "},
        {"idempotency_key": "short"},
    ],
)
def test_create_rejects_bad_input(mock_client, bad):
    with pytest.raises(ServiceNowValidationError):
        make(mock_client, **bad)


def test_work_notes_and_comments_are_separate(mock_client):
    ticket = make(mock_client)
    mock_client.add_work_note(ticket.sys_id, "internal reasoning")
    mock_client.add_comment(ticket.sys_id, "Please restart the client")
    assert mock_client.work_notes(ticket.sys_id) == ["internal reasoning"]
    assert mock_client.comments(ticket.sys_id) == ["Please restart the client"]


def test_update_rejects_protected_fields(mock_client):
    ticket = make(mock_client)
    with pytest.raises(ServiceNowValidationError):
        mock_client.update_incident(ticket.sys_id, {"state": "6"})


def test_update_recalculates_priority(mock_client):
    ticket = make(mock_client)
    updated = mock_client.update_incident(ticket.sys_id, {"urgency": "1", "impact": "1"})
    assert updated.priority == "1"


def test_resolve(mock_client):
    ticket = make(mock_client)
    done = mock_client.resolve_incident(ticket.sys_id, "Resolved by caller", "Restarted client")
    assert done.state == "6"
    assert done.close_code == "Resolved by caller"


def test_resolve_rejects_unknown_code_and_empty_notes(mock_client):
    ticket = make(mock_client)
    with pytest.raises(ServiceNowValidationError):
        mock_client.resolve_incident(ticket.sys_id, "Solved (Permanently)", "x")
    with pytest.raises(ServiceNowValidationError):
        mock_client.resolve_incident(ticket.sys_id, "Resolved by caller", "  ")


def test_reassign_sets_group_and_note(mock_client, instance_config):
    ticket = make(mock_client)
    updated = mock_client.reassign_incident(
        ticket.sys_id, "Network Support", note="Needs network team"
    )
    assert updated.assignment_group == instance_config.group_id("Network Support")
    assert mock_client.work_notes(ticket.sys_id) == ["Needs network team"]


def test_reassign_unknown_group(mock_client):
    ticket = make(mock_client)
    with pytest.raises(ServiceNowValidationError):
        mock_client.reassign_incident(ticket.sys_id, "Imaginary Team")


def test_search_filters(mock_client):
    vpn = make(mock_client, short_description="VPN timeout")
    printer = make(mock_client, short_description="Printer offline", category="hardware")
    mock_client.resolve_incident(printer.sys_id, "Resolved by caller", "Power cycled")
    assert [i.number for i in mock_client.search_incidents(text="vpn")] == [vpn.number]
    assert [i.number for i in mock_client.search_incidents()] == [vpn.number]
    assert len(mock_client.search_incidents(active_only=False)) == 2


def test_get_by_number_and_sys_id(mock_client):
    ticket = make(mock_client)
    assert mock_client.get_incident(ticket.number).sys_id == ticket.sys_id
    assert mock_client.get_incident(ticket.sys_id).number == ticket.number


def test_get_unknown(mock_client):
    with pytest.raises(ServiceNowNotFoundError):
        mock_client.get_incident("INC9999999")
    with pytest.raises(ServiceNowNotFoundError):
        mock_client.get_incident("a" * 32)
    with pytest.raises(ServiceNowValidationError):
        mock_client.get_incident("garbage")


def test_knowledge_pagination(mock_client):
    everything = mock_client.fetch_knowledge_articles(limit=50)
    paged = list(mock_client.iter_knowledge_articles(page_size=2))
    assert [a.number for a in paged] == [a.number for a in everything]
    assert len(paged) >= 3


def test_failure_injection(mock_client):
    mock_client.fail_next(ServiceNowUnavailableError("down"))
    with pytest.raises(ServiceNowUnavailableError):
        mock_client.ping()
    assert mock_client.ping() is True
