# ADR-0013: Agent-to-agent interop over A2A with signed Agent Cards

- **Status:** Accepted
- **Date:** 2026-09-21
- **Deciders:** Jeff Lynch

## Context
Interchange already talks to *tools* over MCP (`mcp_server.py`, stdio, tool schemas —
ADR-0003). It has never talked to another *agent*. An enterprise platform (IBM watsonx
Orchestrate, and others) that wants to route a question to Interchange isn't a tool
caller; it's a peer agent that needs to discover what Interchange can do, establish who
it's talking to, and hand off a task it can track through completion — not just get a
function's return value back.

A plain REST call could move the same bytes, but it would have to reinvent, by hand and
undocumented, everything the Agent2Agent (A2A) protocol already standardizes: a
published capability description, a signed identity for that description, a task
lifecycle (submitted → working → completed/failed), and streaming progress events. A2A
1.0 is the current spec for exactly this. The open question was which version of it to
speak, because the field is not settled: A2A 1.0 is the current spec, but as of this
writing IBM watsonx Orchestrate registers *external* A2A agents against
`external_chat/A2A/0.3.0` — the previous interface shape, not 1.0. An agent that speaks
only 1.0 cannot be registered into Orchestrate today.

The MCP/A2A boundary also needed to be explicit, for the teaching layer as much as the
code: MCP is agent-to-tool (this repo's `search_docs`/`lookup_segment` over stdio); A2A
is agent-to-agent (HTTP, an Agent Card, task lifecycle, its own identity story). Neither
replaces the other; this ADR adds the second without touching the first.

Constraints carried over from earlier ADRs still apply: honest telemetry (ADR-0004),
guardrails and audit as a layer reused on every path (`CLAUDE.md`), and no proprietary
content — the hotel profile corpus is self-authored demo content, not a real property's
policies.

## Options considered
1. **Plain REST endpoint** — a `/ask` POST that takes a question and returns an answer.
   Simplest to build; but no standard capability discovery, no standard identity
   proof for the caller to check, no task lifecycle or streaming, and every enterprise
   caller would need bespoke glue instead of a spec-compliant client.
2. **MCP only, exposed further out** — let another agent call our tools directly over
   MCP instead of adding A2A. Rejected: MCP's contract is tool schemas, not agent
   identity or task lifecycle; stretching it to be the inter-agent surface blurs a
   distinction worth keeping sharp for the lesson and for real deployments where a
   platform team draws exactly this line.
3. **A2A 1.0 only** — spec-current, but unregistrable in watsonx Orchestrate's current
   external-agent flow (`external_chat/A2A/0.3.0`), which would make the enterprise
   platform integration part of the demo undemonstrable.
4. **A2A 1.0 with a 0.3 compat interface — chosen.** Serve the current 1.0 JSON-RPC
   interface as the primary surface, and add a second interface entry on the Agent Card
   for 0.3-shaped calls, using the a2a-sdk's compat support, so Orchestrate's
   `external_chat/A2A/0.3.0` registration flow can discover and call the same agent.

## Decision
Build a new `a2a_agent/` package (not `a2a/`, which would shadow the `a2a-sdk` import).
It contains:

- **A signed Agent Card.** The card is JWS-signed with ES256 over a JCS-canonicalized
  (RFC 8785) representation of the card, per A2A spec §8.4. The signing key's `kid` is
  pinned to `interchange-2026-09`; the client verifies with `algorithms=["ES256"]` and
  the pinned key, and explicitly refuses to follow a `jku` remote-key-fetch header on
  the card — key material comes only from what we ship, never from a URL the card
  itself points at.
- **Two interfaces on the card**: the native A2A 1.0 JSON-RPC interface, and a second
  entry for the 0.3 compat shape, so both a 1.0-speaking client and watsonx
  Orchestrate's 0.3 external-agent flow can use the same deployed agent.
- **An API key on the JSON-RPC task path.** The Agent Card endpoint itself stays open —
  discovery has to work before a caller has a key — but every task submission requires
  a valid API key, checked per caller.
- **A `caller` field in the audit log.** Every A2A task is attributed to the identity
  that called it, alongside the existing audit fields (model, sources, cost, grounded).
- **A `requester` client agent** (`a2a_agent/requester.py` and friends) that
  demonstrates the other side: it fetches and verifies the Agent Card before sending a
  task, and streams task events to the console.
- **A `DEMO_PROFILE=rail|hotel` switch** so the same agent code answers either from the
  existing EDI/rail corpus or from a self-authored hotel demo corpus
  (`a2a_agent/profiles.yaml`), proving the knowledge-agent shape isn't rail-specific.
- **Streaming task events on.** Task state changes stream to the client rather than
  requiring polling.
- **Per-agent tier declarations** for the agent-factory-kit (`agents/*/instance.yaml`):
  `interchange-knowledge` is `tool-using-read-only`, `requester` is `read-only`. These
  are declarations for later certification tooling, not a claim that certification has
  run.
- **The existing input guardrail and output grounding check run unchanged on the A2A
  path.** A2A is a new transport into the same guarded core, not a new code path that
  bypasses it.

**Deferred, explicitly:** push notifications, gRPC transport, and any cross-agent
router are out of scope this sprint. The card advertises exactly the capabilities that
exist.

### OWASP Agentic Top 10 (2026) mapping
- **ASI01 — goal hijack:** the input guardrail (prompt-injection heuristics, OWASP
  LLM01) runs unchanged on every A2A task; A2A does not get a lighter-weight path.
- **ASI03 — identity and privilege abuse:** signed Agent Card with a pinned `kid`, an
  API key checked per caller, a declared tier per agent, and the caller recorded in the
  audit log — the same request is traceable to who asked for it.
- **ASI07 — insecure inter-agent communication:** JCS+JWS gives the card integrity;
  tests cover tampered, unsigned, and unknown-`kid` cards being rejected; transport is
  TLS; no remote key fetch is ever followed.

## Consequences
**Positive**
- Interchange gains a second, standards-based integration surface (agent-to-agent)
  distinct from its existing tool surface (agent-to-tool via MCP), with the boundary
  documented rather than blurred.
- The 0.3 compat interface makes the agent registrable into a real enterprise
  orchestration platform (watsonx Orchestrate) today, not only once it adopts 1.0.
- Identity and privilege controls (signed card, pinned key, per-caller API key,
  per-agent tier, caller-in-audit) map directly onto three ASI categories, giving the
  teaching layer (lesson 07) a concrete worked example instead of an abstract one.
- The `DEMO_PROFILE` switch demonstrates the knowledge agent generalizes past rail/EDI
  without writing new agent code, reinforcing the industry-agnostic positioning.

**Negative**
- Two interfaces on one card is more surface to keep in sync than one; a future 1.0-only
  world would let the 0.3 compat entry be dropped.
- Pinning a single `kid` means key rotation is a manual, out-of-band step for now — no
  rotation automation exists yet.
- Streaming task events add a bit of client-side complexity (event handling instead of
  a single response) for a demo whose task usually completes in one turn anyway.

**Honest limits**
- This is a personal build, not a fielded multi-tenant service.
- The watsonx Orchestrate registration targets a 30-day trial tenant, not a production
  or paid account.
- The hotel corpus is self-authored demo content for this repo; it is not any real
  hotel's actual policy, and is not a data-sourcing claim about any brand.
- No push notifications, no gRPC transport, and no cross-agent router ship this sprint.

**Deviations found during implementation**
- none recorded yet
