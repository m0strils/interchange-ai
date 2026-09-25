"""Executable acceptance criteria for the BM25 half of hybrid retrieval (ADR-0007).

Gherkin lives in ``features/hybrid_retrieval.feature``. This is "the BM25 win":
an exact EDI transaction-set code (e.g. ``997``, ``417``) must retrieve its own
defining document. Dense embeddings blur short numeric tokens — ``214`` and ``417``
land in nearly the same region of vector space — so a purely dense retriever can
surface the wrong doc for an exact code. The lexical (BM25) component does not: it
matches the code as a token. Hybrid retrieval fuses both so exact codes win.

Offline discipline (per the frozen contract): this test NEVER touches Chroma,
embeddings, the network, or the fused ``retrieve()``. Importing ``interchange`` is
safe (embeddings are only loaded when ``retrieve()``/``build_index()`` is called).
The steps read the two real docs from disk, chunk them with ``interchange.chunk``
(the FROZEN contract shape: ``list[{"text","section"}]``), and assert directly on
``interchange.bm25_rank`` — that ranking IS the mechanism under test.
"""
from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

import interchange

scenarios("hybrid_retrieval.feature")


# --- Given -----------------------------------------------------------------
@given("the real corpus chunked with its source filenames")
def real_corpus(context):
    """Read the two real docs from disk, chunk each, and keep every chunk's
    source filename alongside its text — two parallel lists indexed together."""
    corpus_texts: list[str] = []
    sources: list[str] = []
    # Recursive, ignore-aware discovery (the ingest path build_index() uses),
    # narrowed to Markdown. On the flat seed corpus this yields exactly the
    # files the old ``DOCS_DIR.glob("*.md")`` did, in the same order.
    md_files = [
        path
        for path in interchange.discover_files(interchange.DOCS_DIR)
        if path.suffix.lower() == ".md"
    ]
    for path in md_files:
        for piece in interchange.chunk(path.read_text()):
            corpus_texts.append(piece["text"])
            sources.append(path.name)
    assert corpus_texts, "expected the real docs to produce at least one chunk"
    context["corpus_texts"] = corpus_texts
    context["sources"] = sources


# --- When ------------------------------------------------------------------
@when(parsers.parse('I BM25-search for the exact code "{code}"'))
def bm25_search(context, code):
    """Rank the corpus by BM25 for the bare code and keep the top index."""
    ranking = interchange.bm25_rank(code, context["corpus_texts"])
    assert ranking, "expected bm25_rank to return a non-empty ranking"
    context["top_index"] = ranking[0]


# --- Then ------------------------------------------------------------------
@then(parsers.parse('the top-ranked chunk comes from "{source}"'))
def top_chunk_source(context, source):
    top_source = context["sources"][context["top_index"]]
    assert top_source == source, (
        f"BM25 top hit for the code came from {top_source!r}, expected {source!r}"
    )
