# ADR-0011: Agentic orchestration trade-offs — Interchange's hand-rolled loop vs. Strands' model-driven approach

- **Status:** Proposed
- **Date:** 2026-09-05
- **Deciders:** Jeff Lynch

## Context

Interchange was designed with an **explicit hand-rolled orchestration loop** (ADR-0002, ADR-0003)
to balance two forces: legibility for teaching and the honest governance seams needed in a
regulated domain. The loop is written in plain code: retrieve, generate, check, iterate or
answer — every decision point visible and traceable.

Discovery of [Strands Agents](https://strandsagents.com/), an open-source production framework
from AWS, raises the question: *what trade-offs did Interchange make, and where does each
approach win?* Strands takes the opposite philosophy — **model-driven orchestration** (prompt
+ tools, LLM plans autonomously) — and brings 117 integrations, built-in multi-agent patterns,
and production-scale observability baked in. This ADR compares the two honestly, documenting
when and why each approach fits.

The comparison directly informs Interchange's positioning: it's not that Interchange *should*
adopt Strands, but that understanding both deepens the teaching value and clarifies the
enterprise-readiness framework (ADR's eight dimensions: security, governance, evaluation,
observability, reliability, cost, deployment, context/memory).

## Options considered

### Option 1: Interchange as-is; document Strands in a separate research post
Keep Interchange's hand-rolled orchestration unchanged. Treat Strands as external reference
material in a blog post or `TEACHING.md` remark.

**Pros:**
- No change to working code; Interchange remains focused and teachable as-is.
- Avoids scope creep (this ADR exists to decide, not to implement).

**Cons:**
- The comparison stays implicit — readers don't see *why* Interchange chose an explicit loop
  or *where* Strands' model-driven approach genuinely wins (beyond "simpler code").
- Misses the teaching moment: the hard trade-offs (legibility vs. model autonomy, explicit
  state vs. implicit planning, audit-first vs. integration-first) are the real lesson.

### Option 2: Adopt Strands wholesale
Rewrite Interchange to use Strands' SDK, tools, and multi-agent orchestration.

**Pros:**
- Immediate access to 117 integrations, memory stores, observability plugins.
- Strands' production patterns (deployment, multi-agent coordination) are battle-tested.
- Positions Interchange as "modern agentic architecture" rather than "hand-rolled learning project."

**Cons:**
- Loses the teaching seam. Strands *hides* the agent loop behind framework abstractions —
  legibility is sacrificed for concision. The "learn the primitive before the framework"
  philosophy (from ADR-0002) evaporates.
- Governance and audit become *secondary*, not the spine (ADR-0003: guardrails + audit are
  first-class). Strands has `agentcore-tool-search` and `agent-control` plugins for policy,
  but they're optional features, not the architecture.
- Contradicts Interchange's honest-claims rule: the project is a *learning-by-building*
  portfolio; a rewrite to use another framework obscures that.

### Option 3: Document the comparison in ADR-0011; reference Strands patterns where they deepen understanding
Write this ADR to honestly compare orchestration philosophies. Document where Interchange's
hand-rolled loop pays off (teaching, audit-first governance, explicit state flow) and where
Strands excels (scale, integrations, model autonomy, deployment patterns). Use Strands as a
reference for future architectural choices (e.g., multi-agent patterns when Interchange scales,
observability pluggability like Strands' Phoenix integration).

**Pros:**
- Teaching value doubles: readers see *two* valid agentic architectures and their trade-offs.
- Clarifies Interchange's positioning: not "the best agent framework" but "an honest,
  audit-first learning project that teaches enterprise agentic patterns."
- Creates a concrete ADR trail showing the decision-making: "we saw Strands; here's why we
  kept our approach; here's what we learned from them."
- Sets up future learning (ADR-0012+) to adopt Strands *patterns* (tools, integrations) where
  they fit Interchange's goals.

**Cons:**
- Requires discipline to keep this ADR honest and not defensive. The temptation is to rationalize
  Interchange's choices rather than admit where Strands does better.

## Decision

**Adopt Option 3.** Write ADR-0011 to document the orchestration trade-offs honestly.
Keep Interchange's hand-rolled loop and audit-first architecture as-is, but reference Strands'
strengths throughout this project's documentation. Use this ADR as the first step in a
"reference architecture" teaching series (compare Interchange to Strands, LangGraph, LlamaIndex
as they apply to different enterprise scenarios).

Rationale: Interchange's value is not "we built the best agent framework." It's "we built an
agentic knowledge runtime the way a regulated enterprise has to, and we're teaching how every
decision (explicit loop, audit-first, state machines, evaluation gates) maps to enterprise
readiness." Strands is a *foil* that makes this story clearer, not a threat.

## Consequences

### Immediate
- This ADR becomes a teaching artifact itself: readers see the decision-making process, including
  the option Interchange *didn't* choose and why.
- Interchange's positioning shifts slightly: "not the only way, but the honest way to reason about
  agentic architectures in regulated domains."

### Future architecture decisions
- When Interchange needs multi-agent coordination (Phase 2+), the ADR for adopting a multi-agent
  pattern (Graph, Swarm, Workflow) will reference Strands' patterns as proven ground.
- If Interchange later adopts LangGraph (still pending ADR-0007 after hand-rolled loop matures),
  this ADR becomes the comparison point: "we chose X for teaching; if we scale, we move to Y."
- Observability patterns: Strands' integration ecosystem (AgentCore Memory, s3-vectors, Phoenix
  tracing) is reference material for ADR-0009 follow-ons.

### Teaching & positioning
- The portfolio becomes *explicitly comparative*: "here's how Interchange approaches the eight
  dimensions; here's how Strands does it; here's what each enterprise context demands."
- This ADR is the first "Lessons learned" document, not just a "we chose this" document.

### Honest caveats
- **This ADR is not a feature comparison.** Strands has 28 model providers; Interchange supports
  Claude via subscription and API. That's not a flaw in Interchange — it's a constraint from the
  $0 cost model (ADR-0003/0004). The ADR must not gloss over this.
- **Strands is actively developed and moving.** This ADR captures Strands as of September 2026;
  117 integrations, Bedrock-first, OTel-native. If Strands pivots, this document says so rather
  than claiming stability we don't have.
- **The "audit-first" spine of Interchange is not Strands' design goal.** Strands optimizes for
  deployment, integration, and model autonomy. It has governance *features*, not governance
  *architecture*. The ADR acknowledges this: different problems, different solutions.

## Verified (research, 2026-09-05)
- Reviewed Strands SDK TypeScript quickstart; 117 integrations catalog; AWS blog on architecture
  and observability patterns.
- Confirmed: Strands' model-driven approach (prompt + tools, LLM plans) vs. Interchange's
  explicit state machine (retrieve → generate → check → iterate or answer).
- Confirmed: Strands' observability (built-in OTel + OpenInference, Phoenix integration) and
  Interchange's dual-layer approach (audit.jsonl + Phoenix tracing, both independent).
- Confirmed: the 8-dimension framework maps to both architectures differently:
  - **Security/Governance:** Interchange spine; Strands plugin (agentcore-tool-search, agent-control)
  - **Observability:** Strands native; Interchange explicit + Phoenix opt-in
  - **Deployment:** Strands optimized (monolith/API/microservices); Interchange subprocess ($0 model)
  - **Cost:** Interchange $0 on subscription; Strands model-provider-agnostic
  - **Evaluation:** Strands has AgentCore RL toolkit; Interchange has ADR-0008 eval gate

## Next steps
- [ ] Finalize ADR-0011 as a teaching artifact (not just a decision).
- [ ] Add a "Strands as reference" section to `TEACHING.md` with links to specific patterns.
- [ ] When multi-agent needs arise (Phase 2), write ADR-0012 on adopting Strands' Graph/Swarm
      patterns, explicitly tied back to this comparison.
