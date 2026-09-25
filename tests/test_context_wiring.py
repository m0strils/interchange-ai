"""Executable acceptance criteria for ADR-0018 Slice D: context assembly wired into
the answer path, resolved once for every surface.

Offline discipline (ADR-0006): no Chroma, no embeddings, no network, no subprocess.
``interchange.retrieve_detail`` is faked with ``conftest.fake_retrieval``, the snapshot
seam with ``conftest.fake_snapshot``, the profile lookup by monkeypatching the
module-level ``interchange.profile_for_collection`` seam, and generation with the offline
``stub`` engine. The BDD scenarios live in ``features/context_wiring.feature`` and are
bound explicitly below (never bulk ``scenarios()``); the surface-parity, retrieval-record
and clamp checks are plain units in the same module.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenario, then, when

import enterprise
import interchange
import policy
from tests.conftest import fake_retrieval, fake_snapshot, last_audit_row


# --- helpers ---------------------------------------------------------------
def _notes_profile(collection: str = "edi") -> dict:
    return {"name": "fake", "collection": collection,
            "retrieval": {"context": "notes", "budget_chars": 20000,
                          "note_max_chars": 16000}}


def _chunks_profile(collection: str = "edi") -> dict:
    return {"name": "fake", "collection": collection,
            "retrieval": {"context": "chunks"}}


def _stub_engine(monkeypatch):
    """Pin the ``api``/``stub`` engines to the offline canned generator."""
    monkeypatch.setitem(interchange.ENGINES, "api", interchange.ENGINES["stub"])


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("context_wiring.feature",
          "A pinned re-ask under a notes profile never assembles")
def test_pinned_reask_never_assembles():
    pass


@scenario("context_wiring.feature",
          "Grounding and audit follow the included set, not the retrieved hits")
def test_grounding_follows_included_set():
    pass


@scenario("context_wiring.feature",
          "Chunks mode assembles without touching the snapshot")
def test_chunks_mode_no_snapshot():
    pass


@scenario("context_wiring.feature",
          "An invalid profile retrieval block falls back to chunks and still answers")
def test_invalid_profile_falls_back_to_chunks():
    pass


@scenario("context_wiring.feature",
          "A public deploy clamps the context mode to chunks")
def test_public_deploy_clamps_to_chunks():
    pass


# --- Given -----------------------------------------------------------------
@given(parsers.parse('the corpus profile declares context "{mode}"'))
def profile_declares_context(context, monkeypatch, mode):
    prof = _notes_profile() if mode == "notes" else _chunks_profile()
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: prof)
    _stub_engine(monkeypatch)


@given("the corpus profile has an invalid retrieval block")
def profile_is_invalid(context, monkeypatch):
    bad = {"name": "bad", "collection": "edi", "retrieval": {"context": "bogus"}}
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: bad)
    _stub_engine(monkeypatch)


@given("a fake snapshot the assembler could expand")
def snapshot_expandable(context, monkeypatch):
    monkeypatch.setattr(interchange, "corpus_snapshot",
                        lambda c: fake_snapshot({"a.md": ["one", "two", "three"]}))


@given("a fake snapshot holding only the first hit's note")
def snapshot_first_note_only(context, monkeypatch):
    monkeypatch.setattr(interchange, "corpus_snapshot",
                        lambda c: fake_snapshot({"a.md": ["one", "two"]}))


@given("the snapshot raises if it is touched")
def snapshot_raises(context, monkeypatch):
    def boom(c):
        raise AssertionError("corpus_snapshot must not be touched in chunks mode")

    monkeypatch.setattr(interchange, "corpus_snapshot", boom)


@given("two pinned chunks are fetched for the corpus")
def two_pins_fetched(context, monkeypatch):
    def fake_fetch(corpus, pins):
        hits = fake_retrieval(
            {"source": "a.md", "text": "one", "chunk": 0},
            {"source": "a.md", "text": "two", "chunk": 1}, corpus=corpus).hits
        for h in hits:
            h["pinned"] = True
        return hits, []

    monkeypatch.setattr(interchange, "fetch_chunks", fake_fetch)
    context["pins"] = [{"id": "a.md:0", "token": "x"}, {"id": "a.md:1", "token": "x"}]


@given("a fake retrieval of a hit in the snapshot and a hit missing from it")
def retrieval_present_and_missing(context, monkeypatch):
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval(
            {"source": "a.md", "text": "one", "chunk": 0},
            {"source": "b.md", "text": "gone", "chunk": 0}))


@given("a fake retrieval of one chunk")
def retrieval_one_chunk(context, monkeypatch):
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval({"source": "a.md", "text": "one", "chunk": 0}))


@given("the deploy is public")
def deploy_public(context, monkeypatch):
    monkeypatch.setenv("A2A_PUBLIC_URL", "https://public.example")


# --- When ------------------------------------------------------------------
@when("I answer a pinned re-ask")
def answer_pinned(context):
    context["detail"] = interchange.answer_detail(
        "what is it?", engine="stub", pin=context["pins"])


@when("I answer over the corpus")
def answer_over_corpus(context):
    context["detail"] = interchange.answer_detail("what is it?", engine="stub")


# --- Then ------------------------------------------------------------------
@then(parsers.parse('the response context mode is "{mode}"'))
def response_context_mode(context, mode):
    assert context["detail"]["context"]["mode"] == mode


@then(parsers.parse("the response context chunks_out equals {n:d}"))
def response_chunks_out(context, n):
    assert context["detail"]["context"]["chunks_out"] == n


@then("the answer is grounded")
def answer_is_grounded(context):
    assert context["detail"]["grounded"] is True


@then(parsers.parse('the audit sources are exactly "{source}"'))
def audit_sources_exactly(context, source):
    assert last_audit_row()["sources"] == [source]


@then("the missing hit's source is absent from the audit sources")
def missing_absent_from_sources(context):
    assert "b.md" not in last_audit_row()["sources"]


@then("the missing hit's source is present in the audit hit_sources")
def missing_present_in_hit_sources(context):
    assert "b.md" in last_audit_row()["hit_sources"]


# --- units -----------------------------------------------------------------
def test_retrieval_record_unchanged_after_assembly(monkeypatch):
    """The scored Retrieval the caller sees is returned unchanged — every hit and score
    field identical before and after assembly (assembly is pure, after ranking)."""
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: _notes_profile())
    monkeypatch.setattr(interchange, "corpus_snapshot",
                        lambda c: fake_snapshot({"a.md": ["one", "two", "three"]}))
    _stub_engine(monkeypatch)
    retr = fake_retrieval({"source": "a.md", "text": "one", "chunk": 0},
                          {"source": "a.md", "text": "two", "chunk": 1})
    before = copy.deepcopy(retr.hits)
    monkeypatch.setattr(interchange, "retrieve_detail", lambda q, **kw: retr)

    detail = interchange.answer_detail("what is it?", engine="stub")
    # the hits the caller gets back are the scored hits, unmutated by assembly
    assert detail["hits"] == before
    for got, orig in zip(detail["hits"], before):
        assert got["final_rank"] == orig["final_rank"]
        for field in ("dense_rank", "dense_distance", "bm25_rank", "bm25_score",
                      "rrf_score", "rerank_score"):
            assert got[field] == orig[field]


def test_all_surfaces_resolve_the_same_context_for_a_collection(monkeypatch):
    """CLI ``answer()``, HTTP ``POST /ask`` and A2A all resolve the profile's ``notes``
    for the ``edi`` collection; MCP ``search_docs`` stays on ``chunks`` by design."""
    import a2a_agent.server as a2a_server
    import mcp_server

    monkeypatch.setenv("INTERCHANGE_CORPORA", "edi")
    monkeypatch.delenv("INTERCHANGE_LOCKED", raising=False)
    monkeypatch.delenv("INTERCHANGE_UNLOCKED", raising=False)
    monkeypatch.setenv("INTERCHANGE_RATE_PER_MIN", "1000")
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: _notes_profile())
    monkeypatch.setattr(interchange, "corpus_snapshot",
                        lambda c: fake_snapshot({"a.md": ["one", "two"]}))
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval({"source": "a.md", "text": "one", "chunk": 0}))
    # mcp_server binds `retrieve` at import (a module-local name), so patch it there.
    monkeypatch.setattr(mcp_server, "retrieve",
                        lambda q, **kw: [("one", {"source": "a.md", "chunk": 0})])
    _stub_engine(monkeypatch)
    policy.reset_buckets()
    policy.reset_semaphore()

    # CLI: answer() -> audit row records the resolved context mode
    interchange.answer("what is it?", engine="stub")
    assert last_audit_row()["context"]["mode"] == "notes"

    # A2A: _answer_as passes mode/context None so the resolver reads the profile
    detail = a2a_server._answer_as("requester", "what is it?", "edi")
    assert detail["context"]["mode"] == "notes"

    # HTTP: the profile default flows through even though the knob is locked (unset)
    from app import create_app
    body = TestClient(create_app()).post("/ask", json={"q": "what is it?"}).json()
    assert body["context"]["mode"] == "notes"

    # MCP: search_docs never assembles — raw per-chunk passages, always chunks
    out = mcp_server.search_docs("what is it?")
    assert out == "[a.md]\none"


def test_search_docs_stays_chunks_under_a_notes_profile(monkeypatch):
    """ADR-0018: ``search_docs`` returns raw per-chunk passages regardless of the
    profile's context — it never runs note assembly."""
    import mcp_server

    monkeypatch.setattr(interchange, "PROFILE_RETRIEVAL",
                        {"mode": "hybrid", "context": "notes"})
    # mcp_server binds `retrieve` at import (a module-local name), so patch it there.
    monkeypatch.setattr(mcp_server, "retrieve",
                        lambda q, **kw: [("one", {"source": "a.md", "chunk": 0}),
                                         ("two", {"source": "a.md", "chunk": 1})])
    out = mcp_server.search_docs("q")
    assert out == "[a.md]\none\n\n[a.md]\ntwo"


def test_profile_budget_over_cap_is_clamped(monkeypatch):
    """A profile budget over ``INTERCHANGE_CONTEXT_BUDGET_MAX`` is clamped by policy
    (policy over profile) in the resolver every surface reads."""
    monkeypatch.setenv("INTERCHANGE_CONTEXT_BUDGET_MAX", "12000")
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: _notes_profile())
    settings = interchange.resolve_context(corpus="edi")
    assert settings["budget_chars"] == 12000
    # note_max_chars <= budget_chars invariant is restored after the clamp
    assert settings["note_max_chars"] <= settings["budget_chars"]


def test_a2a_resolves_the_real_hotel_profile_to_chunks(monkeypatch):
    """A2A passes mode/context None, so the resolver reads the collection's real profile:
    hotel carries no ``retrieval`` block → ``chunks`` / ``hybrid`` (no Chroma touched)."""
    import a2a_agent.server as a2a_server

    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval({"source": "policies.md", "text": "late checkout",
                                        "chunk": 0}, corpus="hotel"))
    _stub_engine(monkeypatch)
    detail = a2a_server._answer_as("requester", "late checkout?", "hotel")
    assert detail["context"]["mode"] == "chunks"
    assert detail["mode"] == "hybrid"


def test_resolve_context_forces_chunks_when_pinned(monkeypatch):
    """A pin is a return-this-chunk capability, not a read-the-note oracle — the resolver
    forces ``chunks`` even under a ``notes`` profile (review finding #1)."""
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: _notes_profile())
    assert interchange.resolve_context(corpus="edi", pinned=True)["mode"] == "chunks"
    assert interchange.resolve_context(corpus="edi", pinned=False)["mode"] == "notes"
