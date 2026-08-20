# ADR-0002: Orchestration for the agentic runtime

- **Status:** Accepted · **superseded in part by [ADR-0003](0003-agent-generation-auth.md)**
  (the live `--agent` runtime moves to the Claude Agent SDK for $0 Max-subscription
  cost; the hand-rolled loop below is retained as Lesson 02 reference code)
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
Phase 1 turns the MVP (retrieve → generate, one shot) into an **agentic knowledge
runtime**: the model decides *whether* to retrieve, can call a domain tool (e.g.
"look up an X12 segment definition"), and can **iterate** — retrieve, reason,
check "do I have enough?", answer or retrieve again. That loop needs an
orchestration approach.

Forces at play:
- **Legibility / teaching.** The runtime is a showcase *and* a teaching aid. The
  control flow should be readable line-by-line, not hidden behind framework magic.
- **Enterprise-readiness.** We need clean seams for retries/timeouts, tracing, and
  state — the reliability/observability dimensions.
- **Skill signal.** LangGraph is a named target skill in the roles this portfolio
  aims at; demonstrating it has real résumé value.
- **Author's strength.** 20 years of event-driven, state-machine architecture —
  LangGraph models agents as *stateful graphs*, which maps directly to that mental
  model.
- **Solo / evenings-and-weekends.** Fewer moving parts ships faster.

## Options considered
1. **Hand-rolled tool-use loop on the Anthropic SDK.** Native tool calling +
   a small `while` loop we own. *Pros:* zero framework deps, every step visible
   and teachable, teaches the agent loop from first principles, trivial to trace
   (we write the log lines). *Cons:* we implement state/retries/branching
   ourselves; doesn't earn the "LangGraph" keyword.
2. **LangGraph.** Agents as stateful graphs (nodes/edges/state), with built-in
   state, checkpointing, streaming, and LangSmith tracing. *Pros:* maps to the
   author's state-machine background, gives production scaffolding, demonstrates a
   demanded skill. *Cons:* heavier dependency + abstraction to learn; some control
   flow moves into the framework, which cuts against line-by-line legibility.
3. **LlamaIndex Workflows / Pydantic AI.** Lighter agent abstractions. *Pros:*
   modern, typed (Pydantic AI). *Cons:* less JD-relevant than LangGraph; still a
   framework to learn.
4. **CrewAI / AutoGen (multi-agent).** *Cons:* overkill for a single-agent
   retrieval loop; deferred until there's a genuine multi-agent need.

## Decision (proposed — open for iteration)
**Iteration 1: build the loop by hand on the Anthropic SDK.** Learn and expose the
agent loop from first principles while it's small (one tool, linear iterate-until-
enough). **Then file a superseding ADR to adopt LangGraph** at the point branching
state / checkpointing genuinely earns its keep (Phase 1b — a second tool, or
parallel retrieval paths).

Rationale: it honors "learn the primitive before the framework," keeps the runtime
legible as a teaching artifact, and still lands LangGraph — with a *real reason*
for it, which is itself the better lesson. Net result over Phase 1: two teachable
ADRs and two lessons (native loop → LangGraph), not one framework adopted on faith.

## Consequences
- Iteration 1 ships fast with no new heavy deps; the loop is fully traceable and
  teachable.
- We defer the "LangGraph" skill signal by one iteration (accepted trade-off).
- We commit to writing ADR-0007 (adopt LangGraph) when branching state appears —
  and to porting the hand-rolled loop, which is a known, bounded cost.

---
> **Resolved 2026-08-19:** accepted as written — native-loop-first. LangGraph is
> deferred to a future superseding ADR, to be filed when branching state / a
> second tool genuinely earns the framework.
