# ADR-0017: Passage-level retrieval quality and lead-chunk handling

- **Status:** Accepted (2026-09-24) — metric built and kept; lead detection kept; merge rejected on measurement
- **Date:** 2026-09-23
- **Deciders:** Jeff Lynch

## Context
The first live questions against the `brain` corpus (ADR-0016) surfaced a failure
the source-level eval cannot see: **the retriever finds the right note and returns
the wrong passage.**

`chunk()` (`interchange.py:194`) splits on Markdown headings and keeps everything
before the first heading as section **`preamble`** (ADR-0007's structure-aware
chunking). A note that opens with YAML frontmatter therefore yields **two tiny
chunks before any body section**: the preamble (the frontmatter, ~190 chars) and
the H1 section (title plus intro, ~285 chars) — both measured on the Brain
reference note — ahead of the first real body section (~600 chars). Those two
lead chunks are short and dense with exactly the topic tokens (`tags`, `type`,
`project`, the title), so both BM25's length normalisation and the dense embedder
prefer them over the longer body sections that carry the actual content. ADR-0014
kept frontmatter in the indexed text **on purpose** — those tokens lift BM25
recall, measured — so this is the cost of a decision that was right, not a bug in
it.

**Measured, 2026-09-23** on the brain corpus (28 notes, 448 chunks, `hybrid+rerank`,
pool 20, rerank_n 30, local cross-encoder). For *"Give me the five most important
Claude Code practices for September 2026 and where the evidence came from"* the
top-4 were:

1. the reference note's **H1** section,
2. the research note's **H1** section,
3. the harness research note's **H1** section,
4. the AI-Tools MOC's **"Conventions"** section.

At `top_k=8` the research note's **"What I learned"** body reached only rank 8, and
the reference note's checklist sections (**"Setup"**, **"Working"**) never appeared
at all. The live answer **named the right notes and could not list a single
practice** — correct about what to read, empty about its content.

**Why the eval did not catch it.** `run_eval` (`interchange.py:1854`) scores a hit
when the expected *source file* appears in the top-k, via `rank_of_expected` and
`hit_at_k` (`interchange.py:729`, `:737`) over source paths. Brain **hit@4 is
18/19** on that metric — every question finds its note. Passage-level quality is
invisible to it. The same shape appeared earlier the same day on a "why" question
over the decision note (the *Decision* section retrieved, the *Options* section
missed), recorded in ADR-0016's update as a gap rather than fixed.

The constraints from earlier ADRs bind: frontmatter stays indexed (ADR-0014's
measured win), chunk ids are `source:index` and golden `expected_source` paths
must not move, the pytest gate stays offline and free (ADR-0005/0006), and every
number here is measured or labelled an estimate (ADR-0004).

## Options considered
1. **Lead-chunk merge at ingest** — fold the `preamble` and H1 chunks into the
   first body chunk of the same note when their combined size is under a threshold,
   so the topic tokens and the first real section travel together. Deterministic,
   no query-time cost, one function. **Chosen for measurement first.**
2. **Same-note neighbour expansion at query time** — when a top hit is a lead
   chunk, pull the next N chunks of the same source and re-rank. This is the
   within-a-note cousin of the **cross-note link expansion ADR-0014 measured and
   rejected** (naive 1-hop regressed hit@1 by 5 rows). **Deferred**, trigger: option 1
   leaves `passage@k` short.
3. **Per-profile `retrieval.top_k`** — a `retrieval.top_k` key so the brain profile
   can ask for 8. Cheap, but it costs context tokens, and **measured alone at k=8 it
   still missed** the checklist sections. Built as a knob, **not a fix.**
4. **Drop frontmatter from indexed text** — reverses ADR-0014's measured recall
   win. **Rejected.**
5. **Short-chunk penalty in fusion** — a heuristic with **no principled threshold**.
   **Rejected.**

## Decision
**Build the metric before the fix.** Passage-level quality is a number we do not
have; option 1 is the cheapest fix, but it must be *measured* against a metric that
can see the problem, not assumed.

- **Slice 2 — section-aware eval.** Golden rows gain an optional `expected_section`
  (case-insensitive substring match on a chunk's `section` label; a list is allowed).
  `run_eval` reports a **`passage@k`** column next to the unchanged **`hit@k`**
  (a top-k chunk whose source *and* section match), plus a **`lead share`**
  diagnostic — the fraction of top-k hits whose section is `preamble` or the note's
  H1. `lead share` is the number the merge must move. Rows without `expected_section`
  score **source-only**, exactly as today, and the summary reports how many rows
  carry a section.
- **Slice 3 — lead-chunk merge at ingest** (option 1). **Accepted only if** rail
  stays **14/14**, vault stays **15/18** (`hybrid+rerank`) with **11/18** `hybrid`
  as the control, **and** brain **`passage@4` rises**. Otherwise the merge is
  reverted, the eval is kept, and option 2 is promoted with these numbers as its
  trigger.
- **Slice 4 — `retrieval.top_k` per profile** (option 3), built as a declared knob,
  set for `brain` only if Slice 3's measurement shows the merge alone is not enough.

## Consequences
- **Chunk ids stay `source:index`**, so golden `expected_source` paths do not move
  and the existing source-level baselines stay verifiable rather than reasserted.
- The merge **changes chunk counts** for every note with a lead chunk, so it forces
  a **full reindex** — ~30 s on the largest corpus (vault, 4,614 chunks, ADR-0016
  measured), which is fine.
- The eval **gains a second headline number** (`passage@k`) and **must keep
  reporting the old one (`hit@k`) unchanged**, so the ADR-0014/0016 source-level
  tables stay comparable across the change.
- Rows **without an `expected_section`** score source-only, so the metric is
  additive: no existing golden row changes meaning.
- This sets up option 2 (same-note neighbour expansion) as the **next** decision if
  the merge falls short, and leaves a `lead:` metadata flag on merged chunks that a
  future fusion boost/penalty could key on — trigger-gated, not built now.

## Verification
This ADR flips to **Accepted** only once the following are **measured** (ADR-0004:
measured, not asserted) and recorded here in an `## Update` section, the way
ADR-0014 and ADR-0016 recorded theirs:

- **Baseline `passage@4` and `lead share`** on the brain corpus **before** Slice 3
  (the number that proves the metric sees the problem — the five-practices row is a
  source hit and a passage miss), and **both again after** the merge.
- **Rail unchanged at 14/14** and **vault at 15/18 (`hybrid+rerank`), 11/18
  (`hybrid`) control** — the source-level numbers do not regress.
- **Rebuild seconds** for the full reindex the merge forces.
- The **live five-practices question** answering with actual practices **and
  citations**, not just naming the right notes.

## Update 2026-09-23 — metric built, baseline recorded (slices 0-2)
Slice 2 landed `expected_section`, `passage@k` and `lead share` (296 tests, then 301
after the slice-1 merge). The brain golden set has 25 rows, 6 with sections. **Measured**
baseline before any retrieval change (k=4, pool 20, rerank_n 30, cross-encoder):

| mode | hit@1 | hit@4 | passage@4 | lead share |
|---|---:|---:|---:|---:|
| hybrid+rerank (profile default) | 19/25 | 23/25 | 3/6 | 0.12 |
| hybrid (control) | 20/25 | 25/25 | 3/6 | 0.14 |

The five-practices row is a source hit at rank 1 and a passage miss in both modes, as is
the EventBridge row; the memory row passes under hybrid and misses under rerank, the
options row the reverse. Live after slice 1: the answer still names the notes and not
the practices, now without connector chatter. This table is what slice 3 must move.

## Update 2026-09-23 — slice 3 step 1: lead is structural; corrected baseline
Step 1 (bda36b3) made "lead" structural — the `preamble` chunk plus the first level-1
heading section, stored as chunk metadata `lead` — after noticing that slice 2's
title-equals-filename heuristic missed two of the three notes that triggered this ADR
(their H1 differs from the filename). The **corrected** pre-merge baseline, all three
corpora rebuilt with the flag (k=4, pool 20, rerank_n 30, cross-encoder; brain now 30
notes / 485 chunks after two plan notes were added):

| corpus | mode | hit@1 | hit@4 | passage@4 | lead share |
|---|---|---:|---:|---:|---:|
| rail (14) | hybrid | 14/14 | 14/14 | n/a | 0.18 |
| vault (18) | hybrid+rerank | 15/18 | 15/18 | n/a | 0.08 |
| vault (18) | hybrid | 11/18 | 14/18 | n/a | 0.06 |
| brain (25, 6 with sections) | hybrid | 19/25 | 25/25 | 3/6 | 0.28 |
| brain | dense | 19/25 | 25/25 | 3/6 | 0.32 |
| brain | bm25 | 17/25 | 23/25 | 2/6 | 0.25 |
| brain | hybrid+links | 10/25 | 23/25 | 3/6 | 0.28 |
| brain | hybrid+rerank (profile default) | 18/25 | 22/25 | 3/6 | 0.26 |

Slice 2's 0.12 was an undercount; the real lead share on the brain corpus is a
quarter to a third of every top-4. Rebuilds: rail 0.3 s, brain 3.4 s, vault 30.4 s.
One operational note: the brain `--mode all` run printed its table and then aborted at
interpreter exit with a native `recursive_mutex lock failed` from library teardown
(cross-encoder + Chroma in one process); the numbers above were printed before it.
Tracked, not fixed here.

## Update 2026-09-23 — slice 3 step 2 measured and reverted; slice 3b opened
The lead-chunk merge (965e326: fold preamble + first H1 into the first body chunk when
the lead is ≤ 600 chars) was built, every corpus rebuilt, and the four gates measured
(k=4, pool 20, rerank_n 30, cross-encoder):

| corpus | mode | hit@1 before → after | hit@4 | passage@4 | lead share | gate |
|---|---|---:|---:|---:|---:|---|
| rail | hybrid | 14/14 → **13/14** | 14/14 | n/a | 0.18 → 0.04 | **fail** |
| vault | hybrid+rerank | 15/18 → **12/18** | 15/18 → 14/18 | n/a | 0.08 → 0.04 | **fail** |
| vault | hybrid (control) | 11/18 → 11/18 | 14/18 → 14/18 | n/a | 0.06 → 0.04 | held |
| brain | hybrid+rerank (default) | 18/25 → 19/25 | 22/25 → 22/25 | 3/6 → **3/6** | 0.26 → 0.12 | **fail** |
| brain | hybrid | 19/25 → 17/25 | 25/25 → 23/25 | 3/6 → 4/6 | 0.28 → 0.13 | — |

Chunk counts after the merge: rail 12 → 10, vault 4,614 → 4,308 (159 notes merged), brain
485 → 454 (20 merged); rebuilds 0.3 / 27.3 / 3.1 s. The live five-practices question still
answered with pointers and no practices; its top-4 now included the plan note that
*describes* this very bug, which is a self-referential trap any corpus of working notes
carries.

**Reading.** Lead share fell on every corpus, so the merge did exactly what it was designed
to do — and the corpus-level numbers got worse where the reranker is in play. The vault
`hybrid` control held while `hybrid+rerank` lost three rows, which points at the merged
chunks themselves: longer texts (lead + body, not re-windowed) give the cross-encoder less
focused passages, and on rail the merge cost one exact-match row. The one gain (brain
`hybrid` passage@4 3/6 → 4/6) was not in the profile's default mode. Three of four gates
failed; the merge is **reverted** (66beeee), the store rebuilt on the reverted code, and
the pre-merge numbers reproduce (rail 14/14, vault 15/18, brain 18/25, passage@4 3/6,
lead share 0.26).

**Kept.** Structural lead detection (`lead` metadata, step 1) and the passage-level eval.

**Slice 3b, triggered by this table:** same-note neighbour expansion at query time — when a
top hit is a lead chunk, also score the next chunk(s) of the same source and let the
fused/reranked list decide. Zero ingest change, no long chunks for the reranker, and the
expansion can be a profile `retrieval` key so rail is untouched. Two cheaper variants to
measure alongside it: merge the *preamble only* (frontmatter, ~190 chars) and leave the H1
intro as its own chunk; and re-window merged text at `CHUNK_CHARS` so the reranker sees
bounded passages. Accept criteria unchanged from slice 3. Also on the list: the native
`recursive_mutex` abort at interpreter exit after `--mode all` with the cross-encoder
loaded (reproduced twice; output is complete before it; exit code is not).

## Update 2026-09-24 — Accepted: metric and lead detection kept, merge reverted, problem carried by ADR-0018
The passage-level eval (`expected_section`, `passage@k`, `lead share`) and structural
lead detection (the `lead` chunk-metadata flag) **stay** — both proved useful and
neither regressed a corpus number. The lead-chunk **merge is reverted** and not
pursued: it did what it was designed to do (lead share fell everywhere) yet broke the
reranker on vault and an exact match on rail, so ranking is the wrong place for the
fix.

The problem this ADR found is real and **unsolved by ranking**: retrieval finds the
right note but the assembled top-4 is the wrong slice of it — whole-note questions
never fit and section questions lose to the lead chunk. That problem is re-stated and
carried forward by **[ADR-0018](0018-context-assembly-with-a-budget.md)**, which
separates the unit of retrieval from the unit of context (two-pass budgeted
assembly), leaving this ADR's ranking, chunking and reranker untouched as the control.
