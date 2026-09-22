"""Offline unit tests for the retrieval-eval runner and its scoring primitives
(ADR-0007 / ADR-0014).

Offline + $0 discipline (mirrors tests/test_retrieval.py's header): no network, no
Chroma, no embeddings. The only two seams that would touch a real index —
``interchange.retrieve`` and ``interchange._known_sources`` — are monkeypatched; the
golden set and the run log live under ``tmp_path`` so no real file is read or
written. Each symbol is imported inside the test that needs it, so a not-yet-landed
function fails only its own test, never collection.
"""
from __future__ import annotations

import json

import pytest

import interchange


# --- helpers ---------------------------------------------------------------
def _write_golden(path, rows):
    """Write `rows` as JSONL and return the path."""
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _install_retrieve(monkeypatch, mapping, recorder=None):
    """Replace interchange.retrieve with an offline fake that maps a question to a
    list of source filenames, returning (text, {"source": ...}) tuples. When
    `recorder` is given, each call appends its keyword args + the collection it saw.
    Its signature matches the real keyword-only contract exactly."""
    def fake(q, *, mode="hybrid", top_k=4, pool=20):
        if recorder is not None:
            recorder.append({"q": q, "mode": mode, "top_k": top_k, "pool": pool,
                             "collection": interchange.active_collection()})
        return [(f"text for {s}", {"source": s}) for s in mapping.get(q, [])]
    monkeypatch.setattr(interchange, "retrieve", fake)


# --- fuse_rankings (the ablation seam) -------------------------------------
def test_fuse_rankings_dense_and_bm25_bypass_fusion():
    """dense/bm25 modes return that single ranking unchanged (a copy, not fused)."""
    from interchange import fuse_rankings

    dense = ["d1", "d2", "d3"]
    bm25 = ["b1", "b2"]
    assert fuse_rankings(dense, bm25, mode="dense") == dense
    assert fuse_rankings(dense, bm25, mode="bm25") == bm25
    assert fuse_rankings(dense, bm25, mode="dense") is not dense  # a copy, not the arg


def test_fuse_rankings_hybrid_equals_rrf():
    """hybrid mode (and the default) is exactly reciprocal_rank_fusion of the two."""
    from interchange import fuse_rankings, reciprocal_rank_fusion

    dense, bm25 = ["a", "b", "c"], ["b", "c", "d"]
    expected = reciprocal_rank_fusion([dense, bm25])
    assert fuse_rankings(dense, bm25, mode="hybrid") == expected
    assert fuse_rankings(dense, bm25) == expected  # default mode is hybrid


def test_fuse_rankings_rejects_unknown_mode():
    """An unknown mode raises ValueError naming the supported MODES."""
    from interchange import MODES, fuse_rankings

    with pytest.raises(ValueError) as exc:
        fuse_rankings(["a"], ["b"], mode="graph")
    assert all(m in str(exc.value) for m in MODES)


# --- rank_of_expected ------------------------------------------------------
def test_rank_of_expected_first_position_and_none():
    """1-based position of the FIRST expected source, None when absent."""
    from interchange import rank_of_expected

    srcs = ["a.md", "b.md", "c.md"]
    assert rank_of_expected(srcs, "a.md") == 1
    assert rank_of_expected(srcs, "c.md") == 3
    assert rank_of_expected(srcs, "z.md") is None
    assert rank_of_expected(["x.md", "b.md", "b.md"], "b.md") == 2  # first match wins


def test_rank_of_expected_accepts_list():
    """expected as a list: the position of the first source matching ANY of them."""
    from interchange import rank_of_expected

    srcs = ["a.md", "b.md", "c.md"]
    assert rank_of_expected(srcs, ["z.md", "b.md"]) == 2
    assert rank_of_expected(srcs, ["z.md", "y.md"]) is None


# --- classify --------------------------------------------------------------
def test_classify_hit_near_miss_absent():
    """None->absent, 1->hit@1, 2..k->hit@k, beyond k->near-miss."""
    from interchange import classify

    assert classify(None, 4) == "absent"
    assert classify(1, 4) == "hit@1"
    assert classify(2, 4) == "hit@k"
    assert classify(4, 4) == "hit@k"
    assert classify(5, 4) == "near-miss"


# --- rank_histogram --------------------------------------------------------
def test_rank_histogram_buckets_sum_to_n():
    """Four keyed buckets whose counts always sum to len(ranks)."""
    from interchange import rank_histogram

    ranks = [1, 1, 2, 4, 5, 9, None, 3]
    k, depth = 4, 10
    hist = rank_histogram(ranks, k, depth)
    assert set(hist) == {"@1", f"@2-{k}", f"@{k+1}-{depth}", "absent"}
    assert sum(hist.values()) == len(ranks)
    assert hist["@1"] == 2
    assert hist[f"@2-{k}"] == 3   # ranks 2, 3, 4
    assert hist[f"@{k+1}-{depth}"] == 2  # ranks 5, 9
    assert hist["absent"] == 1

    # a rank beyond depth folds into absent; buckets still sum to n
    ranks2 = [1, 99, None]
    hist2 = rank_histogram(ranks2, k, depth)
    assert sum(hist2.values()) == len(ranks2)
    assert hist2["absent"] == 2


# --- unknown_expected ------------------------------------------------------
def test_unknown_expected_lists_paths_absent_from_index():
    """Expected sources not in the index, deduped, in first-seen order; rows with
    no expected source are ignored."""
    from interchange import unknown_expected

    rows = [
        {"question": "q1", "expected_source": "a.md"},
        {"question": "q2", "expected_source": "missing.md"},
        {"question": "q3", "expected_sources": ["a.md", "also-missing.md"]},
        {"question": "q4", "expected_source": "missing.md"},   # duplicate
        {"question": "q5", "unanswerable": True},               # no expected -> ignored
    ]
    assert unknown_expected(rows, {"a.md", "b.md"}) == ["missing.md", "also-missing.md"]


# --- run_eval --------------------------------------------------------------
def test_run_eval_skips_rows_without_expected_source(tmp_path, monkeypatch):
    golden = _write_golden(tmp_path / "golden.jsonl", [
        {"question": "answerable one", "expected_source": "a.md"},
        {"question": "an unanswerable one", "unanswerable": True},
    ])
    _install_retrieve(monkeypatch, {"answerable one": ["a.md"]})
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md"})

    out = interchange.run_eval(golden_path=golden, k=1,
                               log_path=tmp_path / "eval-runs.jsonl", quiet=True)
    assert out["skipped"] == 1
    assert out["n"] == 1
    assert out["hits"] == 1
    assert len(out["results"]) == 1


def test_run_eval_appends_one_jsonl_row_with_per_row_ranks(tmp_path, monkeypatch):
    golden = _write_golden(tmp_path / "golden.jsonl", [
        {"question": "q1", "expected_source": "a.md"},
        {"question": "q2", "expected_source": "b.md"},
    ])
    _install_retrieve(monkeypatch, {
        "q1": ["a.md", "x.md"],          # expected at rank 1
        "q2": ["x.md", "y.md", "b.md"],  # expected at rank 3
    })
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md", "b.md"})
    log = tmp_path / "eval-runs.jsonl"

    interchange.run_eval(golden_path=golden, k=1, depth=10, mode="dense",
                         log_path=log, quiet=True)
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["mode"] == "dense"
    assert "ts" in row
    assert {r["question"]: r["rank"] for r in row["results"]} == {"q1": 1, "q2": 3}

    # a second run APPENDS rather than overwriting
    interchange.run_eval(golden_path=golden, k=1, log_path=log, quiet=True)
    assert len([ln for ln in log.read_text().splitlines() if ln.strip()]) == 2


def test_run_eval_sets_and_resets_active_collection(tmp_path, monkeypatch):
    golden = _write_golden(tmp_path / "golden.jsonl", [
        {"question": "q1", "expected_source": "a.md"},
    ])
    seen = []
    _install_retrieve(monkeypatch, {"q1": ["a.md"]}, recorder=seen)
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md"})
    before = interchange.active_collection()

    interchange.run_eval(golden_path=golden, k=1, collection="vault",
                         log_path=tmp_path / "eval-runs.jsonl", quiet=True)
    # inside the run, retrieve saw the overridden collection ...
    assert seen and seen[0]["collection"] == "vault"
    # ... and it is reset to the module default afterwards
    assert interchange.active_collection() == before


def test_run_eval_passes_mode_and_depth_to_retrieve(tmp_path, monkeypatch):
    golden = _write_golden(tmp_path / "golden.jsonl", [
        {"question": "q1", "expected_source": "a.md"},
    ])
    seen = []
    _install_retrieve(monkeypatch, {"q1": ["a.md"]}, recorder=seen)
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md"})

    interchange.run_eval(golden_path=golden, k=1, mode="bm25", depth=7, pool=25,
                         log_path=tmp_path / "eval-runs.jsonl", quiet=True)
    assert seen[0]["mode"] == "bm25"
    assert seen[0]["top_k"] == 7   # depth is passed as retrieve's top_k
    assert seen[0]["pool"] == 25


def test_run_eval_return_dict_keeps_legacy_keys(tmp_path, monkeypatch):
    golden = _write_golden(tmp_path / "golden.jsonl", [
        {"question": "q1", "expected_source": "a.md"},
    ])
    _install_retrieve(monkeypatch, {"q1": ["a.md"]})
    monkeypatch.setattr(interchange, "_known_sources", lambda: {"a.md"})

    out = interchange.run_eval(golden_path=golden, k=1,
                               log_path=tmp_path / "eval-runs.jsonl", quiet=True)
    for key in ("n", "hits", "hit_at_k", "k"):          # the legacy contract
        assert key in out
    for key in ("hit_at_1", "histogram", "near_miss", "absent", "mode", "corpus",
                "golden", "depth", "pool", "skipped", "results"):  # the slice-3 additions
        assert key in out
