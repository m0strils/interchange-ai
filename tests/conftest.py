"""Shared fixtures for the acceptance (pytest-bdd) and unit layers (ADR-0005).

Two guarantees enforced here:
  * Tests never touch the real ``audit.jsonl`` — ``enterprise.AUDIT_PATH`` is
    redirected to a per-test tmp file by an autouse fixture.
  * Steps share state through a ``context`` dict (question asked, answer returned,
    whether the fake engine was actually invoked, etc.).
"""
from __future__ import annotations

import json
import random

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


def fake_snapshot(notes: dict) -> interchange.Snapshot:
    """An offline ``interchange.Snapshot`` for context assembly (ADR-0018 Slice B).

    ``notes`` maps each source to its per-source chunk texts, in chunk-index order;
    chunk ``j`` becomes id ``f"{source}:{j}"`` with metas
    ``{source, chunk, section, title, lead}`` (``lead`` on chunk 0). The ids/docs/
    metas lists are then **deliberately shuffled** with a fixed seed, so a test that
    relies on note order proves ``chunk_map`` sorts by chunk index rather than by
    Chroma's ``get`` order. ``bm25`` is ``None`` (assembly never touches it).
    """
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    for source, chunks in notes.items():
        title = source[:-3] if source.endswith(".md") else source
        for j, text in enumerate(chunks):
            ids.append(f"{source}:{j}")
            docs.append(text)
            metas.append({"source": source, "chunk": j, "section": f"section-{j}",
                          "title": title, "lead": j == 0})
    order = list(range(len(ids)))
    random.Random(1234).shuffle(order)          # prove chunk_map sorts, not list order
    ids = [ids[i] for i in order]
    docs = [docs[i] for i in order]
    metas = [metas[i] for i in order]
    return interchange.Snapshot(count=len(ids), ids=ids, docs=docs, metas=metas,
                                bm25=None, space="l2")


@pytest.fixture
def context() -> dict:
    """Mutable scratch space shared across Given/When/Then steps in one scenario."""
    return {}


@pytest.fixture(autouse=True)
def isolated_profiles(monkeypatch):
    """Disable the machine's personal profiles overlay for every test.

    The corpus-profiles overlay (``INTERCHANGE_PROFILES``, ADR-0016) defaults to
    ``~/.interchange/profiles.yaml``, which exists on some dev machines and defines
    extra profiles. Setting the env var to the empty string turns the overlay off so
    the gate reads only the committed ``profiles.yaml`` — never this machine's real
    overlay. A test that wants an overlay monkeypatches the var back to a tmp file.
    """
    monkeypatch.setenv("INTERCHANGE_PROFILES", "")


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
