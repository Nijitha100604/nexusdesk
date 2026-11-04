from app.rag.chunking import MAX_CHARS, chunk_sections
from app.rag.cleaning import content_hash, html_to_sections, normalize_text
from app.rag.models import Section


def test_sections_split_at_headings():
    html = "<p>Intro line</p><h2>Symptoms</h2><ul><li>One</li><li>Two</li></ul><h2>Fix</h2><ol><li>Do a</li><li>Do b</li></ol>"
    sections = html_to_sections(html)
    assert [s.heading for s in sections] == ["", "Symptoms", "Fix"]
    assert sections[1].text == "- One\n- Two"
    assert sections[2].text == "1. Do a\n2. Do b"


def test_scripts_styles_and_entities():
    html = "<style>p{color:red}</style><script>alert(1)</script><p>Tom &amp; Jerry&nbsp;rock</p>"
    sections = html_to_sections(html)
    assert len(sections) == 1
    assert "alert" not in sections[0].text and "color" not in sections[0].text
    assert sections[0].text.startswith("Tom & Jerry")


def test_table_and_breaks():
    html = "<table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table>line one<br>line two"
    text = html_to_sections(html)[0].text
    assert "Name | Value" in text and "A | 1" in text
    assert "line one\nline two" in text


def test_empty_and_malformed_html():
    assert html_to_sections("") == []
    assert html_to_sections("<p>unclosed <b>bold")[0].text == "unclosed bold"


def test_normalize_text_and_hash():
    assert normalize_text("a \x00 b\n\n c") == "a b c"
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("a", "c")
    assert content_hash("ab", "") != content_hash("a", "b")


def test_short_document_is_one_chunk():
    sections = [Section("Symptoms", "- a"), Section("Fix", "1. b")]
    chunks = chunk_sections(sections)
    assert len(chunks) == 1 and chunks[0].section == ""
    assert "Symptoms" in chunks[0].body and "1. b" in chunks[0].body


def test_long_document_keeps_sections_and_respects_size():
    sections = [
        Section("Symptoms", "- " + "x" * 600),
        Section("Cause", "y" * 700),
        Section("Resolution", "\n".join(f"{i}. step {i} " + "z" * 150 for i in range(1, 9))),
    ]
    chunks = chunk_sections(sections)
    assert len(chunks) >= 3
    assert all(len(c.body) <= MAX_CHARS + 50 for c in chunks)
    assert any(c.section == "Symptoms" for c in chunks)
    joined = "\n".join(c.body for c in chunks)
    for i in range(1, 9):
        assert f"{i}. step {i}" in joined  # nothing lost


def test_small_sections_are_merged():
    sections = [Section("A", "a" * 100), Section("B", "b" * 100), Section("C", "c" * 1700)]
    chunks = chunk_sections(sections)
    assert chunks[0].section == "A / B"
    assert all(len(c.body) <= MAX_CHARS + 50 for c in chunks)


def test_overlap_between_split_chunks():
    body = "\n".join(f"line {i} " + "w" * 90 for i in range(40))
    chunks = chunk_sections([Section("Long", body)])
    assert len(chunks) > 1
    first_lines, second_lines = chunks[0].body.split("\n"), chunks[1].body.split("\n")
    assert first_lines[-1] in second_lines  # the last line is repeated


def test_one_enormous_line_is_wrapped():
    chunks = chunk_sections([Section("Long", "word " * 1000)])
    assert len(chunks) > 1 and all(len(c.body) <= MAX_CHARS + 50 for c in chunks)


def test_empty_sections_give_no_chunks():
    assert chunk_sections([]) == []
    assert chunk_sections([Section("A", "  ")]) == []
