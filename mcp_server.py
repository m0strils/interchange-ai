"""
Interchange — MCP tool server (stdio).

Exposes the two domain tools (search_docs, lookup_segment) over the Model Context
Protocol so a *subscription-run* agent — headless Claude Code (`claude -p`) — can
call them without a metered API key. See docs/adr/0003 (subscription runtime) and
0004 (tools via MCP).

The tool logic is reused verbatim from the reference loop (agent.py), so the tools
behave identically whether the runtime is the metered API loop or this one.

Normally launched by the agent runtime via `--mcp-config`, not by hand. To debug
standalone it just speaks MCP over stdio: `python mcp_server.py`.

Requires: pip install mcp
"""
from __future__ import annotations

import os

from mcp.server import FastMCP         # high-level MCP server (the `mcp` SDK's FastMCP)

import enterprise
import interchange
from agent import _lookup_segment      # reuse the exact tool logic
from interchange import retrieve

mcp = FastMCP("interchange")


@mcp.tool()
def search_docs(query: str) -> str:
    """Search the indexed EDI/rail knowledge base. Returns the top matching
    passages, each tagged with its [source] filename so the answer can cite it."""
    hits = retrieve(query)
    if not hits:
        return "No matching passages."
    # instruction/data separation: passages are DATA, tagged by source
    return "\n\n".join(f"[{m['source']}]\n{d}" for d, m in hits)


@mcp.tool()
def lookup_segment(segment_id: str) -> str:
    """Look up the definition of an X12 EDI segment by identifier (e.g. ISA, GS, ST, N1)."""
    return _lookup_segment(segment_id)


@mcp.tool()
def ask_interchange(question: str) -> str:
    """Ask Interchange a question and get back the full governed answer —
    retrieval, citation and the grounding check included, not just raw passages.

    The MCP half of the MCP-vs-A2A pair (ADR-0013): the *same* ``answer()`` a
    peer agent reaches over A2A, reached instead as a tool by an agent in a
    trusted local process. Different protocol, different trust story, one
    governed core — and the audit row proves it, differing only in ``caller``.
    """
    token = enterprise.CALLER.set("mcp")
    try:
        return interchange.answer(
            question, engine=os.environ.get("INTERCHANGE_ENGINE", "api")
        )
    finally:
        enterprise.CALLER.reset(token)


if __name__ == "__main__":
    mcp.run()  # stdio transport (the default)
