"""
Interchange — subscription agent runtime (ADR-0003).

Runs the agentic loop on your Claude *subscription* (Max/Pro) instead of the
metered API, by driving headless Claude Code (`claude -p`) with the MCP tool
server (mcp_server.py). No ANTHROPIC_API_KEY; $0 marginal cost.

This is the same subscription product the `--engine claude-code` RAG path already
uses — now given tools via MCP. The hand-rolled API loop (agent.py) survives as
the Lesson 02 reference ("what the framework does under the hood").

The trade recorded in ADR-0003: this path reports ESTIMATED tokens and $0 cost
(Claude Code doesn't meter per call), where the API loop gives exact telemetry.
Same input/output guardrails and audit either way.

Prereqs: the `claude` CLI installed and logged into your subscription, and
`pip install mcp` for the tool server.
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from enterprise import GuardrailViolation, audit, guard_input, guard_output
from interchange import DOCS_DIR, MODEL, _explain

_HERE = pathlib.Path(__file__).parent
_MCP_SERVER = _HERE / "mcp_server.py"

# Least privilege: allow ONLY our two MCP tools — no bash, no file access. This is
# the enterprise-readiness Security posture (scoped, allow-listed tools) and it's
# why we do NOT use a blanket bypass-permissions mode.
_ALLOWED_TOOLS = "mcp__interchange__search_docs,mcp__interchange__lookup_segment"

SYSTEM_PROMPT = (
    "You are Interchange, an assistant for X12/EDI and rail trading-partner "
    "integration. Use the MCP tools to gather information before answering — "
    "search_docs for document-grounded questions, lookup_segment for segment "
    "definitions; you may call them multiple times. Answer ONLY from tool results "
    "and cite the source filename in [brackets] for retrieved facts. If the tools "
    "do not contain the answer, say so plainly — do not invent details."
)


def answer_agentic_sub(question: str, explain: bool = False) -> str:
    """Answer via the subscription agent (claude -p + MCP). Same guardrails as the
    API loop; runs on your Claude subscription at $0 marginal cost."""
    # -- enterprise: input guardrail (unchanged) --
    if explain:
        _explain("stage 1 input guardrail (OWASP LLM01)")
    try:
        question = guard_input(question)
    except GuardrailViolation as e:
        if explain:
            _explain(f"  blocked: {e}")
        audit(question=question, model=MODEL, sources=[], in_tokens=0, out_tokens=0,
              latency_ms=0, grounded=False, blocked=str(e), engine="claude-code")
        return f"🛑 Request blocked by input guardrail: {e}"
    if explain:
        _explain("  passed")

    if not shutil.which("claude"):
        sys.exit("The subscription agent needs the `claude` CLI (Claude Code) "
                 "installed and logged into your Max/Pro plan.")

    # Register our MCP tool server inline; command = this interpreter so the server
    # runs in the same venv (where `mcp` and chromadb are installed).
    mcp_config = json.dumps({
        "mcpServers": {
            "interchange": {
                "type": "stdio",
                "command": sys.executable,
                "args": [str(_MCP_SERVER)],
            }
        }
    })
    cmd = [
        "claude", "-p", question,
        "--mcp-config", mcp_config,
        "--allowedTools", _ALLOWED_TOOLS,
        "--append-system-prompt", SYSTEM_PROMPT,
        "--output-format", "json",
    ]
    if explain:
        _explain(f"stage 2 launching headless Claude Code on your subscription "
                 f"with MCP tools [{_ALLOWED_TOOLS}] (least-privilege allow-list)")

    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240, cwd=str(_HERE))
    latency_ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        sys.exit(f"claude -p failed: {proc.stderr.strip()[:300]}")

    # Parse the structured output; tolerate a plain-text fallback across versions.
    try:
        out = json.loads(proc.stdout)
        text = (out.get("result") or "").strip()
        usage = out.get("usage") or {}
    except json.JSONDecodeError:
        text, usage = proc.stdout.strip(), {}

    # Subscription billing isn't per-call: record ESTIMATED tokens; audit() zeroes
    # cost for non-api engines. Honest by design (ADR-0003).
    in_tokens = usage.get("input_tokens") or (len(question) // 4)
    out_tokens = usage.get("output_tokens") or (len(text) // 4)

    # Grounding check: does the answer cite a real doc? We can't see which sources
    # the sub-session retrieved, so pass the whole doc set as the candidate list —
    # a citation of any real doc counts as grounded.
    doc_sources = sorted(os.path.basename(p) for p in
                         glob.glob(str(DOCS_DIR / "*.md")) + glob.glob(str(DOCS_DIR / "*.txt")))
    text, grounded = guard_output(text, doc_sources)
    if explain:
        _explain(f"stage 3 output guardrail — {'grounded ✅' if grounded else '⚠️ UNGROUNDED'}")
        _explain(f"  audit: ~{in_tokens} in / ~{out_tokens} out tok (estimated), "
                 f"{latency_ms}ms, $0 marginal (subscription) -> audit.jsonl")
    audit(question=question, model=MODEL, sources=[], in_tokens=in_tokens,
          out_tokens=out_tokens, latency_ms=latency_ms, grounded=grounded, engine="claude-code")
    return text
