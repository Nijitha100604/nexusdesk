"""Sync ServiceNow knowledge into the vector store.

Run from the backend folder:
    python -m app.workers.sync              # incremental: only new or changed documents
    python -m app.workers.sync --dry-run    # show what would change
    python -m app.workers.sync --rebuild    # wipe the index and embed everything again
    python -m app.workers.sync --stats      # what is in the index

Safe to run repeatedly and from a scheduler.
"""

from __future__ import annotations

import argparse
import os
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.rag.documents import (
    article_to_document,
    build_chunks,
    incident_to_document,
)
from app.rag.embeddings import Embedder
from app.rag.models import KB_ARTICLE, Chunk, Document
from app.rag.store import VectorStore

STALE_LOCK_SECONDS = 3600


class SyncError(RuntimeError):
    pass


@dataclass
class SyncReport:
    seen: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0
    chunks_written: int = 0
    chunks_deleted: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"documents seen={self.seen} new={self.new} updated={self.updated} "
            f"unchanged={self.unchanged} removed={self.removed} skipped={self.skipped} | "
            f"chunks written={self.chunks_written} deleted={self.chunks_deleted} | "
            f"{self.seconds:.1f}s"
        )


@contextmanager
def sync_lock(path: Path) -> Iterator[None]:
    """One sync at a time. A lock older than an hour is treated as left over from a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > STALE_LOCK_SECONDS:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SyncError(
            f"another sync is running (lock file {path}); delete it if it is stale"
        ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def collect_documents(
    client: Any,
    *,
    group_categories: dict[str, str],
    instance_url: str,
    include_incidents: bool,
    max_incidents: int,
    all_incidents: bool,
    report: SyncReport,
) -> dict[str, Document]:
    docs: dict[str, Document] = {}
    for article in client.iter_knowledge_articles(page_size=50):
        doc = article_to_document(article, instance_url)
        if doc is None:
            report.skipped += 1
            report.notes.append(f"article {article.number} skipped (empty after cleaning)")
            continue
        previous = docs.get(doc.doc_id)
        if previous is None or doc.updated >= previous.updated:
            docs[doc.doc_id] = doc
    if include_incidents:
        for incident in client.iter_resolved_incidents(page_size=50, max_items=max_incidents):
            doc = incident_to_document(
                incident, group_categories, instance_url, only_nexusdesk=not all_incidents
            )
            if doc is None:
                report.skipped += 1
                continue
            docs[doc.doc_id] = doc
    return docs


def run_sync(
    client: Any,
    store: VectorStore,
    embedder: Embedder,
    *,
    group_categories: dict[str, str],
    instance_url: str,
    include_incidents: bool = True,
    max_incidents: int = 1000,
    all_incidents: bool = False,
    dry_run: bool = False,
    allow_empty: bool = False,
    batch_size: int = 32,
    log: Callable[[str], None] = print,
) -> SyncReport:
    started = time.time()
    report = SyncReport()
    # Everything is read before anything is changed, so a failed fetch cannot damage the index.
    docs = collect_documents(
        client,
        group_categories=group_categories,
        instance_url=instance_url,
        include_incidents=include_incidents,
        max_incidents=max_incidents,
        all_incidents=all_incidents,
        report=report,
    )
    existing = store.doc_states()
    report.seen = len(docs)

    fetched_articles = sum(1 for d in docs.values() if d.source_type == KB_ARTICLE)
    indexed_articles = sum(1 for s in existing.values() if s.source_type == KB_ARTICLE)
    if fetched_articles == 0 and indexed_articles > 0 and not allow_empty:
        raise SyncError(
            f"ServiceNow returned no articles but {indexed_articles} are indexed. Refusing to "
            "delete them (check access and SN_KB_SYS_ID, or pass --allow-empty)."
        )

    to_write: list[Chunk] = []
    stale_ids: list[str] = []
    for doc_id, doc in docs.items():
        chunks = build_chunks(doc, embedder.name)
        state = existing.get(doc_id)
        if state is None:
            report.new += 1
        elif state.content_hash != chunks[0].metadata["content_hash"]:
            report.updated += 1
            new_ids = {c.chunk_id for c in chunks}
            stale_ids += [cid for cid in state.chunk_ids if cid not in new_ids]
        else:
            report.unchanged += 1
            continue
        to_write += chunks
    for doc_id, state in existing.items():
        if doc_id not in docs:
            report.removed += 1
            stale_ids += state.chunk_ids

    report.chunks_written = len(to_write)
    report.chunks_deleted = len(stale_ids)
    if dry_run:
        report.seconds = time.time() - started
        return report

    for start in range(0, len(to_write), batch_size):
        batch = to_write[start : start + batch_size]
        vectors = embedder.embed_passages([c.text for c in batch])
        store.upsert(batch, vectors)
        log(f"  embedded {min(start + batch_size, len(to_write))}/{len(to_write)} chunks")
    store.delete(stale_ids)
    report.seconds = time.time() - started
    return report


def print_stats(store: VectorStore) -> None:
    metas = store.metadatas()
    print(f"chunks: {len(metas)}")
    docs = {m["doc_id"]: m for m in metas}
    print(f"documents: {len(docs)}")
    for source, count in sorted(Counter(m["source_type"] for m in docs.values()).items()):
        print(f"  {source}: {count}")
    print("by category:")
    for category, count in sorted(Counter(m["category"] for m in docs.values()).items()):
        print(f"  {category}: {count}")
    models = {m.get("embedding_model") for m in metas}
    print(f"embedding model(s): {sorted(str(m) for m in models)}")


def main() -> None:
    from app.core.config import get_settings
    from app.rag.categories import group_categories
    from app.rag.factory import get_embedder, get_store
    from app.servicenow import create_client
    from app.servicenow.instance import load_instance_config

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="wipe the index first")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--no-incidents", action="store_true")
    parser.add_argument("--max-incidents", type=int, default=1000)
    parser.add_argument(
        "--all-incidents",
        action="store_true",
        help="also index tickets that were not created through NexusDesk (ServiceNow demo data)",
    )
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    store = get_store()
    if args.stats:
        print_stats(store)
        return

    config = load_instance_config(settings.sn_config_path or None, allow_example=True)
    client = create_client(settings)
    print(
        f"ServiceNow mode: {settings.servicenow_mode}; embedding model: {settings.embedding_model}"
    )
    lock = settings.chroma_dir / ".sync.lock"
    try:
        with sync_lock(lock):
            if args.rebuild and not args.dry_run:
                print("Rebuilding: clearing the index")
                store.reset()
            report = run_sync(
                client,
                store,
                get_embedder(),
                group_categories=group_categories(config.groups),
                instance_url=settings.sn_instance,
                include_incidents=not args.no_incidents,
                max_incidents=args.max_incidents,
                all_incidents=args.all_incidents,
                dry_run=args.dry_run,
                allow_empty=args.allow_empty,
            )
    except SyncError as exc:
        raise SystemExit(f"Sync stopped: {exc}") from exc
    print(("[dry run] " if args.dry_run else "") + report.summary())
    for note in report.notes[:10]:
        print(f"  note: {note}")


if __name__ == "__main__":
    main()
