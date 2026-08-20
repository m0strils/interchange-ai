# Architecture Decision Records

This log captures the **significant architectural decisions** for Interchange —
one file per decision, in the order they were made.

## Why we keep these
- **Governance / traceability.** Every consequential change is reproducible and
  has a recorded rationale. (This is the enterprise-readiness *Governance*
  dimension, made concrete.)
- **Learning.** The `Context → Options → Decision → Consequences` shape is a
  lesson in itself. Where `lessons/` teach *how* the system works, ADRs teach
  *why it's built this way* — including the roads not taken.

## Format
Short (Michael Nygard style). Each ADR has: **Status**, **Context**,
**Options considered**, **Decision**, **Consequences**. ADRs are immutable once
**Accepted** — we don't edit history; a later decision *supersedes* an earlier
one and both stay in the log.

**Statuses:** `Proposed` · `Accepted` · `Superseded by ADR-NNNN` · `Deprecated`

## Index
| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-orchestration-framework.md) | Orchestration for the agentic runtime | Accepted (superseded in part by 0003) |
| [0003](0003-agent-generation-auth.md) | Generation auth for the agent runtime (API vs Max) | Accepted → **subscription: `claude -p` + MCP** (amended) |
| [0004](0004-telemetry-accuracy.md) | Telemetry accuracy & honesty for the subscription runtime | Accepted → **measured from `claude -p` json** |
| [0005](0005-testing-strategy.md) | Testing strategy — TDD + Gherkin acceptance criteria | **Proposed** |

_(MCP tool server — was pencilled as a separate ADR — was implemented under
ADR-0003's amendment; see `mcp_server.py`. No standalone ADR needed.)_

## Backlog (numbers assigned when written, in decision order)
- Retrieval strategy: hybrid (BM25 + vector) + reranking + a *retrieve-vs-long-context* router
- Evaluation as a release gate (RAGAS golden set)
- Tracing/observability backend (Phoenix vs. Langfuse)

_Template: copy [`0000-template.md`](0000-template.md)._
