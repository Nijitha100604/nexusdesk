import json

from app.llm.base import LLMError
from app.rag.answering import (
    NO_KNOWLEDGE,
    UNAVAILABLE,
    answer_question,
    build_context,
    combine_confidence,
    grounding_score,
)  # fmt: skip
from app.rag.retriever import Retriever
from app.rag.store import InMemoryStore
from app.workers.sync import run_sync
from tests.rag.fakes import FakeClient, FakeEmbedder, ScriptedLLM


def retriever():
    store = InMemoryStore()
    run_sync(
        FakeClient(),
        store,
        FakeEmbedder(),
        group_categories={},
        instance_url="https://x",
        log=lambda _: None,
    )
    return Retriever(store, FakeEmbedder(), min_similarity=0.3)


def reply(**over):
    data = {
        "answerable": True,
        "answer": "1. Check your internet connection [S1].\n2. Restart the VPN client [S1].",
        "citations": ["S1"],
        "confidence": 0.9,
        "missing_info": "",
    }
    data.update(over)
    return json.dumps(data)


QUESTION = "my vpn client shows a connection timeout"


def test_cited_answer_uses_real_kb_numbers():
    llm = ScriptedLLM(reply())
    result = answer_question(QUESTION, retriever(), llm)
    assert result.answerable and result.reason == "ok"
    assert "[KB0000001]" in result.answer and "[S1]" not in result.answer
    assert [c.number for c in result.citations] == ["KB0000001"]
    assert 0 < result.confidence <= 1 and result.grounding_score == 1.0
    assert "<sources>" in llm.last_user and QUESTION in llm.last_user


def test_no_relevant_knowledge_never_calls_the_model():
    llm = ScriptedLLM()
    result = answer_question("quantum chromodynamics lattice", retriever(), llm)
    assert not result.answerable and result.answer == NO_KNOWLEDGE
    assert result.reason == "no_relevant_knowledge" and llm.calls == 0


def test_model_declines():
    result = answer_question(QUESTION, retriever(), ScriptedLLM(reply(answerable=False)))
    assert not result.answerable and result.reason == "model_declined" and result.confidence == 0.0


def test_uncited_answer_is_rejected():
    result = answer_question(
        QUESTION,
        retriever(),
        ScriptedLLM(reply(answer="Restart the VPN client now.", citations=[])),
    )
    assert not result.answerable and result.reason == "uncited_answer"


def test_invented_citation_is_removed_and_confidence_capped():
    answer = "1. Restart the VPN client [S1].\n2. Call the helpline on the portal [S7]."
    result = answer_question(QUESTION, retriever(), ScriptedLLM(reply(answer=answer)))
    assert result.answerable and result.reason == "invalid_citation_removed"
    assert "S7" not in result.answer and result.confidence <= 0.3


def test_combined_label_markers():
    result = answer_question(
        QUESTION,
        retriever(),
        ScriptedLLM(reply(answer="Restart the VPN client [S1, S2].", citations=[])),
    )
    assert result.answerable
    assert result.citations and result.citations[0].number == "KB0000001"


def test_bad_json_and_llm_errors():
    assert (
        answer_question(QUESTION, retriever(), ScriptedLLM("not json at all")).reason
        == "invalid_model_output"
    )
    assert (
        answer_question(QUESTION, retriever(), ScriptedLLM("[1, 2]")).reason
        == "invalid_model_output"
    )
    error = answer_question(QUESTION, retriever(), ScriptedLLM(LLMError("down")))
    assert error.reason == "llm_error" and error.answer == UNAVAILABLE


def test_code_fences_are_tolerated():
    result = answer_question(QUESTION, retriever(), ScriptedLLM("```json\n" + reply() + "\n```"))
    assert result.answerable


def test_ungrounded_answer_has_low_confidence():
    answer = (
        "Open the registry editor and delete the HKEY_LOCAL_MACHINE software policies key [S1]."
    )
    result = answer_question(QUESTION, retriever(), ScriptedLLM(reply(answer=answer)))
    assert result.grounding_score < 0.6 and result.confidence <= 0.4


def test_grounding_score_and_confidence_helpers():
    context = "Restart the VPN client. Reinstall the VPN client if the problem persists."
    assert grounding_score("Restart the VPN client [S1].", context) == 1.0
    assert (
        grounding_score(
            "Reformat the entire hard drive immediately and reinstall windows.", context
        )
        == 0.0
    )
    assert grounding_score("Ok.", context) == 1.0
    assert combine_confidence(0.8, 1.0, 1.0, citations_ok=True) == 1.0
    assert combine_confidence(0.35, 0.0, 1.0, citations_ok=True) == 0.0
    assert combine_confidence(0.8, 1.0, 0.2, citations_ok=True) == 0.4
    assert combine_confidence(0.8, 1.0, 1.0, citations_ok=False) == 0.3


def test_context_is_limited_and_labelled():
    r = retriever()
    hits = r.search("printer offline vpn password", min_similarity=0.0, top_k=3)
    context, labels = build_context(hits, max_chars=10_000)
    assert list(labels) == [f"S{i}" for i in range(1, len(hits) + 1)]
    assert context.startswith("[S1] KB article")
    _, small = build_context(hits, max_chars=50)
    assert len(small) == 1  # at least one source is always kept
