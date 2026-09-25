Feature: Retrieval mode follows the profile, tools gate the MCP server (ADR-0016 slice 4)
  As one engine serving several corpora
  I want each corpus to retrieve with its declared default and expose only its tools
  So that the vault reranks by default and a notes server never ships the X12 tool.

  Scenario: A profile's retrieval mode is the default and an explicit flag wins
    Given a recorder standing in for retrieval
    And the applied profile declares mode "hybrid+rerank" with rerank "cross-encoder"
    When I answer with no explicit mode
    Then the retrieval was run with mode "hybrid+rerank"
    When I answer with an explicit mode "hybrid"
    Then the retrieval was run with mode "hybrid"
    Given no profile is applied
    When I answer with no explicit mode
    Then the retrieval was run with mode "hybrid"

  Scenario: A declared rerank mode with no reranker fails plainly
    Given the applied profile declares mode "hybrid+rerank" with rerank "cross-encoder"
    And the reranker backend cannot import
    When I answer expecting a plain failure
    Then it fails naming "requirements-rerank.txt"

  Scenario: The X12 segment tool is absent from a non-EDI profile's MCP server
    When the MCP server starts under profile "vault"
    Then the registered tools are exactly "search_docs, ask_interchange"
    When the MCP server starts under profile "rail"
    Then the registered tools are exactly "lookup_segment, search_docs, ask_interchange"
