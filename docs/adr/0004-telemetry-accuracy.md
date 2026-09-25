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

## Update — 2026-09-22
Both `claude -p` call sites (`interchange._generate_claude_code`, `agent_sub`) ran in
the **caller's** working directory. Launched from inside a repo with a `.claude/` Stop
hook, the child session ran the hook (the pytest gate) and returned **hook commentary**
in place of the answer — measured telemetry over the wrong text, flagged UNGROUNDED;
from `/tmp` the same question answered correctly. Fix: both now run in a repo-free
`interchange.headless_cwd()` and pass `--setting-sources user`, so no project settings
or hooks load. Telemetry stays measured; the number now covers the real answer.

## Update — 2026-09-23 (observed; fix in progress)
The **same failure class** as the 2026-09-22 update — the headless generation
session picking up ambient config and returning *it* in place of the answer — has a
second source, so this update lands on the ADR that owns that story rather than a new
one. `--setting-sources user` loads user settings, and **that pulls in every MCP
server in `~/.claude.json`**. On this machine that is now **two Obsidian vault
connectors**. `interchange._generate_claude_code` runs `claude -p` with no MCP
restriction, so both servers load into a session that should only generate text from
the context it was handed: the model spends tokens on their tool descriptions,
attempts calls, is denied, and narrated *"both Obsidian connectors were denied"*
instead of answering the five-practices question (observed 2026-09-23). `agent_sub.py`
passes `--mcp-config` for the interchange server plus an `--allowedTools` allow-list,
but **without `--strict-mcp-config` the user-scope servers still load** and cost
context even though the allow-list blocks their use.

**Fix in progress (Slice 1 of the lead-chunks plan), flags to be confirmed by that
slice** — not yet landed, not yet verified:
- `--strict-mcp-config` on **both** paths, so only servers named by `--mcp-config`
  load (and with no `--mcp-config`, none). The RAG path then loads **zero** MCP
  servers; the agent path loads **only** the interchange server.
- A **tool-free** generation session for the RAG path via `--tools ""` **if a manual
  $0 check confirms** it yields a session with no built-in tools; otherwise
  `--disallowedTools` for the file/shell built-ins that could read the machine
  (`Read`, `Bash`, `Edit`, `Write`, `Glob`, `Grep`, `WebFetch`, `WebSearch`). Which
  one shipped will be recorded here once Slice 1 verifies it.

Claude Code 2.1.267 documents both `--strict-mcp-config` and `--tools`. Telemetry is
unaffected — this is the runtime's **tool surface**, not its usage accounting; it is
recorded here because it is the direct continuation of the 2026-09-22 headless-hygiene
finding on the same `claude -p` runtime.

**Confirmed 2026-09-23 (slice 1 landed, merge 8a5b2c9).** The RAG engine now passes
`--strict-mcp-config` and `--tools ""` (an empty tool list is the documented
"disable all tools" form in Claude Code 2.1.267; verified once at $0: `is_error`
false, no permission denials, one turn); the subscription agent passes
`--strict-mcp-config` so only its `--mcp-config` server loads. **Measured** on the
same question, same corpus, same engine: the headless session's reported input
fell from 31,880 to 9,851 tokens and the answer no longer mentions connectors.
Offline scenarios pin the argv (`features/headless_hygiene.feature`).
