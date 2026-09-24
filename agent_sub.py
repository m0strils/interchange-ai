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
from a2a_agent.profiles import load_profile, profile_persona, profile_tools
from enterprise import GuardrailViolation, audit, guard_input, guard_output
from interchange import (
    DOCS_DIR,
    MODEL,
    _explain,
    discover_files,
    headless_cwd,
    parse_claude_usage,
    rel_source,
)

_HERE = pathlib.Path(__file__).parent
_MCP_SERVER = _HERE / "mcp_server.py"

# The rail default persona, used when the active profile carries no `persona`
# (ADR-0016 slice 3). agent_system_prompt() appends a least-privilege tool sentence.
SYSTEM_PROMPT = (
    "You are Interchange, an assistant for X12/EDI and rail trading-partner "
    "integration. Use the MCP tools to gather information before answering — "
    "search_docs for document-grounded questions, lookup_segment for segment "
    "definitions; you may call them multiple times. Answer ONLY from tool results "
    "and cite the source filename in [brackets] for retrieved facts. If the tools "
    "do not contain the answer, say so plainly — do not invent details."
)


def _active_profile() -> dict:
    """The profile this subscription agent serves this call (ADR-0016 slice 3).

    ``interchange.apply_profile`` exports ``DEMO_PROFILE`` when it runs, so
    ``load_profile()`` (argless → ``DEMO_PROFILE``, default ``rail``) returns the
    applied profile — persona, tools and all. Tolerant: a profile whose ``docs_dir``
    env is unset raises ``SystemExit`` and an unknown name raises ``KeyError``;
    either falls back to rail defaults (an empty block → no persona, both tools)."""
    try:
        return load_profile()
    except (SystemExit, KeyError):
        return {}


def allowed_tools(profile: dict | None = None) -> str:
    """The ``--allowedTools`` allow-list for the active (or given) profile: the
    profile's tools, each namespaced ``mcp__interchange__<tool>`` and comma-joined.

    Least privilege (the enterprise-readiness Security posture — scoped, allow-listed
    tools, no blanket bypass): a notes profile that lists only ``search_docs`` never
    gets ``lookup_segment`` (ADR-0016). Rail keeps both, unchanged."""
    p = _active_profile() if profile is None else profile
    return ",".join(f"mcp__interchange__{tool}" for tool in profile_tools(p))


def agent_system_prompt(profile: dict | None = None) -> str:
    """The subscription agent's system voice for the active (or given) profile: the
    profile's ``persona`` (ADR-0016) or the rail default ``SYSTEM_PROMPT``, plus one
    sentence naming the MCP tools it may use (built from ``profile_tools``)."""
    p = _active_profile() if profile is None else profile
    base = profile_persona(p) or SYSTEM_PROMPT
    tools = ", ".join(profile_tools(p))
    return f"{base} You may use only these MCP tools: {tools}."


def answer_agentic_sub(question: str, explain: bool = False) -> str:
    """Answer via the subscription agent (claude -p + MCP). Same guardrails as the
    API loop; runs on your Claude subscription at $0 marginal cost.

    The headless session runs in `headless_cwd()` with `--setting-sources user` so
    the child Claude must not inherit the calling repo's project settings and hooks
    (a project Stop hook would otherwise return hook commentary in place of the
    answer, flagged UNGROUNDED — ADR-0004 update)."""
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
    # Persona + tool allow-list follow the active profile at call time (ADR-0016):
    # the corpus a single process serves picks its own voice and least-privilege tools.
    profile = _active_profile()
    prompt = agent_system_prompt(profile)
    allowed = allowed_tools(profile)
    cmd = [
        "claude", "-p", question,
        "--mcp-config", mcp_config,
        "--allowedTools", allowed,
        "--append-system-prompt", prompt,
        "--output-format", "json",
        "--setting-sources", "user",
        # Only the --mcp-config interchange server loads; the machine's user-scope
        # MCP servers (Obsidian vaults) never enter this session even though the
        # allow-list already blocks their use, so they cost no context (2026-09-23).
        "--strict-mcp-config",
    ]
    if explain:
        _explain(f"stage 2 launching headless Claude Code on your subscription "
                 f"with MCP tools [{allowed}] (least-privilege allow-list)")

    # When tracing is on, hand Claude Code its own OTel env so it emits the native
    # interaction->llm_request->tool span tree and propagates traceparent into the MCP
    # server (ADR-0009). Empty merge (== inherit) when tracing is off.
    env = {**os.environ, **obs.claude_code_trace_env()}
    t0 = time.monotonic()
    with obs.span("agent", **{"openinference.span.kind": "AGENT", "input.value": question}):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                              cwd=headless_cwd(), env=env)
    latency_ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        sys.exit(f"claude -p failed: {proc.stderr.strip()[:300]}")

    # Parse the structured output via the shared helper (ADR-0004): MEASURED usage +
    # shadow cost when `claude -p` reports them, else a LABELED estimate over the full
    # prompt sent (system + question). model = what actually ran (Opus), not MODEL.
    info = parse_claude_usage(proc.stdout,
                              est_input_chars=len(prompt) + len(question))
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
