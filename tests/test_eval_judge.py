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
