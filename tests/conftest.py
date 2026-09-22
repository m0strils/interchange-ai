"""Shared fixtures for the acceptance (pytest-bdd) and unit layers (ADR-0005).

Two guarantees enforced here:
  * Tests never touch the real ``audit.jsonl`` — ``enterprise.AUDIT_PATH`` is
    redirected to a per-test tmp file by an autouse fixture.
  * Steps share state through a ``context`` dict (question asked, answer returned,
    whether the fake engine was actually invoked, etc.).
"""
from __future__ import annotations

import json

import pytest

import enterprise
import interchange


def fake_retrieval(*hits, corpus: str = "edi"):
    """An offline ``interchange.Retrieval`` for the surfaces that now call
    ``retrieve_detail`` (slice 2). Each ``hit`` is a small dict — at least
    ``source`` and ``text`` — and is filled out into a realistic *scored* Hit
    record (dense/bm25/rrf numbers, final_rank in call order) carrying a **valid**
    pin token minted for ``corpus`` via ``interchange.mint_pin``, so a pinned
    re-ask over these hits verifies. Score fields can be overridden per hit.

    Returns the same ``Retrieval`` shape ``retrieve_detail`` returns, with a
    real ``score_legend`` (``dense_distance.kind == "l2"``), so a test can drive
    the whole governed pipeline without Chroma.
    """
    made = []
    for i, h in enumerate(hits, start=1):
        source = h.get("source", "x12-overview.md")
        chunk = h.get("chunk", 0)
        cid = h.get("id") or f"{source}:{chunk}"
        made.append({
            "id": cid,
            "pin": interchange.mint_pin(corpus, cid),
            "corpus": corpus,
            "source": source,
            "chunk": chunk,
            "section": h.get("section"),
            "title": h.get("title"),
            "text": h["text"],
            "meta": h.get("meta", {"source": source, "chunk": chunk}),
            "final_rank": i,
            "dense_rank": h.get("dense_rank", i),
            "dense_distance": h.get("dense_distance", round(1.60 + 0.1 * i, 4)),
            "bm25_rank": h.get("bm25_rank", i),
            "bm25_score": h.get("bm25_score", round(8.0 - i, 3)),
            "rrf_score": h.get("rrf_score", round(0.033 - 0.001 * i, 5)),
            "rerank_score": h.get("rerank_score"),
            "rerank_backend": h.get("rerank_backend"),
            "pinned": False,
        })
    return interchange.Retrieval(
        hits=made,
        scoring=interchange.score_legend("l2", None),
        timings={"dense_ms": 1, "bm25_ms": 1, "rrf_ms": 0, "rerank_ms": 0},
        space="l2", corpus=corpus,
    )


@pytest.fixture
def context() -> dict:
    """Mutable scratch space shared across Given/When/Then steps in one scenario."""
    return {}


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Redirect the audit log to a throwaway tmp file so no test writes the real one.

    Autouse: every test (acceptance or unit) gets an isolated, empty audit log.
    """
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(enterprise, "AUDIT_PATH", audit_file)
    return audit_file


def read_audit_rows(path=None) -> list[dict]:
    """Return all audit rows as parsed dicts (empty list if the log is absent)."""
    path = path or enterprise.AUDIT_PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def last_audit_row(path=None) -> dict:
    """Return the most recently written audit row (the record under test)."""
    rows = read_audit_rows(path)
    assert rows, "expected at least one audit row to have been written"
    return rows[-1]
