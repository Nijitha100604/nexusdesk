"""Check the generated data before it is loaded.  python scripts/seed/validate_data.py --sample

Exit code 1 means there are errors to fix. Warnings need a human look.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

from seed_common import (
    ARTICLES_FILE,
    CATEGORIES,
    EVAL_FILE,
    INCIDENT_PLAN,
    INCIDENTS_FILE,
    REVIEW_FILE,
    article_text,
    jaccard,
    read_jsonl,
    trigrams,
    validate_article,
    validate_eval,
    validate_incident,
)
from seed_data import TOPICS

EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.)+[a-z]{2,}", re.IGNORECASE)
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
TOKEN = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
SECRET_PREFIX = re.compile(r"\b(?:gsk_|AIza|sk-|ghp_|xox[bp]-)\w+")
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")


def is_private_ip(ip: str) -> bool:
    a, b, *_ = (int(x) for x in ip.split("."))
    return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def scan_text(label: str, text: str, errors: list[str]) -> None:
    for match in EMAIL.finditer(text):
        if not match.group(0).lower().endswith(SAFE_EMAIL_DOMAINS):
            errors.append(f"{label}: email address {match.group(0)!r}")
    for match in PHONE.finditer(text):
        if sum(c.isdigit() for c in match.group(0)) >= 9:
            errors.append(f"{label}: phone-like number {match.group(0)!r}")
    for match in IPV4.finditer(text):
        if all(int(x) <= 255 for x in match.group(0).split(".")) and not is_private_ip(
            match.group(0)
        ):
            errors.append(f"{label}: public IP address {match.group(0)!r}")
    if URL.search(text):
        errors.append(f"{label}: contains a web link")
    if TOKEN.search(text) or SECRET_PREFIX.search(text):
        errors.append(f"{label}: looks like a key or token")


def find_duplicates(
    items: list[tuple[str, str]], limit: float, kind: str, errors: list[str]
) -> None:
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ratio = SequenceMatcher(
                None, items[i][1].lower(), items[j][1].lower()
            ).ratio()
            if ratio >= limit:
                errors.append(
                    f"near-duplicate {kind}: {items[i][0]} and {items[j][0]} ({ratio:.2f})"
                )


def write_review(articles, incidents, evals) -> None:
    rng = random.Random(7)
    out = ["# Manual review sample (generated; not committed)\n"]
    out.append("## Articles\n")
    for a in rng.sample(articles, min(8, len(articles))):
        out.append(f"### {a['art_id']} - {a['title']}\n")
        out.append("Symptoms: " + "; ".join(a["symptoms"]) + "\n")
        out.append("Cause: " + a["cause"] + "\n")
        out += [f"{n}. {s}" for n, s in enumerate(a["resolution_steps"], 1)]
        out.append("\nEscalate if: " + a["escalate_if"] + "\n")
    out.append("## Incidents\n")
    for i in rng.sample(incidents, min(12, len(incidents))):
        out.append(
            f"- **{i['inc_id']}** ({i['category']}, u{i['urgency']}/i{i['impact']}): "
            f"{i['short_description']}\n  - {i['description']}\n  - Resolution ({i['close_code']}): "
            f"{i['close_notes']}"
        )
    out.append("\n## Evaluation tickets\n")
    for e in rng.sample(evals, min(15, len(evals))):
        out.append(
            f"- **{e['eval_id']}** [{e['scenario']}, {e['split']}] -> {e['expected_category']}, "
            f"P{e['expected_priority']}, route {e['expected_route']}, article {e['expected_article']}\n"
            f"  - {e['message']}"
        )
    REVIEW_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Review sample written to {REVIEW_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample", action="store_true", help="write REVIEW.md for manual reading"
    )
    args = parser.parse_args()

    articles, incidents, evals = (
        read_jsonl(ARTICLES_FILE),
        read_jsonl(INCIDENTS_FILE),
        read_jsonl(EVAL_FILE),
    )
    errors: list[str] = []
    warnings: list[str] = []

    # 1. schema
    for a in articles:
        errors += [f"{a.get('art_id')}: {p}" for p in validate_article(a)]
    for i in incidents:
        errors += [f"{i.get('inc_id')}: {p}" for p in validate_incident(i)]
    for e in evals:
        errors += [f"{e.get('eval_id')}: {p}" for p in validate_eval(e)]
    for kind, rows, key in (
        ("article", articles, "art_id"),
        ("incident", incidents, "inc_id"),
        ("eval", evals, "eval_id"),
    ):
        counts = Counter(r.get(key) for r in rows)
        errors += [f"duplicate {kind} id {k}" for k, c in counts.items() if c > 1]

    # 2. counts
    for cat in CATEGORIES:
        want_a, have_a = len(TOPICS[cat]), sum(a["category"] == cat for a in articles)
        want_i, have_i = (
            INCIDENT_PLAN[cat],
            sum(i["category"] == cat for i in incidents),
        )
        if have_a < want_a:
            warnings.append(f"articles {cat}: {have_a}/{want_a}")
        if have_i < want_i:
            warnings.append(f"incidents {cat}: {have_i}/{want_i}")

    # 3. duplicates
    find_duplicates(
        [(a["art_id"], a["title"]) for a in articles], 0.85, "article title", errors
    )
    for cat in CATEGORIES:
        find_duplicates(
            [
                (i["inc_id"], i["short_description"])
                for i in incidents
                if i["category"] == cat
            ],
            0.9,
            "incident summary",
            errors,
        )
    find_duplicates(
        [(e["eval_id"], e["message"]) for e in evals],
        0.85,
        "evaluation message",
        errors,
    )

    # 4. personal data and secrets
    for a in articles:
        scan_text(a["art_id"], article_text(a), errors)
    for i in incidents:
        scan_text(
            i["inc_id"],
            f"{i['short_description']} {i['description']} {i['close_notes']}",
            errors,
        )
    for e in evals:
        scan_text(e["eval_id"], e["message"], errors)

    # 5. evaluation labels and leakage
    known = {a["art_id"] for a in articles}
    for e in evals:
        if e.get("expected_article") and e["expected_article"] not in known:
            errors.append(
                f"{e['eval_id']}: expected_article {e['expected_article']} does not exist"
            )
    corpus = [(a["art_id"], trigrams(article_text(a))) for a in articles]
    corpus += [
        (i["inc_id"], trigrams(f"{i['description']} {i['close_notes']}"))
        for i in incidents
    ]
    for e in evals:
        grams = trigrams(e["message"])
        if len(grams) < 4:
            continue
        best_id, best = max(
            ((cid, jaccard(grams, cg)) for cid, cg in corpus),
            key=lambda x: x[1],
            default=("", 0),
        )
        if best >= 0.5:
            errors.append(
                f"{e['eval_id']}: overlaps {best_id} too much ({best:.2f}); evaluation leak"
            )
        elif best >= 0.3:
            warnings.append(f"{e['eval_id']}: fairly similar to {best_id} ({best:.2f})")
    splits = Counter(e["split"] for e in evals)
    if evals and min(splits.get("dev", 0), splits.get("test", 0)) < 5:
        warnings.append(f"split is unbalanced: {dict(splits)}")

    print(
        f"articles={len(articles)} incidents={len(incidents)} eval={len(evals)} splits={dict(splits)}"
    )
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    if args.sample and articles and incidents and evals:
        write_review(articles, incidents, evals)
    print(
        "FAILED" if errors else "OK (read the warnings and the review sample yourself)"
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
