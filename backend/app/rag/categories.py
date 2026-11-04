"""NexusDesk categories as stored in chunk metadata."""

from __future__ import annotations

CATEGORY_LABELS = {
    "network_vpn": "Network and VPN",
    "software_access": "Software and Access",
    "hardware": "Hardware",
    "email_collaboration": "Email and Collaboration",
    "account_password": "Account and Password",
    "other": "Other",
}
_LABEL_TO_KEY = {label.lower(): key for key, label in CATEGORY_LABELS.items()}

# Past tickets carry no NexusDesk category in ServiceNow; derive it from the assignment group.
GROUP_CATEGORY = {
    "Network Support": "network_vpn",
    "Software Support": "software_access",
    "Hardware Support": "hardware",
    "Messaging Support": "email_collaboration",
    "Service Desk": "service_desk",  # covers both account_password and other
}


def category_from_label(label: str) -> str:
    return _LABEL_TO_KEY.get(label.strip().lower(), "unknown")


def group_categories(groups: dict[str, str]) -> dict[str, str]:
    """{group name: sys_id} -> {sys_id: category key}."""
    return {
        sys_id: GROUP_CATEGORY[name] for name, sys_id in groups.items() if name in GROUP_CATEGORY
    }


def filter_values(category: str) -> list[str]:
    """Metadata values that should match when the caller filters on `category`."""
    values = [category, "unknown"]
    if category in ("account_password", "other"):
        values.append("service_desk")
    return values
