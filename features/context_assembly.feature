Feature: Context assembly with a budget (ADR-0018)
  As the answer engine
  I want the context assembled by note under a budget, not just the four ranked chunks
  So that whole-note and section questions are answered from the content, while
     ranking, the credential guard, and the byte-identical `chunks` behaviour are kept.

  # Offline (ADR-0006): assemble_context is pure. No Chroma, no embeddings, no network.
  # The snapshot is a `fake_snapshot` whose list order is deliberately shuffled, so a
  # note that assembles in chunk-index order proves `chunk_map` sorts.

  Scenario: chunks mode returns exactly the hits, byte-identical to today
    Given a note "a.md" with chunks "alpha"
    And a note "b.md" with chunks "beta"
    And a hit into "a.md" chunk 0
    And a hit into "b.md" chunk 0
    When I assemble the context in "chunks" mode
    Then the context is byte-identical to the joined hit blocks
    And included_sources equals hit_sources

  Scenario: the seed pass includes every hit even under a one-character budget
    Given a note "a.md" with chunks "alpha"
    And a note "b.md" with chunks "beta"
    And a hit into "a.md" chunk 0
    And a hit into "b.md" chunk 0
    When I assemble the context in "notes" mode with budget 1 and note-max 1
    Then every hit's own chunk is included
    And dropped_hits is 0
    And the budget was hit

  Scenario: a small note is included whole in chunk-index order from a shuffled snapshot
    Given a note "n.md" with chunks "c0, c1, c2"
    And a hit into "n.md" chunk 1
    When I assemble the context in "notes" mode with budget 20000 and note-max 16000
    Then the reason for "n.md" is "whole"
    And the context has one "n.md" header
    And the context is the whole note "n.md" with chunks "c0, c1, c2"

  Scenario: a note over the note-max falls back to neighbours
    Given a note "big.md" with 5 chunks of 100 characters
    And a hit into "big.md" chunk 2
    When I assemble the context in "notes" mode with budget 1000 and note-max 300
    Then the reason for "big.md" is "note_too_big"
    And fallbacks is 1
    And more than one chunk of "big.md" is included

  Scenario: a whole note that does not fit the remaining budget is skipped whole
    Given a note "a.md" with 1 chunk of 300 characters
    And a note "b.md" with 2 chunks of 200 characters
    And a hit into "a.md" chunk 0
    And a hit into "b.md" chunk 0
    When I assemble the context in "notes" mode with budget 600 and note-max 600
    Then the reason for "b.md" is "budget_exhausted"
    And the budget was hit
    And only 1 chunk of "b.md" is included
    And no included chunk text is truncated

  Scenario: no chunk is included twice when two hits share a source
    Given a note "n.md" with chunks "c0, c1, c2"
    And a hit into "n.md" chunk 0
    And a hit into "n.md" chunk 1
    When I assemble the context in "notes" mode with budget 20000 and note-max 16000
    Then the context has one "n.md" header
    And each included chunk of "n.md" appears once

  Scenario: an expansion-added secret-like chunk is dropped and counted
    Given a note "n.md" whose chunk 1 looks like a credential
    And a hit into "n.md" chunk 0
    When I assemble the context in "notes" mode with budget 20000 and note-max 16000
    Then secret_drops is 1
    And the seed chunk of "n.md" is kept
    And the credential-like chunk is absent from the context

  Scenario: included_sources holds every seeded source and chars equals the text length
    Given a note "a.md" with chunks "a0"
    And a note "b.md" with chunks "b0, b1"
    And a hit into "a.md" chunk 0
    And a hit into "b.md" chunk 0
    When I assemble the context in "notes" mode with budget 20000 and note-max 16000
    Then included_sources is "a.md, b.md"
    And chars equals the length of the text

  Scenario: assembly rejects an unknown mode
    Given a note "a.md" with chunks "alpha"
    And a hit into "a.md" chunk 0
    When I assemble the context in "bogus" mode
    Then assembly raises a ValueError

  Scenario: assembly rejects a note-max larger than the budget
    Given a note "a.md" with chunks "alpha"
    And a hit into "a.md" chunk 0
    When I assemble the context in "notes" mode with budget 100 and note-max 200
    Then assembly raises a ValueError

  Scenario: profile_retrieval rejects a string budget and clamps nothing
    Given a profile whose retrieval budget_chars is the string "12000"
    When I read the profile's retrieval
    Then a retrieval ValueError names "budget_chars"

  Scenario: policy clamps notes to chunks and caps the budget
    Given the context mode max is "chunks" and the budget max is 24000
    And context settings mode "notes" budget 30000 note-max 16000
    When I clamp the context settings
    Then the clamped mode is "chunks"
    And the clamped budget is 24000
