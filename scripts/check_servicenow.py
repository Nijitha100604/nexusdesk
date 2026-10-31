"""ServiceNow connectivity and permission check.

Run from the repo root:
    python scripts/check_servicenow.py          # read-only checks
    python scripts/check_servicenow.py --write  # also creates, updates and resolves
                                                # one test incident
"""

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import get_settings

failures = 0


def passed(name: str, detail: str = "") -> None:
    print(f"[PASS] {name}" + (f" - {detail}" if detail else ""))


def failed(name: str, detail: str = "") -> None:
    global failures
    failures += 1
    print(f"[FAIL] {name}" + (f" - {detail}" if detail else ""))


def warn(name: str, detail: str = "") -> None:
    print(f"[WARN] {name}" + (f" - {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write", action="store_true", help="also test write operations"
    )
    args = parser.parse_args()

    s = get_settings()
    if not (s.sn_instance and s.sn_user and s.sn_password):
        print("SN_INSTANCE, SN_USER and SN_PASSWORD must be set in the root .env file.")
        return 1

    base = f"{s.sn_instance.rstrip('/')}/api/now/table"
    client = httpx.Client(
        auth=(s.sn_user, s.sn_password),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=20,
    )

    def call(method: str, path: str, **kwargs) -> httpx.Response | None:
        try:
            return client.request(method, f"{base}/{path}", **kwargs)
        except httpx.HTTPError as exc:
            print(f"       request error: {type(exc).__name__}: {exc}")
            return None

    print(f"Instance: {s.sn_instance}  User: {s.sn_user}\n")

    # 1. Incident read
    r = call(
        "GET", "incident", params={"sysparm_limit": 1, "sysparm_fields": "number,state"}
    )
    if r is not None and r.status_code == 200:
        passed("Incident read", f"{len(r.json()['result'])} row(s)")
    else:
        failed(
            "Incident read", f"HTTP {r.status_code if r is not None else 'no response'}"
        )

    # 2. Knowledge read with the sync filter
    query = "workflow_state=published"
    if s.sn_kb_sys_id:
        query += f"^kb_knowledge_base={s.sn_kb_sys_id}"
    else:
        warn("SN_KB_SYS_ID not set", "checking all readable published articles")
    r = call(
        "GET",
        "kb_knowledge",
        params={
            "sysparm_query": query,
            "sysparm_fields": "number,short_description,text",
            "sysparm_limit": 5,
        },
    )
    if r is None or r.status_code != 200:
        failed(
            "Knowledge read",
            f"HTTP {r.status_code if r is not None else 'no response'}",
        )
    else:
        rows = r.json()["result"]
        if rows:
            has_text = bool(rows[0].get("text"))
            passed(
                "Knowledge read", f"{len(rows)} article(s), body present: {has_text}"
            )
        else:
            failed(
                "Knowledge read",
                "empty list (no article, or user criteria block access)",
            )

    # 3. Least-privilege boundary: system tables should be denied
    r = call(
        "GET",
        "sys_choice",
        params={"sysparm_query": "name=incident^element=state", "sysparm_limit": 1},
    )
    if r is None:
        failed("sys_choice boundary", "no response")
    elif r.status_code == 403 or (r.status_code == 200 and not r.json()["result"]):
        passed("sys_choice boundary", "denied as intended")
    else:
        warn(
            "sys_choice boundary",
            "service user can read system tables; broader than needed",
        )

    # 4. Write path (optional)
    if args.write:
        print("\nWrite checks (creates one test incident):")
        r = call(
            "POST",
            "incident",
            json={
                "short_description": "[NexusDesk check] connectivity test",
                "description": "Created by scripts/check_servicenow.py. Safe to ignore.",
                "category": "inquiry",
                "urgency": "3",
                "impact": "3",
            },
        )
        if r is None or r.status_code != 201:
            failed(
                "Create incident", f"HTTP {r.status_code if r is not None else 'none'}"
            )
            print(f"       {r.text[:200] if r is not None else ''}")
        else:
            rec = r.json()["result"]
            sys_id, number = rec["sys_id"], rec["number"]
            passed("Create incident", f"{number}, priority {rec.get('priority')}")

            r = call(
                "PATCH", f"incident/{sys_id}", json={"work_notes": "check script note"}
            )
            if r is not None and r.status_code == 200:
                passed("Add work note")
            else:
                failed(
                    "Add work note",
                    f"HTTP {r.status_code if r is not None else 'none'}",
                )

            r = call(
                "PATCH",
                f"incident/{sys_id}",
                json={
                    "state": "6",
                    "close_code": "Resolved by caller",
                    "close_notes": "Closed by the connectivity check script.",
                },
            )
            if r is not None and r.status_code == 200:
                passed("Resolve incident", f"state {r.json()['result']['state']}")
            else:
                failed(
                    "Resolve incident",
                    f"HTTP {r.status_code if r is not None else 'none'}",
                )
                print(f"       {r.text[:300] if r is not None else ''}")

    print(
        f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
