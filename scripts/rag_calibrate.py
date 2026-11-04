"""Measure retrieval on the DEV evaluation tickets and suggest a similarity threshold.

    python scripts/rag_calibrate.py            # dev split only
Use the test split only for final reporting (Phase 15), never to tune.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from app.rag.factory import get_retriever

EVAL_FILE = ROOT / "data" / "eval" / "test_tickets.jsonl"
MANIFEST_FILE = ROOT / "data" / "synthetic" / "seed_manifest.json"


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def describe(name: str, values: list[float]) -> None:
    if not values:
        print(f"{name}: no data")
        return
    print(
        f"{name}: n={len(values)} min={min(values):.2f} p10={percentile(values, 10):.2f} "
        f"median={percentile(values, 50):.2f} p90={percentile(values, 90):.2f} max={max(values):.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--rerank", action="store_true")
    args = parser.parse_args()
    if args.split == "test":
        print(
            "WARNING: the test split is for final reporting only. Do not tune on it.\n"
        )

    tickets = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tickets = [t for t in tickets if t["split"] == args.split]
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    number_of = {art_id: entry["number"] for art_id, entry in manifest.items()}
    retriever = get_retriever(rerank=args.rerank)

    matches = [t for t in tickets if t["scenario"] == "article_match"]
    hit_at = {1: 0, 3: 0, args.k: 0}
    match_top, other_top, misses = [], [], []
    for ticket in matches:
        wanted = number_of.get(ticket["expected_article"], "?")
        hits = retriever.search(
            ticket["message"],
            source_types=["kb_article"],
            top_k=args.k,
            min_similarity=-1.0,
        )
        numbers = [h.number for h in hits]
        for k in hit_at:
            hit_at[k] += wanted in numbers[:k]
        if wanted not in numbers[:3]:
            misses.append(
                (
                    ticket["eval_id"],
                    wanted,
                    numbers[:3],
                    hits[0].similarity if hits else 0,
                )
            )
    for ticket in tickets:
        top = retriever.search(ticket["message"], top_k=1, min_similarity=-1.0)
        similarity = top[0].similarity if top else 0.0
        if ticket["scenario"] == "article_match":
            match_top.append(similarity)
        elif ticket["scenario"] in ("no_kb", "vague"):
            other_top.append(similarity)

    n = len(matches) or 1
    print(
        f"split={args.split} rerank={args.rerank} article_match tickets={len(matches)}"
    )
    for k, count in sorted(hit_at.items()):
        print(f"  KB article in top {k}: {count}/{len(matches)} = {count / n:.0%}")
    describe("top similarity, tickets that HAVE an article", match_top)
    describe("top similarity, tickets with NO article (no_kb, vague)", other_top)
    if match_top and other_top:
        low_match, high_other = percentile(match_top, 10), percentile(other_top, 90)
        if low_match > high_other:
            print(
                f"\nSuggested RAG_MIN_SIMILARITY: about {(low_match + high_other) / 2:.2f}"
            )
        else:
            print(
                f"\nThe two groups overlap (p10 {low_match:.2f} <= p90 {high_other:.2f}). "
                "Pick a threshold near the p90 of the no-article group and rely on the "
                "grounding check and escalation for the rest."
            )
    for eval_id, wanted, got, similarity in misses:
        print(
            f"  miss {eval_id}: wanted {wanted}, got {got} (top similarity {similarity:.2f})"
        )


if __name__ == "__main__":
    main()
