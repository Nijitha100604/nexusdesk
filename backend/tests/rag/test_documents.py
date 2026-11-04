from app.rag.documents import article_to_document, build_chunks, incident_to_document
from tests.rag.fakes import PRINTER, VPN, make_article, make_incident

GROUPS = {"sys-net": "network_vpn", "sys-desk": "service_desk"}


def test_article_category_boilerplate_and_url():
    doc = article_to_document(VPN, "https://dev1.service-now.com/")
    assert doc.category == "network_vpn"
    assert doc.url == "https://dev1.service-now.com/kb_view.do?sysparm_article=KB0000001"
    text = " ".join(s.text for s in doc.sections)
    assert "Category:" not in text and "Synthetic demo article" not in text
    assert "Restart the VPN client" in text


def test_unknown_category_and_empty_article():
    doc = article_to_document(make_article("KB9", "Title here", "<p>Some body text</p>"), "")
    assert doc.category == "unknown" and doc.url == ""
    assert article_to_document(make_article("KB8", "Empty", "<p> </p>"), "") is None
    assert article_to_document(make_article("KB7", "  ", "<p>text</p>"), "") is None


def test_incident_document():
    inc = make_incident(
        "INC1", "VPN will not connect", "It times out.", "Reinstalled client.", "sys-net"
    )
    doc = incident_to_document(inc, GROUPS, "https://x")
    assert doc.category == "network_vpn" and doc.source_type == "incident"
    assert [s.heading for s in doc.sections] == ["Problem", "Resolution"]
    unknown = incident_to_document(
        make_incident("INC2", "Title ok", "desc", "notes", "other"), GROUPS, ""
    )
    assert unknown.category == "unknown"


def test_incidents_that_must_not_be_indexed():
    assert (
        incident_to_document(make_incident("I", "[NexusDesk test] check", "d", "n"), GROUPS, "")
        is None
    )
    assert incident_to_document(make_incident("I", "Title ok", "desc", ""), GROUPS, "") is None
    assert incident_to_document(make_incident("I", "Title ok", "", "notes"), GROUPS, "") is None


def test_demo_incidents_without_correlation_id_are_skipped():
    demo = make_incident(
        "INC3", "Email server is down", "Nobody gets mail.", "Restarted it.", correlation_id=""
    )
    assert incident_to_document(demo, GROUPS, "") is None
    assert incident_to_document(demo, GROUPS, "", only_nexusdesk=False) is not None


def test_chunk_metadata_is_chroma_safe():
    doc = article_to_document(PRINTER, "https://x")
    chunks = build_chunks(doc, "model-a")
    assert chunks[0].chunk_id == "KB0000002:000"
    for value in chunks[0].metadata.values():
        assert isinstance(value, (str, int, float, bool))
    assert chunks[0].metadata["number"] == "KB0000002"
    assert chunks[0].text.startswith("Printer shows offline")


def test_hash_changes_with_content_and_model():
    doc = article_to_document(PRINTER, "")
    base = build_chunks(doc, "model-a")[0].metadata["content_hash"]
    assert build_chunks(doc, "model-a")[0].metadata["content_hash"] == base
    assert build_chunks(doc, "model-b")[0].metadata["content_hash"] != base
    changed = article_to_document(
        make_article("KB0000002", "Printer shows offline", PRINTER.text + "<p>New</p>"), ""
    )
    assert build_chunks(changed, "model-a")[0].metadata["content_hash"] != base
