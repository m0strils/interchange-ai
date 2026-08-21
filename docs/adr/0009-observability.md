# ADR-0009: Observability — OpenTelemetry tracing viewed in a local Phoenix

- **Status:** Accepted
- **Date:** 2026-08-20
- **Deciders:** Jeff Lynch

## Context
Interchange already has *request-level* observability: `enterprise.audit()` writes a
JSONL row per request (model, engine, sources, tokens, shadow/marginal cost, latency,
grounded, blocked) and `--audit` summarizes it (`enterprise.py:95`, `:139`). That row
is the durable governance record.

What it lacks is *per-stage* and *nested* visibility. Within one request there is no
breakdown of how long `retrieve()` vs the generation call vs `guard_input`/`guard_output`
took (`interchange.py`; `enterprise.py:48`, `:64`). Worse, inside `--agent` the loop is a
black box: the `claude -p` + MCP subprocess (`agent_sub.py:95`) collapses into a single
flat audit row, so *which* MCP tools the model called — `search_docs`, `lookup_segment`
(`mcp_server.py:27`, `:38`) — how often, and how long, is invisible.

Closing this is roadmap #3, and it is the sequenced follow-on to ADR-0008, which
explicitly deferred "observability tracing of eval runs" to **ADR-0009** so the trace
surface wasn't designed before the eval existed. Scope confirmed: **the RAG path and the
agent loop.**

The honest constraints from ADR-0003/0004/0006 still hold: **$0** (no metered API),
honest telemetry, and — critically — the `pre-push` gate (ADR-0006) must stay **offline,
instant, and dependency-light**. Tracing cannot land in that gate, and its dependencies
cannot bloat every clone's test environment.

## Options (the menu)

**Backend / UI**
1. **Arize Phoenix** — OTel transport + OpenInference semantic conventions, self-hosts
   free (Elastic License 2.0), runs in-process/local with little friction, and has eval
   synergy with ADR-0008. Backend-swappable (it's just OTLP).
2. **Langfuse** — MIT-licensed, excellent agent-replay UI. *Con:* wants a Docker-compose
   stack to self-host — more moving parts than a local learning repo needs.
3. **OpenLLMetry / Traceloop** — an SDK that leans on auto-instrumentation (see below);
   pairs with a hosted backend. Convenient *only* where it can patch an in-process client.

**Instrumentation style**
4. **SDK auto-instrumentation** (`openinference-instrumentation-anthropic`, OpenLLMetry).
   Monkey-patches an in-process SDK client so spans appear "for free." **It loses here:**
   our generation does *not* go through a patchable in-process SDK call — the RAG path
   runs through the engine dict / `claude -p`, and the agent path is a `claude -p`
   subprocess (`agent_sub.py:95`). There is no client object in our process to patch, so
   auto-instrumentation would silently produce empty traces.
5. **Manual OpenInference spans** — hand-place spans at the seams we care about. More
   code, but it's the *only* thing that works given our subprocess/engine-dict shape, and
   it puts spans exactly where the domain stages are.
6. **A lightweight hand-rolled span layer** (our own timing/JSON, no OTel). Zero deps,
   but reinvents a standard and throws away the free Phoenix UI and backend-swappability.

**Agent path specifically**
7. **Hand-rolled cross-process spans** — manually stitch parent/child spans across the
   subprocess boundary. Fragile; duplicates work Claude Code already does.
8. **Claude Code's built-in OTel** — Claude Code (what `--agent` already runs) emits a
   native `claude_code.interaction → llm_request → tool` span tree and propagates
   `traceparent` into the MCP server when the right env vars are set on the subprocess.
   Nearly dep-free on our side.

## Decision
Adopt **OTel + OpenInference conventions, viewed in a local Arize Phoenix** ($0,
`Elastic-2.0`), over Langfuse (option 1 over 2) — Phoenix runs local with less friction
and shares conventions with the ADR-0008 eval work. Instrumentation splits by path:

- **RAG path — manual OpenInference spans** (option 5, not 4). A new guarded
  `observability.py` exposes one seam, `span(name, **attrs)`, a context manager that
  yields an OpenInference-tagged span when tracing is on and a **null context** otherwise.
  Callers wrap the stages: `retrieve()` (with child spans for dense / bm25 / rrf), the
  engine generation call in `answer()`, and `guard_input`/`guard_output`. Auto-
  instrumentation is rejected for the honest reason above: there is nothing in-process to
  patch.
- **Agent path — Claude Code's native OTel** (option 8, not 7). `agent_sub.py` merges a
  small env dict (`claude_code_trace_env()`) into the `subprocess.run(..., env=...)` call
  (`agent_sub.py:95`), so Claude Code exports its own `interaction → llm_request → tool`
  tree to the same local Phoenix, with the MCP tool calls nested via propagated
  `traceparent`. We wrap the subprocess in a parent span for continuity.

**Off by default.** Everything is gated on `INTERCHANGE_TRACING=1`. When the flag is
unset — or set but the trace deps aren't installed — every seam no-ops cleanly (guarded
imports, mirroring the existing `import chromadb`-inside-a-function pattern). The trace
dependencies (`arize-phoenix`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`,
`openinference-semantic-conventions`) ship as an **optional extra** in a separate
`requirements-trace.txt` — deliberately **not** in `requirements-dev.txt`, so they never
enter the offline `pre-push` env (they'd bloat every clone and risk conflicts with
`chromadb`). The ADR-0006 gate is therefore untouched.

**Two complementary layers, kept distinct.** `audit.jsonl` stays the durable, always-on
governance/compliance record (`enterprise.audit`, unchanged); Phoenix is the opt-in,
dev-time trace UI for latency and nested-call debugging. Neither replaces the other.

## Consequences
- **Two grounding layers of observability, taught explicitly:** an always-on request
  audit (compliance) vs an opt-in per-stage/nested trace (debugging & latency). The
  distinction is the lesson, mirroring ADR-0008's runtime-guardrail-vs-eval split.
- **The agent loop stops being a black box:** MCP tool calls become visible as nested
  spans, and the agent trace is *nearly dep-free on our side* — env vars on the subprocess
  plus a running local Phoenix, no hand-rolled cross-process plumbing.
- **The pre-push gate is unaffected** — tracing is off by default and its deps live
  outside the test environment; `pytest` stays green with nothing new installed.
- **Backend-swappable:** because it's OTLP + OpenInference, pointing at a different
  collector later is a config change, not a re-instrumentation.
- **Deferred, with triggers:** tracing the `--grade` eval runs (ADR-0008's original
  hand-off — worth doing once the trace seam is proven on live requests); and a
  hosted/remote OTLP collector if this ever goes multi-service (until then, local Phoenix
  wins on friction).

## Honest caveats
- **The conventions are pre-stable.** OTel's GenAI semantic conventions — and
  OpenInference — are still **experimental** in 2026 (GenAI moved to a dedicated repo in
  June 2026; no 1.0; the two coexist without having converged). We are adopting an
  *emerging* standard, not a settled one, and say so rather than implying stability.
- **Claude Code trace *export* is beta.** Metrics and logs are GA, but exporting the
  full trace span tree requires `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` (alongside
  `CLAUDE_CODE_ENABLE_TELEMETRY` and the `OTEL_*` vars). A beta feature on the agent path
  is a known, documented risk — not a claim of production-grade tracing.
- **The exact OTLP port was a build-time detail — now confirmed.** Verified against
  Phoenix **20.3.0**: it accepts OTLP/HTTP at **`:6006/v1/traces`**, which is
  `observability.py`'s default (override with `INTERCHANGE_OTLP_ENDPOINT`). A different
  Phoenix version or a standalone collector (`:4318`) would still need re-checking.

## Verified (live, 2026-08-20)
End-to-end against a local Phoenix 20.3.0, `INTERCHANGE_TRACING=1`, $0 subscription:
- **RAG path:** a traced `--ask` exported the full tree — `guard_input`, `retrieve`
  (+ `retrieve.dense`/`.bm25`/`.rrf`), `generate`, `guard_output` — read back via the
  Phoenix client (7 spans).
- **Agent path:** a traced `--agent` run produced Claude Code's **native** span tree
  (`claude_code.interaction → llm_request → tool → tool.execution`) nested under our
  `agent` span, in the same Phoenix — the beta trace export works.
- The offline `pre-push` gate stays green whether the trace deps are absent *or* present
  (tracing no-ops unless `INTERCHANGE_TRACING=1`).
- Tracing immediately paid off: it surfaced that in this environment the `--agent` path
  wasn't connecting the `interchange` MCP tools (only the host's global connectors were
  visible) — a separate ADR-0003 concern, made visible by the trace.

## Research
This decision was validated by a 2026 survey of the LLM-observability tooling — OTel's
GenAI convention status (still experimental), Phoenix vs Langfuse vs OpenLLMetry/Traceloop
trade-offs, the OpenInference-vs-OTel-GenAI coexistence, local Phoenix with manual
OpenInference spans, and Claude Code / Agent SDK built-in OTel (env vars, native span
tree, MCP `traceparent` propagation). The survey is what turned us away from auto-
instrumentation (nothing in-process to patch) and toward the split of manual RAG spans +
Claude Code's native agent telemetry.
