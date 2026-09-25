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
**Options considered**, **Decision**, **Consequences**. Accepted decisions are
never rewritten; corrections land as dated Updates. A later decision
*supersedes* an earlier one and both stay in the log.

**Statuses:** `Proposed` · `Accepted` · `Superseded by ADR-NNNN` · `Deprecated`

## Index
| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-orchestration-framework.md) | Orchestration for the agentic runtime | Accepted (superseded in part by 0003) |
| [0003](0003-agent-generation-auth.md) | Generation auth for the agent runtime (API vs Max) | Accepted → **subscription: `claude -p` + MCP** (amended) |
| [0004](0004-telemetry-accuracy.md) | Telemetry accuracy & honesty for the subscription runtime | Accepted → **measured from `claude -p` json** |
| [0005](0005-testing-strategy.md) | Testing strategy — TDD + Gherkin acceptance criteria | Accepted → **pytest + pytest-bdd** |
| [0006](0006-quality-gate.md) | Quality gate — local git hook, not hosted CI | Accepted → **`.githooks/pre-push`** |
| [0007](0007-retrieval-strategy.md) | Retrieval strategy — hybrid, structure-aware, measured | Accepted → **hybrid + tiny eval now** |
| [0008](0008-evaluation-gate.md) | Answer-quality evaluation — refusal-/answer-correctness, advisory | Accepted → **`--grade`, $0, advisory** |
| [0009](0009-observability.md) | Observability — OpenTelemetry tracing viewed in a local Phoenix | Accepted → **OTel + Phoenix, off by default** |
| [0010](0010-document-ingestion-formats.md) | Document ingestion formats — PDF via pypdf (BSD) over pymupdf4llm (AGPL) | Accepted → **pypdf, flat text, no OCR** |
| [0011](0011-strands-comparison.md) | Agentic orchestration trade-offs — Interchange's explicit loop vs. Strands' model-driven | Proposed → **reference architecture comparison** |
| 0012 | _reserved, never written (see [0011](0011-strands-comparison.md))_ | — |
| [0013](0013-a2a-agent-interop.md) | Agent-to-agent interop over A2A with signed Agent Cards | Accepted → **A2A 1.0 + 0.3 compat, signed card, pinned kid** |
| [0014](0014-vault-corpus-and-measured-ablations.md) | Vault corpus: recursive ingestion, read-only profile, measured ablations | Accepted → **reranker trigger fired (hit@1 11→15/18); link expansion regressed, deferred** |
| [0015](0015-browser-workbench-surface.md) | Browser workbench over the same governed pipeline — scored retrieval, policy tier, streamed stages | Accepted → **vendored no-build Preact at `/ui`, `POST /ask/stream` SSE, env-is-policy** |
| [0016](0016-corpus-profiles-as-portable-data.md) | Corpus profiles as portable data — overlay, index dir, persona, retrieval, tools | Accepted → **`INTERCHANGE_PROFILES` overlay, `INTERCHANGE_CHROMA_DIR`, `--profile`, per-profile persona/retrieval/tools** |
| [0017](0017-passage-level-retrieval-and-lead-chunks.md) | Passage-level retrieval quality and lead-chunk handling — metric before fix | Accepted → **metric + lead detection kept; merge rejected on measurement (carried by 0018)** |
| [0018](0018-context-assembly-with-a-budget.md) | Context assembly with a budget — the retrieval unit is not the context unit | Accepted → **two-pass fair-share assembly, `notes` on brain (7/7 context@4, 93% graded), HTTP knob locked by default, judge grades the governed path** |

_(MCP tool server — was pencilled as a separate ADR — was implemented under
ADR-0003's amendment; see `mcp_server.py`. No standalone ADR needed.)_

## Backlog (numbers assigned when written, in decision order)
- Trace the ADR-0008 `--grade` eval runs — trigger: the ADR-0009 trace seam proven on live requests
- A repeatable answer-quality baseline / regression check — trigger: the LLM judge is made deterministic (ADR-0008 v1 is advisory, no baseline)
- Reranking (local cross-encoder) — **measured (ADR-0014):** the trigger fired and paid off (hit@1 11→15/18, $0). Open item — reranker as default path: latency + rail check
- Link-aware expansion — trigger: linked rows missing under hybrid+rerank on a future golden set (ADR-0014: naive 1-hop regressed hit@1 by 5 rows, deferred)
- TypeSafe Jev reranker — **measured 2026-09-22 (ADR-0014):** parity with the local cross-encoder on the vault golden set; stays opt-in, metered (~3¢/run)
- Retrieve-vs-long-context router + agentic multi-hop — trigger: corpus outgrows the context window
- Incremental reindex by content hash — trigger: measured full rebuild > 5 min or intra-day freshness needed (ADR-0016)
- Cross-corpus fan-out query — trigger: same question asked of two corpora repeatedly (ADR-0016)
- Retrieved-text injection scan — trigger: any corpus of untrusted text wants more than `chunks` context (ADR-0018)
- Same-note neighbour expansion — trigger: lead-chunk merge leaves passage@k short (ADR-0017) — **subsumed by ADR-0018 as the `notes` fallback**

_Template: copy [`0000-template.md`](0000-template.md)._
