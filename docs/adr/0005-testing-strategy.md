# ADR-0005: Testing strategy — TDD + Gherkin acceptance criteria

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
The app has no automated tests. We want two things: **executable acceptance
criteria in Gherkin** (business-readable specs for the behaviors that matter —
grounding, guardrails, telemetry honesty) and **unit coverage** of the
deterministic core. This is the enterprise-readiness **Evaluation / Quality-Gate**
dimension, made concrete — and it's the natural home for the honesty behaviors the
ADR-0004 code review just surfaced (correct model attribution, measured-vs-estimated).

Two hard constraints shape the choice:
- **Free & offline.** The only thing that costs money or needs auth is the model
  call. Everything else — input guardrail (injection), output guardrail
  (grounding/citation), the audit record + telemetry math, the `claude -p` usage
  parse, segment lookup, chunking, retrieval — is deterministic and testable with
  the **generation boundary stubbed**. Tests must run in CI at $0, no model calls.
- **Business-readable specs.** Gherkin `Given/When/Then` doubles as a governance
  artifact and a portfolio signal (an executable spec), not just developer tests.

## Options considered
1. **pytest + pytest-bdd** — Gherkin `.feature` files with steps as pytest
   functions. *Pros:* one runner for acceptance *and* unit tests, pytest fixtures,
   coverage, CI-friendly. *Cons:* steps are a thin layer over pytest (slightly less
   "pure BDD").
2. **behave** — the canonical Gherkin/BDD runner. *Pros:* purest BDD experience.
   *Cons:* a second toolchain alongside pytest for unit tests.
3. **pytest only, no Gherkin** — simplest, but drops the business-readable
   acceptance-criteria artifact you explicitly asked for.

## Decision (proposed)
**pytest + pytest-bdd.** One test runner for both layers. Structure:
- `features/*.feature` — Gherkin **acceptance criteria** (the executable spec).
- `tests/` — pytest **unit tests** for the deterministic units.
- A **stubbed generation seam** (fake engine / patched `claude -p` subprocess and
  Anthropic call) so no test hits a live model — $0, offline, deterministic.

**Workflow:** TDD going forward (red → green → refactor); characterization tests
for existing behavior now. **First scenarios encode the ADR-0004 review findings** —
correct model attribution, grounded-vs-ungrounded, injection blocked, telemetry
measured-vs-estimated — then we fix the code to make them pass. The review becomes
the test backlog.

## Consequences
- A **free, offline CI quality gate** — runs on every change, no spend (fits ADR-0003).
- The Gherkin specs are a governance + teaching artifact (executable acceptance criteria).
- Small new deps: `pytest`, `pytest-bdd`.
- Requires building one **model-stub seam** so the deterministic core is testable in
  isolation — a small, healthy refactor (dependency-injection at the generation boundary).
- Sets up a future ADR: **CI wiring** (run the gate on push) and, later, RAGAS
  answer-quality evals as a second gate.
