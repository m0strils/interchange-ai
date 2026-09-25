"""Unit tests for the answer-quality eval scoring (ADR-0008).

Covers the four PURE functions in eval_judge — answer_correctness, refusal_correct,
parse_judge_verdict, faithfulness_score. No network, no LLM, no Chroma: the LLM seam
(_run_judge) and generation engine are exercised only in the bdd layer, stubbed.

Symbols are imported inside each test (house style, see test_units.py) so a
not-yet-landed function fails only its own test, not collection.
"""
from __future__ import annotations


# --- answer_correctness (deterministic keyword coverage) -------------------
def test_answer_correctness_all_facts_present_is_one():
    from eval_judge import answer_correctness
    ans = "The 997 Functional Acknowledgment confirms syntactic receipt."
    assert answer_correctness(ans, ["997", "functional acknowledgment"]) == 1.0


def test_answer_correctness_is_case_insensitive():
    from eval_judge import answer_correctness
    assert answer_correctness("An 824 APPLICATION ADVICE.", ["application advice"]) == 1.0


def test_answer_correctness_partial_coverage_is_fraction():
    from eval_judge import answer_correctness
    # one of two facts present -> 0.5
    assert answer_correctness("The 214 message.", ["214", "carrier shipment"]) == 0.5


def test_answer_correctness_no_expected_facts_is_one():
    from eval_judge import answer_correctness
    assert answer_correctness("anything at all", []) == 1.0


# --- handled_unanswerable (correct = no unsupported claim) ------------------
# Refusal-correctness is defined via faithfulness, NOT a decline-phrase regex: a
# real grade run showed the regex false-negatived a good refusal that cited what IS
# covered, and couldn't separate a clean decline from a hedged wrong answer (ADR-0008).
def test_handled_unanswerable_true_when_faithfulness_is_one():
    from eval_judge import handled_unanswerable
    # a clean decline (or only-supported statements) -> faithfulness 1.0 -> correct
    assert handled_unanswerable(1.0) is True


def test_handled_unanswerable_false_when_any_claim_unsupported():
    from eval_judge import handled_unanswerable
    # a hallucinated out-of-corpus answer introduces unsupported claims -> < 1.0
    assert handled_unanswerable(0.33) is False
    assert handled_unanswerable(0.0) is False


# --- parse_judge_verdict (robust JSON extraction) --------------------------
def test_parse_judge_verdict_clean_json():
    from eval_judge import parse_judge_verdict
    v = parse_judge_verdict('{"claims":[{"claim":"a","supported":true},'
                            '{"claim":"b","supported":false}]}')
    assert len(v["claims"]) == 2
    assert v["claims"][0]["supported"] is True
    assert v["claims"][1]["supported"] is False


def test_parse_judge_verdict_extracts_from_fenced_prose():
    from eval_judge import parse_judge_verdict
    text = 'Here is my verdict:\n```json\n{"claims":[{"claim":"x","supported":true}]}\n```\n'
    v = parse_judge_verdict(text)
    assert v["claims"] == [{"claim": "x", "supported": True}]


def test_parse_judge_verdict_garbage_returns_empty_claims():
    from eval_judge import parse_judge_verdict
    assert parse_judge_verdict("no json here at all") == {"claims": []}
    assert parse_judge_verdict('{"not_claims": 1}') == {"claims": []}


# --- faithfulness_score (zero-claim is the important case) ------------------
def test_faithfulness_score_all_supported_is_one():
    from eval_judge import faithfulness_score
    v = {"claims": [{"claim": "a", "supported": True}, {"claim": "b", "supported": True}]}
    assert faithfulness_score(v) == 1.0


def test_faithfulness_score_half_supported_is_half():
    from eval_judge import faithfulness_score
    v = {"claims": [{"claim": "a", "supported": True}, {"claim": "b", "supported": False}]}
    assert faithfulness_score(v) == 0.5


def test_faithfulness_score_zero_claims_is_one_not_zero_division():
    from eval_judge import faithfulness_score
    # a refusal has no factual claims -> trivially faithful, never 0/0
    assert faithfulness_score({"claims": []}) == 1.0


# --- the governed grade path (_generate -> answer_detail, ADR-0008/0018) ----
# The judge used to hand-roll the RAG path (retrieve -> top-k join -> engine ->
# grounding), which bypassed context assembly, persona and the profile-resolved mode
# and so graded a context no surface builds any more (ADR-0018). It now grades
# answer_detail's governed output with the audit-row write suppressed (audit=False).
# These exercise that seam offline: the model boundary and profile lookup are stubbed,
# and the autouse conftest fixtures isolate the audit log and disable the overlay.
def _install_engine(monkeypatch, engine: str, text: str):
    """Install a canned generation engine that returns `text` for `engine`."""
    import interchange

    def fake(user_content):
        return {"text": text, "in": 100, "out": 20, "cost": None,
                "telemetry": "estimated", "model": interchange.MODEL}
    monkeypatch.setitem(interchange.ENGINES, engine, fake)


def test_generate_delegates_to_answer_detail_with_audit_off(monkeypatch):
    """_generate is now a thin call to answer_detail(audit=False) and returns its
    text / assembled context / included sources — no hand-rolled retrieval path."""
    import eval_judge
    import interchange
    calls = {}

    def recorder(question, *, engine, audit=True, **kw):
        calls.update(question=question, engine=engine, audit=audit)
        return {"text": "ANSWER [notes.md]", "answer_text": "ANSWER",
                "context_text": "the CONTEXT the engine actually saw",
                "sources": ["notes.md"], "grounded": True, "blocked": None,
                "hits": [], "context": {"mode": "notes"}}

    monkeypatch.setattr(interchange, "answer_detail", recorder)
    text, context, sources = eval_judge._generate("what is an 824?", "claude-code")
    assert calls["audit"] is False
    assert calls["engine"] == "claude-code"
    assert (text, context, sources) == (
        "ANSWER [notes.md]", "the CONTEXT the engine actually saw", ["notes.md"])


def test_answer_detail_audit_false_writes_no_row_but_still_answers(monkeypatch,
                                                                   isolated_audit_log):
    """audit=False runs the full governed pipeline (grounded answer, real record) but
    writes NO audit row; the default writes exactly one and the record is unchanged."""
    import interchange
    from tests.conftest import fake_retrieval, read_audit_rows

    # hermetic chunks-mode pipeline: no profile (defaults to chunks -> no snapshot),
    # canned retrieval, canned engine.
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: None)
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval({"source": "x12-overview.md",
                                        "text": "An 824 reports application errors.",
                                        "chunk": 0}))
    _install_engine(monkeypatch, "api", "An 824 reports errors [x12-overview.md].")

    d = interchange.answer_detail("what is an 824?", engine="api", audit=False)
    assert d["blocked"] is None and d["grounded"] is True   # a real grounded answer
    assert "824" in d["text"]
    assert read_audit_rows(isolated_audit_log) == []        # grade run wrote no row

    d2 = interchange.answer_detail("what is an 824?", engine="api")   # default audits
    rows = read_audit_rows(isolated_audit_log)
    assert len(rows) == 1
    assert d2["model"] == d["model"]                        # record unchanged by flag


def test_generate_context_is_the_assembled_context_the_engine_saw(monkeypatch, tmp_path):
    """The context the judge receives equals the context the engine saw: under a
    notes-mode profile, assembly pulls a neighbour chunk that retrieval never returned,
    and a grade scores an expected fact that lives only in that expanded chunk."""
    import json

    import eval_judge
    import interchange
    from tests.conftest import fake_retrieval, fake_snapshot

    fake_profile = {"name": "notestest", "collection": "notestest",
                    "retrieval": {"mode": "hybrid", "context": "notes",
                                  "budget_chars": 12000, "note_max_chars": 4000}}
    monkeypatch.setattr(interchange, "profile_for_collection", lambda c: fake_profile)

    seed = "Seed chunk: the 850 is a purchase order."
    neighbour = "expandedonlyfact appears solely in the neighbour chunk."
    # retrieval surfaces ONLY chunk 0; chunk 1 (the neighbour) is not a hit.
    monkeypatch.setattr(
        interchange, "retrieve_detail",
        lambda q, **kw: fake_retrieval({"source": "notes.md", "text": seed, "chunk": 0}))
    monkeypatch.setattr(interchange, "corpus_snapshot",
                        lambda c: fake_snapshot({"notes.md": [seed, neighbour]}))

    # the engine echoes the reference DATA it was handed, so the answer carries whatever
    # assembly put in the context.
    def echo(user_content):
        return {"text": user_content, "in": 10, "out": 10, "cost": None,
                "telemetry": "estimated", "model": interchange.MODEL}
    monkeypatch.setitem(interchange.ENGINES, "claude-code", echo)

    text, context, sources = eval_judge._generate("what is the 850?", "claude-code")
    assert neighbour in context      # assembly pulled a chunk retrieval never returned
    assert seed in context
    assert sources == ["notes.md"]

    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        json.dumps({"question": "q1", "expected_facts": ["expandedonlyfact"]}) + "\n"
        + json.dumps({"question": "q2", "expected_facts": ["expandedonlyfact"]}) + "\n")
    monkeypatch.setattr(eval_judge, "GRADE_LOG", tmp_path / "grade-runs.jsonl")
    monkeypatch.setattr(eval_judge, "_run_judge", lambda prompt: json.dumps({"claims": []}))

    summary = eval_judge.run_grade(golden_path=golden, engine="claude-code")
    # the expected fact lives only in the expanded neighbour chunk -> assembly is what
    # put it in the answer the grade scored.
    assert summary["answer_correctness"] == 1.0
