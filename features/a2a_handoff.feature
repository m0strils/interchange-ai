Feature: A2A agent handoff
  As a peer agent calling Interchange over Agent2Agent (A2A)
  I want the same governed pipeline the CLI and MCP tool get — signed identity,
  guardrails, grounding, and audit
  So that a handoff between agents is verifiable and accounted for, not a bare
  unauthenticated API call.

  Background:
    Given a fresh audit log
    And an ephemeral ES256 signing key pair
    And the knowledge base returns a passage from "x12-overview.md"

  Scenario: A signed card is verified and the handoff is answered, cited, and audited
    Given the knowledge agent for profile "rail" is mounted
    When the requester asks the profile's sample question with a valid API key
    Then the card is verified
    And the answer is cited and grounded
    And the audit row shows caller "a2a:requester"

  Scenario: A request with a missing API key is refused before the task runs
    Given the knowledge agent for profile "rail" is mounted
    When the requester asks a question with a missing API key
    Then the request fails with a 401

  Scenario: An injection attempt over A2A is blocked without ever calling the engine
    Given the knowledge agent for profile "rail" is mounted
    When the requester sends an injection attempt as the question
    Then the task fails
    And the engine was never called
    And the audit row is blocked

  Scenario: Switching the profile changes the active collection
    Given the knowledge agent for profile "rail" is mounted
    And the knowledge agent for profile "hotel" is mounted
    When the requester asks each profile's sample question
    Then the pipeline read collection "edi" for profile "rail"
    And the pipeline read collection "hotel" for profile "hotel"

  Scenario: A streamed response yields WORKING then COMPLETED then the artifact
    Given the knowledge agent for profile "rail" is mounted
    When the requester asks the profile's sample question with a valid API key
    Then the task states include "WORKING" before "COMPLETED"
    And the completed task carries the answer artifact
