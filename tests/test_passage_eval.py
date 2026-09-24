"""Executable acceptance criteria for passage-level retrieval scoring (ADR-0017).

Offline discipline (ADR-0006): no Chroma, no embeddings, no network. ``retrieve``,
``_known_sources`` and ``_known_sections`` — the only Chroma-touching seams — are
monkeypatched; the golden set and the run log live under ``tmp_path``.

Placement (Slice-2 lesson): these scenarios live in their own
``features/passage_eval.feature`` bound here with explicit ``scenario(...)`` calls,
never appended to ``features/retrieval_eval.feature`` (which ``test_retrieval_eval.py``
bulk-binds with ``scenarios()``).
"""
from __future__ import annotations

import json

from pytest_bdd import given, parsers, scenario, then, when

import interchange

QUESTION = "the passage eval question under test"


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("passage_eval.feature",
          "A source hit without an expected_section stays a source-only score")
def test_source_only_when_no_section():
    pass


@scenario("passage_eval.feature",
          "A matching source-and-section chunk is a passage hit at its rank")
def test_passage_hit_at_rank():
    pass


@scenario("passage_eval.feature", "A lead-only result is a source hit but a passage miss")
def test_lead_only_is_passage_miss():
    pass


@scenario("passage_eval.feature", "An expected_section list matches any of its sections")
def test_section_list_matches_any():
    pass


@scenario("passage_eval.feature", "Lead share counts preamble and H1 chunks")
def test_lead_share_counts_preamble_and_h1():
    pass


@scenario("passage_eval.feature",
          "golden-add refuses an unknown section and writes the field when valid")
def test_golden_add_section():
    pass


@scenario("passage_eval.feature",
          "The mode-comparison table carries the passage and lead columns")
def test_mode_all_table_columns():
    pass


@scenario("passage_eval.feature",
          "The eval log record carries the passage and lead diagnostics")
def test_log_record_carries_diagnostics():
    pass


# --- helpers ---------------------------------------------------------------
def _install_retrieve(monkeypatch, chunks):
    """Fake retrieve(): map QUESTION to (doc, meta) pairs; each meta carries
    ``source``/``section``/``title``. Signature matches the keyword-only contract."""
    def fake(q, *, mode="hybrid", top_k=4, pool=20, rerank_n=30):
        if q != QUESTION:
            return []
        return [(f"text {i}", {"source": s, "section": sec, "title": t})
                for i, (s, sec, t) in enumerate(chunks)]
    monkeypatch.setattr(interchange, "retrieve", fake)


def _parse_spec(spec, title):
    """"a.md@Sec,b.md@Sec2" + a shared title -> [(source, section, title), ...]."""
    out = []
    for part in spec.split(","):
        source, _, section = part.partition("@")
        out.append((source, section, title))
    return out


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- Given -----------------------------------------------------------------
@given(parsers.parse('a golden row expecting source "{src}" with no section'))
def golden_no_section(context, monkeypatch, tmp_path, src):
    _write_golden(context, monkeypatch, tmp_path, {"question": QUESTION,
                                                   "expected_source": src})


@given(parsers.parse('a golden row expecting source "{src}" and section "{section}"'))
def golden_with_section(context, monkeypatch, tmp_path, src, section):
    _write_golden(context, monkeypatch, tmp_path,
                  {"question": QUESTION, "expected_source": src,
                   "expected_section": section})


@given(parsers.parse('a golden row expecting source "{src}" and either section '
                     '"{a}" or "{b}"'))
def golden_with_section_list(context, monkeypatch, tmp_path, src, a, b):
    _write_golden(context, monkeypatch, tmp_path,
                  {"question": QUESTION, "expected_source": src,
                   "expected_section": [a, b]})


def _write_golden(context, monkeypatch, tmp_path, row):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps(row) + "\n", encoding="utf-8")
    context["golden_path"] = golden
    context["log_path"] = tmp_path / "eval-runs.jsonl"
    monkeypatch.setattr(interchange, "_known_sources",
                        lambda: {row.get("expected_source")})


@given(parsers.parse('a question whose retrieval returns "{spec}" each titled "{title}"'))
def question_returns(context, monkeypatch, spec, title):
    _install_retrieve(monkeypatch, _parse_spec(spec, title))


@given(parsers.parse('retrieved chunks with sections "{spec}" each titled "{title}"'))
def chunks_with_sections(context, spec, title):
    context["hits_meta"] = [{"source": "n.md", "section": sec, "title": title}
                            for sec in spec.split(",")]


@given(parsers.parse('an index where "{src}" has sections "{spec}"'))
def index_with_sections(context, monkeypatch, tmp_path, src, spec):
    sections = set(spec.split(","))
    context["golden_path"] = tmp_path / "golden.jsonl"
    monkeypatch.setattr(interchange, "_known_sources", lambda: {src})
    monkeypatch.setattr(interchange, "_known_sections",
                        lambda source: sections if source == src else set())


# --- When ------------------------------------------------------------------
@when(parsers.parse("I run the passage eval at k {k:d}"))
def run_passage_eval(context, k):
    context["result"] = interchange.run_eval(
        golden_path=context["golden_path"], k=k, depth=10,
        log_path=context["log_path"], quiet=True)


@when(parsers.parse("I measure the lead share at k {k:d}"))
def measure_lead_share(context, k):
    context["lead_share"] = interchange.lead_share(context["hits_meta"], k)


@when(parsers.parse('I golden-add "{q}" expecting "{src}" with sections "{spec}"'))
def golden_add_sections(context, q, src, spec):
    sections = spec.split(",")
    try:
        context["row"] = interchange.golden_add(
            context["golden_path"], q, [src], "paraphrase", None, "x", sections=sections)
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
@then(parsers.parse("the run counts {n:d} source hit"))
def counts_source_hit(context, n):
    assert context["result"]["hits"] == n


@then("passage@k is reported as not-applicable")
def passage_na(context):
    assert context["result"]["passage_rows"] == 0


@then("the row records no passage rank")
def no_passage_rank(context):
    row = context["result"]["results"][0]
    assert row.get("passage_rank") is None


@then(parsers.parse("the row records passage rank {rank:d}"))
def row_passage_rank(context, rank):
    row = context["result"]["results"][0]
    assert row["passage_rank"] == rank


@then(parsers.parse("passage@k is {a:d} over {b:d}"))
def passage_a_over_b(context, a, b):
    assert context["result"]["passage_at_k"] == a
    assert context["result"]["passage_rows"] == b


@then(parsers.parse('the lead share is "{expected}"'))
def lead_share_is(context, expected):
    assert f"{context['lead_share']:.2f}" == expected


@then(parsers.parse('the new row\'s expected_section is "{section}"'))
def new_row_section(context, section):
    assert context["row"]["expected_section"] == section


@then(parsers.parse('it fails naming section "{section}" and source "{src}"'))
def fails_naming_section(context, section, src):
    assert "exit" in context, "expected a SystemExit"
    msg = str(context["exit"])
    assert section in msg and src in msg, msg


@then(parsers.parse('the new row\'s expected_section lists "{a},{b}"'))
def new_row_section_list(context, a, b):
    assert context["row"]["expected_section"] == [a, b]


@then(parsers.parse('the comparison table header carries "{a}" and "{b}"'))
def table_header_carries(context, a, b):
    out = context["out"]
    assert a in out, out
    assert b in out, out


@then("the eval log record carries passage_at_k and lead_share")
def log_record_diagnostics(context):
    lines = [ln for ln in context["log_path"].read_text().splitlines() if ln.strip()]
    record = json.loads(lines[-1])
    assert "passage_at_k" in record
    assert "lead_share" in record
