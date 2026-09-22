"""Offline unit tests for the hybrid+rerank retrieval mode (ADR-0007 trigger /
ADR-0014).

Offline + $0 discipline (mirrors tests/test_eval_runner.py): NO backend is ever
imported — sentence_transformers, flashrank and typesafe_sdk stay out of the gate,
exactly as the lazy-import scorers guarantee in production. The reorder is a pure
function; the retrieve seam is exercised through the pure `_apply_rerank` helper with
a fake scorer, so no Chroma, network, or model is touched. Each symbol is imported
inside the test that needs it, so a not-yet-landed function fails only its own test.
"""
from __future__ import annotations

import json

import pytest

import interchange


# --- rerank_candidates (the pure reorder) ----------------------------------
def test_rerank_candidates_reorders_by_scores():
    """Ids come back ordered by score DESCENDING."""
    from interchange import rerank_candidates

    ids = ["a", "b", "c", "d"]
    scores = [0.1, 0.9, 0.3, 0.7]
    assert rerank_candidates(ids, scores) == ["b", "d", "c", "a"]


def test_rerank_candidates_ties_keep_input_order():
    """Equal scores preserve the input order (a stable sort), so a reranker that
    can't separate two candidates never reshuffles the fused order underneath them."""
    from interchange import rerank_candidates

    ids = ["a", "b", "c", "d"]
    scores = [1.0, 1.0, 2.0, 1.0]
    # c (2.0) leads; a, b, d all tie at 1.0 and keep their input order
    assert rerank_candidates(ids, scores) == ["c", "a", "b", "d"]


def test_rerank_candidates_length_mismatch_raises():
    """A length mismatch is a caller bug, not a silent truncation -> ValueError."""
    from interchange import rerank_candidates

    with pytest.raises(ValueError):
        rerank_candidates(["a", "b", "c"], [0.5, 0.4])


# --- retrieve's rerank seam (_apply_rerank + the registry) -----------------
def test_retrieve_rerank_mode_uses_registered_scorer_and_window(monkeypatch):
    """The rerank seam resolves the scorer from the registry named by
    INTERCHANGE_RERANK, scores ONLY the top `rerank_n` candidates' TEXTS, and
    returns the top `top_k` after reordering — all without Chroma."""
    from interchange import _apply_rerank, _resolve_reranker

    seen = {}

    def fake_scorer(question, texts):
        seen["question"] = question
        seen["texts"] = list(texts)
        return [float(i) for i in range(len(texts))]  # ascending: last candidate wins

    monkeypatch.setattr(interchange, "RERANKERS", {"fake": fake_scorer})
    monkeypatch.setattr(interchange, "RERANK_BACKEND", "fake")

    fused = [f"c{i}" for i in range(10)]
    by_id = {cid: (f"text-{cid}", {"source": f"{cid}.md"}) for cid in fused}

    backend, scorer = _resolve_reranker()
    assert backend == "fake"

    out = _apply_rerank("q?", fused, by_id, scorer, rerank_n=4, top_k=2)

    # the scorer saw only the top rerank_n candidates' texts, in fused order
    assert seen["question"] == "q?"
    assert seen["texts"] == ["text-c0", "text-c1", "text-c2", "text-c3"]
    # ascending scores => c3 highest, then c2; top_k=2 trims the rest
    assert out == ["c3", "c2"]


def test_apply_rerank_drops_ids_missing_from_by_id(monkeypatch):
    """Candidate ids absent from by_id are dropped before scoring (the window is
    filtered), so the scorer never sees a text that isn't there."""
    from interchange import _apply_rerank

    seen = {}

    def fake_scorer(question, texts):
        seen["texts"] = list(texts)
        return [1.0 for _ in texts]

    fused = ["c0", "ghost", "c1"]
    by_id = {"c0": ("text-c0", {}), "c1": ("text-c1", {})}
    out = _apply_rerank("q?", fused, by_id, fake_scorer, rerank_n=5, top_k=5)
    assert seen["texts"] == ["text-c0", "text-c1"]
    assert out == ["c0", "c1"]


# --- run_eval rerank metadata ----------------------------------------------
def test_run_eval_logs_rerank_metadata(tmp_path, monkeypatch):
    """A hybrid+rerank run records rerank {backend, window, calls, telemetry} in the
    return dict and the log row; local backends are `measured` with 0 metered calls."""
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"question": "q1", "expected_source": "a.md"}) + "\n")

    def fake(q, *, mode="hybrid", top_k=4, pool=20, rerank_n=30):
        return [("text for a.md", {"source": "a.md"})]

    monkeypatch.setattr(interchange, "retrieve", fake)
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md"})
    monkeypatch.setattr(interchange, "RERANK_BACKEND", "cross-encoder")

    log = tmp_path / "eval-runs.jsonl"
    out = interchange.run_eval(golden_path=golden, k=1, mode="hybrid+rerank",
                               rerank_n=30, log_path=log, quiet=True)

    rr = out["rerank"]
    assert rr == {"backend": "cross-encoder", "window": 30, "calls": 0,
                  "telemetry": "measured"}
    row = json.loads([ln for ln in log.read_text().splitlines() if ln.strip()][-1])
    assert row["rerank"] == rr


def test_run_eval_rerank_is_null_for_non_rerank_modes(tmp_path, monkeypatch):
    """Every other mode logs rerank: null — the field is present but unset."""
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"question": "q1", "expected_source": "a.md"}) + "\n")

    def fake(q, *, mode="hybrid", top_k=4, pool=20):
        return [("text for a.md", {"source": "a.md"})]

    monkeypatch.setattr(interchange, "retrieve", fake)
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md"})

    out = interchange.run_eval(golden_path=golden, k=1, mode="hybrid",
                               log_path=tmp_path / "eval-runs.jsonl", quiet=True)
    assert out["rerank"] is None
