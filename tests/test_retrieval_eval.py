"""Executable acceptance criteria for the retrieval eval (ADR-0007 / ADR-0014).

Gherkin lives in ``features/retrieval_eval.feature``. Mirrors
tests/test_hybrid_retrieval.py: ``scenarios(...)``, the shared ``context`` dict
fixture (conftest.py), and a monkeypatched boundary. Every run is offline and free —
``interchange.retrieve`` and ``interchange._known_sources`` are stubbed, and the
golden set + run log live under ``tmp_path`` — so no embeddings, network, or real
files are ever touched.
"""
from __future__ import annotations

import json

from pytest_bdd import given, parsers, scenarios, then, when

import interchange

scenarios("retrieval_eval.feature")

QUESTION = "the eval question under test"


def _install_retrieve(monkeypatch, context, mapping):
    """Fake retrieve(): map a question to source filenames, recording each call's
    mode/depth/collection into the context. Signature matches the real keyword-only
    contract."""
    calls = context.setdefault("retrieve_calls", [])

    def fake(q, *, mode="hybrid", top_k=4, pool=20, rerank_n=30):
        calls.append({"q": q, "mode": mode, "top_k": top_k, "pool": pool,
                      "rerank_n": rerank_n, "collection": interchange.active_collection()})
        return [(f"text for {s}", {"source": s}) for s in mapping.get(q, [])]

    monkeypatch.setattr(interchange, "retrieve", fake)


def _sources_with_expected_at(expected, position):
    """A retrieved-source list placing `expected` at 1-based `position`, padded with
    unique filler before and after so rank and near-miss are exercised realistically."""
    return ([f"filler-{i}.md" for i in range(position - 1)]
            + [expected] + [f"tail-{i}.md" for i in range(3)])


# --- Given -----------------------------------------------------------------
@given(parsers.parse('an index that holds "{a}" and "{b}"'))
def index_holds(context, monkeypatch, a, b):
    known = {a, b}
    context["known"] = known
    monkeypatch.setattr(interchange, "_known_sources", lambda: known)


@given(parsers.parse('a golden question expecting "{expected}" retrieved at position {pos:d}'))
def golden_expecting_at(context, monkeypatch, tmp_path, expected, pos):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"question": QUESTION, "expected_source": expected}) + "\n")
    context["golden_path"] = golden
    context["log_path"] = tmp_path / "eval-runs.jsonl"
    _install_retrieve(monkeypatch, context, {QUESTION: _sources_with_expected_at(expected, pos)})


@given("a golden set with one answerable and one unanswerable question")
def golden_mixed(context, monkeypatch, tmp_path):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        json.dumps({"question": QUESTION, "expected_source": "x12-overview.md"}) + "\n"
        + json.dumps({"question": "an unanswerable one", "unanswerable": True}) + "\n"
    )
    context["golden_path"] = golden
    context["log_path"] = tmp_path / "eval-runs.jsonl"
    _install_retrieve(monkeypatch, context, {QUESTION: ["x12-overview.md"]})


# --- When ------------------------------------------------------------------
@when(parsers.parse("I run the retrieval eval at k {k:d} depth {depth:d}"))
def run_eval_k_depth(context, k, depth):
    context["result"] = interchange.run_eval(
        golden_path=context["golden_path"], k=k, depth=depth,
        log_path=context["log_path"], quiet=True)


@when(parsers.parse('I run the retrieval eval on corpus "{corpus}"'))
def run_eval_corpus(context, corpus):
    context["before_collection"] = interchange.active_collection()
    context["result"] = interchange.run_eval(
        golden_path=context["golden_path"], k=4, collection=corpus,
        log_path=context["log_path"], quiet=True)


@when("I run the retrieval eval verbosely")
def run_eval_verbose(context, capsys):
    context["result"] = interchange.run_eval(
        golden_path=context["golden_path"], k=4, depth=10,
        log_path=context["log_path"], quiet=False)
    context["out"] = capsys.readouterr().out


@when(parsers.parse("I run the retrieval eval in hybrid+rerank mode with window {n:d}"))
def run_eval_rerank(context, monkeypatch, n):
    monkeypatch.setattr(interchange, "RERANK_BACKEND", "cross-encoder")
    context["result"] = interchange.run_eval(
        golden_path=context["golden_path"], k=4, mode="hybrid+rerank", rerank_n=n,
        log_path=context["log_path"], quiet=True)


@when(parsers.parse('I rerank candidates "{ids}" with scores "{scores}"'))
def rerank_ids(context, ids, scores):
    id_list = ids.split(",")
    score_list = [float(s) for s in scores.split(",")]
    context["reranked"] = interchange.rerank_candidates(id_list, score_list)


@when("I fuse a dense ranking and a bm25 ranking under each single mode")
def fuse_single_modes(context):
    context["dense"] = ["d1", "d2", "d3"]
    context["bm25"] = ["b1", "b2"]
    context["dense_result"] = interchange.fuse_rankings(
        context["dense"], context["bm25"], mode="dense")
    context["bm25_result"] = interchange.fuse_rankings(
        context["dense"], context["bm25"], mode="bm25")


# --- Then ------------------------------------------------------------------
@then(parsers.parse("the run records rank {rank:d} for that question"))
def run_records_rank(context, rank):
    row = next(r for r in context["result"]["results"] if r["question"] == QUESTION)
    assert row["rank"] == rank


@then("the run counts it as a hit")
def counts_as_hit(context):
    assert context["result"]["hits"] == 1


@then("the run counts it as a miss")
def counts_as_miss(context):
    assert context["result"]["hits"] == 0


@then(parsers.parse("the near-miss count is {n:d}"))
def near_miss_is(context, n):
    assert context["result"]["near_miss"] == n


@then("dense mode returns the dense ranking unchanged")
def dense_unchanged(context):
    assert context["dense_result"] == context["dense"]


@then("bm25 mode returns the bm25 ranking unchanged")
def bm25_unchanged(context):
    assert context["bm25_result"] == context["bm25"]


@then(parsers.parse('the retrieval ran against collection "{corpus}"'))
def retrieval_against_collection(context, corpus):
    calls = context["retrieve_calls"]
    assert calls and all(c["collection"] == corpus for c in calls)


@then("the active collection afterwards is the module default")
def active_reset(context):
    assert interchange.active_collection() == context["before_collection"]


@then("the eval log has exactly one row")
def log_one_row(context):
    lines = [ln for ln in context["log_path"].read_text().splitlines() if ln.strip()]
    context["log_rows"] = [json.loads(ln) for ln in lines]
    assert len(context["log_rows"]) == 1


@then("that row carries the mode, the corpus, and a rank for the question")
def row_carries_fields(context):
    row = context["log_rows"][0]
    assert row["mode"] == "hybrid"
    assert row["corpus"]  # a resolved collection name, not empty
    ranks = {r["question"]: r["rank"] for r in row["results"]}
    assert ranks[QUESTION] == 1


@then(parsers.parse('the output flags "{name}" as unknown before the scores'))
def output_flags_unknown(context, name):
    out = context["out"]
    assert name in out, out
    # the warning lands before the hit@ aggregates
    assert out.index(name) < out.index("hit@1"), out


@then(parsers.parse("the run skips {n:d} row"))
def run_skips(context, n):
    assert context["result"]["skipped"] == n


@then(parsers.parse("the run scores {n:d} row"))
def run_scores(context, n):
    assert context["result"]["n"] == n


@then(parsers.parse('the reranked order is "{expected}"'))
def reranked_order(context, expected):
    assert context["reranked"] == expected.split(",")


@then(parsers.parse('that row records rerank backend "{backend}", window {n:d}, '
                    'and telemetry "{tel}"'))
def row_records_rerank(context, backend, n, tel):
    row = context["log_rows"][0]
    assert row["rerank"] == {"backend": backend, "window": n, "calls": 0,
                             "telemetry": tel}
