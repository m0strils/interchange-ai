Feature: Answer-quality evaluation catches what retrieval eval can't
  As an operator of Interchange
  I want the grade run to reward correct refusals and flag fabricated answers
  So that the metric that actually fails on a from-context RAG — declining when the
     corpus can't answer — is measured, not assumed.

  # The whole harness runs offline here: retrieval, the generation engine, and the
  # judge's claude -p call are all stubbed. Faithfulness is a monitor; the headline
  # signal for out-of-corpus questions is refusal-correctness.

  Scenario: A fabricated answer to an out-of-corpus question fails refusal-correctness
    Given a golden set with one unanswerable question
    And retrieval returns an irrelevant passage from "x12-overview.md"
    And the model fabricates a cited answer instead of refusing
    And the judge finds the fabricated claim unsupported
    When I run the grade
    Then refusal-correctness is 0
    And the monitored faithfulness is below 1

  Scenario: A correct refusal to an out-of-corpus question passes refusal-correctness
    Given a golden set with one unanswerable question
    And retrieval returns an irrelevant passage from "x12-overview.md"
    And the model correctly declines to answer
    And the judge finds no claims to check
    When I run the grade
    Then refusal-correctness is 1
    And the monitored faithfulness is 1
