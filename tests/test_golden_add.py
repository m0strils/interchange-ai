"""Executable acceptance criteria for ADR-0016 slice 5: ``--golden-add`` appends a
*validated* golden row — eval-as-you-go.

Offline discipline (ADR-0006): no Chroma. ``interchange._known_sources`` (the only
Chroma-touching seam) is monkeypatched to the set of sources the "index" holds, so the
validation runs without a store. Golden files live under ``tmp_path``.

Placement (Slice-2 lesson): these scenarios live in their own
``features/golden_add.feature`` bound here with explicit ``scenario(...)`` calls, never
appended to a feature another module bulk-binds with ``scenarios()``.
"""
from __future__ import annotations

import json
import os

from pytest_bdd import given, parsers, scenario, then, when

import interchange


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("golden_add.feature",
          "A miss becomes a golden row only if its expected source is indexed")
def test_miss_becomes_row_only_if_indexed():
    pass


@scenario("golden_add.feature", "Several expected sources become expected_sources")
def test_several_expected_sources():
    pass


@scenario("golden_add.feature", "A duplicate question is refused")
def test_duplicate_question_refused():
    pass


@scenario("golden_add.feature", "The golden file is created when absent")
def test_golden_file_created_when_absent():
    pass


# --- helpers ---------------------------------------------------------------
def _rows(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --- Given -----------------------------------------------------------------
@given(parsers.re(r'a golden set with one row and an index holding "(?P<a>[^"]+)" and '
                  r'"(?P<b>[^"]+)"'))
def golden_with_one_row(context, monkeypatch, tmp_path, a, b):
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps({"question": "q1", "expected_source": a,
                                "kind": "exact"}) + "\n", encoding="utf-8")
    context["golden"] = path
    monkeypatch.setattr(interchange, "_known_sources", lambda: {a, b})


@given(parsers.re(r'a golden path under tmp that does not exist, index holding '
                  r'"(?P<a>[^"]+)"'))
def golden_absent(context, monkeypatch, tmp_path, a):
    path = tmp_path / "sub" / "golden-new.jsonl"
    context["golden"] = path
    assert not path.exists()
    monkeypatch.setattr(interchange, "_known_sources", lambda: {a})


@given(parsers.parse('a row for "{q}" already exists'))
def row_already_exists(context, q):
    with context["golden"].open("a", encoding="utf-8") as f:
        f.write(json.dumps({"question": q, "expected_source": "a/b.md",
                            "kind": "paraphrase"}) + "\n")


# --- When ------------------------------------------------------------------
@when(parsers.parse('I add "{q}" expecting "{src}" as a "{kind}"'))
def add_row(context, q, src, kind):
    try:
        context["row"] = interchange.golden_add(
            context["golden"], q, [src], kind, None, "x")
    except SystemExit as e:
        context["exit"] = e


@when(parsers.parse('I add "{q}" expecting the unindexed "{src}"'))
def add_unindexed(context, q, src):
    try:
        context["row"] = interchange.golden_add(
            context["golden"], q, [src], "paraphrase", None, "x")
    except SystemExit as e:
        context["exit"] = e


@when(parsers.parse('I add "{q}" expecting both "{a}" and "{b}"'))
def add_two_sources(context, q, a, b):
    context["row"] = interchange.golden_add(
        context["golden"], q, [a, b], "paraphrase", None, "x")


# --- Then ------------------------------------------------------------------
@then(parsers.parse("the golden set has {n:d} rows"))
def golden_has_n_rows(context, n):
    assert len(_rows(context["golden"])) == n


@then(parsers.parse("the golden set still has {n:d} rows"))
def golden_still_has_n_rows(context, n):
    assert len(_rows(context["golden"])) == n


@then(parsers.parse('the new row\'s expected_source is "{src}" and kind is "{kind}"'))
def new_row_fields(context, src, kind):
    assert context["row"]["expected_source"] == src
    assert context["row"]["kind"] == kind


@then(parsers.re(r'the new row lists expected_sources \["(?P<a>[^"]+)", "(?P<b>[^"]+)"\] '
                 r'and has no expected_source'))
def new_row_expected_sources(context, a, b):
    assert context["row"]["expected_sources"] == [a, b]
    assert "expected_source" not in context["row"]


@then(parsers.parse('it fails naming "{needle}"'))
def failure_names(context, needle):
    assert needle in str(context["exit"])


@then(parsers.parse("the golden file now exists with {n:d} row"))
def golden_file_created(context, n):
    assert context["golden"].exists()
    assert len(_rows(context["golden"])) == n


# --- unit: main() --golden-add appends to the resolved golden path ---------
def test_main_golden_add_appends(monkeypatch, tmp_path):
    """``main()`` with ``--profile hotel --golden-add`` appends one row to the golden
    set named by an explicit ``--golden``, validating against the indexed sources."""
    monkeypatch.setenv("INTERCHANGE_PROFILES", "")
    golden = tmp_path / "golden-hotel.jsonl"
    # Snapshot the globals + env vars apply_profile rebinds/writes so this run (which
    # applies the hotel profile via main()) never leaks into another test.
    for attr in ("DOCS_DIR", "COLLECTION", "GOLDEN_PATH",
                 "PROFILE_RETRIEVAL", "PROFILE_TOOLS"):
        monkeypatch.setattr(interchange, attr, getattr(interchange, attr))
    for key in ("INTERCHANGE_COLLECTION", "INTERCHANGE_DOCS_DIR",
                "INTERCHANGE_GOLDEN", "INTERCHANGE_IGNORE", "DEMO_PROFILE"):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"policies.md"})
    monkeypatch.setattr("sys.argv", [
        "interchange.py", "--profile", "hotel", "--golden", str(golden),
        "--golden-add", "--question", "x", "--expected", "policies.md"])
    interchange.main()
    rows = [json.loads(line) for line in golden.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0] == {"question": "x", "expected_source": "policies.md",
                       "kind": "paraphrase"}
