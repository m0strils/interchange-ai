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

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import observability as obs  # no-op unless INTERCHANGE_TRACING=1 (ADR-0009)
from enterprise import GuardrailViolation, audit, guard_input, guard_output
from interchange import DOCS_DIR, MODEL, _explain, discover_files, parse_claude_usage, rel_source

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

    # When tracing is on, hand Claude Code its own OTel env so it emits the native
    # interaction->llm_request->tool span tree and propagates traceparent into the MCP
    # server (ADR-0009). Empty merge (== inherit) when tracing is off.
    env = {**os.environ, **obs.claude_code_trace_env()}
    t0 = time.monotonic()
    with obs.span("agent", **{"openinference.span.kind": "AGENT", "input.value": question}):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                              cwd=str(_HERE), env=env)
    latency_ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        sys.exit(f"claude -p failed: {proc.stderr.strip()[:300]}")

    # Parse the structured output via the shared helper (ADR-0004): MEASURED usage +
    # shadow cost when `claude -p` reports them, else a LABELED estimate over the full
    # prompt sent (system + question). model = what actually ran (Opus), not MODEL.
    info = parse_claude_usage(proc.stdout,
                              est_input_chars=len(SYSTEM_PROMPT) + len(question))
    text = info["text"]
    in_tokens, out_tokens = info["in"], info["out"]
    cost, telemetry, model = info["cost"], info["telemetry"], info["model"]

    # Grounding check: does the answer cite a real doc? We can't see which sources
    # the sub-session retrieved, so pass the whole doc set as the candidate list —
    # a citation of any real doc counts as grounded. Use the same recursive,
    # ignore-aware discovery the index is built from (rel_source, so a nested vault
    # note matches its folder-qualified citation); identical to the old flat glob on
    # the seed corpus.
    doc_sources = sorted(rel_source(DOCS_DIR, p) for p in discover_files(DOCS_DIR))
    text, grounded = guard_output(text, doc_sources)
    if explain:
        shadow = f"${cost:.4f}" if cost is not None else "n/a"
        _explain(f"stage 3 output guardrail — {'grounded ✅' if grounded else '⚠️ UNGROUNDED'}")
        _explain(f"  audit ({telemetry}): {in_tokens} in / {out_tokens} out tok, "
                 f"{latency_ms}ms, shadow≈{shadow}, $0 marginal -> audit.jsonl")
    audit(question=question, model=(model or MODEL), sources=[], in_tokens=in_tokens,
          out_tokens=out_tokens, latency_ms=latency_ms, grounded=grounded,
          engine="claude-code", telemetry=telemetry, cost_usd=cost)
    return text
