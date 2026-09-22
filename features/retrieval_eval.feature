Feature: Retrieval eval — measured, not claimed (ADR-0007, ADR-0014)
  As the author of a governed knowledge runtime
  I want the retrieval eval to record the rank of the expected note, its mode and
     corpus, and the near-miss count
  So that ADR-0007's deferred reranker/router triggers become numbers I can read,
     not claims — and so an ablation (dense/bm25/hybrid) is a measured comparison.

  # Offline discipline: retrieve() and _known_sources() are stubbed, the golden set
  # and the run log live under tmp_path — no embeddings, no network, no real files.
  # Reranking never runs in the offline gate either: the rerank scenarios exercise the
  # pure reorder and the eval's rerank metadata only — the scorer backends
  # (cross-encoder / flashrank / typesafe) import lazily and are never touched here.
  Background:
    Given an index that holds "x12-overview.md" and "rail-edi-notes.md"

  Scenario: The eval reports the rank of the expected note, not only a hit
    Given a golden question expecting "x12-overview.md" retrieved at position 2
    When I run the retrieval eval at k 4 depth 10
    Then the run records rank 2 for that question
    And the run counts it as a hit

  Scenario: An expected note beyond k but within depth is counted as precision headroom
    Given a golden question expecting "x12-overview.md" retrieved at position 6
    When I run the retrieval eval at k 4 depth 10
    Then the near-miss count is 1
    And the run counts it as a miss

  Scenario: Dense-only and BM25-only modes bypass fusion
    When I fuse a dense ranking and a bm25 ranking under each single mode
    Then dense mode returns the dense ranking unchanged
    And bm25 mode returns the bm25 ranking unchanged

  Scenario: Evaluating a named corpus leaves the default collection untouched afterwards
    Given a golden question expecting "x12-overview.md" retrieved at position 1
    When I run the retrieval eval on corpus "vault"
    Then the retrieval ran against collection "vault"
    And the active collection afterwards is the module default

  Scenario: Every eval run appends one JSONL row with mode, corpus and per-question ranks
    Given a golden question expecting "x12-overview.md" retrieved at position 1
    When I run the retrieval eval at k 4 depth 10
    Then the eval log has exactly one row
    And that row carries the mode, the corpus, and a rank for the question

  Scenario: A golden row whose expected source is not in the index is flagged before scoring
    Given a golden question expecting "not-in-index.md" retrieved at position 1
    When I run the retrieval eval verbosely
    Then the output flags "not-in-index.md" as unknown before the scores

  Scenario: Unanswerable golden rows are skipped by the retrieval eval
    Given a golden set with one answerable and one unanswerable question
    When I run the retrieval eval at k 4 depth 10
    Then the run skips 1 row
    And the run scores 1 row

  Scenario: The reranker reorders the fused candidate window by relevance score
    When I rerank candidates "a,b,c" with scores "0.1,0.9,0.3"
    Then the reranked order is "b,c,a"

  Scenario: Equal reranker scores preserve the fused order
    When I rerank candidates "a,b,c" with scores "1.0,1.0,1.0"
    Then the reranked order is "a,b,c"

  Scenario: A rerank eval run records its backend, window and telemetry label
    Given a golden question expecting "x12-overview.md" retrieved at position 1
    When I run the retrieval eval in hybrid+rerank mode with window 30
    Then the eval log has exactly one row
    And that row records rerank backend "cross-encoder", window 30, and telemetry "measured"
