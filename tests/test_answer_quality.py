"""Acceptance steps for the answer-quality grade (ADR-0008).

Gherkin in features/answer_quality.feature. Every external boundary is stubbed so the
run is offline and free (never calls a live model, embeddings, or Chroma):
  * retrieval:  interchange.retrieve -> a canned passage
  * generation: interchange.ENGINES["claude-code"] -> a canned engine dict
  * judge:      eval_judge._run_judge -> a canned verdict JSON string
  * grade log:  eval_judge.GRADE_LOG -> a tmp file (never the real one)

The summary returned by run_grade is asserted through the `context` dict fixture.
"""
from __future__ import annotations

import json

from pytest_bdd import given, parsers, scenarios, then, when

import eval_judge
import interchange

scenarios("answer_quality.feature")


# --- Given -----------------------------------------------------------------
@given("a golden set with one unanswerable question")
def golden_one_unanswerable(context, tmp_path, monkeypatch):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"question": "What is the 850 Purchase Order?",
                                  "unanswerable": True}) + "\n")
    context["golden_path"] = golden
    # keep the real grade log pristine
    monkeypatch.setattr(eval_judge, "GRADE_LOG", tmp_path / "grade-runs.jsonl")


@given(parsers.parse('retrieval returns an irrelevant passage from "{source}"'))
def stub_retrieval(context, monkeypatch, source):
    passage = ("ANSI ASC X12 is an EDI standard.", {"source": source, "chunk": 0})
    monkeypatch.setattr(interchange, "retrieve", lambda q: [passage])


def _install_engine(monkeypatch, text):
    def fake(user_content):
        return {"text": text, "in": 100, "out": 20, "cost": None,
                "telemetry": "estimated", "model": "claude-opus-4-8"}
    monkeypatch.setitem(interchange.ENGINES, "claude-code", fake)


@given("the model fabricates a cited answer instead of refusing")
def model_fabricates(context, monkeypatch):
    _install_engine(monkeypatch, "The 850 is a Purchase Order transaction set [x12-overview.md].")


@given("the model correctly declines to answer")
def model_declines(context, monkeypatch):
    _install_engine(monkeypatch, "The context does not contain information about the 850.")


@given("the judge finds the fabricated claim unsupported")
def judge_unsupported(context, monkeypatch):
    verdict = json.dumps({"claims": [{"claim": "850 is a Purchase Order", "supported": False}]})
    monkeypatch.setattr(eval_judge, "_run_judge", lambda prompt: verdict)


@given("the judge finds no claims to check")
def judge_no_claims(context, monkeypatch):
    monkeypatch.setattr(eval_judge, "_run_judge", lambda prompt: json.dumps({"claims": []}))


# --- When ------------------------------------------------------------------
@when("I run the grade")
def run_the_grade(context):
    context["summary"] = eval_judge.run_grade(golden_path=context["golden_path"],
                                              engine="claude-code")


# --- Then ------------------------------------------------------------------
@then(parsers.parse("refusal-correctness is {value:d}"))
def assert_refusal(context, value):
    assert context["summary"]["refusal_correctness"] == value


@then("the monitored faithfulness is below 1")
def assert_faithfulness_below_one(context):
    assert context["summary"]["mean_faithfulness"] < 1.0


@then("the monitored faithfulness is 1")
def assert_faithfulness_one(context):
    assert context["summary"]["mean_faithfulness"] == 1.0
