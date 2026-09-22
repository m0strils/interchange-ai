# Lesson 07 — Handing off to another agent over A2A

Every earlier lesson answered a question *inside* this process: a user (or Claude
Code) asks, Interchange retrieves, grounds, and answers. This lesson adds a
different shape of caller: another agent, possibly running inside someone else's
platform, that needs to discover what Interchange can do, prove who it's talking
to, and hand off a task rather than call a function. That's what the
Agent-to-Agent (A2A) protocol is for. The decision is
[ADR-0013](../docs/adr/0013-a2a-agent-interop.md). Here's the *why*.

## What A2A adds over a tool call

MCP (Lesson 03) is agent-to-*tool*: a schema, a function name, arguments in,
a result out. It assumes the caller already trusts the process it's talking to
and just wants a well-typed function. A2A is agent-to-*agent*: the caller may be
a different vendor's orchestration platform, running agents it didn't write,
and before it sends anything it needs to answer three questions a tool call
never asks: what can this agent do, is this really that agent, and how do I
track a task that might take more than one round trip. A2A standardizes all
three: a published **Agent Card**, a **signed** identity for that card, and a
**task lifecycle** with streaming events instead of a single blocking call.

## Anatomy of the Agent Card

The Agent Card is what a caller fetches first, at a well-known, unauthenticated
endpoint — discovery has to work before anyone has a key. It describes the
agent's name, what it can do, and how to reach it: which interfaces it speaks
and at what URL. Interchange's card lists **two interfaces** — more on that
below — and nothing it can't actually do. An honest card is part of the same
"don't overclaim" rule the rest of this repo follows; a card advertising a
capability that doesn't exist is a lie a machine will act on.

## Why sign it, and how verification fails

A card fetched over plain HTTP is just a claim. Anyone who can intercept or
spoof the response can hand a caller a fake card pointing at a fake agent.
Interchange signs its card with a JWS over a JCS-canonicalized representation
of the card (A2A spec §8.4) using ES256, and pins the signing key's `kid` to
`interchange-2026-09`. The `requester` client verifies with
`algorithms=["ES256"]` against that pinned key — nothing else. Three ways
verification is designed to fail, on purpose:

- **Tampered card** — the JCS canonicalization changes, the signature no
  longer matches, verification rejects it.
- **Unsigned card** — no JWS at all, rejected outright.
- **Unknown `kid`** — a card signed with a key we didn't pin, rejected.

One thing the verifier deliberately does *not* do: follow a `jku` header to
fetch a key from a URL the card itself supplies. That would let whoever
controls the card also control the key that verifies it — trust would prove
nothing. Key material comes only from what we ship.

## 1.0 vs 0.3 interfaces

A2A 1.0 is the current spec. But as of this writing, IBM watsonx Orchestrate
registers *external* A2A agents against `external_chat/A2A/0.3.0` — the
previous interface shape. An agent that speaks only 1.0 can't be registered
into Orchestrate's external-agent flow today. So the card lists two interface
entries: native 1.0 JSON-RPC, and a 0.3-compat entry served via the a2a-sdk's
compat support. Same agent, same guardrails, two ways in — a real illustration
of what "the field hasn't converged yet" looks like in practice, not just a
sentence about it.

## Task lifecycle and streaming

A2A tasks move through states — submitted, working, completed or failed —
rather than returning a single opaque blob. Interchange streams task events as
they happen instead of making the caller poll. For a one-shot knowledge
question this looks almost like a normal request/response; the payoff shows up
when a task takes longer or when a caller wants to show progress instead of a
spinner.

## The OWASP mapping

This lesson maps to three categories from the OWASP Top 10 for Agentic
Applications (2026):

| Category | What covers it here |
|---|---|
| **ASI01 — goal hijack** | the input guardrail (prompt-injection heuristics, OWASP LLM01) runs unchanged on the A2A path — no lighter-weight path for an agent caller |
| **ASI03 — identity and privilege abuse** | signed card, pinned `kid`, an API key checked per caller, a declared tier per agent, caller recorded in the audit log |
| **ASI07 — insecure inter-agent communication** | JCS+JWS card integrity, rejected tampered/unsigned/unknown-`kid` cards, TLS transport, no remote key fetch |

The API key protects the JSON-RPC task path; the Agent Card endpoint stays open
because discovery has to work before a caller has credentials.

## Run it yourself

```bash
make a2a-demo PROFILE=hotel      # or PROFILE=rail
pytest -q tests/test_a2a.py
```

`DEMO_PROFILE=rail|hotel` points the same agent code at either this repo's
existing EDI/rail corpus or a small, self-authored hotel-policy corpus
(`hotel-demo/`), to show the knowledge-agent shape isn't rail-specific — the
profile is data (`a2a_agent/profiles.yaml`), not new code.

## What this does not prove

This is a personal build, run against a single deployed instance. It does not
prove multi-tenant scale, key rotation (the `kid` is pinned manually, not
rotated automatically), or production traffic. The watsonx Orchestrate
registration targets a 30-day trial tenant, not a production account — it
demonstrates that a real enterprise orchestration platform *can* discover and
call this agent, not that it does so today at any scale. The hotel corpus is
self-authored demo content, not sourced from any real property. Push
notifications, gRPC transport, and any cross-agent router are explicitly out
of scope this sprint (ADR-0013).
