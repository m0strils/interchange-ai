Feature: Context-assembly eval (ADR-0018)
  As the author of a governed knowledge runtime
  I want the eval to score the context the engine actually SEES — the assembled
     context, computed from the first k hits under the profile's context settings —
  So that whole-note and section questions are measured on included chunk metadata,
     never a text substring, and "include everything" pays a real char counter-metric.

  # Offline discipline (ADR-0006): retrieve() returns (doc, meta) pairs (stubbed),
  # eval_snapshot() returns a fake_snapshot (stubbed), and _known_sources/_known_sections
  # are monkeypatched. `chunks` context needs no snapshot; `notes` context assembles by
  # note under a budget. Section matching is on the (source, section) metadata of the
  # INCLUDED chunks. These scenarios live here and are bound with explicit scenario()
  # calls — never appended to the bulk-bound retrieval_eval.feature.

  Scenario: A section row is a context hit when an included chunk of the source matches (ANY)
    Given a golden row expecting source "n.md" and section "section-1"
    And a retrieval returning chunks "n.md:0:section-0,n.md:1:section-1"
    When I run the context eval at k 4 in chunks mode
    Then context@k is 1 over 1
    And the row is a context hit

  Scenario: An expected_sections_all row needs every label — two of three present is a miss
    Given a golden row expecting source "n.md" with all sections "A,B,C"
    And a retrieval returning chunks "n.md:0:A,n.md:1:B"
    When I run the context eval at k 4 in chunks mode
    Then context@k is 0 over 1
    And the row is a context miss
    Given a retrieval returning chunks "n.md:0:A,n.md:1:B,n.md:2:C"
    When I run the context eval at k 4 in chunks mode
    Then context@k is 1 over 1
    And the row is a context hit

  Scenario: chunks context degenerates to passage@k for a single-section row
    Given a golden row expecting source "n.md" and section "section-1"
    And a retrieval returning chunks "n.md:0:section-0,n.md:1:section-1"
    When I run the context eval at k 4 in chunks mode
    Then context@k equals passage@k

  Scenario: notes context on a small note is a context hit and a note hit
    Given a golden row expecting source "n.md" and section "section-2"
    And a snapshot where "n.md" has chunks "aaa|bbb|ccc"
    And a retrieval returning chunks "n.md:0:seed"
    When I run the context eval at k 4 in notes mode
    Then the row is a context hit
    And the row is a note hit
    And the row's context kind is "whole"

  Scenario: A note over note_max_chars is ineligible for note@k and is named in the summary
    Given a golden row expecting source "big.md" and section "section-0"
    And a snapshot where "big.md" has chunks "0123456789012345678901234567890123456789|0123456789012345678901234567890123456789"
    And a retrieval returning chunks "big.md:0:seed"
    And a note-max of 50
    When I run the context eval with summary at k 4 in notes mode
    Then note@k is reported as not-applicable
    And the summary names "big.md" as ineligible

  Scenario: The eval assembles from the first k pairs only
    Given a golden row expecting source "n.md" and section "section-4"
    And a retrieval returning chunks "n.md:0:section-0,n.md:1:section-1,n.md:2:section-2,n.md:3:section-3,n.md:4:section-4"
    When I run the context eval at k 4 in chunks mode
    Then the row is a context miss
    And the row records passage rank 5

  Scenario: No Chroma call in the eval path when retrieve and eval_snapshot are stubbed
    Given a golden row expecting source "n.md" and section "section-1"
    And a snapshot where "n.md" has chunks "aaa|bbb"
    And a retrieval returning chunks "n.md:0:seed"
    And Chroma is forbidden
    When I run the context eval at k 4 in notes mode
    Then the run completed without touching Chroma

  Scenario: golden-add --sections-all refuses an unknown label and writes a list when valid
    Given an index where "ref.md" has sections "Setup,Working,Structure"
    When I golden-add "practices all q" expecting "ref.md" with all-sections "Setup,Working"
    Then the new row's expected_sections_all lists "Setup,Working"
    When I golden-add "bad all q" expecting "ref.md" with all-sections "Nonexistent"
    Then it fails naming section "Nonexistent" and source "ref.md"

  Scenario: The mode-comparison table carries the context columns
    Given a golden row expecting source "n.md" and section "section-1"
    And a retrieval returning chunks "n.md:0:section-0,n.md:1:section-1"
    When I run the eval in mode all
    Then the comparison table header carries "ctx@4" and "note@4"
    And the comparison table header carries "chars"

  Scenario: The eval log record carries the context diagnostics
    Given a golden row expecting source "n.md" and section "section-1"
    And a retrieval returning chunks "n.md:0:section-0,n.md:1:section-1"
    When I run the context eval at k 4 in chunks mode
    Then the eval log record carries the context keys
    And the eval log record still carries passage_at_k and lead_share
