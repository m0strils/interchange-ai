# ADR-0018: Context assembly with a budget — the retrieval unit is not the context unit

- **Status:** Accepted (2026-09-24; measured — see Updates)
- **Date:** 2026-09-24
- **Deciders:** Jeff Lynch

## Context
ADR-0017 proved a failure the source-level eval could not see, and then proved
the ranking fix wrong. Two things are now measured and settled:

- **Retrieval finds the right notes.** On the `brain` corpus, source `hit@4` is
  **22–25/25** in every mode (ADR-0017's corrected baseline table). The retriever
  is not the problem.
- **The context is still wrong for two classes of question.** *Whole-note*
  questions ("the five most important practices", "what did I decide and why")
  span many sections of one or two notes; a ten-section reference note can never
  fit in top-4, whichever four chunks rank first. *Section* questions ("what does
  the checklist say about memory") find the right note, but its lead chunk
  outranks the relevant section — brain **lead share 0.26**, `passage@4` **3/6**.
- **Fixing ranking by changing chunk shape does not work.** ADR-0017's lead-chunk
  merge (its `Update 2026-09-23 — slice 3 step 2 measured and reverted`) lowered
  lead share on every corpus and, in doing so, **broke the reranker**: rail
  14/14 → 13/14, vault `hybrid+rerank` 15/18 → 12/18, brain default `passage@4`
  unchanged at 3/6. The cross-encoder wants short, focused passages. Ranking is
  not where the fix belongs; the merge was reverted, and the passage metric and
  structural `lead` detection were kept.

The root cause is structural: **the unit of retrieval and the unit of context are
the same thing.** The engine only ever sees four ~600-char chunks chosen by
chunk-level scoring. For a personal knowledge base they should differ, and the
notes are small enough that they can:

- **brain**: median **6.2k** chars, **25/30** notes under 12k.
- **vault**: median **8.4k** chars, **144/196** notes under 12k.

The **headless input-token baseline is 9,851** tokens (measured after the
strict-MCP fix), which is the number the counter-metric must be held against so
"include the whole note" does not silently balloon the prompt.

Four review findings (review-plan, four lenses, 2026-09-24) shape the design and
must not be re-introduced:

1. **Pin escalation.** A pin proves one chunk was returned; it is not a
   read-the-note capability. A pinned re-ask under a `notes` profile must not
   assemble.
2. **Sources-from-hits.** Today `answer_detail` derives `sources`, the grounding
   check (`guard_output(text, sources)`), and `cited = any(f"[{name}]" in text …)`
   from the *hit* set. Once assembly can drop a ranked note under budget, a dropped
   note is no longer a legitimate citation target; grounding and audit must follow
   the *included* set.
3. **Greedy expansion is not a superset.** A naive expand-in-place can evict a
   hit's own chunk; `assembled ⊇ chunks` must be guaranteed by construction (a
   seed pass), not hoped for.
4. **The label metric is vacuous in `notes` mode.** If the whole note is included,
   every section label is trivially present. The gate must measure the *included
   chunk set* and pay a real counter-metric (chars and tokens), or "include
   everything" passes for free.

Constraints from earlier ADRs bind: chunk ids stay `source:index` so golden
`expected_source` paths do not move (ADR-0017); frontmatter stays indexed
(ADR-0014's measured recall win); the pytest gate stays offline and free
(ADR-0005/0006); every number is measured or labelled an estimate (ADR-0004).

## Options considered
1. **Larger top_k alone** — ask for more chunks. Measured at k=8 in ADR-0017 and
   it *still* missed the checklist sections; it also spends context tokens for
   chunks that do not travel together. **Rejected.**
2. **Chunk merge at ingest** — fold lead chunks into the first body chunk.
   Measured and **rejected in ADR-0017**: lowered lead share everywhere and broke
   the reranker on vault and an exact match on rail.
3. **Retrieve-vs-long-context router** — route whole notes vs chunks by corpus
   size. A real future decision, but its trigger is *corpus outgrows the window*
   (ADR-0014 backlog); it is not this problem. **Deferred, trigger unchanged.**
4. **Bigger chunks** — widen `CHUNK_CHARS`. Repeats the merge failure: longer
   passages, worse reranking. **Rejected.**
5. **A third public `neighbours` mode** — expose neighbour expansion as its own
   selectable value. It is only ever exercised as the internal fallback of `notes`;
   a third public knob is surface with no independent use. **Rejected** (kept as an
   internal fallback instead).
6. **Two-pass budgeted assembly** *(chosen)* — keep chunks as the retrieval and
   reranking unit; after ranking, a pure step assembles context *by note, under a
   budget*: seed every hit's own chunk, then expand each hit to its whole note if
   it fits or to its neighbours if not. Ranking is untouched and the
   `assembled ⊇ chunks` invariant is tested, not assumed.

## Decision
Introduce **ADR-0018: context assembly with a budget.** After `retrieve_detail`
returns ranked hits, a pure step assembles the context the engine sees. Ranking,
fusion, chunking and the reranker are untouched — those numbers and their per-row
ranks are the control.

### Mechanism
```
assemble_context(hits, chunk_map, *, mode, budget_chars, note_max_chars) -> Assembled
Assembled = {text, included, hit_sources, included_sources,
             chars, dropped_hits, fallbacks, budget_hit, reasons}
```

- **Two public modes.** `chunks` (today's behaviour; the default for every profile
  that does not opt in) and `notes`. Neighbour expansion is the internal fallback
  of `notes`, **not** a third public value.
- **Pass 1, seed.** Every hit's own chunk, in rank order, is included first. Four
  chunks of at most 1,200 chars always fit, so `assembled ⊇ chunks` holds **by
  construction** and is asserted by a test.
- **Pass 2, expand.** For each hit in rank order: if the whole note (sum of its
  chunk texts, which exceeds the file by the overlap) is at most `note_max_chars`
  **and** fits the remaining budget, include the entire note in chunk-index order;
  otherwise widen around the hit by ±1, ±2 chunks of the same source while budget
  remains. Never include a chunk twice. A note that does not fit is skipped whole,
  **never truncated mid-chunk**, and its reason is recorded (`budget_exhausted`,
  `note_too_big`, `not_retrieved` for eval rows).
- **Budget is measured on the assembled string**, source labels included. Chunks
  of one source are emitted as **one block under a single `[source]` header**, in
  chunk order.
- **Chunk map.** A per-source list of snapshot indices sorted by
  `int(meta["chunk"])`, built once and cached on the `Snapshot` (which today keys
  only on `count`; see `corpus_snapshot`). Chroma get-order is **not** relied on; a
  scenario feeds a deliberately shuffled snapshot and asserts note order.
- **Credential guard on expansion.** Every expansion-added chunk passes
  `looks_like_secret` before inclusion; drops are counted and reported. The ingest
  guard is file-scoped and runs once; this is the second line for near-misses.
- **Pinned re-asks never assemble.** When `pinned` is true, mode is forced to
  `chunks` regardless of profile or argument (review finding #1). `fetch_chunks`
  is a capability, not a read-the-note oracle.

### What downstream sees
- **`included_sources`** (sources that contributed at least one character) is what
  the grounding check, the citation check, and the audit row's `sources` use.
  **`hit_sources`** is recorded separately in the audit row and the retrieval
  frame. A source that ranked but was dropped by the budget is never a legitimate
  citation target (review finding #2).
- The scored `Retrieval` record is **returned to clients unchanged**. A test
  asserts its equality (hits, final ranks, every score) before and after assembly.
- The retrieval frame, the SSE done event, and the audit row **always** carry
  `context: {mode, chunks_in, chunks_out, chars, budget_hit, fallbacks,
  dropped_hits, assemble_ms}` — in `chunks` mode too, so the schema is not
  mode-dependent. Only the `--explain` stderr line is conditional: the existing
  stage lines stay **byte-identical** for `chunks`, the counts go on the stage-3
  context line for `notes`, with a second locked transcript baseline in the
  workbench test module.
- An OTel `assemble` span carries the same fields.

### Profile keys and precedence
`retrieval: {context: notes, budget_chars: 20000, note_max_chars: 16000}`.
Validation in `profile_retrieval`: `context ∈ {chunks, notes}`, both budgets
positive ints, `note_max_chars ≤ budget_chars`, else a named `ValueError`; any
resolution failure at answer time falls back to `chunks` (**fail closed**, toward
less context). Precedence: explicit argument, then the collection's profile, then
the code default. Resolution happens in **one place, inside `answer_detail`**, from
`profile_for_collection(active_collection())`, so CLI, HTTP, MCP and A2A resolve
alike. The existing mode mismatch — A2A and HTTP ignore the profile's `mode` — is
fixed in the same slice by the same resolver, and re-measured. The overlay merge
replaces the whole `retrieval` block, so the brain overlay restates
`mode: hybrid+rerank` alongside `context`.

### Policy tier
- **`INTERCHANGE_CONTEXT_MODE_MAX`** (default `chunks` on a public deploy, `notes`
  locally) and **`INTERCHANGE_CONTEXT_BUDGET_MAX`** (default 24,000) clamp whatever
  the profile says. Policy over profile, not just policy over request.
- The HTTP `context` knob is **locked by default**: a request may name it only when
  `INTERCHANGE_UNLOCKED` lists it. `/options` reports it as locked. `AskRequest`
  gains **`extra="forbid"`** now (it has none today), so an unknown `context` field
  is rejected rather than silently ignored today and silently honoured later.
- **`search_docs`** (MCP) stays pinned to `chunks` regardless of profile — today it
  retrieves with the profile's mode. It feeds a tool-bearing agent session that
  calls it repeatedly; that is the weakest downstream containment, not the
  strongest.
- **Metered spend:** `estimated_spend_today` counts **every** row's `cost_usd`, not
  only rows labelled `telemetry == "estimated"`, and `/ask*` checks the daily
  budget on every request when the engine is metered. This lands **before** assembly
  is wired.

### Corpora in scope
- **brain**: `context: notes`. The brain overlay gains
  `ignore: ["30-Career/People/", "30-Career/Interviews/"]` so third-party names and
  interview notes never assemble whole. Roles, Applications, Positioning stay.
- **rail, hotel, vault**: `chunks`. Vault opts in only after its own measured run.
- **research**: **out of scope.** Every research dump is 45–104 KB of self-declared
  untrusted text; the input guardrail scans only the question and the output check
  certifies any answer that cites a source. `notes` there would mean ~20k contiguous
  untrusted characters on every answer. Research stays on `chunks` until a
  retrieved-text injection scan exists as its own ADR.

## Eval: metrics that can fail
Ranking metrics are untouched. On the assembled context, computed from the first
`k` hits (not the eval's depth-10 list) with the profile's context settings and an
**injected snapshot**:

- **`context@k`**: a section row hits when an *included* chunk has an expected
  source **and** a section label matching, by the existing `_section_matches` rule,
  on **chunk metadata — never a text substring**. For the new field
  **`expected_sections_all`** (a list), **every** listed label must be present.
  **`expected_section` keeps its ANY rule**, so `passage@k` and ADR-0017's numbers
  do not move.
- **`note@k`**: a row hits when **every chunk id of every expected source** is
  included. The denominator is rows whose expected sources are all at most
  `note_max_chars`; ineligible rows are listed by name.
- **Counter-metric, gated:** mean assembled characters per row and, from the live
  runs, measured headless input tokens — reported as sections recovered per
  thousand added tokens. This is what stops "include everything" from passing.
- **Per row:** `included: whole | neighbours | seed-only`, `reason`, `chars`. Run
  level: `notes_included`, `hits_dropped`, `fallbacks`, `secret_drops`.
- **Fakes:** `fake_snapshot()` beside `fake_retrieval()` in conftest; the retrieve
  fakes are untouched; a scenario asserts no Chroma call in the eval path.

## Pre-registered expectations
Written before Slice B (ADR-0004: pre-register, then measure). With
`note_max_chars` 16,000, six section rows point at notes that qualify for
whole-note inclusion (the 4.9k reference note, the 2.0k decision note, the 10.8k
and 13.0k research notes); the EventBridge note (15.3k) qualifies at the edge;
nothing over 16k. Expected:

- **`context@4` at least 6 of 7** with both whole-note rows passing.
- **`note@4` at least 5 of eligible.**
- **Mean assembled characters under 14,000.**
- **Measured headless input tokens under 15,000** (from the 9,851 baseline).

Any row that misses must carry a reason **other than** `budget_exhausted` on a note
under the cap — otherwise the budget is wrong, not the eval.

**On the frozen set.** The two whole-note questions **already exist as golden
rows** and gain `expected_sections_all` rather than being added, so the frozen set
is **25 rows with 7 section rows** — six carrying `expected_section` (the
five-practices row also carrying `expected_sections_all`, i.e. both) plus the "why
not fork" row via the `expected_sections_all` field only. This is *not* the 27
rows / 8 section rows the plan first sketched when it assumed the two rows were
additions; the plan was corrected to 25 / 7 and the `6 of 7` target above is the
pre-registered figure. The set is frozen (sha256 recorded below)
before any assembler code, and `passage@4` and lead share are re-baselined on it as
the control.

## Control baseline (frozen set)
Golden file `~/.interchange/golden-brain.jsonl`, 25 rows, 7 section rows, frozen at
sha256 `b92dca860896af04ab332610d972764f9f3aa0af3a7f68e23fe69c3eb93b93d0`. The corpus
is frozen with it: 31 files / 513 chunks after the `30-Career/People/` and
`30-Career/Interviews/` ignore (rebuild 3.6 s). Plan notes in the vault quote the eval
questions and attract retrieval, so no new Brain notes land until Slice E has measured;
if the vault changes anyway the control is re-run immediately before Slice E and both
runs are recorded. **Measured** 2026-09-24, k=4, pool 20, rerank_n 30, cross-encoder;
`passage@4` still counts only the six `expected_section` rows (the ALL field is scored
from Slice C):

| mode | hit@1 | hit@4 | passage@4 | near-miss | absent | lead share |
|---|---:|---:|---:|---:|---:|---:|
| hybrid | 17/25 | 25/25 | 3/6 | 0 | 0 | 0.30 |
| dense | 18/25 | 24/25 | 2/6 | 1 | 0 | 0.32 |
| bm25 | 15/25 | 23/25 | 2/6 | 1 | 1 | 0.24 |
| hybrid+links | 9/25 | 20/25 | 2/6 | 5 | 0 | 0.29 |
| hybrid+rerank (profile default) | 17/25 | 22/25 | 2/6 | 2 | 1 | 0.25 |

Per section row under the default mode: five-practices source rank 3, passage miss;
audit-commands passage hit @1; long-horizon passage hit @2; checklist-memory source
absent at depth 10; options passage @5 (near-miss); EventBridge passage miss. These
per-row positions are the control that Slice E diffs against.

## Stated assumptions
Overturnable — if any is wrong, correct it here and re-measure:

- **`30-Career/People/` and `30-Career/Interviews/` leave the brain index.**
  Third-party names and interview notes must never assemble whole.
- **`note_max_chars` 16,000, `budget_chars` 20,000, policy cap 24,000.** Sized to
  the measured note-size distribution; the cap clamps the profile, not just the
  request.
- **The HTTP `context` knob is locked by default.** An operator unlocks it via
  `INTERCHANGE_UNLOCKED`; until then the body may not name it.

## Consequences
- **What becomes true.** Whole-note and section questions can be answered from the
  content, not just pointed at the right note; grounding, citation and audit follow
  the *included* set, so a budget-dropped note can never be a phantom citation;
  every surface (CLI, HTTP, MCP, A2A) resolves context settings through one path,
  closing the A2A/HTTP mode mismatch; the `context` telemetry schema is
  mode-independent; ranking, its per-row ranks, and rail/vault numbers are
  unchanged and stay the control.
- **Costs.** The context term of the shadow cost roughly **quadruples** (~4×) —
  at **$0 marginal** on the subscription, but honestly recorded. The explain
  transcript gains a **second locked baseline** (`notes`) to maintain alongside the
  byte-identical `chunks` one. The eval fake seam gains a **snapshot fixture**
  (`fake_snapshot`).
- **What it sets up.** A **retrieved-text injection scan** becomes the explicit gate
  for ever moving `research` (or any untrusted-text corpus) off `chunks` — its own
  ADR, its own trigger. The retrieve-vs-long-context **router trigger is unchanged**
  (corpus outgrows the window); this decision does not pre-empt it.
- **Follow-ups, not blocking** (P2 from the plan):
  - [ ] Pass the headless prompt on stdin instead of argv now that it carries whole
    personal notes.
  - [ ] Thread the snapshot through the `Retrieval` record so assembly and
    `index_meta` add no client construction or `count()` call.
  - [ ] LRU-bound `_SNAP_CACHE` to a few collections (~30 MB for all five today).
  - [ ] Build stamp written at reindex; snapshot cache keyed on `(count, stamp)` so
    a same-count rebuild is visible to a running server.
  - [ ] Record the shadow-cost line before and after (the context term ~quadruples).
  - [ ] The native abort at interpreter exit after `--mode all` with the reranker
    loaded: release the model, never `os._exit`, which drops buffered OTel spans.
  - [ ] Deep-merge the `retrieval` block in the overlay so a private `context` key
    does not drop the committed `mode`.

## Verification
This ADR flips to **Accepted** only once measured and recorded here (the way
ADR-0014/0016/0017 recorded theirs):

1. `pytest -q` green after each slice; `verify-change` scan against `dev`.
2. Golden set hash unchanged from Slice A through Slice F.
3. Rail explain transcript byte-identical on `chunks`; the `notes` transcript
   matches its own locked baseline.
4. Retrieval-record equality test green; per-row ranks identical before and after.
5. Pre-registered expectations met, or the slice reverted with the numbers
   recorded.
6. Audit rows show `included_sources`, the `context` fields, and `assemble_ms`; the
   metered budget check fires on the HTTP path.

**Accept / revert rule.** Accept when rail and vault ranking are unchanged with
identical per-row ranks, brain control columns match Slice A, `context@4` and
`note@4` meet the pre-registered expectations, mean chars and input tokens are
under their ceilings, and all three graded live answers pass. Otherwise record the
numbers, **revert the wiring (Slice D) in one commit, and keep Slices A–C** (the
frozen set, the fixed budget, the assembler, and the eval).

## Update 2026-09-24 — slice C measured; stop rule fired; expansion rule revised
Slice C (c82fc97) built `context@k`, `note@k` and the chars counter-metric on the assembled
context. Ranking columns are identical to the control across all runs (assembly is after
ranking, now proven, not asserted). **Measured** on the frozen set, profile default
(`hybrid+rerank`, `notes`, budget 20,000, cap 16,000):

| expectation | pre-registered | measured | result |
|---|---|---|---|
| context@4, both whole-note rows passing | ≥ 6/7 | 4/7, both whole-note rows miss | **fail** |
| note@4 | ≥ 5 of eligible | 17/24 | pass |
| mean assembled chars | < 14,000 | 16,702 (max 20,000) | **fail** |

Both whole-note misses carry `budget_exhausted` on notes under the cap (the 1,978-char
decision note and the 4,918-char reference note, both at source rank 3). Knob variants
run on the eval before touching the design:

| budget | cap | context@4 | note@4 | mean chars |
|---:|---:|---:|---:|---:|
| 20,000 | 16,000 | 4/7 | 17/24 | 16,702 |
| 24,000 | 16,000 | 5/7 | 20/24 | 18,845 |
| 20,000 | 8,000 | 4/7 | 10/15 | 16,702 |
| 20,000 | 6,000 | 4/7 | 8/13 | 16,702 |
| 12,000 | 6,000 | 4/7 | 7/13 | 10,865 |
| 24,000 | 6,000 | 5/7 | 9/13 | 18,845 |

Mean chars sit at the budget whatever the cap. **Reading:** the fault is the expansion
rule, not a knob. Pass 2 lets the first hits spend the whole budget — a big note is
included whole up to the cap, and an over-cap note's neighbour fallback "widens while
budget remains" — so a small target note at rank 3 never gets its turn. The corpus
made this vivid: the largest brain note (20,160 chars) is this ADR's own plan note, which
quotes the eval questions and outranks the notes the questions are about. The corpus stays
frozen; the self-referential trap is recorded, not edited away.

**Revised rule (slice B′), pre-registered before the code moves.** Pass 1 unchanged
(seed every hit). Pass 2, *fair share*: each hit gets `(budget − seeded) / n_hits`; in
rank order a hit takes its whole note if the note is under the cap and fits its share,
else neighbours bounded to ±1 chunk within its share. Pass 3, *redistribute*: the unspent
remainder, in rank order, first completes notes that now fit whole, then widens neighbours
to ±2. Neighbours never widen beyond ±2. Expectations unchanged: context@4 ≥ 6/7 with both
whole-note rows passing, note@4 ≥ 5 of eligible, mean chars < 14,000. The checklist-memory
row is `not_retrieved` (a ranking miss) and is the one row assembly cannot recover, so 6/7
is the ceiling. Knobs unchanged (20,000 / 16,000). Slice D stays unstarted until the
revised assembler meets the expectations on the eval.

## Update 2026-09-24 — slice B′ measured; knob decision; stop rule passes
Slice B′ (fa7129e) implemented the fair-share rule. **Measured**, profile default
(`hybrid+rerank`, `notes`, 20,000 / 16,000): context@4 **6/7** with both whole-note rows
recovered, note@4 **19/24**, mean chars **14,509** — two of three expectations met, the
chars ceiling missed by 3.6%. The one context miss is a ranking miss (source absent at
depth 10), the pre-registered ceiling. Budget sweep on the eval, cap 16,000: 18,000 →
5/7 at 13,038; 17,000 → 5/7 at 12,550; 16,000 → 4/7 at 10,850. Cap 12,000 variants: 4/7.
Under the ceiling the 15,395-char EventBridge note stops fitting and its row falls back;
the pair (6/7, < 14,000) is not jointly reachable at any budget with the reranker on.

**Knob decision.** The `--mode all` table shows plain `hybrid` with `notes` at **7/7,
21/24, mean 12,961**, inside every ceiling. On this corpus the control already had hybrid
equal or better than rerank on every ranking column (hit@4 25/25 vs 22/25; passage@4 3/6
vs 2/6), and ADR-0016 recorded that the reranker's vault win did not transfer to the brain
set. The brain overlay's `mode` is therefore set to `hybrid` (a profile key, reversible;
the vault profile keeps `hybrid+rerank`, its measured best). Confirmed as the profile
default: hit@1 17/25, hit@4 25/25, passage@4 3/6, lead 0.30 (identical to the control's
hybrid row); **context@4 7/7, note@4 21/24, mean chars 12,961, max 19,761**; 43 whole,
24 fallbacks, 0 secret drops, 11 budget hits. No pre-registered expectation was changed.
Slice D (wiring) proceeds on this configuration; slice E re-measures it live.

## Update 2026-09-24 — slices D and E: wired, measured on every surface, Accepted
Slice D (a18c121) wired assembly into `answer_detail` behind one resolver (argument >
collection profile > default, clamped by policy; `chunks` when pinned or on any failure),
made `sources` the included set with `hit_sources` recorded separately, added the
mode-independent `context` block to the retrieve frame, the HTTP response and done event,
the audit row and an OTel `assemble` span, locked the HTTP `context` knob by default
(`INTERCHANGE_UNLOCKED` opens it; `/options` reports the lock), pinned `search_docs` to
`chunks`, and fixed A2A to resolve the profile's retrieval mode. The `chunks` explain
transcript is byte-identical; a second locked baseline covers `notes`; a test pins the
scored `Retrieval` record equal before and after assembly. Known remaining mismatch,
recorded: the HTTP surface keeps its request/policy-driven retrieval mode (default
`hybrid`) rather than the profile's, to keep the existing lock semantics; brain's mode
is `hybrid`, so it has no effect there; vault over HTTP runs `hybrid` not `hybrid+rerank`.

**Slice E, measured** (k=4, pool 20; brain profile `hybrid`/`notes`/20,000/16,000):

| gate | required | measured | result |
|---|---|---|---|
| rail hit@1 / hit@4 | 14/14 unchanged | 14/14, 14/14 (context n/a, mean 1,508 chars) | pass |
| vault hit@1 (`chunks`) | 15/18 unchanged | 15/18 (mean 1,892 chars) | pass |
| brain ranking columns | identical to control | hit@1 17/25, hit@4 25/25, passage@4 3/6, lead 0.30; **0 per-row rank differences** vs the pre-wiring chunks run | pass |
| brain context@4 | ≥ 6/7, both whole-note rows | **7/7** | pass |
| brain note@4 | ≥ 5 of eligible | **21/24** | pass |
| mean assembled chars | < 14,000 | **12,961** (max 19,761) | pass |
| headless input tokens, mean of 3 live | < 15,000 | **14,615** (16,614 / 15,744 / 11,486; baseline 9,851) | pass on the mean; two single runs over |
| live answers grounded | 3/3 | 3/3, `grounded` true in the audit rows | pass |
| graded answers (3-row pre-registered rubric, `~/.interchange/graded-brain.jsonl`) | pass | **answer-correctness 93%** (0.80 / 1.00 / 1.00), **faithfulness 97%** | pass |

Live detail: the five-practices question now lists five practices with an evidence trail
(4 notes, 33 chunks, 19.4k chars, 14.6 s, shadow cost $0.068 at $0 marginal); the
checklist-memory question quotes the three Memory items (25 chunks, 17.5k chars, 6.8 s);
the fork question gives the reasoning from the decision note (12 chunks, 6.3k chars,
9.7 s). Assembly itself costs 2–3 ms; generation dominates latency. The shadow-cost line
roughly tripled on the context term, as ADR-0004's honesty rule expects to see recorded.

**A defect the gate found.** The first graded run scored 40% / 56%: `eval_judge._generate`
reproduced the pre-ADR-0018 path by hand (raw top-k chunks, no persona, no assembly, no
included-sources grounding) and so graded a context no surface builds any more. Fixed in
68e7eb0: the judge now calls `answer_detail(audit=False)` and grades the governed path
(ADR-0008 updated). The 40% is kept here as the honest "before" of the same three answers.

**Follow-ups (P2, not blocking):** replace the judge's scoped audit-path redirect with an
explicit write flag on `enterprise.audit`; HTTP retrieval mode from the profile once the
lock semantics are extended to it; the P2 checklist from the plan (stdin prompt, snapshot
threading, cache bound and build stamp, overlay deep-merge). The `research` corpus stays on
`chunks` until a retrieved-text injection scan exists. The brain corpus freeze is lifted.
