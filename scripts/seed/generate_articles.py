"""Generate synthetic knowledge articles.  python scripts/seed/generate_articles.py --limit 2"""

from __future__ import annotations

import argparse
import time

from seed_common import (
    ARTICLES_FILE,
    CATEGORY_CODES,
    CATEGORY_LABELS,
    append_jsonl,
    normalize_article_body,
    read_jsonl,
    validate_article,
    validate_article_body,
)
from seed_data import TOPICS
from seed_llm import DailyLimitError, complete_json, settings

SYSTEM = (
    "You write internal IT knowledge base articles for a fictional company. "
    "Rules: plain text only (no HTML, no markdown, no numbering inside list items); "
    "no real people, real phone numbers, real email addresses, IP addresses or web links; "
    "refer generically to 'the corporate VPN client', 'the company software portal' and "
    "'the Service Desk' instead of naming vendor-specific menus you are unsure about; "
    "steps must be concrete and in a sensible order. Answer with one JSON object only."
)

USER = """Write one knowledge base article.
Category: {category}
Topic: {topic}
Content hints: {hint}

Return JSON with exactly these keys:
{{
  "title": "clear title, 15-100 characters",
  "symptoms": ["2 to 5 things the employee notices"],
  "cause": "1-3 sentences on the usual cause",
  "resolution_steps": ["4 to 8 concrete steps the employee or technician follows"],
  "escalate_if": "when the employee should contact the Service Desk or when the ticket must be escalated",
  "keywords": ["3 to 8 short search keywords"]
}}"""


def check(obj):
    obj = normalize_article_body(obj) if isinstance(obj, dict) else obj
    return obj, validate_article_body(obj)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after this many new articles"
    )
    parser.add_argument(
        "--sleep", type=float, default=5.0, help="seconds between calls"
    )
    parser.add_argument("--category", choices=list(TOPICS), help="only this category")
    args = parser.parse_args()

    provider, model = settings()
    done = {a["art_id"] for a in read_jsonl(ARTICLES_FILE)}
    created = 0
    print(f"Using {provider}:{model}; {len(done)} article(s) already saved")

    for category, topics in TOPICS.items():
        if args.category and category != args.category:
            continue
        for index, (topic, hint) in enumerate(topics):
            art_id = f"ART-{CATEGORY_CODES[category]}-{index + 1:03d}"
            if art_id in done:
                continue
            if args.limit and created >= args.limit:
                print(f"Reached --limit {args.limit}")
                return
            print(f"[{art_id}] {topic}")
            try:
                body = complete_json(
                    SYSTEM,
                    USER.format(
                        category=CATEGORY_LABELS[category], topic=topic, hint=hint
                    ),
                    provider=provider,
                    model=model,
                    check=check,
                )
            except DailyLimitError as exc:
                print(
                    f"Daily limit reached: {exc}\nRun the same command later to resume."
                )
                return
            except ValueError as exc:
                print(f"  skipped after retries: {exc}")
                continue
            record = {
                "art_id": art_id,
                "category": category,
                "topic": topic,
                **body,
                "synthetic": True,
                "generated_by": f"{provider}:{model}",
            }
            problems = validate_article(record)
            if problems:
                print(f"  rejected: {problems}")
                continue
            append_jsonl(ARTICLES_FILE, record)
            created += 1
            time.sleep(args.sleep)

    total = sum(len(t) for t in TOPICS.values())
    print(f"Done. {len(read_jsonl(ARTICLES_FILE))}/{total} articles in {ARTICLES_FILE}")


if __name__ == "__main__":
    main()
