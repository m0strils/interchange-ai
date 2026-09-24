Feature: Headless Claude Code sessions load no stray MCP servers or tools
  The headless `claude -p` call sites must be pure of the calling machine's
  user-scope MCP servers, so a text-generation session cannot try (and be denied)
  the owner's Obsidian connectors and answer with connector chatter in place of the
  question (observed 2026-09-23). The RAG engine loads no MCP servers and no
  built-in tools; the subscription agent loads only its own interchange MCP server.

  Scenario: The RAG engine never loads user MCP servers
    Given a fake claude CLI that records its argv
    When the RAG engine generates an answer for "q"
    Then the RAG argv passes "--strict-mcp-config"
    And the RAG argv does not pass "--mcp-config"
    And the RAG argv disables all built-in tools

  Scenario: The subscription agent loads only the interchange MCP server
    Given a fake claude CLI that records its argv
    When the subscription agent answers "what is a 214?"
    Then the subscription argv passes "--strict-mcp-config"
    And the subscription argv passes "--mcp-config" exactly once

  Scenario: The headless working directory is unchanged
    Given a fake claude CLI that records its argv
    When the RAG engine generates an answer for "q"
    And the subscription agent answers "what is a 214?"
    Then every recorded session ran in the repo-free headless cwd
