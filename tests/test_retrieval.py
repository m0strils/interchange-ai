"""Pytest unit tests for the hybrid-retrieval primitives (ADR-0007).

Test-first, bound to the FROZEN CONTRACT (ADR-0007) — not to the concurrently
authored implementation. Covers only the FIVE pure functions in ``interchange``:
``chunk``, ``tokenize``, ``bm25_rank``, ``reciprocal_rank_fusion``, ``hit_at_k``.

Offline + $0 discipline (contract "Constraints"): no network, no Chroma, no
embeddings. We NEVER call ``retrieve()`` / ``run_eval()`` / build an index — only
pure functions over in-memory strings or the real docs read from disk. File reads
are allowed; embeddings are not.

App imports resolve because pytest.ini sets ``pythonpath = .``. Each symbol is
imported *inside* the test that needs it (mirroring test_units.py's
``parse_claude_usage`` pattern) so a not-yet-landed function fails only its own
test, never collection.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Real corpus on disk (contract "Corpus facts"). File reads are permitted; the
# ban is on embeddings / index builds, not on reading Markdown.
DOCS = Path(__file__).resolve().parent.parent / "docs"
X12 = DOCS / "x12-overview.md"
RAIL = DOCS / "rail-edi-notes.md"


def _build_corpus():
    """Chunk both real docs into parallel (texts, sources) lists.

    Returns ``(texts, sources)`` where ``sources[i]`` is the filename the chunk at
    ``texts[i]`` came from — lets a BM25 index assertion map back to its source doc.
    Uses the contract's ``chunk`` so the corpus matches production chunking.
    """
    from interchange import chunk

    texts: list[str] = []
    sources: list[str] = []
    for path in (X12, RAIL):
        for c in chunk(path.read_text()):
            texts.append(c["text"])
            sources.append(path.name)
    return texts, sources


# --- chunk: structure-aware Markdown chunking (contract "chunk") -----------
def test_chunk_section_label_comes_from_nearest_heading():
    """Each chunk carries its nearest preceding heading text (no ``#`` marks) as
    ``section``; the heading line itself stays in the chunk text."""
    from interchange import chunk

    chunks = chunk("# Title\nBody under title.")
    titled = [c for c in chunks if c["section"] == "Title"]
    assert titled, "expected a chunk labelled with the heading text 'Title'"
    assert "# Title" in titled[0]["text"]  # heading line included in chunk text


def test_chunk_content_before_first_heading_is_preamble():
    """Content before the first heading gets section ``"preamble"``."""
    from interchange import chunk

    chunks = chunk("Intro sentence before any heading.\n\n# Real Heading\nBody.")
    pre = [c for c in chunks if c["section"] == "preamble"]
    assert pre, "expected a 'preamble' chunk for pre-heading content"
    assert "Intro sentence" in pre[0]["text"]
    assert any(c["section"] == "Real Heading" for c in chunks)


def test_chunk_drops_whitespace_only_chunks():
    """Whitespace-only chunks are dropped — leading blank lines before the first
    heading must NOT yield an (empty) 'preamble' chunk."""
    from interchange import chunk

    chunks = chunk("   \n\n\t\n# Real Heading\nSome body text.")
    sections = [c["section"] for c in chunks]
    assert "preamble" not in sections, "whitespace-only preamble should be dropped"
    assert "Real Heading" in sections
    # And nothing that survived is blank.
    assert all(c["text"].strip() for c in chunks)


def test_chunk_long_section_splits_into_windows_sharing_label():
    """A section body exceeding CHUNK_CHARS is split into multiple char windows,
    and every window keeps the SAME section label."""
    from interchange import chunk, CHUNK_CHARS

    body = ("lorem ipsum dolor sit amet " * (CHUNK_CHARS // 5 + 20))
    text = "## Big Section\n" + body
    big = [c for c in chunk(text) if c["section"] == "Big Section"]
    assert len(big) >= 2, "oversized section should split into multiple chunks"
    assert all(c["section"] == "Big Section" for c in big)  # shared label


def test_chunk_real_x12_doc_yields_real_heading_section():
    """Chunking the real x12-overview.md produces a chunk whose section matches a
    real heading — 'Common transaction sets' (contract "Corpus facts")."""
    from interchange import chunk

    sections = {c["section"] for c in chunk(X12.read_text())}
    assert "Common transaction sets" in sections


# --- tokenize: BM25 tokenizer (contract "tokenize") -----------------------
def test_tokenize_lowercases_and_splits_on_non_alphanumeric():
    """Lowercases and splits on any non-alphanumeric character."""
    from interchange import tokenize

    assert tokenize("Hello WORLD") == ["hello", "world"]
    assert tokenize("ISA/GS-ST") == ["isa", "gs", "st"]


def test_tokenize_keeps_digit_runs_intact():
    """Digit runs survive as single tokens so exact codes stay searchable
    (contract: 824 / 997 / 008010 survive whole)."""
    from interchange import tokenize

    assert tokenize("824 997 008010") == ["824", "997", "008010"]
    # mixed alnum boundaries still split, but the digit run itself is one token
    assert tokenize("997-Functional Acknowledgment") == ["997", "functional", "acknowledgment"]
    assert "997" in tokenize("the 997 ack confirms receipt")


def test_tokenize_drops_empties():
    """Runs of separators (and empty input) produce no empty tokens."""
    from interchange import tokenize

    assert tokenize("  //  ") == []
    assert tokenize("") == []
    assert tokenize("-alpha--beta-") == ["alpha", "beta"]


# --- bm25_rank: Okapi BM25 over chunk texts (contract "bm25_rank") ---------
def test_bm25_rank_empty_corpus_returns_empty():
    """Empty corpus -> []."""
    from interchange import bm25_rank

    assert bm25_rank("anything", []) == []


def test_bm25_rank_ties_broken_by_ascending_index():
    """Identical docs score equally; ties break by ascending corpus index (stable)."""
    from interchange import bm25_rank

    ranked = bm25_rank("alpha", ["alpha beta gamma", "alpha beta gamma"])
    assert ranked == [0, 1]


def test_bm25_rank_unique_code_ranks_its_source_doc_first():
    """A query for a code UNIQUE to one doc ranks a chunk from that doc first:
    '997' -> x12-overview.md content; '417' -> rail-edi-notes.md content
    (contract "DISCRIMINATORS"). Corpus built by reading real docs + chunk()."""
    from interchange import bm25_rank

    texts, sources = _build_corpus()

    top_997 = bm25_rank("997", texts)[0]
    assert sources[top_997] == "x12-overview.md"

    top_417 = bm25_rank("417", texts)[0]
    assert sources[top_417] == "rail-edi-notes.md"


# --- reciprocal_rank_fusion (contract "reciprocal_rank_fusion") -----------
def test_rrf_empty_input_returns_empty():
    """Empty input -> []."""
    from interchange import reciprocal_rank_fusion

    assert reciprocal_rank_fusion([]) == []


def test_rrf_hand_computed_order_default_k():
    """Hand-computed example, default k=60. score(key)=Σ 1/(60+rank_1based).

      rankings = [[a,b,c], [b,c,d]]
        b = 1/62 + 1/61 = 0.032522   (present in both -> wins)
        c = 1/63 + 1/62 = 0.032002   (present in both)
        a = 1/61        = 0.016393   (one list, rank 1)
        d = 1/63        = 0.015873   (one list, rank 3)

    Expected order: b, c, a, d. Demonstrates: multi-list keys beat single-list
    keys; a key absent from a ranking (a, d) still ranks via the other."""
    from interchange import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]])
    assert fused == ["b", "c", "a", "d"]


def test_rrf_multi_list_key_beats_single_list_key():
    """A key present in multiple rankings outranks a key in only one, even when
    the single-list key holds first place there."""
    from interchange import reciprocal_rank_fusion

    # 'shared' is 2nd in both lists; 'solo' is 1st but only in one list.
    fused = reciprocal_rank_fusion([["solo", "shared"], ["other", "shared"]])
    assert fused[0] == "shared"


def test_rrf_explicit_k_tie_breaks_by_best_rank_then_first_appearance():
    """Explicit k. Equal fused scores break by best (lowest) rank seen, then by
    first appearance. With [[x,y],[y,x]] both score 1/(k+1)+1/(k+2) and both have
    a best rank of 1, so first appearance decides -> x precedes y."""
    from interchange import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion([["x", "y"], ["y", "x"]], k=10)
    assert fused == ["x", "y"]


# --- hit_at_k (contract "hit_at_k") ---------------------------------------
def test_hit_at_k_expected_as_str_within_and_outside_k():
    """expected as str: True iff it appears within the first k positions."""
    from interchange import hit_at_k

    retrieved = ["a.md", "b.md", "c.md"]
    assert hit_at_k(retrieved, "b.md", k=2) is True
    assert hit_at_k(retrieved, "c.md", k=2) is False  # position 3, outside k=2
    assert hit_at_k(retrieved, "c.md", k=3) is True


def test_hit_at_k_expected_as_list_any_match():
    """expected as list: True iff ANY listed source appears within the first k."""
    from interchange import hit_at_k

    retrieved = ["a.md", "b.md", "c.md"]
    assert hit_at_k(retrieved, ["x.md", "b.md"], k=2) is True
    assert hit_at_k(retrieved, ["x.md", "z.md"], k=3) is False


def test_hit_at_k_duplicates_count_as_positions():
    """Duplicates in retrieved_sources count as list positions (not distinct
    sources): a repeated early hit pushes later sources out of the first k."""
    from interchange import hit_at_k

    retrieved = ["a.md", "a.md", "b.md"]
    assert hit_at_k(retrieved, "a.md", k=1) is True
    assert hit_at_k(retrieved, "b.md", k=2) is False  # b.md sits at position 3
    assert hit_at_k(retrieved, "b.md", k=3) is True
