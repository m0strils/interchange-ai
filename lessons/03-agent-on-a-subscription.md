# Lesson 03 — Running the agent on a subscription (API vs. Max, and MCP)

Lesson 02 built a hand-rolled agent loop on the metered Messages API. It works,
and its token/cost telemetry is exact — but every run costs money. This lesson
answers a real question a builder actually asks: *can I run the agent on my Claude
subscription instead of paying per call?*

The answer is yes — but it forces an architectural decision, and the decision is
worth more than the code. It's recorded in
[ADR-0003](../docs/adr/0003-agent-generation-auth.md); read it for the full
reasoning. Here's the short version and the *why*.

## The constraint that drives everything

A Claude **subscription** (Pro/Max) authorizes the **Claude Code product** — the
`claude` CLI and the Agent SDK. It does **not** authorize raw Messages API calls;
that's a separate, metered billing surface. So the hand-rolled API loop from
Lesson 02 *cannot* run on the subscription, full stop.

And every subscription-capable route runs the agent loop *itself*. So you can't
have both "hand-rolled, fully legible loop" **and** "runs on my subscription."
One gives. We kept the hand-rolled loop as *this lesson's reference* and moved the
**live** `--agent` runtime onto the subscription.

## The mechanism: headless Claude Code + an MCP tool server

The runtime is `claude -p` (headless Claude Code, which runs on your subscription)
driven with our two tools exposed over the **Model Context Protocol (MCP)**:

```
your question ──> claude -p (subscription)
                     │  discovers tools via --mcp-config
                     ▼
              mcp_server.py  ──►  search_docs / lookup_segment
                     │
              answer (grounded, cited) ──> output guardrail ──> audit
```

- **`mcp_server.py`** — a tiny stdio MCP server (mcp 2.x `MCPServer`) exposing `search_docs`
  and `lookup_segment`. The tool logic is *reused verbatim* from Lesson 02, so the
  tools behave identically on either runtime.
- **`agent_sub.py`** — runs `claude -p` with that server, restricted to **only**
  those two tools (`--allowedTools`), and re-applies the same input guardrail,
  grounding check, and audit log.

Two production details worth noticing:
- **Least-privilege tools.** We allow-list exactly two MCP tools — not a blanket
  "allow everything." That's the Security dimension: a subscription agent with
  bash/file access would be a liability; scoped tools are the safe default.
- **MCP is the integration seam.** Exposing tools over MCP (rather than as
  in-process Python) is what lets a *different* runtime — Claude Code, or later a
  different host entirely — use the same tools unchanged. That decoupling is the
  point of ADR-0004.

## The honest trade

| | API loop (Lesson 02) | Subscription agent (this lesson) |
|---|---|---|
| Cost | metered per call | **$0 marginal** (your subscription) |
| Telemetry | **exact** tokens/cost | **measured** tokens + a shadow cost, `$0` marginal (ADR-0004) |
| Loop | hand-rolled, fully visible | Claude Code's, driven via MCP |
| Auth | API key | your Claude login |

The audit log still records every run — it records **measured** tokens and a
shadow cost with `$0` marginal for this engine (ADR-0004), matching the existing
`--engine claude-code` RAG path.
That honesty (an estimate labeled as an estimate) is itself the lesson: **know
which of your numbers are measured and which are inferred.**

## Map to the framework

| Dimension | What this lesson adds |
|---|---|
| Cost | zero marginal cost — run the agent freely while learning |
| Security | least-privilege MCP tool allow-list (no bash/file access) |
| Context & Memory | tools delivered over MCP — reusable across runtimes |
| Governance | audit spans the subscription run; estimates labeled as estimates |

## Try it yourself

Prereqs: the `claude` CLI logged into your Max/Pro plan, and `pip install mcp`.

```bash
python interchange.py --reindex                      # build the index
python interchange.py --agent --explain --ask "What is a 214 and which segment starts it?"
```

`--agent` now runs on your subscription — no API key. `--explain` narrates the
guardrail, the launch, and the grounding verdict. (First run may pause a few
seconds while the MCP server connects.)

## What's honest about this

The `claude -p` + MCP wiring is built to the documented CLI, but the live
round-trip — does Claude Code actually invoke the MCP tools on your machine —
only proves out on a real run with your login. If a tool isn't auto-allowed,
the `--allowedTools` name format (`mcp__interchange__<tool>`) is the first thing
to check. The hand-rolled loop in `agent.py` remains your exact-telemetry
fallback whenever an API key *is* present.
