# ADR-0014: Vault corpus — recursive ingestion, read-only profile, and measured retrieval ablations

- **Status:** Accepted
- **Date:** 2026-09-22
- **Deciders:** Jeff Lynch

## Context
ADR-0007 chose hybrid retrieval (BM25 + dense, fused with RRF) and measured it:
on the 14-question golden set over the two seed docs, hybrid scored **14/14**
against dense-only's **13/14**. It deferred **reranking** ("when the eval shows
precision headroom") and the **router / agentic multi-hop** ("when the corpus
outgrows the context window") behind explicit triggers. Neither has fired,
because neither is currently a number: 14 questions over two documents cannot
produce one.

Ingestion is the other limit. `build_index()` globs `DOCS_DIR/*.md|txt|pdf`
**flat** and records `source` as the **basename** — fine for two seed files,
wrong for anything with folders.

The corpus that would change this is already on disk: a personal **Obsidian
vault**, roughly **207 Markdown notes, ~2.2 MB, ~1,100 wikilinks**, in PARA
folders. It brings every problem the flat glob has never faced: **duplicate
basenames** (`Index.md` three times, `ROADMAP.md` and `Welcome.md` twice each),
which Chroma rejects outright since ids are `f"{name}:{j}"`; **nested
`.obsidian/` directories**; a **secret-bearing root note** holding live keys; a
`Templates/` folder of Templater `<% %>` placeholders; and large raw research
dumps that are noise. It also brings what the seed corpus cannot: a real link
graph.

An internal research pass on 2026-09-22 surveyed whether link- or graph-aware
retrieval beats hybrid. The verdict is unhelpful to anyone hoping to build a
graph:

- **Single-hop / fact QA: graph never wins.** Han et al. (arXiv 2502.11371) put
  dense/hybrid at 64.78 F1 on NQ against 63.01 for the best graph method; Cahoon
  (arXiv 2503.02922) has hybrid at 61.7 against GraphRAG's 54.9.
- **Multi-hop gains are modest and only from cheap, RRF-seeded expansion.**
  SPRIG (arXiv 2602.23372) reports HotpotQA Recall@10 of 0.867 for graph
  expansion *seeded by RRF* against 0.851 for RRF alone — and 0.775, a loss, for
  the same expansion **without** RRF seeds. HippoRAG2 adds about +3 F1 overall.
- **Community-summary GraphRAG loses on real corpora** (WildGraphBench, arXiv
  2602.02053: naive 15.84 F1 against MS-GraphRAG's 13.78, on graph's own home
  task) and costs **4 to 25 LLM tokens per corpus token** to index.
- **Link expansion specifically is near-inert:** LARAG (arXiv 2605.07517)
  measured **+0.0004 F1** for **+35% tokens**.
- **No published measurement exists at personal-vault scale.** Every Obsidian
  graph plugin ships with zero eval; the one published vault benchmark is
  hybrid-only, with no link ablation.

So the research says *don't build the graph*, and says nothing at all about this
shape of corpus. The decision here is therefore not "add graph retrieval". It is
**build the trigger, not the feature**: point the existing runtime at a corpus
big and linked enough for ADR-0007's deferred triggers to become numbers, and
let those numbers decide what gets built next. The vault is **read-only**
throughout; nothing in this work writes into it.

## Options (the menu)
1. **Recursion: always with an ignore file, vs opt-in behind a flag.** Always is
   one code path, so seed corpus and vault are ingested by identical logic and
   the ignore file is the only lever; the cost is that `docs/adr/` would silently
   join the `edi` collection unless something excludes it. Opt-in keeps today's
   behaviour bit-identical but leaves two paths to test and a flag to remember.
2. **Ignore mechanism: gitignore-lite file + defaults + env, vs full gitignore
   semantics, vs a hardcoded list.** Gitignore-lite (directory patterns, basename
   globs, path globs) covers every case this corpus has, in pure functions that
   unit-test offline. Full semantics (negation, `**`, precedence) means a
   dependency or a parser worth more than the problem. A hardcoded list needs a
   code edit and a test change per corpus.
3. **Source identity: relative POSIX path, vs basename plus a separate path key.**
   Relative path is one field that is already unique, and on a flat corpus it is
   *equal to* the basename, so nothing downstream moves. Basename plus a path key
   keeps `source` short but leaves ids colliding on duplicate titles and forces
   every consumer (eval, audit, citations) to learn which key means what.
4. **Frontmatter: keep it in the indexed text, vs strip it.** Keeping it feeds
   BM25 the tokens a vault carries deliberately (`tags`, `type`, `project`) at a
   cost of a few lines of YAML noise per chunk. Stripping gives the dense encoder
   cleaner prose and discards the corpus's own hand-written index terms.
5. **Credential guard: none, vs a pattern guard as a second layer.** None trusts
   one ignore list to be complete forever. A pattern guard is a heuristic that
   will miss novel shapes, but it fails closed on the common one and turns
   "I remembered to list that file" into "the pipeline also checks".
6. **Ablation switch: `retrieve(mode=...)` keyword parameter, vs separate
   functions, vs an env var.** A keyword-only parameter with a default leaves
   every positional caller and every test monkeypatch untouched and keeps one
   seam. Separate functions duplicate the embedding and BM25 plumbing four ways.
   An env var makes the mode ambient and invisible at the call site and in the log.
7. **Link expansion: append neighbours, vs re-fuse through RRF.** Appending is
   trivial and guarantees neighbours rank below every fused hit, which is exactly
   the arrangement that cannot win. Re-fusing treats the link list as a third
   ranking: the **RRF-seeded** pattern, the only graph design the research found
   robust (SPRIG: seeded 0.867, unseeded 0.775).
8. **Reranker backend: local cross-encoder, vs TypeSafe, vs none.** The local
   cross-encoder (`ms-marco-MiniLM-L-6-v2`) is $0, offline, and ADR-0007's
   original plan. TypeSafe's System One (Jev) scores one Noul per
   question-candidate pair: metered, roughly 100 ms per pair, returning a
   **calibrated probability** rather than an uncalibrated score — worth measuring
   once against a free baseline. None keeps the dependency tree as it is and
   leaves ADR-0007's trigger untested.
9. **Where the vault lives: an A2A profile block, vs a new module.** ADR-0013
   already made the vertical **data, not code**: `a2a_agent/profiles.yaml` holds
   `rail` and `hotel` and the executor binds a collection per profile. A third
   block reuses that whole mechanism; a new module would be a second, competing
   way to say "which corpus".

## Decision

**Now.**

- **Recursive ingestion, always**, with a gitignore-lite exclusion stack:
  `docs/.interchangeignore` (containing `adr/`), a `DEFAULT_IGNORE` of
  `.obsidian/`, `.trash/`, `.git/`, `_attachments/`, an unconditional rule that
  **any path segment beginning with a dot is ignored**, and `INTERCHANGE_IGNORE`
  for per-run additions. Patterns support directory segments, basename globs and
  path globs; nothing else.
- **`source` is the relative POSIX path** from the corpus root. On a flat corpus
  this equals the basename, so `eval/golden.jsonl` and `hit_at_k` are untouched
  and the 14/14 baseline stays verifiable rather than assumed.
- **Frontmatter stays in the indexed text.** `tags`, `type` and `project` are
  precisely the BM25 tokens this corpus was written to carry.
- **A `looks_like_secret()` guard** as a second layer: a credential keyword
  followed by a long opaque run causes a **WARN and skip**, counted in the
  indexing summary.
- **`retrieve(question, *, mode, top_k, pool)`**, keyword-only with today's
  defaults, over a pure `fuse_rankings()`. Modes: **`hybrid`** (RRF, default),
  **`dense`**, **`bm25`**, **`hybrid+links`**, **`hybrid+rerank`**.
- **`hybrid+links`** re-fuses the one-hop wikilink neighbours of the **top 3
  fused notes** through RRF as a third ranking, not as an appended tail.
  Invariant: with no links resolved, it ranks identically to `hybrid`.
- **`hybrid+rerank`** defaults to the **local cross-encoder** ($0). **TypeSafe is
  opt-in** via `INTERCHANGE_RERANK`, never runs in the pytest gate, and its
  metered calls are counted and labelled **`estimated`** (ADR-0004).
- **The vault is a `vault:` profile block** in `a2a_agent/profiles.yaml` (data,
  not code, per ADR-0013), carrying its `collection`, a `docs_dir` from
  `${INTERCHANGE_VAULT_DIR}`, an `ignore` list and a `golden` path.
- **`--eval` gains `--golden`, `--corpus`, `--mode`, `--depth`, `--pool`** and
  appends **one JSONL row per run** to `eval/eval-runs.jsonl` (gitignored)
  recording the **rank of the expected source** per question, the **near-miss
  count** (expected found within `depth` but outside `k`) and a rank histogram.
  Near-miss is ADR-0007's "precision headroom" trigger, expressed as a number.
- **A user-vetted `eval/golden-vault.jsonl`**, drafted from the indexed notes and
  vetted by the user before the first scored run.

**Sequencing.** The **links ablation is built and measured now**: it is the only
expansion design with robust evidence behind it, and nobody has published this
measurement at vault scale. The **reranker slice is gated on near-miss > 0** on
the hybrid vault run. If there is no headroom, ADR-0007's reranker stays deferred
for a measured reason instead of an assumed one.

**Still deferred.** Entity graphs, community summaries, and the
retrieve-vs-long-context router; their triggers are unchanged.

## Consequences
- The vault stays **read-only**, and its index lives under the **repo's**
  `.chroma`, not inside the vault.
- The `edi` collection's ids and sources are **unchanged**, because relative path
  equals basename on a flat corpus. Verified, not asserted: 14/14 hybrid and
  13/14 dense must both reproduce.
- **`pool` and `depth` become logged parameters.** RRF over a longer candidate
  list can change top-k, so a result is only comparable against a run with the
  same pool and depth. Defaults match today's values.
- **Duplicate titles** in link resolution resolve by Obsidian's own shortest-path
  rule, and links that resolve to nothing are **counted and reported**, so the
  link graph's real coverage is visible instead of assumed.
- **`--eval` stays a manual runner outside the pytest gate.** It touches
  embeddings, so it cannot be offline and free; only pure functions are gated.
- **Ignore-lite has no negation and no `**` patterns.** A corpus needing either
  gets a real gitignore parser, and that is a new decision.
- **The credential guard is a heuristic, not a scanner.** It will miss shapes it
  was not written for; it is a second layer behind the ignore list, never the
  first.
- **The vault profile needs `INTERCHANGE_VAULT_DIR` exported from the shell**,
  because `DOCS_DIR` resolves at import and `.env` loads after the `--eval`
  branch. A `.env` entry would be read too late: a sharp edge worth stating
  rather than hiding.
- If the numbers say links and reranking do not help on this corpus, **that is a
  result and it gets published here**. The point of the slice is the measurement,
  not the feature.

## Update — built and measured (2026-09-22)
Built the "Now" slice and ran it. The vault is ingested read-only: **188 notes,
4,614 chunks** reach the index (after the ignore stack and the credential guard),
and a **user-vetted `eval/golden-vault.jsonl`** of **18 rows** (5 exact, 5
paraphrase, 5 linked, 3 duplicate-title; row 11 accepts two sources) was scored
against it. Retrieval config: `k=4`, `depth=10`, rerank window 30, local
cross-encoder `ms-marco-MiniLM-L-6-v2` ($0, telemetry **measured**). Every number
below is from `eval/eval-runs.jsonl` (timestamped 2026-09-22); nothing here is
asserted.

**Vault, pool = 20** (`mode | hit@1 | hit@4 | near-miss | absent`):

| mode | hit@1 | hit@4 | near-miss | absent |
| --- | --- | --- | --- | --- |
| hybrid | 11/18 | 14/18 | 1 | 3 |
| dense | 9/18 | 12/18 | 4 | 2 |
| bm25 | 9/18 | 10/18 | 1 | 7 |
| hybrid+links | 6/18 | 13/18 | 2 | 3 |
| hybrid+rerank | 15/18 | 15/18 | 0 | 3 |

**Vault, pool = 50** (RRF over a longer candidate list — a logged parameter, so
comparable only against another pool-50 run):

| mode | hit@1 | hit@4 | near-miss | absent |
| --- | --- | --- | --- | --- |
| hybrid | 12/18 | 14/18 | 3 | 1 |
| dense | 9/18 | 12/18 | 4 | 2 |
| bm25 | 9/18 | 10/18 | 1 | 7 |
| hybrid+links | 4/18 | 13/18 | 3 | 2 |
| hybrid+rerank | 15/18 | 17/18 | 0 | 1 |

**Rail seed corpus** (14 answerable rows, 3 docs, 12 chunks), as a control:
hybrid **14/14**, dense **13/14**, bm25 **13/14**, `hybrid+links` **14/14**
(identical to hybrid — the seed corpus carries no wikilinks, so the invariant
holds), `hybrid+rerank` **13/14 @1 and 14/14 @4** — a mild reorder within an
already-perfect top-4, where there was no headroom to gain. ADR-0007's 14/14 vs
13/14 reproduces, so the ablation harness is verified, not assumed.

**Where the misses are (hybrid, pool 20).** Every miss is a **paraphrase** row —
rows 6, 8, 9, 10 sit at ranks 5, absent, absent, absent at depth 10; at depth 30
they sit at 5, 7, 16, absent. Dense-only ranks three of those at 1, 7, 5, so
**fusing with BM25 buries them**: the exact-token signal that rescues codes drags
down questions whose match is purely semantic. Every **exact**, **linked**, and
**duplicate-title** row hits at k=4 under plain hybrid.

**Why `hybrid+links` regressed.** One-hop expansion from the top-3 fused seeds hurt
even the linked rows it was meant to help (row 16 rank 2 → 8; row 13 rank 1 → 3):
hub notes — project Index / MOC notes — carry dozens of wikilinks, and the third
RRF list weights every neighbour equally, so expansion adds noise faster than
signal. **164 of the vault's wikilinks were unresolved** (Templater placeholders,
links to non-Markdown attachments, dangling titles), so the link graph's real
coverage is lower than its raw count suggests — counted and reported, per the
Consequences above.

**Credential guard.** Its first version **skipped 13 of 188 notes**, all false
positives on placeholders and code (`your-api-key`, `process.env.X`, `KEY_xxxxxx`,
`z.string()`). Tightened to require a literal 20+ char value with 3+ digits, a
placeholder denylist, and known key shapes, it now skips **0**; a digit-free
passphrase is an accepted false negative (the guard is a second layer, never the
first). `<secret-note>.md` is excluded by the profile ignore list and never
reaches the guard at all.

### Verdicts on the triggers

- **ADR-0007 reranker trigger ("when the eval shows precision headroom") — FIRED
  and PAID OFF.** The hybrid run showed near-miss > 0: **4 rows** sat in top-10 but
  outside @1. The local cross-encoder recovered **3 of them to rank 1** (hit@1
  **11 → 15/18**), and at pool 50 recovered a 4th into top-4 (**hit@4 17/18**), at
  **$0** and offline. Reranking stays an **eval mode and an opt-in**; whether to make
  it the **default retrieval path** is a separate decision, gated on latency and on
  confirming the rail `hybrid+rerank` 13/14 @1 is not a real loss (it is a reorder
  within a perfect top-4, no headroom lost). Caveat recorded honestly: the rerank
  **window of 30 was chosen after seeing where the misses sat** (fused ranks up to
  16) — a fitted parameter, not a blind default.
- **Link-aware expansion trigger ("when linked-neighbourhood questions miss") — NOT
  FIRED.** Linked rows all hit under plain hybrid, and naive 1-hop expansion
  **regressed hit@1 by 5 rows**. This matches the literature the Context cites (LARAG
  +0.0004 F1; SPRIG: unseeded graph expansion loses to RRF). **Deferred** with a
  new, narrower trigger: build it only if a **future golden set shows linked rows
  missing under `hybrid+rerank`**; a cheap variant worth one run then is expansion
  from the **top-1 seed only**, or neighbours **down-weighted in RRF** rather than
  equal-weighted.
- **TypeSafe Jev reranker — MEASURED (2026-09-22).** Run like-for-like against the
  local cross-encoder on this same 18-row golden set; the numbers, per-row reading,
  cost note and verdict are in the **TypeSafe Jev reranker — measured** subsection
  below. It is labelled **estimated / metered** (ADR-0004), never mixed with the $0
  numbers above.

### TypeSafe Jev reranker — measured (2026-09-22)

Run like-for-like against the local cross-encoder on the vault golden set (18 rows,
`k=4`, rerank window 30, mode `hybrid+rerank`). The key came from the **macOS
keychain** (service `typesafe`), loaded into the process env **at run time** — never
written to a file. Each TypeSafe run made **540 Noul calls** (18 questions × 30
candidates), telemetry labelled **`estimated`** (ADR-0004). Every number is from
`eval/eval-runs.jsonl` (2026-09-22, orchestrator-run); nothing here is asserted.

| pool | backend | hit@1 | hit@4 | calls | telemetry |
| --- | --- | --- | --- | --- | --- |
| 20 | cross-encoder (local) | 15/18 | 15/18 | 0 | measured |
| 20 | typesafe (Jev, one Noul per pair) | 14/18 | 17/18 | 540 | estimated |
| 50 | cross-encoder (local) | 15/18 | 17/18 | 0 | measured |
| 50 | typesafe | 15/18 | 17/18 | 540 | estimated |

**Per-row differences** (identical set at both pools; row, kind, cross-encoder rank,
typesafe rank): row 4 (exact) 1 vs 2; row 8 (paraphrase) absent-or-4 vs 1; row 9
(paraphrase) absent-or-3 vs 1; row 12 (linked) 1 vs 2. At pool 20 the cross-encoder
left rows 8 and 9 outside top-4; at pool 50 it placed them at 4 and 3, with Jev at 1
in both. Reading: **Jev is stronger on the two hardest paraphrase rows** and
**slightly weaker on two rows that hinge on an exact identifier**, where it demotes
the right note to rank 2. Net at `k=4` they **tie at pool 50**; at pool 20 Jev wins
hit@4 by 2 and loses hit@1 by 1. Both backends leave the **same one paraphrase row
absent** (row 10) — a candidate-window miss, not a reranking miss.

**Cost.** Estimated from TypeSafe's published cookbook rate (~$0.0645 per 1,200
calls): roughly **$0.03 per 18-question run**, **$0.06 for both runs**. No exact
billing figure was captured, so the label stays **`estimated`** and is never mixed
with the $0 cross-encoder numbers.

**Verdict.** TypeSafe Jev is a **viable reranker at parity** with the local
cross-encoder on this set, at ~100 ms per pair and ~3 cents per 18-question run,
versus $0 for the cross-encoder. Under the **subscription-first rule** (CLAUDE.md)
the **local cross-encoder stays the default**; **Jev is the opt-in** when a
calibrated probability per pair is wanted — for example, to threshold and **refuse**
rather than just reorder — or when no local model can run. Both are **eval modes, not
the default retrieval path**; that decision is still open on latency.

**Pool size matters and is logged.** 20 → 50 moved hybrid @1 **11 → 12** and rerank
@4 **15 → 17**. A result is only comparable against a run with the same pool and
depth, exactly as the Consequences warned.

**Honesty caveats.** This is **18 questions, one vault, one author** — a
**directional** signal, not a benchmark. The golden set was **drafted by a model and
vetted by the owner** before any number was trusted. And, as noted, the reranker
window was tuned to where the misses landed. The point of this slice was the
measurement; the reranker paying off and link expansion not are both **results**,
recorded here either way.
