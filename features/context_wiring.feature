Feature: Context assembly wired into the answer path (ADR-0018)
  As the owner of the governed knowledge runtime
  I want the answer path to assemble context by note under a budget, resolved once
  So that grounding, citation and audit follow the included set and a pin never assembles.

  Scenario: A pinned re-ask under a notes profile never assembles
    Given the corpus profile declares context "notes"
    And a fake snapshot the assembler could expand
    And two pinned chunks are fetched for the corpus
    When I answer a pinned re-ask
    Then the response context mode is "chunks"
    And the response context chunks_out equals 2

  Scenario: Grounding and audit follow the included set, not the retrieved hits
    Given the corpus profile declares context "notes"
    And a fake snapshot holding only the first hit's note
    And a fake retrieval of a hit in the snapshot and a hit missing from it
    When I answer over the corpus
    Then the audit sources are exactly "a.md"
    And the missing hit's source is absent from the audit sources
    And the missing hit's source is present in the audit hit_sources

  Scenario: Chunks mode assembles without touching the snapshot
    Given the corpus profile declares context "chunks"
    And the snapshot raises if it is touched
    And a fake retrieval of one chunk
    When I answer over the corpus
    Then the answer is grounded
    And the response context mode is "chunks"

  Scenario: An invalid profile retrieval block falls back to chunks and still answers
    Given the corpus profile has an invalid retrieval block
    And a fake retrieval of one chunk
    When I answer over the corpus
    Then the answer is grounded
    And the response context mode is "chunks"

  Scenario: A public deploy clamps the context mode to chunks
    Given the deploy is public
    And the corpus profile declares context "notes"
    And a fake retrieval of one chunk
    When I answer over the corpus
    Then the response context mode is "chunks"
