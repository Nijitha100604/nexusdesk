"""Ask the RAG pipeline a question.

python scripts/ask.py "my vpn keeps timing out"
python scripts/ask.py "printer offline" --category hardware --rerank --sources
python scripts/ask.py "my vpn keeps timing out" --no-llm     # retrieval only
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from app.rag.answering import answer_question
from app.rag.factory import get_llm, get_retriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument(
        "--category", help="e.g. network_vpn, hardware, account_password"
    )
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument(
        "--sources", action="store_true", help="print the retrieved chunks"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="retrieval only, no answer"
    )
    args = parser.parse_args()

    retriever = get_retriever(rerank=args.rerank)
    if args.no_llm:
        hits = retriever.search(
            args.question, category=args.category, min_similarity=0.0
        )
        for hit in hits:
            print(
                f"{hit.similarity:.3f}  {hit.number}  [{hit.source_type}/{hit.category}]  {hit.title}"
            )
        return

    result = answer_question(
        args.question, retriever, get_llm(), category=args.category
    )
    print(f"\n{result.answer}\n")
    print(
        f"answerable={result.answerable} reason={result.reason} confidence={result.confidence} "
        f"top_similarity={result.top_similarity} grounding={result.grounding_score}"
    )
    for citation in result.citations:
        print(f"  cited: {citation.number} ({citation.source_type}) {citation.title}")
    if args.sources:
        for hit in result.hits:
            print(f"\n--- {hit.number} similarity={hit.similarity:.3f}\n{hit.text}")


if __name__ == "__main__":
    main()
