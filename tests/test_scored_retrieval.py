"""Offline unit tests for slice-1 scored retrieval (ADR-0015 browser workbench).

Discipline (mirrors tests/test_rerank.py): NO retrieval backend and NO real Chroma
are ever touched. The pure ranking core (`rank_chunks`) is exercised with an
in-memory `Snapshot` built from a REAL `BM25Okapi` over five hand-written chunks and
a FAKE scorer registered in `interchange.RERANKERS`; the Chroma-touching seams
(`corpus_snapshot`, `fetch_chunks`) run against a stub `chromadb.PersistentClient`.
Each symbol is imported inside the test that needs it, so a not-yet-landed function
fails only its own test.
"""
from __future__ import annotations

import chromadb
import pytest
from rank_bm25 import BM25Okapi

import interchange
from interchange import Snapshot, tokenize


# --- fixtures: a five-chunk in-memory snapshot -----------------------------
# Chunk 4 ("e.md:0") deliberately shares NO token with the query "invoice 824
# advice", so its BM25 score is 0.0 (rank must show as None). The dense pool is a
# subset of three ids, so the two ids outside it must carry dense_rank=None.
DOCS = [
    "invoice 824 application advice reports errors",   # a.md:0
    "the 824 advice acknowledges an invoice",          # a.md:1
    "advice about invoice reconciliation",             # b.md:0
    "824 transaction set overview and codes",          # c.md:0
    "rail timetable glossary of yard terms",           # d.md:0  (zero overlap)
]
IDS = ["a.md:0", "a.md:1", "b.md:0", "c.md:0", "d.md:0"]
METAS = [
    {"source": "a.md", "chunk": 0, "section": "824 Advice", "title": "a", "links": "c.md"},
    {"source": "a.md", "chunk": 1, "section": "824 Advice", "title": "a", "links": "c.md"},
    {"source": "b.md", "chunk": 0, "section": "Recon", "title": "b", "links": ""},
    {"source": "c.md", "chunk": 0, "section": "Overview", "title": "c", "links": "d.md"},
    {"source": "d.md", "chunk": 0, "section": "Glossary", "title": "d", "links": ""},
]
QUERY = "invoice 824 advice"


def make_snapshot() -> Snapshot:
    return Snapshot(count=len(IDS), ids=list(IDS), docs=list(DOCS), metas=[dict(m) for m in METAS],
                    bm25=BM25Okapi([tokenize(d) for d in DOCS]), space="l2")


# --- bm25_scores <-> bm25_rank ---------------------------------------------
def test_bm25_scores_order_agrees_with_bm25_rank():
    """`bm25_rank` is exactly the argsort of `bm25_scores` (desc, ties by index)."""
    scores = interchange.bm25_scores(QUERY, DOCS)
    assert len(scores) == len(DOCS)
    expected = sorted(range(len(DOCS)), key=lambda i: (-scores[i], i))
    assert interchange.bm25_rank(QUERY, DOCS) == expected


def test_bm25_scores_zero_for_no_overlap():
    """A query sharing no token with any doc scores all-zero (0.0 = no overlap)."""
    scores = interchange.bm25_scores("zzz nonexistent qqq", DOCS)
    assert scores == [0.0] * len(DOCS)


# --- rrf_scores <-> reciprocal_rank_fusion ---------------------------------
def test_rrf_scores_hand_computed():
    """`[["a","b"],["b"]]`, k=60. `a` appears once at rank 1 -> 1/61. `b` appears at
    rank 2 in the first list and rank 1 in the second -> 1/62 + 1/61 (Σ 1/(k+rank),
    ranks 1-based). `b` still outscores `a` and leads the fusion — which is the point
    of the example; the plan's shorthand "b = 2/61" mislabels b's first-list rank as 1,
    so this asserts the arithmetically correct value that matches reciprocal_rank_fusion."""
    table = interchange.rrf_scores([["a", "b"], ["b"]], k=60)
    assert table["a"] == pytest.approx(1 / 61)
    assert table["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert table["b"] > table["a"]


def test_rrf_scores_argsort_equals_reciprocal_rank_fusion():
    """The score table's descending argsort is exactly the fused order."""
    rankings = [["a", "b", "c"], ["b", "d"], ["c", "b"]]
    table = interchange.rrf_scores(rankings)
    argsort = sorted(table, key=lambda key: -table[key])
    assert argsort == interchange.reciprocal_rank_fusion(rankings)
    # and the documented tiny example
    assert sorted(interchange.rrf_scores([["a", "b"], ["b"]], k=60),
                  key=lambda k: -interchange.rrf_scores([["a", "b"], ["b"]], k=60)[k]) == \
        interchange.reciprocal_rank_fusion([["a", "b"], ["b"]], k=60)


# --- rank_chunks: hybrid ----------------------------------------------------
def _monotone(values: list) -> bool:
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def test_rank_chunks_hybrid():
    """Hybrid fuses dense+bm25: a bm25-only chunk gets dense_rank=None; a zero-score
    chunk gets bm25_rank=None but every other hit has one; final_rank is 1..n and
    rrf_score is monotone non-increasing in final_rank."""
    snap = make_snapshot()
    dense_ids = ["c.md:0", "a.md:0", "b.md:0"]      # a 3-wide pool; d.md:0 & a.md:1 outside
    dense_dists = [0.11, 0.22, 0.33]
    timings: dict = {}
    hits = interchange.rank_chunks(QUERY, snap, dense_ids, dense_dists, mode="hybrid",
                                   top_k=5, rerank_n=30, rerank_backend=None, timings=timings)

    assert [h["final_rank"] for h in hits] == list(range(1, len(hits) + 1))
    by_id = {h["id"]: h for h in hits}

    # a.md:1 is outside the dense pool -> dense_rank/dense_distance are None
    assert by_id["a.md:1"]["dense_rank"] is None
    assert by_id["a.md:1"]["dense_distance"] is None
    # c.md:0 is dense rank 1 with its distance carried through
    assert by_id["c.md:0"]["dense_rank"] == 1
    assert by_id["c.md:0"]["dense_distance"] == pytest.approx(0.11)

    # d.md:0 shares no query token -> score 0.0 -> rank shown as None
    assert by_id["d.md:0"]["bm25_score"] == 0.0
    assert by_id["d.md:0"]["bm25_rank"] is None
    # every hit that overlaps the query has a bm25_rank
    for h in hits:
        if h["bm25_score"] and h["bm25_score"] > 0.0:
            assert h["bm25_rank"] is not None

    # rrf_score present for every hit and monotone in final_rank
    assert all(h["rrf_score"] is not None for h in hits)
    assert _monotone([h["rrf_score"] for h in hits])
    # source/section/title come from metadata, never parsed from the id
    assert by_id["a.md:0"]["source"] == "a.md"
    assert by_id["a.md:0"]["section"] == "824 Advice"
    assert by_id["a.md:0"]["rerank_score"] is None
    assert by_id["a.md:0"]["pinned"] is False
    assert timings["bm25_ms"] >= 0 and timings["rrf_ms"] >= 0


def test_rank_chunks_dense_mode_is_dense_order_no_rrf():
    """`dense` bypasses fusion: order == dense order, rrf_score is None for all."""
    snap = make_snapshot()
    dense_ids = ["c.md:0", "a.md:0", "b.md:0"]
    hits = interchange.rank_chunks(QUERY, snap, dense_ids, [0.1, 0.2, 0.3], mode="dense",
                                   top_k=5, rerank_n=30, rerank_backend=None, timings={})
    assert [h["id"] for h in hits] == dense_ids
    assert all(h["rrf_score"] is None for h in hits)


def test_rank_chunks_bm25_mode():
    """`bm25` returns the whole-corpus bm25 order; rrf_score None; top_k trims."""
    snap = make_snapshot()
    dense_ids = ["c.md:0", "a.md:0"]
    hits = interchange.rank_chunks(QUERY, snap, dense_ids, None, mode="bm25",
                                   top_k=3, rerank_n=30, rerank_backend=None, timings={})
    expected = [IDS[i] for i in interchange.bm25_rank(QUERY, DOCS)][:3]
    assert [h["id"] for h in hits] == expected
    assert all(h["rrf_score"] is None for h in hits)
    # dense_dists was None -> every dense_distance is None
    assert all(h["dense_distance"] is None for h in hits)


def test_rank_chunks_hybrid_links_fuses_three_rankings():
    """`hybrid+links` fuses dense, bm25 AND the one-hop link ranking; the order is
    exactly the three-way RRF and rrf_score stays monotone."""
    snap = make_snapshot()
    dense_ids = ["a.md:0", "b.md:0", "c.md:0"]
    hits = interchange.rank_chunks(QUERY, snap, dense_ids, [0.1, 0.2, 0.3],
                                   mode="hybrid+links", top_k=5, rerank_n=30,
                                   rerank_backend=None, timings={})
    bm25_ids = [IDS[i] for i in interchange.bm25_rank(QUERY, DOCS)]
    link_ids = interchange._link_ranking(IDS, METAS, dense_ids, bm25_ids)
    assert link_ids, "fixture must produce a non-empty link ranking (three rankings)"
    expected = interchange.reciprocal_rank_fusion([dense_ids, bm25_ids, link_ids])[:5]
    assert [h["id"] for h in hits] == expected
    assert _monotone([h["rrf_score"] for h in hits])


def test_rank_chunks_hybrid_rerank_scores_only_inside_window(monkeypatch):
    """`hybrid+rerank` reorders the top `rerank_n` fused candidates with the registered
    backend: returned hits carry a rerank_score and rerank_backend, and rerank_ms is
    recorded."""
    def fake_scorer(question, texts):
        return [float(i) for i in range(len(texts))]     # ascending -> last candidate wins

    monkeypatch.setitem(interchange.RERANKERS, "fake", fake_scorer)
    snap = make_snapshot()
    dense_ids = ["a.md:0", "b.md:0", "c.md:0"]
    timings: dict = {}
    hits = interchange.rank_chunks(QUERY, snap, dense_ids, [0.1, 0.2, 0.3],
                                   mode="hybrid+rerank", top_k=2, rerank_n=3,
                                   rerank_backend="fake", timings=timings)
    assert len(hits) == 2
    for h in hits:
        assert h["rerank_score"] is not None
        assert h["rerank_backend"] == "fake"
    assert "rerank_ms" in timings
    # ascending scores => the last-scored window candidate leads the reranked order
    assert hits[0]["rerank_score"] >= hits[1]["rerank_score"]


# --- score_legend -----------------------------------------------------------
def test_score_legend_kinds():
    """Kinds reflect the space and the rerank backend; no rerank entry when not
    reranked; typesafe is `estimated`, local backends `measured`."""
    plain = interchange.score_legend("l2", None)
    assert plain["dense_distance"]["kind"] == "l2"
    assert plain["bm25_score"]["kind"] == "bm25_okapi"
    assert plain["rrf_score"]["kind"] == "rrf"
    assert "rerank_score" not in plain

    ce = interchange.score_legend("cosine", "cross-encoder")
    assert ce["dense_distance"]["kind"] == "cosine"
    assert ce["rerank_score"]["kind"] == "logit"
    assert ce["rerank_score"]["telemetry"] == "measured"

    assert interchange.score_legend("l2", "flashrank")["rerank_score"]["kind"] == "score"

    ts = interchange.score_legend("l2", "typesafe")["rerank_score"]
    assert ts["kind"] == "probability"
    assert ts["telemetry"] == "estimated"


# --- retrieve() wrapper -----------------------------------------------------
def test_retrieve_wrapper_projects_detail_hits(monkeypatch):
    """`retrieve()` is the (text, meta) projection of `retrieve_detail().hits`, and it
    forwards its retrieval knobs to `retrieve_detail`."""
    seen = {}

    def fake_detail(question, *, mode="hybrid", top_k=4, pool=20, rerank_n=30,
                    rerank_backend=None):
        seen.update(question=question, mode=mode, top_k=top_k, pool=pool, rerank_n=rerank_n)
        return interchange.Retrieval(
            hits=[{"text": "t1", "meta": {"source": "a.md"}},
                  {"text": "t2", "meta": {"source": "b.md"}}],
            scoring={}, timings={}, space="l2", corpus="edi")

    monkeypatch.setattr(interchange, "retrieve_detail", fake_detail)
    out = interchange.retrieve("q?", mode="bm25", top_k=2)
    assert out == [("t1", {"source": "a.md"}), ("t2", {"source": "b.md"})]
    assert seen == {"question": "q?", "mode": "bm25", "top_k": 2, "pool": 20, "rerank_n": 30}


# --- pin tokens -------------------------------------------------------------
def test_mint_and_verify_pin_roundtrip_and_scoping():
    """A minted pin verifies for its (corpus, id) and fails on tamper, a different
    corpus, or a different id; the token is 16 hex chars."""
    token = interchange.mint_pin("edi", "x12-overview.md:3")
    assert len(token) == 16 and all(c in "0123456789abcdef" for c in token)
    assert interchange.verify_pin("edi", "x12-overview.md:3", token)

    tampered = ("0" if token[0] != "0" else "1") + token[1:]
    assert not interchange.verify_pin("edi", "x12-overview.md:3", tampered)
    assert not interchange.verify_pin("hotel", "x12-overview.md:3", token)   # cross-corpus
    assert not interchange.verify_pin("edi", "x12-overview.md:4", token)     # different id
    assert not interchange.verify_pin("edi", "x12-overview.md:3", "")        # empty


# --- fetch_chunks (stubbed Chroma) -----------------------------------------
class _StubCol:
    def __init__(self, store: dict):
        self.store = store          # id -> (doc, meta)

    def get(self, ids=None, include=None):
        # Chroma does NOT preserve request order and drops unknown ids: return the
        # present ids in REVERSED request order to prove fetch_chunks reorders.
        present = [i for i in (ids or []) if i in self.store]
        present = list(reversed(present))
        return {"ids": present,
                "documents": [self.store[i][0] for i in present],
                "metadatas": [self.store[i][1] for i in present]}

    def count(self):
        return len(self.store)


class _StubClient:
    col = None

    def __init__(self, path=None):
        pass

    def get_collection(self, name):
        return _StubClient.col


def test_fetch_chunks_reorders_dedupes_and_reports_missing(monkeypatch):
    store = {
        "a.md:0": ("doc a", {"source": "a.md", "chunk": 0, "section": "S", "title": "a"}),
        "b.md:0": ("doc b", {"source": "b.md", "chunk": 0, "section": "S", "title": "b"}),
        "c.md:0": ("doc c", {"source": "c.md", "chunk": 0, "section": "S", "title": "c"}),
    }
    _StubClient.col = _StubCol(store)
    monkeypatch.setattr(chromadb, "PersistentClient", _StubClient)

    # request order c, a, (dup c), b, and a missing id x
    pins = [{"id": cid, "token": interchange.mint_pin("edi", cid)}
            for cid in ["c.md:0", "a.md:0", "c.md:0", "b.md:0", "x.md:9"]]
    hits, missing = interchange.fetch_chunks("edi", pins)

    assert [h["id"] for h in hits] == ["c.md:0", "a.md:0", "b.md:0"]   # request order, deduped
    assert missing == ["x.md:9"]
    assert [h["final_rank"] for h in hits] == [1, 2, 3]
    for h in hits:
        assert h["pinned"] is True
        assert h["source"] == h["id"].split(":")[0]                   # from metadata, matches here
        for field in ("dense_rank", "dense_distance", "bm25_rank", "bm25_score",
                      "rrf_score", "rerank_score", "rerank_backend"):
            assert h[field] is None


def test_fetch_chunks_rejects_a_bad_token(monkeypatch):
    _StubClient.col = _StubCol({"a.md:0": ("doc a", {"source": "a.md"})})
    monkeypatch.setattr(chromadb, "PersistentClient", _StubClient)
    with pytest.raises(PermissionError):
        interchange.fetch_chunks("edi", [{"id": "a.md:0", "token": "deadbeefdeadbeef"}])


# --- corpus_snapshot cache --------------------------------------------------
class _CacheCol:
    def __init__(self):
        self._rows = [("a:0", "doc a0", {"source": "a", "chunk": 0}),
                      ("a:1", "doc a1", {"source": "a", "chunk": 1}),
                      ("b:0", "doc b0", {"source": "b", "chunk": 0})]
        self.metadata = {"hnsw:space": "l2"}
        self.get_calls = 0

    def count(self):
        return len(self._rows)

    def get(self, include=None):
        self.get_calls += 1
        return {"ids": [r[0] for r in self._rows],
                "documents": [r[1] for r in self._rows],
                "metadatas": [r[2] for r in self._rows]}

    def add_row(self):
        self._rows.append(("c:0", "doc c0", {"source": "c", "chunk": 0}))


def test_corpus_snapshot_caches_and_rebuilds_on_count_change(monkeypatch):
    col = _CacheCol()

    class Client:
        def __init__(self, path=None):
            pass

        def get_collection(self, name):
            return col

    monkeypatch.setattr(chromadb, "PersistentClient", Client)
    interchange._SNAP_CACHE.pop("snapcol", None)

    s1 = interchange.corpus_snapshot("snapcol")
    assert col.get_calls == 1
    assert s1.count == 3 and s1.space == "l2" and s1.ids == ["a:0", "a:1", "b:0"]

    # unchanged count -> same cached object, no second get()
    s2 = interchange.corpus_snapshot("snapcol")
    assert s2 is s1
    assert col.get_calls == 1

    # count changes -> rebuild
    col.add_row()
    s3 = interchange.corpus_snapshot("snapcol")
    assert s3 is not s1
    assert s3.count == 4
    assert col.get_calls == 2
    interchange._SNAP_CACHE.pop("snapcol", None)


def test_corpus_snapshot_space_defaults_to_l2_when_absent(monkeypatch):
    class BareCol:
        def count(self):
            return 1

        def get(self, include=None):
            return {"ids": ["a:0"], "documents": ["doc"], "metadatas": [{"source": "a"}]}

    class Client:
        def __init__(self, path=None):
            pass

        def get_collection(self, name):
            return BareCol()

    monkeypatch.setattr(chromadb, "PersistentClient", Client)
    interchange._SNAP_CACHE.pop("baremeta", None)
    snap = interchange.corpus_snapshot("baremeta")
    assert snap.space == "l2"
    interchange._SNAP_CACHE.pop("baremeta", None)
