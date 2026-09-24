"""Executable acceptance criteria for context assembly with a budget (ADR-0018).

Offline discipline (ADR-0006): ``assemble_context`` is pure — no Chroma, no
embeddings, no network. The snapshot is a ``fake_snapshot`` (conftest) whose list
order is shuffled, so a note that assembles in chunk-index order proves ``chunk_map``
sorts rather than relying on Chroma's ``get`` order.

Placement (Slice-2/passage-eval lesson): these scenarios live in their own
``features/context_assembly.feature`` bound here with explicit ``scenario(...)``
calls, never bulk-bound with ``scenarios()``.
"""
from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenario, then, when

import interchange
from conftest import fake_snapshot


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("context_assembly.feature",
          "chunks mode returns exactly the hits, byte-identical to today")
def test_chunks_byte_identical():
    pass


@scenario("context_assembly.feature",
          "the seed pass includes every hit even under a one-character budget")
def test_seed_pass_under_tiny_budget():
    pass


@scenario("context_assembly.feature",
          "a small note is included whole in chunk-index order from a shuffled snapshot")
def test_small_note_whole_in_order():
    pass


@scenario("context_assembly.feature",
          "a note over the note-max falls back to neighbours")
def test_note_too_big_falls_back():
    pass


@scenario("context_assembly.feature",
          "a whole note that does not fit the remaining budget is skipped whole")
def test_budget_exhausted_skips_whole():
    pass


@scenario("context_assembly.feature",
          "no chunk is included twice when two hits share a source")
def test_no_chunk_twice():
    pass


@scenario("context_assembly.feature",
          "an expansion-added secret-like chunk is dropped and counted")
def test_expansion_secret_dropped():
    pass


@scenario("context_assembly.feature",
          "included_sources holds every seeded source and chars equals the text length")
def test_included_sources_and_chars():
    pass


@scenario("context_assembly.feature", "assembly rejects an unknown mode")
def test_rejects_unknown_mode():
    pass


@scenario("context_assembly.feature",
          "assembly rejects a note-max larger than the budget")
def test_rejects_note_max_over_budget():
    pass


@scenario("context_assembly.feature",
          "profile_retrieval rejects a string budget and clamps nothing")
def test_profile_rejects_string_budget():
    pass


@scenario("context_assembly.feature",
          "policy clamps notes to chunks and caps the budget")
def test_policy_clamps_context():
    pass


# --- builders --------------------------------------------------------------
def _padded(marker: str, length: int) -> str:
    """A chunk text of exactly ``length`` chars, starting with a unique marker so a
    test can tell chunks apart and detect any mid-chunk truncation."""
    if len(marker) >= length:
        return marker[:length]
    return marker + "x" * (length - len(marker))


def _notes(context) -> dict:
    return context.setdefault("notes", {})


def _hits(context) -> list:
    return context.setdefault("hits", [])


# --- Given -----------------------------------------------------------------
@given(parsers.parse('a note "{source}" with chunks "{spec}"'))
def note_with_chunks(context, source, spec):
    _notes(context)[source] = [c.strip() for c in spec.split(",")]


@given(parsers.parse('a note "{source}" with {n:d} chunks of {length:d} characters'))
def note_with_sized_chunks(context, source, n, length):
    _notes(context)[source] = [_padded(f"{source}#{j}", length) for j in range(n)]


@given(parsers.parse('a note "{source}" with {n:d} chunk of {length:d} characters'))
def note_with_one_sized_chunk(context, source, n, length):
    _notes(context)[source] = [_padded(f"{source}#{j}", length) for j in range(n)]


@given(parsers.parse('a note "{source}" whose chunk {idx:d} looks like a credential'))
def note_with_secret_chunk(context, source, idx):
    chunks = ["seed text of the note", "AKIAIOSFODNN7EXAMPLE is a live-looking key",
              "an ordinary trailing chunk"]
    chunks[idx] = "AKIAIOSFODNN7EXAMPLE is a live-looking key"
    _notes(context)[source] = chunks
    context["secret_chunk_text"] = chunks[idx]


@given(parsers.parse('a hit into "{source}" chunk {idx:d}'))
def hit_into(context, source, idx):
    text = _notes(context)[source][idx]
    _hits(context).append({"source": source, "chunk": idx, "text": text})


@given(parsers.parse('a profile whose retrieval budget_chars is the string "{value}"'))
def profile_string_budget(context, value):
    context["profile"] = {"name": "probe",
                          "retrieval": {"context": "notes", "budget_chars": value}}


@given(parsers.parse('the context mode max is "{mode}" and the budget max is {budget:d}'))
def policy_maxes(monkeypatch, mode, budget):
    monkeypatch.setenv("INTERCHANGE_CONTEXT_MODE_MAX", mode)
    monkeypatch.setenv("INTERCHANGE_CONTEXT_BUDGET_MAX", str(budget))


@given(parsers.parse('context settings mode "{mode}" budget {budget:d} note-max {note_max:d}'))
def context_settings(context, mode, budget, note_max):
    context["settings"] = {"context": mode, "budget_chars": budget,
                           "note_max_chars": note_max}


# --- When ------------------------------------------------------------------
def _run_assemble(context, mode, **kw):
    snap = fake_snapshot(_notes(context))
    try:
        context["result"] = interchange.assemble_context(
            _hits(context), snap, mode=mode, **kw)
    except ValueError as exc:
        context["error"] = exc


@when(parsers.parse('I assemble the context in "{mode}" mode'))
def assemble_default(context, mode):
    _run_assemble(context, mode)


@when(parsers.parse('I assemble the context in "{mode}" mode with budget {budget:d} '
                    'and note-max {note_max:d}'))
def assemble_with_budget(context, mode, budget, note_max):
    _run_assemble(context, mode, budget_chars=budget, note_max_chars=note_max)


@when("I read the profile's retrieval")
def read_profile_retrieval(context):
    from a2a_agent.profiles import profile_retrieval

    try:
        context["retrieval"] = profile_retrieval(context["profile"])
    except ValueError as exc:
        context["error"] = exc


@when("I clamp the context settings")
def clamp_settings(context):
    import policy

    context["clamped"] = policy.clamp_context(context["settings"])


# --- Then ------------------------------------------------------------------
@then("the context is byte-identical to the joined hit blocks")
def context_byte_identical(context):
    hits = _hits(context)
    expected = "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)
    assert context["result"].text == expected


@then("included_sources equals hit_sources")
def included_equals_hit_sources(context):
    a = context["result"]
    assert a.included_sources == a.hit_sources


@then("every hit's own chunk is included")
def every_hit_included(context):
    a = context["result"]
    included = set(a.included)
    for h in _hits(context):
        assert (h["source"], h["chunk"]) in included


@then(parsers.parse("dropped_hits is {n:d}"))
def dropped_hits_is(context, n):
    assert context["result"].dropped_hits == n


@then("the budget was hit")
def budget_was_hit(context):
    assert context["result"].budget_hit is True


@then(parsers.parse('the reason for "{source}" is "{reason}"'))
def reason_for_source(context, source, reason):
    assert context["result"].reasons.get(source) == reason


@then(parsers.parse('the context has one "{source}" header'))
def one_header(context, source):
    assert context["result"].text.count(f"[{source}]") == 1


@then(parsers.parse('the context is the whole note "{source}" with chunks "{spec}"'))
def context_is_whole_note(context, source, spec):
    chunks = [c.strip() for c in spec.split(",")]
    expected = f"[{source}]\n" + "\n\n".join(chunks)
    assert context["result"].text == expected


@then(parsers.parse("fallbacks is {n:d}"))
def fallbacks_is(context, n):
    assert context["result"].fallbacks == n


@then(parsers.parse('more than one chunk of "{source}" is included'))
def more_than_one_chunk(context, source):
    count = sum(1 for s, _ in context["result"].included if s == source)
    assert count > 1


@then(parsers.parse('only {n:d} chunk of "{source}" is included'))
def only_n_chunks(context, n, source):
    count = sum(1 for s, _ in context["result"].included if s == source)
    assert count == n


@then("no included chunk text is truncated")
def no_truncation(context):
    a = context["result"]
    notes = _notes(context)
    for source, idx in a.included:
        assert notes[source][idx] in a.text


@then(parsers.parse('each included chunk of "{source}" appears once'))
def each_chunk_once(context, source):
    refs = [(s, i) for s, i in context["result"].included if s == source]
    assert len(refs) == len(set(refs))


@then(parsers.parse("secret_drops is {n:d}"))
def secret_drops_is(context, n):
    assert context["result"].secret_drops == n


@then(parsers.parse('the seed chunk of "{source}" is kept'))
def seed_kept(context, source):
    # the hit's own chunk (the seed) must still be included
    seed_chunks = {h["chunk"] for h in _hits(context) if h["source"] == source}
    included = {i for s, i in context["result"].included if s == source}
    assert seed_chunks <= included


@then("the credential-like chunk is absent from the context")
def secret_absent(context):
    assert context["secret_chunk_text"] not in context["result"].text


@then(parsers.parse('included_sources is "{spec}"'))
def included_sources_is(context, spec):
    want = [s.strip() for s in spec.split(",")]
    assert context["result"].included_sources == want


@then("chars equals the length of the text")
def chars_equals_len(context):
    a = context["result"]
    assert a.chars == len(a.text)


@then("assembly raises a ValueError")
def assembly_raises(context):
    assert isinstance(context.get("error"), ValueError)


@then(parsers.parse('a retrieval ValueError names "{token}"'))
def retrieval_valueerror_names(context, token):
    assert isinstance(context.get("error"), ValueError)
    assert token in str(context["error"])


@then(parsers.parse('the clamped mode is "{mode}"'))
def clamped_mode_is(context, mode):
    assert context["clamped"]["context"] == mode


@then(parsers.parse("the clamped budget is {budget:d}"))
def clamped_budget_is(context, budget):
    assert context["clamped"]["budget_chars"] == budget


# --- plain-pytest units: chunk_map sorts a shuffled snapshot ---------------
def test_chunk_map_sorts_shuffled_snapshot():
    snap = fake_snapshot({"n.md": [f"chunk-{j}" for j in range(6)]})
    cmap = interchange.chunk_map(snap)
    chunk_order = [int(snap.metas[i]["chunk"]) for i in cmap["n.md"]]
    assert chunk_order == [0, 1, 2, 3, 4, 5]


def test_chunk_map_is_cached_on_the_snapshot():
    snap = fake_snapshot({"n.md": ["c0", "c1"]})
    first = interchange.chunk_map(snap)
    assert snap.chunk_map_cache is first
    assert interchange.chunk_map(snap) is first


@pytest.mark.parametrize("budget,note_max", [(0, 0), (-1, -1), (100, 0)])
def test_assemble_rejects_nonpositive_budgets(budget, note_max):
    snap = fake_snapshot({"a.md": ["alpha"]})
    hits = [{"source": "a.md", "chunk": 0, "text": "alpha"}]
    with pytest.raises(ValueError):
        interchange.assemble_context(hits, snap, mode="notes",
                                     budget_chars=budget, note_max_chars=note_max)
