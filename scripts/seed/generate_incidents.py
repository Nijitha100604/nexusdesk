"""Generate synthetic resolved incidents.  python scripts/seed/generate_incidents.py --limit 6"""

from __future__ import annotations

import argparse
import math
import time
from difflib import SequenceMatcher

from seed_common import (
    ARTICLES_FILE,
    CATEGORY_LABELS,
    INCIDENT_PLAN,
    INCIDENTS_FILE,
    RESOLUTION_TYPES,
    append_jsonl,
    normalize_ticket,
    read_jsonl,
    validate_incident,
    validate_ticket_body,
)
from seed_llm import DailyLimitError, complete_json, settings

BATCH = 6

SYSTEM = (
    "You create realistic, RESOLVED IT helpdesk tickets for a fictional company, as test data. "
    "Rules: plain text only; first-person descriptions written by different kinds of employees "
    "(terse, polite, frustrated, non-technical); resolution notes written by the technician in "
    "1-3 sentences saying what was actually done; no real names, emails, phone numbers, "
    "IP addresses or web links; no ticket numbers. Answer with one JSON object only."
)

USER = """Category: {category}
Knowledge article topics in this category (about 70% of the tickets should relate to one of
these; the rest should be different problems that no article covers):
{topics}

Summaries already used (do not repeat or closely paraphrase them):
{used}

Write {n} different resolved tickets. Impact should be "3" (one user) for most, sometimes "2".
Urgency "1" means work blocked with no workaround, "2" workaround exists, "3" minor.

Return JSON: {{"tickets": [{{
  "short_description": "what the employee wrote as the summary, 10-100 characters",
  "description": "2-4 sentences, first person",
  "urgency": "1" or "2" or "3",
  "impact": "1" or "2" or "3",
  "resolution_type": "employee_fixed" (the employee fixed it by following guidance)
                      or "permanent_fix" or "workaround",
  "close_notes": "what the technician did, 1-3 sentences",
  "related_topic": "the matching article topic, or none"
}}]}}"""


def check(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("tickets"), list):
        return None, ['response must be {"tickets": [...]}']
    good, errors = [], []
    for i, raw in enumerate(obj["tickets"]):
        ticket = normalize_ticket(raw) if isinstance(raw, dict) else raw
        problems = validate_ticket_body(ticket)
        if problems:
            errors.append(f"ticket {i}: {'; '.join(problems)}")
        else:
            good.append(ticket)
    return (good, []) if good else (None, errors or ["no tickets returned"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after this many new incidents"
    )
    parser.add_argument("--sleep", type=float, default=5.0)
    parser.add_argument("--category", choices=list(INCIDENT_PLAN))
    args = parser.parse_args()

    articles = read_jsonl(ARTICLES_FILE)
    if not articles:
        raise SystemExit(
            "Run generate_articles.py first; incidents are based on the article topics."
        )
    provider, model = settings()
    created = 0

    for category, target in INCIDENT_PLAN.items():
        if args.category and category != args.category:
            continue
        topics = [a["title"] for a in articles if a["category"] == category]
        batches_left = math.ceil(target / BATCH) + 4
        while batches_left > 0:
            existing = read_jsonl(INCIDENTS_FILE)
            same = [i for i in existing if i["category"] == category]
            needed = target - len(same)
            if needed <= 0:
                break
            if args.limit and created >= args.limit:
                print(f"Reached --limit {args.limit}")
                return
            batches_left -= 1
            n = min(BATCH, needed)
            used = [i["short_description"] for i in same][-25:]
            print(f"[{category}] {len(same)}/{target}; asking for {n}")
            try:
                tickets = complete_json(
                    SYSTEM,
                    USER.format(
                        category=CATEGORY_LABELS[category],
                        topics="\n".join(f"- {t}" for t in topics) or "- (none)",
                        used="\n".join(f"- {u}" for u in used) or "- (none yet)",
                        n=n,
                    ),
                    provider=provider,
                    model=model,
                    check=check,
                    temperature=0.9,
                )
            except DailyLimitError as exc:
                print(
                    f"Daily limit reached: {exc}\nRun the same command later to resume."
                )
                return
            except ValueError as exc:
                print(f"  batch skipped: {exc}")
                continue
            summaries = [i["short_description"].lower() for i in same]
            for ticket in tickets[:n]:
                text = ticket["short_description"].lower()
                if any(SequenceMatcher(None, text, s).ratio() > 0.9 for s in summaries):
                    print(f"  duplicate skipped: {ticket['short_description']}")
                    continue
                rows = read_jsonl(INCIDENTS_FILE)
                number = max((int(r["inc_id"][-4:]) for r in rows), default=0) + 1
                record = {
                    "inc_id": f"INC-SEED-{number:04d}",
                    "category": category,
                    "short_description": ticket["short_description"],
                    "description": ticket["description"],
                    "urgency": ticket["urgency"],
                    "impact": ticket["impact"],
                    "resolution_type": ticket["resolution_type"],
                    "close_code": RESOLUTION_TYPES[ticket["resolution_type"]],
                    "close_notes": ticket["close_notes"],
                    "related_topic": str(ticket.get("related_topic", "none")),
                    "synthetic": True,
                    "generated_by": f"{provider}:{model}",
                }
                if validate_incident(record):
                    continue
                append_jsonl(INCIDENTS_FILE, record)
                summaries.append(text)
                created += 1
            time.sleep(args.sleep)

    print(
        f"Done. {len(read_jsonl(INCIDENTS_FILE))}/{sum(INCIDENT_PLAN.values())} incidents saved"
    )


if __name__ == "__main__":
    main()
