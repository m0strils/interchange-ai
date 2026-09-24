"""Executable acceptance criteria for the context-assembly eval (ADR-0018 Slice C).

Offline discipline (ADR-0006): ``retrieve`` returns ``(doc, meta)`` pairs (stubbed),
``eval_snapshot`` returns a ``fake_snapshot`` (conftest, stubbed), and
``_known_sources`` / ``_known_sections`` are monkeypatched; the golden set and the run
log live under ``tmp_path``. ``chunks`` context needs no snapshot (so it never touches
Chroma, exactly like the ADR-0017 passage eval); ``notes`` context assembles by note
under a budget. Section matching is on the INCLUDED chunk metadata, never a substring.

Placement (Slice-2/passage-eval lesson): these scenarios live in their own
``features/context_eval.feature`` bound here with explicit ``scenario(...)`` calls,
never appended to the bulk-bound ``features/retrieval_eval.feature``.
"""
from __future__ import annotations

import json

import chromadb
from pytest_bdd import given, parsers, scenario, then, when

import interchange
from conftest import fake_snapshot

QUESTION = "the context eval question under test"


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("context_eval.feature",
          "A section row is a context hit when an included chunk of the source matches (ANY)")
def test_section_row_context_hit_any():
    pass


@scenario("context_eval.feature",
          "An expected_sections_all row needs every label — two of three present is a miss")
def test_sections_all_needs_every_label():
    pass


@scenario("context_eval.feature",
          "chunks context degenerates to passage@k for a single-section row")
def test_chunks_degenerates_to_passage():
    pass


@scenario("context_eval.feature",
          "notes context on a small note is a context hit and a note hit")
def test_notes_small_note_context_and_note_hit():
    pass


@scenario("context_eval.feature",
          "A note over note_max_chars is ineligible for note@k and is named in the summary")
def test_note_over_cap_ineligible_and_named():
    pass


@scenario("context_eval.feature", "The eval assembles from the first k pairs only")
def test_assembles_from_first_k_only():
    pass


@scenario("context_eval.feature",
          "No Chroma call in the eval path when retrieve and eval_snapshot are stubbed")
def test_no_chroma_call():
    pass


@scenario("context_eval.feature",
          "golden-add --sections-all refuses an unknown label and writes a list when valid")
def test_golden_add_sections_all():
    pass


@scenario("context_eval.feature", "The mode-comparison table carries the context columns")
def test_mode_all_context_columns():
    pass


@scenario("context_eval.feature", "The eval log record carries the context diagnostics")
def test_log_record_context_keys():
    pass


# --- helpers ---------------------------------------------------------------
def _parse_chunks(spec):
    """"src:ci:sec,src:ci:sec" -> [(source, chunk_index, section), ...]."""
    out = []
    for part in spec.split(","):
        src, ci, sec = part.split(":", 2)
        out.append((src, int(ci), sec))
    return out


def _install_retrieve(monkeypatch, chunks):
    """Fake retrieve(): map QUESTION to (doc, meta) pairs carrying source/chunk/section
    (the eval-stub contract). Signature matches the keyword-only production one."""
    def fake(q, *, mode="hybrid", top_k=4, pool=20, rerank_n=30):
        if q != QUESTION:
            return []
        return [(f"text {src}:{ci}",
                 {"source": src, "chunk": ci, "section": sec, "title": src})
                for (src, ci, sec) in chunks]
    monkeypatch.setattr(interchange, "retrieve", fake)


def _write_golden(context, monkeypatch, tmp_path, row):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"question": QUESTION, **row}) + "\n", encoding="utf-8")
    context["golden_path"] = golden
    context["log_path"] = tmp_path / "eval-runs.jsonl"
    src = row.get("expected_source")
    monkeypatch.setattr(interchange, "_known_sources", lambda: {src} if src else set())


# --- Given -----------------------------------------------------------------
@given(parsers.parse('a golden row expecting source "{src}" and section "{section}"'))
def golden_with_section(context, monkeypatch, tmp_path, src, section):
    _write_golden(context, monkeypatch, tmp_path,
                  {"expected_source": src, "expected_section": section})


@given(parsers.parse('a golden row expecting source "{src}" with all sections "{spec}"'))
def golden_with_sections_all(context, monkeypatch, tmp_path, src, spec):
    _write_golden(context, monkeypatch, tmp_path,
                  {"expected_source": src, "expected_sections_all": spec.split(",")})


@given(parsers.parse('a retrieval returning chunks "{spec}"'))
def retrieval_returns(context, monkeypatch, spec):
    _install_retrieve(monkeypatch, _parse_chunks(spec))


@given(parsers.parse('a snapshot where "{src}" has chunks "{spec}"'))
def snapshot_with(context, monkeypatch, src, spec):
    notes = context.setdefault("snapshot_notes", {})
    notes[src] = spec.split("|")
    snap = fake_snapshot(notes)
    monkeypatch.setattr(interchange, "eval_snapshot", lambda collection: snap)


@given(parsers.parse("a note-max of {n:d}"))
def note_max_of(context, n):
    context["note_max"] = n


@given("Chroma is forbidden")
def chroma_forbidden(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("the eval path touched Chroma")
    monkeypatch.setattr(chromadb, "PersistentClient", _boom)


@given(parsers.parse('an index where "{src}" has sections "{spec}"'))
def index_with_sections(context, monkeypatch, tmp_path, src, spec):
    sections = set(spec.split(","))
    context["golden_path"] = tmp_path / "golden.jsonl"
    monkeypatch.setattr(interchange, "_known_sources", lambda: {src})
    monkeypatch.setattr(interchange, "_known_sections",
                        lambda source: sections if source == src else set())


# --- When ------------------------------------------------------------------
def _run(context, k, mode, quiet):
    kwargs = dict(golden_path=context["golden_path"], k=k, depth=10,
                  log_path=context["log_path"], quiet=quiet, context=mode)
    if context.get("note_max") is not None:
        kwargs["note_max_chars"] = context["note_max"]
    if context.get("budget") is not None:
        kwargs["budget_chars"] = context["budget"]
    return interchange.run_eval(**kwargs)


@when(parsers.parse("I run the context eval at k {k:d} in {mode} mode"))
def run_context_eval(context, k, mode):
    context["result"] = _run(context, k, mode, quiet=True)


@when(parsers.parse("I run the context eval with summary at k {k:d} in {mode} mode"))
def run_context_eval_summary(context, capsys, k, mode):
    context["result"] = _run(context, k, mode, quiet=False)
    context["out"] = capsys.readouterr().out


@when(parsers.parse('I golden-add "{q}" expecting "{src}" with all-sections "{spec}"'))
def golden_add_sections_all(context, q, src, spec):
    try:
        context["row"] = interchange.golden_add(
            context["golden_path"], q, [src], "paraphrase", None, "x",
            sections_all=spec.split(","))
    except SystemExit as e:
        context["exit"] = e


@when("I run the eval in mode all")
def run_mode_all(context, monkeypatch, capsys):
    monkeypatch.setitem(interchange.run_eval.__kwdefaults__, "log_path",
                        context["log_path"])
    monkeypatch.setattr("sys.argv",
                        ["interchange.py", "--eval", "--mode", "all",
                         "--golden", str(context["golden_path"]), "--k", "4"])
    interchange.main()
    context["out"] = capsys.readouterr().out


# --- Then ------------------------------------------------------------------
def _first_row(context):
    return context["result"]["results"][0]


@then(parsers.parse("context@k is {a:d} over {b:d}"))
def context_a_over_b(context, a, b):
    assert context["result"]["context_at_k"] == a
    assert context["result"]["context_rows"] == b


@then("the row is a context hit")
def row_is_context_hit(context):
    assert _first_row(context)["context_hit"] is True


@then("the row is a context miss")
def row_is_context_miss(context):
    assert _first_row(context)["context_hit"] is False


@then("the row is a note hit")
def row_is_note_hit(context):
    assert _first_row(context)["note_hit"] is True


@then(parsers.parse('the row\'s context kind is "{kind}"'))
def row_context_kind(context, kind):
    assert _first_row(context)["context_kind"] == kind


@then("context@k equals passage@k")
def context_equals_passage(context):
    r = context["result"]
    assert r["context_at_k"] == r["passage_at_k"]
    assert r["context_rows"] == r["passage_rows"]


@then("note@k is reported as not-applicable")
def note_na(context):
    assert context["result"]["note_rows"] == 0


@then(parsers.parse('the summary names "{name}" as ineligible'))
def summary_names_ineligible(context, name):
    out = context["out"]
    assert "ineligible:" in out, out
    assert name in out.split("ineligible:", 1)[1], out


@then(parsers.parse("the row records passage rank {rank:d}"))
def row_passage_rank(context, rank):
    assert _first_row(context)["passage_rank"] == rank


@then("the run completed without touching Chroma")
def run_completed(context):
    assert context["result"] is not None


@then(parsers.parse('the new row\'s expected_sections_all lists "{a},{b}"'))
def new_row_sections_all(context, a, b):
    assert context["row"]["expected_sections_all"] == [a, b]


@then(parsers.parse('it fails naming section "{section}" and source "{src}"'))
def fails_naming_section(context, section, src):
    assert "exit" in context, "expected a SystemExit"
    msg = str(context["exit"])
    assert section in msg and src in msg, msg


@then(parsers.parse('the comparison table header carries "{a}" and "{b}"'))
def table_header_carries_two(context, a, b):
    out = context["out"]
    assert a in out, out
    assert b in out, out


@then(parsers.parse('the comparison table header carries "{a}"'))
def table_header_carries_one(context, a):
    assert a in context["out"], context["out"]


@then("the eval log record carries the context keys")
def log_record_context_keys(context):
    lines = [ln for ln in context["log_path"].read_text().splitlines() if ln.strip()]
    record = json.loads(lines[-1])
    for key in ("context_mode", "context_at_k", "context_rows", "note_at_k",
                "note_rows", "context_chars_mean"):
        assert key in record, (key, record)


@then("the eval log record still carries passage_at_k and lead_share")
def log_record_legacy_keys(context):
    lines = [ln for ln in context["log_path"].read_text().splitlines() if ln.strip()]
    record = json.loads(lines[-1])
    assert "passage_at_k" in record
    assert "lead_share" in record
