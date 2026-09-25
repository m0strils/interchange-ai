# Teaching — learn to build a governed knowledge runtime, one lesson at a time

Interchange doubles as a course. The idea: **"RAG is dead" is only true of naive,
chunk-and-pray RAG.** What's durable is the *knowledge runtime* — retrieval +
verification + reasoning + access-control + audit as one integrated system. This
repo is a small, honest, readable reference build of that pattern, and each build
phase becomes a numbered lesson.

Every lesson follows the same shape: **what we add · why an enterprise needs it ·
which OWASP LLM Top 10 / NIST AI RMF clause it maps to.** Nothing is claimed as
done that isn't — lessons teach the controls that exist and name the ones that
don't yet (see the [README scorecard](README.md#enterprise-readiness-scorecard)).

## The lessons so far

- **[Lesson 01 — The MVP: a grounded, audited RAG loop](lessons/01-mvp.md)** —
  the `retrieve → ground → audit` core: input guardrail + instruction/data
  separation, the grounding/citation check (why an honest "I don't know" beats a
  confident hallucination), and the per-request audit + cost log. Run it with
  `--explain` and watch each stage narrate itself.
- **[Lesson 02 — From one-shot RAG to an agentic loop](lessons/02-agentic-loop.md)** —
  the model *drives* retrieval and a segment-lookup tool, iterating until it has
  enough context — a hand-rolled loop on the metered API, with exact telemetry.
- **[Lesson 03 — Running the agent on a subscription (API vs. Max, and MCP)](lessons/03-agent-on-a-subscription.md)** —
  move the live agent onto your Claude subscription via headless `claude -p` + an
  MCP tool server; least-privilege tools, $0 marginal cost, estimates labeled as
  estimates.
- **[Lesson 04 — Hybrid retrieval, and how to *prove* it helped](lessons/04-hybrid-retrieval.md)** —
  upgrade retrieval from dense-only to **hybrid** (BM25 + dense, fused with RRF) +
  structure-aware chunking, then build a golden **hit@k** eval that *measures* the
  gain (dense 93% → hybrid 100%) instead of asserting it.
- **[Lesson 05 — Evaluating the answer, and the metric that lied](lessons/05-evaluating-the-answer.md)** —
  measure answer quality where it can actually fail (refusal- and answer-correctness),
  why faithfulness is **circular** on a from-context RAG, and how verifying against real
  output caught a refusal metric mis-scoring a good refusal — corrected before shipping.
- **[Lesson 06 — Observability: two layers, and the bug tracing caught](lessons/06-observability-tracing.md)** —
  add opt-in OpenTelemetry tracing (manual spans for RAG, Claude Code's native OTel for
  the agent) to a local Phoenix atop the always-on audit log; why auto-instrumentation
  finds nothing to patch here, and how the first traced agent run surfaced a latent
  MCP-server bug.
- **[Lesson 07 — Handing off to another agent over A2A](lessons/07-a2a-handoff.md)** —
  add an agent-to-agent surface (signed Agent Card, JWS/JCS integrity, pinned key,
  task lifecycle with streaming) alongside the existing agent-to-tool (MCP) surface,
  serving both the current A2A 1.0 interface and a 0.3 compat interface so an
  enterprise orchestration platform can register the agent today; mapped to
  OWASP Agentic ASI01/ASI03/ASI07.
- **[Lesson 08 — A browser workbench that shows its scores honestly](lessons/08-browser-workbench.md)** —
  add a same-origin `/ui` over the same guarded pipeline: scored evidence with honest
  labels (why a bar for an unbounded logit lies and a rank slopegraph is honest), a
  streamed stage timeline, a policy-vs-preference tier, pins as HMAC capability tokens
  (why `pin=id` was a read-any-chunk oracle), and a metered budget read from the audit
  ledger; two bugs worth teaching — contextvars across threads and `+` in a query
  string; mapped to OWASP LLM01/output-handling/excessive-agency/RAG-poisoning and
  NIST AI RMF GOVERN/MEASURE.
- **[Lesson 09 — Many corpora, one engine; and the retrieval unit is not the context unit](lessons/09-corpora-and-context.md)** —
  ADR-0014 to 0018 as one lesson: a corpus becomes a profile (path, persona, retrieval
  mode, tool allow-list) with a private overlay so personal corpora never enter the
  tree; a real vault as a corpus with a credential guard and measured ablations
  (reranker trigger fired, link expansion rejected); a passage-level metric that saw
  what `hit@k` could not; an ingest merge measured and rejected; and context assembled
  by note under a fair-share budget after ranking — brain context@4 2/7 → 7/7, graded
  answers 40% → 93%, zero ranking changes — with two rules the design review added
  (pins never assemble; sources follow the included set) and the judge bug the gate
  caught; mapped to OWASP LLM01/LLM06/LLM08 and NIST GOVERN/MEASURE/MANAGE.

## The curriculum = the 8-dimension enterprise-readiness framework

Interchange is built against an 8-dimension enterprise-readiness framework. Read
as a curriculum, each dimension is a lesson (or a cluster of them). Lesson 01
covers the security/governance/grounding core; the rest arrive as the project
grows, in roadmap order.

| # | Dimension | What you'll learn to build | Lesson |
|---|---|---|---|
| 1 | **Security** | input/output guardrails, prompt-injection defense (OWASP LLM01), instruction/data separation; a web policy tier + capability-token pins on a new surface | ✅ [01](lessons/01-mvp.md) [08](lessons/08-browser-workbench.md) |
| 2 | **Governance & Compliance** | per-request audit log (who asked what, which sources, cost), NIST AI RMF GOVERN; policy-vs-preference tiers + a ledger-enforced budget | ✅ [01](lessons/01-mvp.md) [08](lessons/08-browser-workbench.md) |
| 3 | **Evaluation & Quality Gates** | golden dataset + faithfulness/groundedness gate (RAGAS) as a CI check | ◐ [04](lessons/04-hybrid-retrieval.md) (retrieval hit@k) + ADR-0008 (`--grade`: refusal-/answer-correctness + faithfulness monitor, advisory; CI gate pending) |
| 4 | **Observability** | tracing every LLM/tool call (Phoenix/Langfuse), cost & latency dashboards, drift | ◐ ADR-0009 (opt-in OpenTelemetry tracing of RAG + agent to a local Phoenix; audit cost/latency in 01) + [08](lessons/08-browser-workbench.md) (per-stage timings streamed to the UI) |
| 5 | **Reliability & Architecture** | retries, timeouts, circuit breakers, fallback routing, graceful "I don't know" | ◐ [08](lessons/08-browser-workbench.md) (per-host rate limit + generation semaphore + graceful 429/503 on the web surface; graceful refusal in 01; retries/fallback still coming) |
| 6 | **Cost & Efficiency** | model routing (cheap model for easy turns), caching, token budgets | ◐ [08](lessons/08-browser-workbench.md) (metered reranking off by default + a daily budget from the ledger; per-request cost + engine routing in 01; caching still coming) |
| 7 | **Deployment & Ops** | IaC, CI/CD, secrets management, AWS Bedrock keeping data in-VPC | ⬜ coming |
| 8 | **Context & Memory Engineering** | agentic retrieval (plan → retrieve → reason → "enough context?"), retrieval-vs-long-context routing, agentic memory — the 2026 headline skill | ◐ [02](lessons/02-agentic-loop.md) [03](lessons/03-agent-on-a-subscription.md) [04](lessons/04-hybrid-retrieval.md) (agentic retrieval + hybrid seam; router/multi-hop deferred) |

**Legend:** ✅ taught & built · ◐ partly built (boundary noted) · ⬜ coming as the
project grows. This mirrors the
README's build/partial/roadmap scorecard — the honesty is deliberate. Knowing
*where a control stops* is part of knowing the control.

## Why teach it this way

The knowledge-runtime pattern is exactly the enterprise-readiness framework:
retrieval + verification (grounding) + access-control (guardrails) + audit as
integrated ops. Building it as a course makes the reasoning visible — you don't
just see *that* there's a guardrail, you see *why* it's there and *which* clause
of OWASP / NIST it answers to. The commit history is the syllabus; `--explain`
is the live lecture.

## Run the lessons

```bash
python interchange.py --reindex                        # local embeddings, no API key
python interchange.py --explain --ask "what is an 824?"  # narrate every stage
python interchange.py --audit                          # governance/cost dashboard
```

New lessons land in [`lessons/`](lessons/) as each roadmap dimension ships.
