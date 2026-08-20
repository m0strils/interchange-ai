# ADR-0003: Generation auth for the agent runtime — metered API vs Max subscription

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
`--agent` (`agent.py`, per [ADR-0002](0002-orchestration-framework.md)) runs a
hand-rolled Messages API tool-use loop, which needs `ANTHROPIC_API_KEY` and bills
metered API usage. We want to run it on a **Claude Max subscription** (no marginal
cost) instead.

Two facts constrain the decision:

1. **A Max/Pro subscription does not authorize raw Messages API calls.** It
   authorizes *Claude Code product* usage — the `claude` CLI and the **Claude Agent
   SDK** (Claude Code as a library). Metered API tool-use is a separate billing
   surface. So the raw tool-loop **cannot** run on the subscription, unchanged.
2. **Every subscription route owns the loop.** The Claude Agent SDK (and Managed
   Agents) run the agent loop *themselves* and ship their own tools. That collides
   head-on with ADR-0002, which chose a hand-rolled loop *specifically* so the
   control flow stays legible and teachable.

The uncomfortable core: **"runs on Max" and "hand-rolled, legible loop" cannot
both be true for the same runtime.** One has to give.

(Note: the RAG path already runs on the subscription today via
`--engine claude-code`, which shells out to `claude -p`. That covers everyday
cost-free iteration. This ADR is only about the *agentic* loop.)

## Options considered
1. **Keep the raw Messages API tool-loop (status quo).** Metered; needs an API
   key. *Pros:* honors ADR-0002 (hand-rolled, every step visible); **exact
   token/cost telemetry**, which is itself a Governance/Cost teaching asset — the
   audit log's real numbers are part of the demo. *Cons:* the agent loop costs
   metered money; doesn't use the Max plan.
2. **Port `--agent` to the Claude Agent SDK.** *Pros:* runs on the Max
   subscription ($0 marginal). *Cons:* the SDK owns the loop — this **reverses
   ADR-0002's rationale** for `--agent`; telemetry drops to *estimated*; heavier,
   different dependency and tool model. The hand-rolled loop survives only as
   Lesson 02's code, not the live runtime.
3. **Keep both, engine-selectable.** Raw loop stays the canonical `--agent`
   (teaching + exact telemetry); add an Agent-SDK-backed mode for $0 runs. *Pros:*
   the *contrast* between them is itself a strong lesson (metered-with-telemetry
   vs subscription-with-estimates). *Cons:* two agent runtimes to maintain — real
   overhead for a solo project.

## Decision
**Option 2 — port the live `--agent` runtime onto the Claude Agent SDK so it runs
on the Max subscription at $0 marginal cost.** The deciding priority is *no metered
API spend*. This **supersedes ADR-0002 for the live runtime**: the Agent SDK owns
the loop. The hand-rolled loop is not deleted — it is preserved as Lesson 02's
reference code ("here's what the framework does under the hood"), the more
valuable teaching role for it now.

Tool delivery: the Agent SDK takes custom tools via an (in-process) MCP server, so
this decision **pulls forward the MCP decision** (was backlog ADR-0004) — we expose
`search_docs` + `lookup_segment` as an MCP tool server and let the subscription
runtime drive them.

## Consequences
- `--agent` runs on the Max subscription — **no API key, $0 marginal cost.**
- **ADR-0002 is superseded (in part)** for the live runtime; the loop is the Agent
  SDK's, not hand-rolled. Lesson 02 keeps the hand-rolled loop as reference.
- **Telemetry becomes estimated**, not exact — the audit log records estimated
  tokens and `$0` cost, matching the existing `claude-code` engine convention.
- New dependency: the Claude Agent SDK + an MCP tool server for our two tools.
- The hand-rolled `agent.py` loop remains as teaching code and as an optional
  `--engine api` escape hatch if an API key is ever present.

---
> **Resolved 2026-08-19:** Option 2 (subscription-first) — the project will not
> fund metered API. Supersedes ADR-0002 for the live `--agent` runtime; the
> hand-rolled loop survives as Lesson 02 reference.

## Amendment (2026-08-19) — mechanism corrected before implementation
Pulling the current Agent SDK docs surfaced a material fact: the **Claude Agent
SDK does not officially support claude.ai/subscription login** — its documented
auth is an API key ([Agent SDK Overview](https://code.claude.com/docs/en/agent-sdk/overview.md)).
An unsupported fallback (SDK reuses Claude Code's cached token when no key is set)
exists but is fragile. That caveat targets *third parties reselling claude.ai
login in a product* — not a user running their own tools through their own Claude
Code.

**Corrected mechanism (decision unchanged):** implement the subscription runtime
as **headless Claude Code (`claude -p`) driven with an in-process MCP tool
server** exposing `search_docs` + `lookup_segment`. This is the same subscription
product `--engine claude-code` already uses (ADR context), now extended with
tools — genuine Max-plan execution, no API key, and normal first-party usage
(not the unsupported redistribution case).

Alternative kept on record: **Agent SDK + API key** (officially supported, exact-ish
usage) — rejected here only because it is API-funded, which the decision excludes.
If exact billing telemetry is ever wanted, that's the superseding path.
