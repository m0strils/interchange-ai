"""Executable acceptance criteria for the lead-chunk merge at ingest (ADR-0017,
Slice 3 step 2).

Offline discipline (ADR-0006): ``merge_lead_chunks`` is pure — no Chroma, no
embeddings — and the two build_index scenarios stub ``chromadb.PersistentClient``
with a recording client (the pattern from ``tests/test_passage_eval.py`` /
``tests/test_apply_profile.py``) so a full ``build_index`` runs against a tmp corpus
with no network and no index build.

Placement (Slice-2 lesson): these scenarios live in their own
``features/lead_chunks.feature`` bound here with explicit ``scenario(...)`` calls,
never a bulk ``scenarios()``.
"""
from __future__ import annotations

import re

import chromadb
from pytest_bdd import given, parsers, scenario, then, when

import interchange


# --- scenario bindings (explicit) ------------------------------------------
@scenario("lead_chunks.feature",
          "Frontmatter and the H1 intro merge into the first body section")
def test_frontmatter_and_h1_merge():
    pass


@scenario("lead_chunks.feature", "A lead run over the limit is left alone")
def test_lead_run_over_limit_left_alone():
    pass


@scenario("lead_chunks.feature", "A title-only note stays one chunk")
def test_title_only_note_stays_one_chunk():
    pass


@scenario("lead_chunks.feature", "A preamble-only document is untouched")
def test_preamble_only_untouched():
    pass


@scenario("lead_chunks.feature", "The merged chunk is not counted by lead_share")
def test_merged_chunk_not_counted_by_lead_share():
    pass


@scenario("lead_chunks.feature", "Chunk ids stay contiguous after a merge")
def test_chunk_ids_contiguous_after_merge():
    pass


@scenario("lead_chunks.feature", "The indexing summary reports merged lead chunks")
def test_summary_reports_merged_lead_chunks():
    pass


# --- recording stub Chroma client (the pattern from test_passage_eval.py) --
class _RecordingCol:
    """A stub Chroma collection that records the single ``add()`` build_index makes."""

    def __init__(self):
        self.added = None

    def add(self, ids=None, documents=None, metadatas=None):
        self.added = {"ids": ids, "documents": documents, "metadatas": metadatas}


class _RecordingClient:
    """A stub ``chromadb.PersistentClient``: delete is a no-op, create hands back a
    fresh recording collection."""

    last = None

    def __init__(self, path=None):
        pass

    def delete_collection(self, name):
        pass

    def create_collection(self, name):
        _RecordingClient.last = _RecordingCol()
        return _RecordingClient.last


# --- Given -----------------------------------------------------------------
@given("a frontmatter note with a short H1 intro and an H2 body")
def frontmatter_short_intro_body(context):
    note = (
        "---\n"
        "type: note\n"
        "tags: [demo]\n"
        "---\n"
        "# A Heading Unlike The Filename\n\n"
        "Short intro under the H1.\n\n"
        "## Body\n\n"
        "the real body content lives here.\n"
    )
    context["chunks"] = interchange.mark_lead(interchange.chunk(note))
    context["before"] = [dict(c) for c in context["chunks"]]


@given("a frontmatter note whose H1 intro is 700 characters")
def frontmatter_long_intro_body(context):
    intro = "x" * 700
    note = (
        "---\n"
        "type: note\n"
        "---\n"
        f"# A Heading\n\n{intro}\n\n"
        "## Body\n\n"
        "the real body content lives here.\n"
    )
    context["chunks"] = interchange.mark_lead(interchange.chunk(note))
    context["before"] = [dict(c) for c in context["chunks"]]


@given("a title-only note")
def title_only_note(context):
    note = "# Just A Title\n\nA one-line note with no further section.\n"
    context["chunks"] = interchange.mark_lead(interchange.chunk(note))
    context["before"] = [dict(c) for c in context["chunks"]]


@given("a preamble-only document with no headings")
def preamble_only_document(context):
    # PDF-style flat text: no Markdown headings at all -> a single preamble chunk.
    note = "Flat extracted text with no markdown headings whatsoever, like a PDF.\n"
    context["chunks"] = interchange.mark_lead(interchange.chunk(note))
    context["before"] = [dict(c) for c in context["chunks"]]


@given("a merging two-body corpus and a recording Chroma client")
def merging_two_body_corpus(context, tmp_path, monkeypatch):
    note = (
        "---\n"
        "type: note\n"
        "tags: [demo]\n"
        "---\n"
        "# A Heading Unlike The Filename\n\n"
        "Short intro under the H1.\n\n"
        "## Body One\n\n"
        "the first real section.\n\n"
        "## Body Two\n\n"
        "the second real section.\n"
    )
    (tmp_path / "note.md").write_text(note, encoding="utf-8")
    monkeypatch.setattr(interchange, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(chromadb, "PersistentClient", _RecordingClient)


# --- When ------------------------------------------------------------------
@when("I merge the lead chunks")
def merge_the_lead_chunks(context):
    context["merged"] = interchange.merge_lead_chunks(context["chunks"])


@when("the merged chunk and a genuine preamble hit are the top 2 results")
def merged_plus_preamble_hits(context):
    context["hits_meta"] = [
        context["merged"][0],
        {"source": "n.md", "section": "preamble", "title": "n", "lead": True},
    ]


@when("I build the index")
def build_the_index(context):
    context["summary"] = interchange.build_index()
    context["added"] = _RecordingClient.last.added


# --- Then ------------------------------------------------------------------
@then(parsers.parse("the merge yields {n:d} chunk"))
def merge_yields_n(context, n):
    assert len(context["merged"]) == n


@then(parsers.parse('chunk 1 has section "{sec}" level {lvl:d} lead {lead} '
                    'merged_lead {merged}'))
def chunk_one_attributes(context, sec, lvl, lead, merged):
    c = context["merged"][0]
    assert c["section"] == sec
    assert c["level"] == lvl
    assert c["lead"] is (lead.strip().lower() == "true")
    assert c["merged_lead"] is (merged.strip().lower() == "true")


@then(parsers.parse('chunk 1\'s text contains in order "{a}", "{b}", "{c}"'))
def chunk_one_text_in_order(context, a, b, c):
    text = context["merged"][0]["text"]
    ia, ib, ic = text.find(a), text.find(b), text.find(c)
    assert ia != -1 and ib != -1 and ic != -1, (ia, ib, ic, text)
    assert ia < ib < ic, (ia, ib, ic)


@then("no chunk was merged")
def no_chunk_merged(context):
    assert not any(c.get("merged_lead") for c in context["merged"])


@then("the chunk count is unchanged")
def chunk_count_unchanged(context):
    assert len(context["merged"]) == len(context["before"])


@then("the lead flags are preserved")
def lead_flags_preserved(context):
    assert [c["lead"] for c in context["merged"]] == \
        [c["lead"] for c in context["before"]]


@then(parsers.parse('the lead share at k {k:d} is "{val}"'))
def lead_share_at_k_is(context, k, val):
    assert f"{interchange.lead_share(context['hits_meta'], k):.2f}" == val


@then(parsers.parse('the chunk ids are "{spec}"'))
def chunk_ids_are(context, spec):
    assert context["added"]["ids"] == spec.split(",")


@then(parsers.parse("the first recorded chunk has merged_lead {b}"))
def first_recorded_merged_lead(context, b):
    assert context["added"]["metadatas"][0]["merged_lead"] is \
        (b.strip().lower() == "true")


@then("the summary reports merged lead chunks")
def summary_reports_merged(context):
    assert re.search(r"; \d+ lead chunks merged\)", context["summary"]), \
        context["summary"]
