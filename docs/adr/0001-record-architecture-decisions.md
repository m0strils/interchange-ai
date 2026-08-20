# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
Interchange is evolving from a single-file RAG MVP into a governed, agentic
knowledge runtime. That evolution is a sequence of consequential choices —
orchestration, tool exposure, retrieval strategy, evaluation, deployment. Two
forces make it worth recording those choices deliberately:

1. **Governance.** A production-minded system has to be reproducible and
   auditable. "Why is it built this way?" should have a durable, versioned answer
   — not tribal memory. This is the enterprise-readiness *Governance* dimension
   applied to our own build.
2. **Learning.** This project doubles as a teaching aid. The reasoning behind a
   decision — the options weighed and the trade-off accepted — is often more
   instructive than the code that results.

## Options considered
1. **Nothing formal** — decisions live in commit messages and memory. Cheap;
   but rationale erodes, and "why not X?" gets re-litigated.
2. **A design doc / wiki** — richer, but tends to drift from the code and rarely
   records *rejected* options.
3. **Architecture Decision Records** (Michael Nygard style) — one immutable file
   per decision, versioned alongside the code, capturing context, options,
   decision, and consequences.

## Decision
Use **ADRs**, stored in `docs/adr/`, one file per significant decision. They are
immutable once **Accepted**; a later ADR *supersedes* an earlier one rather than
editing it, so the reasoning history stays intact.

## Consequences
- Consequential changes carry a recorded, reviewable rationale — a real
  governance and onboarding asset, and a visible signal to anyone reading the repo.
- Each ADR pairs with the `lessons/`: lessons teach *how*, ADRs teach *why*.
- Small ongoing cost: a few minutes to write an ADR when a real decision is made.
  We only record *architecturally significant* choices, not every commit.
