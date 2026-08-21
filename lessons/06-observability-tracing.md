# Lesson 06 — Observability: two layers, and the bug tracing caught

Every earlier lesson recorded *something* about each request: Lesson 01's audit log
already captures model, sources, tokens, cost, latency, grounded/blocked — one JSONL
row per request. So why add tracing at all? Because a flat row can't show you the
*shape* of a request: how long retrieve vs generate vs the guardrails took, or — inside
`--agent` — which tools the model actually called and in what order. This lesson adds
that second layer, and in doing so it caught a bug that had been hiding since Lesson 03.

The decision is [ADR-0009](../docs/adr/0009-observability.md). Here's the *why*.

## Two layers, kept distinct

| | audit log (Lesson 01) | traces (this lesson) |
|---|---|---|
| Granularity | one row per request | a span per *stage*, nested |
| Always on? | yes — the compliance record | opt-in (`INTERCHANGE_TRACING=1`) |
| Answers | "what happened, what did it cost?" | "*where* did the time go? what did the agent *do*?" |
| Lives in | `audit.jsonl` (durable) | a local Phoenix UI (dev-time) |

They're complementary, not a replacement. `audit.jsonl` is the governance record you
keep; traces are the microscope you switch on when debugging. Neither is the other.

## Why not just "turn on auto-instrumentation"?

The tempting shortcut in 2026 is a one-liner: install
`openinference-instrumentation-anthropic` (or OpenLLMetry), call `.instrument()`, and
LLM spans appear "for free." **It does nothing here** — and understanding why is the
lesson. Auto-instrumentation works by monkey-patching an in-process SDK *client*. But
Interchange's generation doesn't go through one: the RAG path calls an engine dict, and
the agent path shells out to `claude -p` (Lesson 03). There is no client object in our
process to patch, so auto-instrumentation would silently produce empty traces.

So we split by path, honestly:

- **RAG path → manual spans.** A small guarded seam, `observability.span(name, **attrs)`,
  wraps each stage: `retrieve` (with `retrieve.dense` / `.bm25` / `.rrf` children),
  `generate`, `guard_input`, `guard_output`. It's a real span when tracing is on and a
  **null context** otherwise — so callers wrap stages unconditionally and pay nothing by
  default.
- **Agent path → Claude Code's own OTel.** Claude Code (what `--agent` runs) has built-in
  OpenTelemetry. We just merge a few env vars into the subprocess
  (`claude_code_trace_env()`), and it emits its native `claude_code.interaction →
  llm_request → tool` tree and propagates `traceparent` into our MCP server — no
  hand-rolled cross-process plumbing.

Both export over OTLP to a local [Arize Phoenix](https://github.com/Arize-ai/phoenix)
($0, self-hosted). It's off unless `INTERCHANGE_TRACING=1`, and its dependencies live in
a separate `requirements-trace.txt` — deliberately **out** of the test env, so the
offline `pre-push` gate never installs them and stays green either way.

## The payoff: tracing caught a real bug

The first time we ran `--agent` with tracing on, the trace showed Claude Code calling
tools — but they were the *host's* connectors (Drive, Gmail), not our `search_docs` /
`lookup_segment`, and the answer came back **ungrounded**. The trace made visible what
the audit row hid: our MCP server wasn't connecting.

The cause: `mcp_server.py` imported `MCPServer`, but the installed `mcp` SDK exposes
`FastMCP`. The import crashed on startup, `claude -p` silently fell back to other
connectors, and the agent answered from the wrong tools. This had been latent since
Lesson 03 — whose ADR honestly warned the live round-trip "only proves out on a real
run." A one-line fix (`MCPServer → FastMCP`) plus a regression test (import
`mcp_server`) closed it. **That's the point of observability**: it doesn't just chart the
happy path, it surfaces the failures your green tests never exercised.

## Map to the framework

| Dimension | What this lesson adds |
|---|---|
| **Observability** | opt-in OpenTelemetry tracing of the RAG + agent paths, viewed in a local Phoenix; per-stage timing + nested agent/tool visibility |
| **Reliability** | the trace exposed (and we fixed) a silent agent-tooling failure the audit row couldn't show |
| **Cost & Efficiency** | tracing is $0/local and off by default; its deps never touch the fast test gate |

## Try it yourself

```bash
pip install -r requirements-trace.txt          # optional; only for viewing traces
phoenix serve                                  # in one terminal → http://localhost:6006
INTERCHANGE_TRACING=1 python interchange.py --ask "what is an 824?" --engine claude-code
INTERCHANGE_TRACING=1 python interchange.py --agent --ask "what is a 214?"
```

Open the **default** project in Phoenix and click a trace: the RAG tree
(`retrieve → dense/bm25/rrf → generate → guardrails`) and the agent's native
`claude_code.*` tool tree. With the flag unset, everything runs identically and no trace
deps are needed.

## What's honest about this

The semantic conventions this rides on (OTel GenAI, OpenInference) are still
**pre-stable** in 2026 — an emerging standard, not a settled one. Claude Code's trace
*export* is a **beta** feature (metrics and logs are GA). And on a two-doc corpus the
trace tree is short — the value is the *pattern* (and the bug it caught), not the volume.
As with every lesson here: the capability is real, and its edges are stated plainly.
```
