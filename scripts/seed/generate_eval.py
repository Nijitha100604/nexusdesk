"""Generate the labelled evaluation tickets (never loaded into ServiceNow or the knowledge base).

    python scripts/seed/generate_eval.py --limit 3
Labels come from the scenario definitions in seed_data.py, not from the LLM.
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict

from seed_common import (
    ARTICLES_FILE,
    EVAL_FILE,
    append_jsonl,
    calculate_priority,
    read_jsonl,
    validate_eval,
)
from seed_data import (
    CRITICAL,
    INJECTION,
    LABEL_CYCLE,
    NO_KB,
    SECURITY,
    SENSITIVE,
    TONES,
    TOPICS,
    VAGUE,
)
from seed_llm import DailyLimitError, complete_json, settings

URGENCY_TEXT = {
    "1": "they cannot do their work at all and there is no workaround",
    "2": "their work is slowed down but they have some workaround",
    "3": "it is only a minor annoyance",
}
IMPACT_TEXT = {
    "1": "it affects the whole company or a whole department",
    "2": "it affects their team or several colleagues",
    "3": "only they are affected",
}

SYSTEM = (
    "You write test messages as an employee typing into a company IT helpdesk chat. "
    "Plain text, natural wording, no real names, emails, phone numbers or links. "
    "Answer with one JSON object only."
)
USER = """Situation: {situation}
Urgency: {urgency}. Impact: {impact}.
Tone: {tone}.

Write ONE message of 1 to 4 sentences, in the first person. Do not mention knowledge articles,
categories or ticket numbers. Do not copy the situation text; describe it the way a real
employee would.
Return JSON: {{"message": "the message"}}"""


def route_for_article(article: dict) -> str:
    topic = article["topic"].lower()
    if "suspicious" in topic or "phishing" in topic:
        return "escalate"
    if "administrator rights" in topic:
        return "approval"
    return "answer"


def build_specs(articles: list[dict]) -> list[dict]:
    specs: list[dict] = []
    for i, art in enumerate(articles):
        urgency, impact = LABEL_CYCLE[i % len(LABEL_CYCLE)]
        specs.append(
            {
                "scenario": "article_match",
                "category": art["category"],
                "urgency": urgency,
                "impact": impact,
                "route": route_for_article(art),
                "article": art["art_id"],
                "situation": (
                    f"They have this problem: {art['topic']}. Typical signs: "
                    f"{'; '.join(art['symptoms'][:3])}."
                ),
                "notes": "",
            }
        )
    for cat, text, u, im in NO_KB:
        specs.append(
            {
                "scenario": "no_kb",
                "category": cat,
                "urgency": u,
                "impact": im,
                "route": "escalate",
                "article": None,
                "situation": f"They need help with this: {text}.",
                "notes": "no matching article; should escalate",
            }
        )
    for cat, text, u, im in CRITICAL:
        specs.append(
            {
                "scenario": "critical",
                "category": cat,
                "urgency": u,
                "impact": im,
                "route": "escalate",
                "article": None,
                "situation": f"Reporting an outage: {text}.",
                "notes": "P1; never auto-resolve",
            }
        )
    for cat, text, u, im, route, note in SENSITIVE:
        specs.append(
            {
                "scenario": "sensitive",
                "category": cat,
                "urgency": u,
                "impact": im,
                "route": route,
                "article": None,
                "situation": f"The employee {text}.",
                "notes": note,
            }
        )
    for cat, text, u, im in SECURITY:
        specs.append(
            {
                "scenario": "security",
                "category": cat,
                "urgency": u,
                "impact": im,
                "route": "escalate",
                "article": None,
                "situation": f"The employee {text}.",
                "notes": "security incident; always escalate",
            }
        )
    for message in VAGUE:
        specs.append(
            {
                "scenario": "vague",
                "category": "other",
                "urgency": "2",
                "impact": "3",
                "route": "clarify",
                "article": None,
                "static": message,
                "notes": "too little detail; labels apply before clarification",
            }
        )
    for message, cat, route, article, note in INJECTION:
        specs.append(
            {
                "scenario": "injection",
                "category": cat,
                "urgency": "3",
                "impact": "3",
                "route": route,
                "article": article,
                "static": message,
                "notes": note,
            }
        )
    return specs


def check(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("message"), str):
        return None, ['response must be {"message": "..."}']
    message = " ".join(obj["message"].split())
    errors = []
    if not 10 <= len(message) <= 600:
        errors.append("message must be 10-600 characters")
    if "<" in message or ">" in message:
        errors.append("message must not contain < or >")
    return message, errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=5.0)
    args = parser.parse_args()

    articles = read_jsonl(ARTICLES_FILE)
    if not articles:
        raise SystemExit("Run generate_articles.py first.")
    expected = sum(len(t) for t in TOPICS.values())
    if len(articles) < expected:
        raise SystemExit(
            f"Only {len(articles)}/{expected} articles exist. Finish generate_articles.py first, "
            "because evaluation ids depend on the full article list."
        )
    specs = build_specs(articles)
    done = {e["eval_id"] for e in read_jsonl(EVAL_FILE)}
    needs_llm = any("static" not in s for s in specs)
    provider, model = settings() if needs_llm else ("", "")
    seen_scenarios: dict[str, int] = defaultdict(int)
    created = 0

    for number, spec in enumerate(specs, start=1):
        eval_id = f"EV-{number:03d}"
        index = seen_scenarios[spec["scenario"]]
        seen_scenarios[spec["scenario"]] += 1
        if eval_id in done:
            continue
        if args.limit and created >= args.limit:
            print(f"Reached --limit {args.limit}")
            return
        if "static" in spec:
            message, source = spec["static"], "static"
        else:
            print(f"[{eval_id}] {spec['scenario']}")
            try:
                message = complete_json(
                    SYSTEM,
                    USER.format(
                        situation=spec["situation"],
                        urgency=URGENCY_TEXT[spec["urgency"]],
                        impact=IMPACT_TEXT[spec["impact"]],
                        tone=TONES[number % len(TONES)],
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
                print(f"  skipped after retries: {exc}")
                continue
            source = f"{provider}:{model}"
            time.sleep(args.sleep)
        record = {
            "eval_id": eval_id,
            "split": "dev" if index % 2 == 0 else "test",
            "scenario": spec["scenario"],
            "message": message,
            "expected_category": spec["category"],
            "expected_urgency": spec["urgency"],
            "expected_impact": spec["impact"],
            "expected_priority": calculate_priority(spec["impact"], spec["urgency"]),
            "expected_article": spec["article"],
            "expected_route": spec["route"],
            "notes": spec["notes"],
            "synthetic": True,
            "generated_by": source,
        }
        problems = validate_eval(record)
        if problems:
            print(f"  rejected: {problems}")
            continue
        append_jsonl(EVAL_FILE, record)
        created += 1

    print(
        f"Done. {len(read_jsonl(EVAL_FILE))}/{len(specs)} evaluation tickets in {EVAL_FILE}"
    )


if __name__ == "__main__":
    main()
