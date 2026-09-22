"""Executable acceptance criteria for vault-corpus ingestion.

Gherkin lives in ``features/vault_corpus.feature``. The behavior under test is
ingest-side only: recursive discovery under a corpus root, the gitignore-lite
ignore rules, folder-relative ``source`` values, and the credential guard.

Offline discipline (mirrors ``test_hybrid_retrieval.py``): no Chroma, no
embeddings, no network. The steps build throwaway trees under ``tmp_path`` (or
read the real ``docs/``) and assert on ``interchange``'s pure functions —
``discover_files`` / ``rel_source`` / ``looks_like_secret``. ``build_index()``
itself, which touches Chroma, is deliberately NOT exercised here (ADR-0006).
"""
from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

import interchange

scenarios("vault_corpus.feature")


def _make_vault(tmp_path, spec: str):
    """Create every relative path named in `spec` (a quoted, comma/and-separated
    list) as a small file under tmp_path, and return the vault root."""
    import re

    for rel in re.findall(r'"([^"]+)"', spec):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\nBody of {rel}.\n", encoding="utf-8")
    return tmp_path


# --- Given -----------------------------------------------------------------
@given(parsers.re(r'a vault with (?P<spec>.+)'))
def vault(context, tmp_path, monkeypatch, spec):
    """A throwaway folder tree. INTERCHANGE_IGNORE is cleared so the scenario
    reads the built-in defaults plus whatever the vault's own ignore file says."""
    monkeypatch.delenv("INTERCHANGE_IGNORE", raising=False)
    context["root"] = _make_vault(tmp_path, spec)


@given(parsers.parse('the vault\'s ignore file lists "{pattern}"'))
def vault_ignore_file(context, pattern):
    """Write a committed-style .interchangeignore into the vault root."""
    ignore = context["root"] / interchange.IGNORE_FILE
    ignore.write_text(f"# scenario-provided\n{pattern}\n", encoding="utf-8")


@given("the real seed docs directory")
def seed_docs(context, monkeypatch):
    """The repo's own docs/ — the corpus the golden eval set is scored against."""
    monkeypatch.delenv("INTERCHANGE_IGNORE", raising=False)
    context["root"] = interchange.DOCS_DIR


@given(parsers.parse('a note whose body is "{body}"'))
def note_body(context, body):
    context["body"] = body


@given(parsers.parse('a fused ranking of notes "{seeds}" whose links are "{links}"'))
def fused_ranking_with_links(context, seeds, links):
    """An in-memory link graph: each named note has exactly one chunk ``name:0``;
    `links` is a comma list of ``src->dst`` edges. Builds the id_source /
    source_links / source_first_chunk maps expand_with_links() consumes."""
    seed_sources = [s.strip() for s in seeds.split(",") if s.strip()]
    source_links: dict[str, list[str]] = {f"{s}.md": [] for s in seed_sources}
    names = set(seed_sources)
    for pair in links.split(","):
        pair = pair.strip()
        if not pair:
            continue
        src, dst = (x.strip() for x in pair.split("->"))
        source_links.setdefault(f"{src}.md", []).append(f"{dst}.md")
        names.update((src, dst))
    context["fused"] = [f"{s}:0" for s in seed_sources]
    context["id_source"] = {f"{n}:0": f"{n}.md" for n in names}
    context["source_links"] = source_links
    context["source_first_chunk"] = {f"{n}.md": f"{n}:0" for n in names}


@given(parsers.parse('a dense ranking "{dense}" and a bm25 ranking "{bm25}"'))
def dense_and_bm25_rankings(context, dense, bm25):
    context["dense"] = [s.strip() for s in dense.split(",") if s.strip()]
    context["bm25"] = [s.strip() for s in bm25.split(",") if s.strip()]


# --- When (wikilink graph) -------------------------------------------------
@when(parsers.parse('I resolve the wikilink "{link}" from "{from_source}"'))
def resolve_wikilink(context, link, from_source):
    root = context["root"]
    known = {interchange.rel_source(root, path) for path in interchange.discover_files(root)}
    titles = interchange.build_title_index(sorted(known))
    targets = interchange.parse_wikilinks(link)
    target = targets[0] if targets else ""
    context["resolved"] = interchange.resolve_link(target, from_source, known, titles)


@when("I expand the ranking along its links")
def expand_ranking(context):
    ids = interchange.expand_with_links(
        context["fused"], context["id_source"],
        context["source_links"], context["source_first_chunk"],
    )
    context["link_candidates"] = [context["id_source"][i] for i in ids]


@when("I fuse them with no link ranking")
def fuse_without_links(context):
    context["hybrid"] = interchange.fuse_rankings(
        context["dense"], context["bm25"], mode="hybrid")
    context["hybrid_links"] = interchange.fuse_rankings(
        context["dense"], context["bm25"], mode="hybrid+links")


# --- When ------------------------------------------------------------------
@when("I discover the vault's indexable files")
def discover(context):
    root = context["root"]
    context["sources"] = [
        interchange.rel_source(root, path) for path in interchange.discover_files(root)
    ]


# --- Then ------------------------------------------------------------------
@then(parsers.parse('the discovered sources are "{expected}"'))
def sources_are(context, expected):
    want = [s.strip() for s in expected.split(",") if s.strip()]
    assert context["sources"] == want, (
        f"discovered {context['sources']!r}, expected {want!r}"
    )


@then("every discovered source is unique")
def sources_unique(context):
    sources = context["sources"]
    assert len(set(sources)) == len(sources), f"duplicate sources in {sources!r}"


@then("the credential guard flags the note")
def guard_flags(context):
    assert interchange.looks_like_secret(context["body"]) is True


@then("the credential guard does not flag the note")
def guard_passes(context):
    assert interchange.looks_like_secret(context["body"]) is False


@then(parsers.parse('the wikilink resolves to "{expected}"'))
def wikilink_resolves(context, expected):
    assert context["resolved"] == expected, (
        f"resolved to {context['resolved']!r}, expected {expected!r}"
    )


@then("the wikilink does not resolve")
def wikilink_unresolved(context):
    assert context["resolved"] is None, f"expected None, got {context['resolved']!r}"


@then(parsers.parse('the link candidates are "{expected}"'))
def link_candidates_are(context, expected):
    want = [f"{s.strip()}.md" for s in expected.split(",") if s.strip()]
    assert context["link_candidates"] == want, (
        f"candidates {context['link_candidates']!r}, expected {want!r}"
    )


@then("hybrid+links ranks identically to hybrid")
def hybrid_links_equals_hybrid(context):
    assert context["hybrid_links"] == context["hybrid"]
