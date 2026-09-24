"""
Interchange — MCP tool server (stdio).

Exposes the domain tools (search_docs, and lookup_segment for EDI profiles) over the
Model Context Protocol so a *subscription-run* agent — headless Claude Code (`claude -p`)
— can call them without a metered API key. See docs/adr/0003 (subscription runtime) and
0004 (tools via MCP).

The tool logic is reused verbatim from the reference loop (agent.py), so the tools
behave identically whether the runtime is the metered API loop or this one.

The corpus this server serves comes from ``DEMO_PROFILE`` (ADR-0016): the profile is
applied in-process at startup, so the tool allow-list, persona and retrieval default all
follow the corpus. ``lookup_segment`` is registered only when the profile's tool list
grants it — a notes/vault profile never sees the X12 segment tool.

Normally launched by the agent runtime via `--mcp-config`, not by hand. To debug
standalone it just speaks MCP over stdio: `python mcp_server.py`.

Requires: pip install mcp
"""
from __future__ import annotations

import os
import sys

from mcp.server import FastMCP         # high-level MCP server (the `mcp` SDK's FastMCP)

import a2a_agent.profiles as profiles
import enterprise
import interchange
from agent import _lookup_segment      # reuse the exact tool logic
from interchange import retrieve

# Apply the profile this server serves before registering tools (ADR-0016), so the tool
# allow-list, persona and retrieval default follow the corpus. A missing/bad profile is
# tolerated with one stderr line — the server still starts on the defaults.
_profile_name = os.environ.get("DEMO_PROFILE")
if _profile_name:
    try:
        interchange.apply_profile(_profile_name)
    except (SystemExit, KeyError) as exc:
        print(f"mcp_server: could not apply profile {_profile_name!r}: {exc}; "
              "continuing with defaults", file=sys.stderr)

# The effective tool allow-list: the applied profile's (``PROFILE_TOOLS``) or the default
# when no profile was applied. Registration below is conditional on it.
_tools = (interchange.PROFILE_TOOLS if interchange.PROFILE_TOOLS is not None
          else profiles.profile_tools({}))

mcp = FastMCP("interchange")


@mcp.tool()
def search_docs(query: str) -> str:
    """Search the indexed knowledge base for passages relevant to the query. Returns
    the top matching passages, each tagged with its [source] filename so the answer
    can cite it."""
    # Retrieve with the applied profile's default mode (ADR-0016), resolved per call.
    # ADR-0018: this tool stays on CHUNKS regardless of the profile's `context` — it
    # returns the raw retrieved passages (one [source] block per chunk), never the
    # note-assembled context. It feeds a tool-bearing agent session that calls it
    # repeatedly, the weakest downstream containment; note assembly (whole personal
    # notes) never happens here. We call `retrieve()` (retrieval only, no assemble step)
    # to make that explicit — assembly lives solely in `answer_detail`.
    mode = (interchange.PROFILE_RETRIEVAL or {}).get("mode", "hybrid")
    hits = retrieve(query, mode=mode)
    if not hits:
        return "No matching passages."
    # instruction/data separation: passages are DATA, tagged by source
    return "\n\n".join(f"[{m['source']}]\n{d}" for d, m in hits)


if "lookup_segment" in _tools:
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
