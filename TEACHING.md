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

## Start here

- **[Lesson 01 — The MVP: a grounded, audited RAG loop](lessons/01-mvp.md)** —
  the `retrieve → ground → audit` core: input guardrail + instruction/data
  separation, the grounding/citation check (why an honest "I don't know" beats a
  confident hallucination), and the per-request audit + cost log. Run it with
  `--explain` and watch each stage narrate itself.

## The curriculum = the 8-dimension enterprise-readiness framework

Interchange is built against an 8-dimension enterprise-readiness framework. Read
as a curriculum, each dimension is a lesson (or a cluster of them). Lesson 01
covers the security/governance/grounding core; the rest arrive as the project
grows, in roadmap order.

| # | Dimension | What you'll learn to build | Lesson |
|---|---|---|---|
| 1 | **Security** | input/output guardrails, prompt-injection defense (OWASP LLM01), instruction/data separation | ✅ [01](lessons/01-mvp.md) |
| 2 | **Governance & Compliance** | per-request audit log (who asked what, which sources, cost), NIST AI RMF GOVERN | ✅ [01](lessons/01-mvp.md) |
| 3 | **Evaluation & Quality Gates** | golden dataset + faithfulness/groundedness gate (RAGAS) as a CI check | ⬜ coming |
| 4 | **Observability** | tracing every LLM/tool call (Phoenix/Langfuse), cost & latency dashboards, drift | ⬜ coming (cost/latency partly in 01) |
| 5 | **Reliability & Architecture** | retries, timeouts, circuit breakers, fallback routing, graceful "I don't know" | ⬜ coming (graceful refusal in 01) |
| 6 | **Cost & Efficiency** | model routing (cheap model for easy turns), caching, token budgets | ⬜ coming (per-request cost + engine routing in 01) |
| 7 | **Deployment & Ops** | IaC, CI/CD, secrets management, AWS Bedrock keeping data in-VPC | ⬜ coming |
| 8 | **Context & Memory Engineering** | agentic retrieval (plan → retrieve → reason → "enough context?"), retrieval-vs-long-context routing, agentic memory — the 2026 headline skill | ⬜ coming |

**Legend:** ✅ taught & built · ⬜ coming as the project grows. This mirrors the
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
