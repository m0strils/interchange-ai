Feature: Persona follows the corpus, tools follow the profile (ADR-0016 slice 3)
  As one process serving several corpora
  I want each corpus answered in its own voice with only its own tools
  So that a hotel question is answered by a hotel assistant, not an EDI expert.

  Scenario: The system prompt follows the corpus, not the process
    Given a fake engine that records the active system prompt
    When I answer a question on the "hotel" corpus
    Then the recorded system prompt mentions "Demo Hotel"
    When I answer a question on the "edi" corpus
    Then the recorded system prompt mentions "X12"

  Scenario: A persona is reset after the request
    Given a fake engine that records the active system prompt
    When I answer a question on the "hotel" corpus
    Then the system prompt outside any request is the module default

  Scenario: The subscription agent's allow-list contains only the profile's tools
    Given the active demo profile is "vault" with its vault dir set
    Then the subscription allow-list is "mcp__interchange__search_docs"
    Given the active demo profile is "rail"
    Then the subscription allow-list is "mcp__interchange__search_docs,mcp__interchange__lookup_segment"

  Scenario: The agent system prompt carries the profile persona
    Then the agent system prompt for "hotel" mentions "Demo Hotel"
    And the agent system prompt for "rail" mentions "X12"
