Feature: Eval-as-you-go — a validated golden row (ADR-0016 slice 5)
  As the owner of a personal corpus
  I want a miss to become a golden row only when its expected source is indexed
  So that the corpus grows its own measured baseline instead of accreting typos.

  Scenario: A miss becomes a golden row only if its expected source is indexed
    Given a golden set with one row and an index holding "a/b.md" and "c.md"
    When I add "q2" expecting "a/b.md" as a "paraphrase"
    Then the golden set has 2 rows
    And the new row's expected_source is "a/b.md" and kind is "paraphrase"
    When I add "q3" expecting the unindexed "ghost.md"
    Then it fails naming "ghost.md"
    And the golden set still has 2 rows

  Scenario: Several expected sources become expected_sources
    Given a golden set with one row and an index holding "a/b.md" and "c.md"
    When I add "q4" expecting both "a/b.md" and "c.md"
    Then the new row lists expected_sources ["a/b.md", "c.md"] and has no expected_source

  Scenario: A duplicate question is refused
    Given a golden set with one row and an index holding "a/b.md" and "c.md"
    And a row for "q2" already exists
    When I add "Q2 " expecting "a/b.md" as a "paraphrase"
    Then it fails naming "Q2"
    And the golden set has 2 rows

  Scenario: The golden file is created when absent
    Given a golden path under tmp that does not exist, index holding "a/b.md"
    When I add "q1" expecting "a/b.md" as a "paraphrase"
    Then the golden file now exists with 1 row
