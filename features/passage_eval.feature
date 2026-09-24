Feature: Passage-level retrieval eval (ADR-0017)
  As the author of a governed knowledge runtime
  I want the eval to score whether the retriever surfaced the answer's PASSAGE, not
     only its source file
  So that a retriever returning only a note's frontmatter/title chunks — a source hit
     with no content — is measured as the miss it is, and lead-chunk dominance is a
     number I can watch fall.

  # Offline discipline: retrieve(), _known_sources() and _known_sections() are stubbed,
  # the golden set and the run log live under tmp_path — no embeddings, no network, no
  # real files. Passage scoring is a source-and-section rule over the (source, section)
  # pairs a run retrieved; a row without an expected_section scores source-only, exactly
  # as before.

  Scenario: A source hit without an expected_section stays a source-only score
    Given a golden row expecting source "note.md" with no section
    And a question whose retrieval returns "note.md@preamble,note.md@Body" each titled "note"
    When I run the passage eval at k 4
    Then the run counts 1 source hit
    And passage@k is reported as not-applicable
    And the row records no passage rank

  Scenario: A matching source-and-section chunk is a passage hit at its rank
    Given a golden row expecting source "note.md" and section "Setup"
    And a question whose retrieval returns "note.md@preamble,note.md@Setup" each titled "note"
    When I run the passage eval at k 4
    Then the run counts 1 source hit
    And the row records passage rank 2
    And passage@k is 1 over 1

  Scenario: A lead-only result is a source hit but a passage miss
    Given a golden row expecting source "note.md" and section "Working"
    And a question whose retrieval returns "note.md@preamble,note.md@note" each titled "note"
    When I run the passage eval at k 4
    Then the run counts 1 source hit
    And the row records no passage rank
    And passage@k is 0 over 1

  Scenario: An expected_section list matches any of its sections
    Given a golden row expecting source "note.md" and either section "Setup" or "Working"
    And a question whose retrieval returns "note.md@preamble,note.md@Working" each titled "note"
    When I run the passage eval at k 4
    Then the row records passage rank 2
    And passage@k is 1 over 1

  Scenario: Lead share counts preamble and H1 chunks
    Given retrieved chunks with sections "preamble,Guide,Setup,Working" each titled "Guide"
    When I measure the lead share at k 4
    Then the lead share is "0.50"

  Scenario: golden-add refuses an unknown section and writes the field when valid
    Given an index where "ref.md" has sections "Setup,Working,Memory"
    When I golden-add "practices q" expecting "ref.md" with sections "Setup"
    Then the new row's expected_section is "Setup"
    When I golden-add "bad section q" expecting "ref.md" with sections "Nonexistent"
    Then it fails naming section "Nonexistent" and source "ref.md"
    When I golden-add "two section q" expecting "ref.md" with sections "Setup,Working"
    Then the new row's expected_section lists "Setup,Working"

  Scenario: The mode-comparison table carries the passage and lead columns
    Given a golden row expecting source "note.md" and section "Setup"
    And a question whose retrieval returns "note.md@preamble,note.md@Setup" each titled "note"
    When I run the eval in mode all
    Then the comparison table header carries "passage@4" and "lead"

  Scenario: The eval log record carries the passage and lead diagnostics
    Given a golden row expecting source "note.md" and section "Setup"
    And a question whose retrieval returns "note.md@preamble,note.md@Setup" each titled "note"
    When I run the passage eval at k 4
    Then the eval log record carries passage_at_k and lead_share
