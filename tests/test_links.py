"""Offline unit tests for the wikilink graph — parse, resolve, and the
`hybrid+links` expansion seam (ADR-0014, slice 4).

Offline + $0 discipline (mirrors tests/test_eval_runner.py's header): no network,
no Chroma, no embeddings. Every function under test is pure — it takes strings and
in-memory dicts and returns strings — so these run in the offline pytest gate. Each
symbol is imported inside the test that needs it, so a not-yet-landed function fails
only its own test, never collection.
"""
from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"


# --- parse_wikilinks -------------------------------------------------------
def test_parse_wikilinks_alias_heading_and_path_forms():
    """Alias (``|``), heading (``#``) and path forms all reduce to the bare target;
    the alias text and heading anchor are discarded."""
    from interchange import parse_wikilinks

    text = (
        "See [[Note]], [[Note Two|its alias]], [[Note Three#Section]], "
        "[[Note Four#Section|Alias]], [[Planning/ROADMAP|Vendor Migration Roadmap]] "
        "and [[../_Tag_Taxonomy|Tag Taxonomy]]."
    )
    assert parse_wikilinks(text) == [
        "Note", "Note Two", "Note Three", "Note Four",
        "Planning/ROADMAP", "../_Tag_Taxonomy",
    ]


def test_parse_wikilinks_drops_templater_placeholders():
    """A Templater target (containing ``<%``) is scaffolding, not a link — dropped;
    real links around it survive."""
    from interchange import parse_wikilinks

    text = "[[<% tp.file.title %>]] and [[Daily/<%date%>]] but [[Real Note]] stays"
    assert parse_wikilinks(text) == ["Real Note"]


def test_parse_wikilinks_dedupes_preserving_order():
    """Repeated targets collapse to one, in first-seen order."""
    from interchange import parse_wikilinks

    assert parse_wikilinks("[[A]] [[B]] [[A]] [[C]] [[B]]") == ["A", "B", "C"]


def test_seed_docs_carry_no_wikilinks():
    """The flat EDI seed corpus has no wikilinks — which is exactly why
    ``hybrid+links`` must rank identically to ``hybrid`` on it (the slice invariant)."""
    from interchange import parse_wikilinks

    md = sorted(DOCS.glob("*.md"))
    assert md, "expected the seed docs/*.md to exist"
    combined = "\n".join(p.read_text(encoding="utf-8") for p in md)
    assert parse_wikilinks(combined) == []


# --- build_title_index -----------------------------------------------------
def test_build_title_index_groups_duplicates():
    """Duplicate stems group under one key, each list sorted shortest-path first
    (Obsidian's rule); a unique stem maps to a single-element list."""
    from interchange import build_title_index

    titles = build_title_index([
        "b/c/Index.md", "a/Index.md", "Other.md",
    ])
    assert titles["Index"] == ["a/Index.md", "b/c/Index.md"]  # shortest path first
    assert titles["Other"] == ["Other.md"]


# --- resolve_link ----------------------------------------------------------
def test_resolve_link_note_relative_dotdot():
    """A ``../Sibling`` link resolves against the linking note's own directory."""
    from interchange import build_title_index, resolve_link

    known = {"03-RESOURCES/_Tag_Taxonomy.md", "03-RESOURCES/Checklists/Monthly.md"}
    titles = build_title_index(sorted(known))
    got = resolve_link("../_Tag_Taxonomy",
                       "03-RESOURCES/Checklists/Monthly.md", known, titles)
    assert got == "03-RESOURCES/_Tag_Taxonomy.md"


def test_resolve_link_root_relative():
    """A root-relative path (no ``../``, not under the note's folder) resolves from
    the corpus root."""
    from interchange import build_title_index, resolve_link

    known = {"01-PROJECTS/spec-cli/Index.md", "02-AREAS/note.md"}
    titles = build_title_index(sorted(known))
    got = resolve_link("01-PROJECTS/spec-cli/Index", "02-AREAS/note.md", known, titles)
    assert got == "01-PROJECTS/spec-cli/Index.md"


def test_resolve_link_bare_title_shortest_path_wins():
    """A bare ``[[Title]]`` with several matches resolves to the shortest path."""
    from interchange import build_title_index, resolve_link

    known = {"z/Index.md", "01-PROJECTS/deep/Index.md", "a/b/Index.md"}
    titles = build_title_index(sorted(known))
    got = resolve_link("Index", "somewhere/note.md", known, titles)
    assert got == "z/Index.md"  # len 10 < 17 < 22


def test_resolve_link_unresolved_is_none():
    """A target that matches nothing — no relative path, no root path, no title —
    resolves to None rather than being guessed."""
    from interchange import build_title_index, resolve_link

    known = {"a/Real.md"}
    titles = build_title_index(sorted(known))
    assert resolve_link("Nonexistent", "a/Real.md", known, titles) is None


# --- expand_with_links -----------------------------------------------------
def _id_source(mapping: dict[str, list[str]]) -> dict[str, str]:
    """Build {chunk_id: source} from {source: [chunk_ids]}."""
    return {cid: src for src, cids in mapping.items() for cid in cids}


def test_expand_with_links_adds_one_hop_targets_of_top_n_notes():
    """The link ranking is the one-hop neighbours of the top-`top_n` fused notes,
    mapped to each neighbour's first chunk when it is not already ranked."""
    from interchange import expand_with_links

    chunks = {"A.md": ["A:0"], "B.md": ["B:0"], "C.md": ["C:0"],
              "N1.md": ["N1:0"], "N2.md": ["N2:0"]}
    id_source = _id_source(chunks)
    fused = ["A:0", "B:0", "C:0"]
    source_links = {"A.md": ["N1.md"], "B.md": ["N2.md"], "C.md": []}
    source_first_chunk = {s: cids[0] for s, cids in chunks.items()}

    got = expand_with_links(fused, id_source, source_links, source_first_chunk, top_n=3)
    assert got == ["N1:0", "N2:0"]

    # narrowing the seed set to the top 1 note only expands A's neighbour
    got1 = expand_with_links(fused, id_source, source_links, source_first_chunk, top_n=1)
    assert got1 == ["N1:0"]


def test_expand_with_links_prefers_a_targets_already_ranked_chunk():
    """When a neighbour's source already has a chunk in the fused list, expansion
    re-ranks the EARLIEST such chunk rather than pulling in its first chunk."""
    from interchange import expand_with_links

    chunks = {"A.md": ["A:0"], "D.md": ["D:0", "D:2", "D:5"]}
    id_source = _id_source(chunks)
    # A is the only seed; it links to D, whose D:2 and D:5 are already fused (D:0 not)
    fused = ["A:0", "D:2", "D:5"]
    source_links = {"A.md": ["D.md"]}
    source_first_chunk = {"A.md": "A:0", "D.md": "D:0"}

    got = expand_with_links(fused, id_source, source_links, source_first_chunk, top_n=1)
    assert got == ["D:2"]  # earliest fused chunk of D, not the fallback D:0


def test_expand_with_links_excludes_seed_sources():
    """A link back to one of the seed notes is dropped — the seed is already
    ranked, so re-adding it would double-count, not expand."""
    from interchange import expand_with_links

    chunks = {"A.md": ["A:0"], "B.md": ["B:0"], "E.md": ["E:0"]}
    id_source = _id_source(chunks)
    fused = ["A:0", "B:0"]
    # A links to B (a seed -> excluded) and E (new); B links only back to A (excluded)
    source_links = {"A.md": ["B.md", "E.md"], "B.md": ["A.md"]}
    source_first_chunk = {s: cids[0] for s, cids in chunks.items()}

    got = expand_with_links(fused, id_source, source_links, source_first_chunk, top_n=2)
    assert got == ["E:0"]


# --- fuse_rankings hybrid+links --------------------------------------------
def test_fuse_rankings_hybrid_plus_links_equals_hybrid_when_no_links():
    """The slice invariant: with no link ranking, ``hybrid+links`` is byte-for-byte
    ``hybrid`` — so a corpus with no resolved links ranks identically either way."""
    from interchange import fuse_rankings

    dense, bm25 = ["a", "b", "c"], ["b", "c", "d"]
    hybrid = fuse_rankings(dense, bm25, mode="hybrid")
    assert fuse_rankings(dense, bm25, mode="hybrid+links") == hybrid
    assert fuse_rankings(dense, bm25, mode="hybrid+links", link_ids=None) == hybrid
    assert fuse_rankings(dense, bm25, mode="hybrid+links", link_ids=[]) == hybrid
