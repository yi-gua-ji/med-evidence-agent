"""BM25 retrieval sanity tests on a tiny temp corpus."""

from __future__ import annotations

from medagent.tools.rag import BM25Index, chunk_document, load_corpus, tokenize


def test_tokenize_drops_stopwords_and_short_tokens():
    tokens = tokenize("The SGLT2 inhibitor reduced a heart failure risk")
    assert "the" not in tokens
    assert "a" not in tokens
    assert "sglt2" in tokens
    assert "failure" in tokens


def test_chunk_document_merges_paragraphs():
    text = "para one\n\n" + ("word " * 400) + "\n\npara three"
    chunks = chunk_document(text, "Title", "doc.md", max_chars=800)
    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 900 for chunk in chunks)


def test_bm25_ranks_matching_chunk_first():
    chunks = chunk_document(
        "SGLT2 inhibitors reduce heart failure hospitalization in trials.", "A", "a.md"
    ) + chunk_document("Statins lower LDL cholesterol in primary prevention.", "B", "b.md")
    index = BM25Index(chunks)
    hits = index.search("heart failure hospitalization sglt2", k=3)
    assert hits
    assert "SGLT2" in hits[0][0].text


def test_load_corpus_reads_markdown(tmp_path):
    (tmp_path / "doc1.md").write_text("# Paper one\n\nEmpagliflozin improved outcomes.", encoding="utf-8")
    (tmp_path / "doc2.jsonl").write_text(json_line({"title": "Paper two", "text": "Dapagliflozin trial."}), encoding="utf-8")
    chunks = load_corpus(str(tmp_path))
    titles = {chunk.title for chunk in chunks}
    assert "Paper one" in titles
    assert "Paper two" in titles


def json_line(record):
    import json

    return json.dumps(record)