"""Values from docs/servicenow-reference.md. Keep the two in sync."""

from enum import StrEnum


class IncidentState(StrEnum):
    NEW = "1"
    IN_PROGRESS = "2"
    ON_HOLD = "3"
    RESOLVED = "6"
    CLOSED = "7"
    CANCELED = "8"


STATE_VALUES = tuple(s.value for s in IncidentState)
INACTIVE_STATES = (
    IncidentState.RESOLVED.value,
    IncidentState.CLOSED.value,
    IncidentState.CANCELED.value,
)

URGENCY_VALUES = ("1", "2", "3")
IMPACT_VALUES = ("1", "2", "3")
SN_CATEGORIES = ("inquiry", "software", "hardware", "network", "database")

GROUP_NAMES = (
    "Service Desk",
    "Network Support",
    "Software Support",
    "Hardware Support",
    "Messaging Support",
)

# The API needs the stored VALUE. Most use an en dash (\u2013); one uses a hyphen.
# TODO: add the 11th row from your sys_choice list if it exists.
CLOSE_CODE_BY_CALLER = "Resolved by caller"
CLOSE_CODE_PERMANENT_FIX = "Resolved \u2013 Permanent Fix Applied"
CLOSE_CODE_WORKAROUND = "Workaround provided"
CLOSE_CODES = (
    "Known error",
    "Duplicate",
    CLOSE_CODE_WORKAROUND,
    CLOSE_CODE_BY_CALLER,
    CLOSE_CODE_PERMANENT_FIX,
    "Resolved \u2013 Fixed by Vendor",
    "Resolved \u2013 Fixed Without Action",
    "Resolved - No response from caller",
    "Not Resolved \u2013 Not Reproducible",
    "Not Resolved \u2013 Problem Raised",
)

# NexusDesk category -> (ServiceNow category, escalation group)
NEXUS_CATEGORIES = {
    "network_vpn": ("network", "Network Support"),
    "software_access": ("software", "Software Support"),
    "hardware": ("hardware", "Hardware Support"),
    "email_collaboration": ("software", "Messaging Support"),
    "account_password": ("inquiry", "Service Desk"),
    "other": ("inquiry", "Service Desk"),
}

# Design rule: only P3 to P5 may be resolved without a human. P1 never, P2 needs approval.
AUTO_RESOLVE_PRIORITIES = ("3", "4", "5")


def calculate_priority(impact: str, urgency: str) -> str:
    """Matches the default ServiceNow matrix (verified in Phase 3): impact + urgency - 1."""
    return str(int(impact) + int(urgency) - 1)
