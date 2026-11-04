import pytest

from app.rag.retriever import Retriever
from app.rag.store import InMemoryStore
from app.workers.sync import SyncError, run_sync, sync_lock
from tests.rag.fakes import VPN, FakeClient, FakeEmbedder, make_article, make_incident

GROUPS = {"sys-net": "network_vpn", "sys-desk": "service_desk"}


def sync(client, store, **kw):
    return run_sync(
        client, store, FakeEmbedder(), group_categories=GROUPS, instance_url="https://x",
        log=lambda _: None, **kw,
    )  # fmt: skip


def test_first_sync_indexes_everything():
    store = InMemoryStore()
    report = sync(FakeClient(), store)
    assert (report.seen, report.new, report.unchanged, report.removed) == (3, 3, 0, 0)
    assert store.count() == report.chunks_written == 3
    assert set(store.doc_states()) == {"KB0000001", "KB0000002", "KB0000003"}


def test_second_sync_does_nothing():
    store, client = InMemoryStore(), FakeClient()
    sync(client, store)
    report = sync(client, store)
    assert (report.new, report.updated, report.unchanged) == (0, 0, 3)
    assert report.chunks_written == 0 and report.chunks_deleted == 0


def test_changed_article_is_reindexed_and_old_chunks_removed():
    store, client = InMemoryStore(), FakeClient()
    sync(client, store)
    long_html = VPN.text + "<h2>Extra</h2><p>" + ("More detail about the tunnel. " * 80) + "</p>"
    client.articles[0] = make_article(
        "KB0000001", VPN.short_description, long_html, "2026-10-09 09:00:00"
    )
    report = sync(client, store)
    assert report.updated == 1 and report.unchanged == 2
    ids = store.doc_states()["KB0000001"].chunk_ids
    assert len(ids) > 1  # the longer article is now several chunks
    shorter = make_article("KB0000001", VPN.short_description, VPN.text, "2026-10-10 09:00:00")
    client.articles[0] = shorter
    sync(client, store)
    assert store.doc_states()["KB0000001"].chunk_ids == ["KB0000001:000"]  # stale chunks deleted


def test_unpublished_article_is_removed():
    store, client = InMemoryStore(), FakeClient()
    sync(client, store)
    client.articles.pop()
    report = sync(client, store)
    assert report.removed == 1 and "KB0000003" not in store.doc_states()


def test_refuses_to_wipe_the_index_when_nothing_is_returned():
    store, client = InMemoryStore(), FakeClient()
    sync(client, store)
    client.articles = []
    with pytest.raises(SyncError):
        sync(client, store)
    assert store.count() == 3
    assert sync(client, store, allow_empty=True).removed == 3


def test_failed_fetch_changes_nothing():
    store, client = InMemoryStore(), FakeClient()
    sync(client, store)
    client.fail = True
    with pytest.raises(RuntimeError):
        sync(client, store)
    assert store.count() == 3


def test_dry_run_writes_nothing():
    store = InMemoryStore()
    report = sync(FakeClient(), store, dry_run=True)
    assert report.new == 3 and store.count() == 0


def test_incidents_are_indexed_and_test_tickets_skipped():
    incidents = [
        make_incident(
            "INC1",
            "VPN keeps disconnecting",
            "The VPN drops every few minutes.",
            "Switched network.",
            "sys-net",
        ),
        make_incident("INC2", "[NexusDesk check] connectivity test", "desc here", "notes here"),
    ]
    store = InMemoryStore()
    report = sync(FakeClient(incidents=incidents), store)
    assert report.seen == 4 and report.skipped == 1
    assert store.doc_states()["INC1"].source_type == "incident"
    assert sync(FakeClient(incidents=incidents), store, include_incidents=False).removed == 1


def test_lock_blocks_a_second_run(tmp_path):
    lock = tmp_path / ".sync.lock"
    with sync_lock(lock):
        with pytest.raises(SyncError):
            with sync_lock(lock):
                pass
    assert not lock.exists()
    with sync_lock(lock):
        pass


def build_retriever(**kw):
    store = InMemoryStore()
    incidents = [
        make_incident(
            "INC1",
            "VPN keeps disconnecting",
            "The VPN drops every few minutes.",
            "Switched network.",
            "sys-net",
        )
    ]
    sync(FakeClient(incidents=incidents), store)
    return Retriever(store, FakeEmbedder(), min_similarity=0.3, **kw)


def test_best_article_comes_first():
    hits = build_retriever().search("my vpn shows a connection timeout")
    assert hits[0].number == "KB0000001"
    assert hits[0].similarity >= hits[-1].similarity


def test_nothing_relevant_returns_nothing():
    assert build_retriever().search("quantum chromodynamics lattice") == []
    assert build_retriever().search("   ") == []


def test_source_type_filter():
    hits = build_retriever().search("vpn disconnecting", source_types=["incident"])
    assert hits and all(h.source_type == "incident" for h in hits)


def test_category_filter_and_fallback():
    retriever = build_retriever()
    hits = retriever.search("forgotten password reset", category="account_password")
    assert hits[0].number == "KB0000003"
    only = retriever.search("printer offline", category="network_vpn", fallback_unfiltered=False)
    assert all(h.category in ("network_vpn", "unknown") for h in only)
    fallback = retriever.search("printer offline", category="network_vpn")
    assert (
        fallback[0].number == "KB0000002"
    )  # the filter found no printer chunk, so it searched everywhere


def test_service_desk_incidents_match_account_and_other_filters():
    store = InMemoryStore()
    inc = make_incident(
        "INC9",
        "Account locked out",
        "My account is locked after typing the wrong password.",
        "Unlocked it.",
        "sys-desk",
    )
    sync(FakeClient(articles=[VPN], incidents=[inc]), store)
    retriever = Retriever(store, FakeEmbedder(), min_similarity=0.1)
    hits = retriever.search(
        "account locked wrong password", category="account_password", fallback_unfiltered=False
    )
    assert [h.number for h in hits] == ["INC9"]


def test_max_per_doc_and_top_k():
    store = InMemoryStore()
    big = make_article(
        "KB5",
        "Big article",
        "<h2>A</h2><p>"
        + ("vpn timeout tunnel " * 120)
        + "</p><h2>B</h2><p>"
        + ("vpn timeout gateway " * 120)
        + "</p><h2>C</h2><p>"
        + ("vpn timeout client " * 120)
        + "</p>",
    )
    sync(FakeClient(articles=[big, VPN]), store)
    retriever = Retriever(store, FakeEmbedder(), min_similarity=0.0, max_per_doc=2)
    hits = retriever.search("vpn timeout", top_k=5)
    assert sum(h.number == "KB5" for h in hits) <= 2


def test_rerank_adds_a_bonus_for_shared_words():
    plain = build_retriever(rerank=False).search("vpn client connection timeout reinstall")
    boosted = build_retriever(rerank=True).search("vpn client connection timeout reinstall")
    assert boosted[0].score > boosted[0].similarity
    assert plain[0].score == plain[0].similarity


def test_threshold():
    strict = build_retriever()
    strict.min_similarity = 0.99
    assert strict.search("vpn connection timeout") == []
