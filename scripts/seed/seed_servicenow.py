"""Load the synthetic data into ServiceNow.

    python scripts/seed/seed_servicenow.py articles --limit 1     # try one first
    python scripts/seed/seed_servicenow.py articles
    python scripts/seed/seed_servicenow.py incidents --limit 3
    python scripts/seed/seed_servicenow.py incidents

Articles are written with TEMPORARY admin credentials (SN_ADMIN_USER / SN_ADMIN_PASSWORD in .env),
because the runtime service user is read-only on the knowledge base. Incidents use the service user.
Both are safe to re-run: existing articles (same title) and incidents (same key) are skipped.
"""

from __future__ import annotations

import argparse
import time

import httpx
from seed_common import (
    ARTICLES_FILE,
    INCIDENTS_FILE,
    MANIFEST_FILE,
    NEXUS_CATEGORIES,
    ServiceNowError,
    build_service_client,
    env,
    read_json,
    read_jsonl,
    render_article_html,
    write_json,
)


class AdminKnowledge:
    """Tiny Table API client for creating knowledge articles as admin."""

    def __init__(self, instance: str, user: str, password: str, kb_sys_id: str) -> None:
        self.base = f"{instance.rstrip('/')}/api/now/table"
        self.kb = kb_sys_id
        self.http = httpx.Client(
            auth=(user, password),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )

    def _request(
        self, method: str, path: str, *, retry: bool = True, **kwargs
    ) -> httpx.Response:
        attempts = 4 if retry else 1
        for attempt in range(attempts):
            try:
                response = self.http.request(method, f"{self.base}/{path}", **kwargs)
            except httpx.TransportError:
                if attempt == attempts - 1:
                    raise
                time.sleep(2**attempt)
                continue
            if response.status_code in (429, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2**attempt)
                continue
            return response
        raise AssertionError("unreachable")

    def find(self, title: str) -> dict | None:
        response = self._request(
            "GET",
            "kb_knowledge",
            params={
                "sysparm_query": f"kb_knowledge_base={self.kb}^short_description={title}",
                "sysparm_fields": "sys_id,number,workflow_state",
                "sysparm_limit": 1,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"lookup failed: HTTP {response.status_code} {response.text[:200]}"
            )
        rows = response.json().get("result", [])
        return rows[0] if rows else None

    def ensure(self, article: dict) -> tuple[dict, bool]:
        """Create the article unless one with the same title exists. Returns (record, created)."""
        for _ in range(3):
            existing = self.find(article["title"])
            if existing:
                return existing, False
            try:
                response = self._request(
                    "POST",
                    "kb_knowledge",
                    retry=False,  # a lost response is handled by looking the article up again
                    json={
                        "kb_knowledge_base": self.kb,
                        "short_description": article["title"],
                        "text": render_article_html(article),
                        "workflow_state": "published",
                        "valid_to": "2100-01-01",
                    },
                )
            except httpx.TransportError:
                continue
            if response.status_code != 201:
                raise RuntimeError(
                    f"create failed: HTTP {response.status_code} {response.text[:300]}"
                )
            record = response.json()["result"]
            if record.get("workflow_state") != "published":
                patch = self._request(
                    "PATCH",
                    f"kb_knowledge/{record['sys_id']}",
                    json={"workflow_state": "published"},
                )
                if patch.status_code != 200:
                    print(
                        f"  warning: could not publish {record.get('number')} (HTTP {patch.status_code})"
                    )
            return record, True
        raise RuntimeError("could not confirm creation after retries")


def seed_articles(args: argparse.Namespace) -> int:
    instance, user, password = (
        env("SN_INSTANCE"),
        env("SN_ADMIN_USER"),
        env("SN_ADMIN_PASSWORD"),
    )
    kb = env("SN_KB_SYS_ID")
    if not (instance and user and password and kb):
        raise SystemExit(
            "Set SN_INSTANCE, SN_KB_SYS_ID, SN_ADMIN_USER and SN_ADMIN_PASSWORD in .env"
        )
    articles = read_jsonl(ARTICLES_FILE)
    if not articles:
        raise SystemExit("No articles found; run generate_articles.py first")
    manifest = read_json(MANIFEST_FILE, {})
    client = AdminKnowledge(instance, user, password, kb)
    created = skipped = failed = 0

    for article in articles:
        if args.limit and created >= args.limit:
            break
        if args.dry_run:
            print(f"[dry run] {article['art_id']} {article['title']}")
            continue
        try:
            record, was_created = client.ensure(article)
        except (RuntimeError, httpx.HTTPError) as exc:
            failed += 1
            print(f"FAILED {article['art_id']}: {exc}")
            continue
        manifest[article["art_id"]] = {
            "number": record.get("number", ""),
            "sys_id": record["sys_id"],
        }
        write_json(MANIFEST_FILE, manifest)
        created += was_created
        skipped += not was_created
        print(
            f"{'created' if was_created else 'exists '} {article['art_id']} -> {record.get('number')}"
        )

    print(f"Articles: created={created} existing={skipped} failed={failed}")
    if not args.dry_run and not failed and not args.limit:
        verify_articles(len(articles))
    return 1 if failed else 0


def verify_articles(expected: int) -> None:
    """Read the articles back as the service user, the way the Phase 6 sync will."""
    service, _config = build_service_client()
    titles = {a.short_description for a in service.iter_knowledge_articles()}
    wanted = {a["title"] for a in read_jsonl(ARTICLES_FILE)}
    missing = wanted - titles
    print(f"Service user can read {len(wanted & titles)}/{expected} seeded articles")
    for title in sorted(missing):
        print(f"  not visible to the service user: {title}")


def seed_incidents(args: argparse.Namespace) -> int:
    incidents = read_jsonl(INCIDENTS_FILE)
    if not incidents:
        raise SystemExit("No incidents found; run generate_incidents.py first")
    if args.dry_run:
        for rec in incidents[: args.limit or None]:
            print(
                f"[dry run] {rec['inc_id']} {rec['category']}: {rec['short_description']}"
            )
        return 0
    service, config = build_service_client()
    callers = list(config.callers.values())
    created = skipped = failed = 0

    for position, rec in enumerate(incidents):
        if args.limit and created >= args.limit:
            break
        sn_category, group = NEXUS_CATEGORIES[rec["category"]]
        key = f"seed-inc-{rec['inc_id'][-4:]}"
        try:
            ticket = service.create_incident(
                short_description=rec["short_description"],
                description=rec["description"],
                category=sn_category,
                urgency=rec["urgency"],
                impact=rec["impact"],
                caller_id=callers[position % len(callers)] if callers else None,
                idempotency_key=key,
            )
            if ticket.state in ("6", "7", "8"):
                skipped += 1
                continue
            service.reassign_incident(
                ticket.sys_id, group, note="Synthetic seed ticket (NexusDesk)."
            )
            service.resolve_incident(
                ticket.sys_id, rec["close_code"], rec["close_notes"]
            )
            created += 1
            print(f"resolved {rec['inc_id']} -> {ticket.number}")
        except (
            ServiceNowError,
            httpx.HTTPError,
        ) as exc:  # report and continue with the next ticket
            failed += 1
            print(f"FAILED {rec['inc_id']}: {exc}")
        time.sleep(0.2)

    print(f"Incidents: resolved={created} already-done={skipped} failed={failed}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="what", required=True)
    for name in ("articles", "incidents"):
        p = sub.add_parser(name)
        p.add_argument(
            "--limit", type=int, default=0, help="stop after this many new records"
        )
        p.add_argument(
            "--dry-run", action="store_true", help="print what would be loaded"
        )
    args = parser.parse_args()
    raise SystemExit(
        seed_articles(args) if args.what == "articles" else seed_incidents(args)
    )


if __name__ == "__main__":
    main()
