# ADR-0004: Telemetry accuracy & honesty for the subscription runtime

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
The audit log (`enterprise.py`) is a governance artifact — the numbers it records
should be **measured**, or **honestly labeled as estimates**, never a misleading
undercount. Today they aren't, uniformly:

- **API paths** (the `agent.py` loop, `_generate_api`) record **exact** token usage
  from `resp.usage`. Good.
- **Subscription paths** (`agent_sub.py`; the `claude-code` RAG engine) fall back to
  a crude `len(text) // 4` estimate that counts only the raw question and answer —
  ignoring the system prompt, tool schemas, tool-result payloads, and every loop
  turn. A real multi-tool run logged **"~6 input tokens."** That's not a rounding
  error; it's noise dressed as data.

Constraint from [ADR-0003](0003-agent-generation-auth.md): this path must not fund
the metered API, so the `count_tokens` endpoint (needs a key) is off the table here.

**Pivotal unknown:** does `claude -p --output-format json` already return real
usage/cost? Our parse fell back to the estimate, but we haven't inspected the raw
output — so we don't yet know whether the fields are absent, nested, or just named
differently from what `agent_sub.py` reads (`out.get("usage")`).

## The plan (options, sequenced)
1. **Investigate first.** Capture raw `claude -p --output-format json` (and
   `stream-json`) output; inspect for usage/cost fields. *Pivotal:* if real numbers
   are there, the fix is simply to parse them — telemetry becomes **measured, at $0**.
2. **If measured usage is available →** parse the correct fields; mark records
   `measured`. Best outcome.
3. **If not →** improve the estimate to count the **full** prompt actually sent
   (system prompt + tool schemas + question + tool-result text) and the full
   generated text — not just the raw Q/A. `chars/4` stays the floor; a small local
   tokenizer is a later option.
4. **Unconditional honesty fix:** add an explicit `telemetry: "measured" | "estimated"`
   field to every audit record, surfaced in `--explain` and `--audit`. The governance
   log must never imply precision it lacks. Do this regardless of 2 vs 3.
5. **Consistency:** same treatment for the `claude-code` RAG engine; mark the API
   paths `measured`.

## Investigation result (2026-08-19) — resolves to "measured"
Captured raw `claude -p --output-format json`. It returns **rich, measured
telemetry**, so Branch 2 wins — nothing needs estimating on the subscription path:
- `usage.{input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
  output_tokens}` — real counts. **True input = input_tokens + cache_creation +
  cache_read** (most of it lives in `cache_creation`, which is *why* reading
  `input_tokens` alone undercounts to near-zero).
- `total_cost_usd` (real API-equivalent) + `modelUsage` (per-model breakdown),
  plus `duration_ms`, `ttft_ms`, `num_turns`, `stop_reason`, `session_id`.

Two bugs in the current parse, now explained:
1. `usage.get("input_tokens") or fallback` treats a legitimate **0** (cache-only
   turn) as missing → fires the estimate. Use explicit presence and **sum the
   cache-token fields**.
2. It ignores `total_cost_usd` entirely.

**Cost-honesty nuance to record:** a trivial call reported `total_cost_usd ≈ $0.21`
— headless Claude Code runs **Opus 4.8 with a ~21k-token cached system prompt**.
On the subscription that's **$0 to you (marginal)**, but the API-equivalent
*shadow cost* is real. So a flat `$0` in the audit is too rosy; the honest record
is **measured shadow cost = `total_cost_usd`, marginal billed = $0**.

## Decision (updated) — adopt Branch 2 (measured)
Parse the real usage/cost from `claude -p --output-format json`: true input =
`input_tokens + cache_creation + cache_read`, output = `output_tokens`, and record
the measured **shadow cost** (`total_cost_usd`) alongside a marginal `$0`. Tag the
record `telemetry: "measured"`. Keep an estimate-with-label as the fallback if a
future CLI omits usage. Same treatment for the `claude-code` RAG engine (switch it
to `--output-format json`); the API paths are already measured.

## Consequences
- The audit stops misleading — every number is measured or clearly flagged an estimate.
- If `claude -p` exposes usage, the subscription path gets **accurate telemetry at $0**.
- Small changes: `audit()` gains a `telemetry` flag; the two subscription call sites
  and `audit_summary()` updated; `--explain` shows the flag.
- No new metered API spend (honors ADR-0003).
