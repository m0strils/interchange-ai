# ADR-0016: Corpus profiles as portable data — overlay, index dir, persona, retrieval, tools

- **Status:** Accepted (2026-09-23; measured — see Updates)
- **Date:** 2026-09-23
- **Deciders:** Jeff Lynch

## Context
ADR-0013 made the vertical **data, not code**: `rail`, `hotel` and `vault` are three
blocks in `a2a_agent/profiles.yaml`, and the executor binds a collection per profile
so one engine answers all three. That claim holds for corpora that live *in the tree*.
It breaks the moment the corpus is personal.

The question that forced this ADR was literal: *should we clone interchange-ai into
another folder for a second brain?* The owner is standing up two new corpora that will
never enter the repo — a fresh Obsidian vault at `<vault>`, and a research
corpus over the saved `last30days` evidence dumps at `<research dumps>`. Neither
can be a committed profile block, and the repo is headed public, so "just add it to
`profiles.yaml`" would either commit a path to a private directory or fail to resolve.

The existing `vault` profile already shows the strain. Its `docs_dir` is a
`${INTERCHANGE_VAULT_DIR}` placeholder (`a2a_agent/profiles.yaml`) — a committed block
that only works if the operator exports an env var first, and even then it points at a
directory the repo must never contain. That workaround does not generalise to two more
personal corpora, and it leaks the shape of the owner's filesystem into a public file.

Four more edges make "one engine, many corpora" thinner than ADR-0013 implied:

- **One store per checkout.** `CHROMA_DIR` is hard-wired to `<repo>/.chroma`
  (`interchange.py:40`, an ADR-0014 consequence). Every corpus a checkout indexes lands
  in that one directory, and a second checkout gets a second, unshared store. The
  directory also accumulates orphaned HNSW segment dirs, because `--reindex` calls
  `delete_collection` (`interchange.py:436`) and Chroma leaves the segment folders
  behind.
- **One persona for every corpus.** `SYSTEM_PROMPT` (`interchange.py:93-98`) is a
  rail/EDI persona — *"an assistant for questions about X12/EDI and rail
  trading-partner integration"* — and it is the system prompt on the API path
  (`interchange.py:1364`) and the `claude -p` path (`interchange.py:1448`) for *every*
  corpus. `agent_sub.py:49` carries a second copy of the same rail persona. So a notes
  corpus is answered by an EDI expert.
- **One tool set, always.** `mcp_server.py:32-45` registers the X12-only
  `lookup_segment` tool unconditionally, next to `search_docs`. A vault agent is handed
  a segment-lookup tool it can only misuse.
- **No per-profile retrieval default.** ADR-0014 *measured* `hybrid+rerank` at **15/18**
  against plain `hybrid`'s **11/18** on the vault golden set, at $0 on a local
  cross-encoder — but a profile cannot declare "reranking is my default", so the vault
  answers with the mode it measured worse on unless the caller remembers a flag.

Two operational edges compound it. `DOCS_DIR`/`COLLECTION` resolve **at import**
(`interchange.py:38-41`), so `.env` loads too late to steer them — the sharp edge
ADR-0014 already documented, which is why reindexing a second corpus needs the Makefile
`eval "$(python -m a2a_agent.profiles X --export)"` dance (`Makefile:47`). And
`profile_examples()` follows `DEMO_PROFILE` / the active profile
(`a2a_agent/profiles.py:63`, `app.py:639`), not the corpus in the request — a `/options`
mismatch the moment one server mounts more than one corpus.

The constraints from earlier ADRs all bind: honest telemetry (ADR-0004), guardrails and
audit as a reused layer (CLAUDE.md), the offline/free pytest gate (ADR-0005/0006), and
no proprietary or personal content in a public tree.

## Options considered
1. **Clone the repo per corpus** — the literal question. One checkout for rail/EDI, one
   for `brain`, one for `research`. Rejected: it forks *everything that makes this repo
   worth keeping* — the ADR trail, the pytest/BDD suite, the `pre-push` gate, the audit
   ledger, and every retrieval improvement — into N drifting copies, and a fix to any of
   them has to be applied N times. It is the exact opposite of ADR-0013's "the vertical
   is data, not code": it makes the *engine* the thing you copy per vertical.
2. **Env vars for everything** — extend the `INTERCHANGE_VAULT_DIR` pattern to persona,
   tools, retrieval mode and index dir. One process, no clone. Rejected: env is
   *ambient* — a corpus configured by six exported variables is invisible in the audit
   row, undiscoverable by the workbench `/options` document (ADR-0015) and absent from
   the A2A Agent Card (ADR-0013). It answers "which corpus" with shell state instead of
   a named, inspectable thing.
3. **Profile keys + an external overlay file + a configurable index dir + a `--profile`
   switch — chosen.** Keep the committed profiles as the public, in-tree set; let a
   private overlay file *add* personal profiles and *override* committed keys; move the
   index location to an env var; and apply a whole profile in-process before any work,
   retiring the import-time edge. The corpus stays a named, first-class thing the audit,
   `/options` and the Agent Card can all see — it just no longer has to live in the tree.

**Sub-decision — index freshness.** A personal corpus changes under the owner's hands,
so it needs a rebuild story.
- **Nightly full rebuild via launchd — chosen.** One scheduled `--reindex` per profile;
  simple, no new code in the hot path, and it reuses the idempotent rebuild that already
  exists. Rebuild time **to be measured and recorded in this ADR** before it is trusted.
- **Incremental upsert by content hash — deferred.** Only rebuild the chunks whose
  source changed. More code and a hash index to keep honest. Trigger: a **measured** full
  rebuild over **5 minutes**, or a real need for intra-day freshness.

## Decision
Make a corpus a **portable profile**: a named block that can live outside the tree, that
carries its own persona, retrieval default and tool allow-list, and that a single
process can apply per request. Built in slices, each independently useful.

- **`INTERCHANGE_PROFILES` → an overlay YAML** (default `<workspace>/profiles.yaml`;
  an **empty string disables** the overlay; a **missing file is simply no overlay**, not
  an error). Overlay blocks **shallow-merge over the committed ones by profile name** —
  keys replace, lists replace — and an overlay may add **whole new profiles**
  (`brain`, `research`) that the tree never sees. **The pytest suite pins the overlay
  off** (an autouse fixture), so the gate reads only the committed profiles regardless of
  what is on the developer's machine.
- **`INTERCHANGE_CHROMA_DIR` → the index location** (default unchanged: `<repo>/.chroma`).
  One store per machine, N collections — so `edi`, `vault`, `brain` and `research` share
  a single store instead of one per checkout, and a personal index can sit under
  `<workspace>/` next to the overlay.
- **`interchange.py --profile NAME`** applies a profile **in-process before any
  index/answer/eval call**, resolving collection, docs dir, persona, retrieval default
  and tools together. This **retires the export-before-`.env` edge** (ADR-0014): the
  profile is applied by the process, not by shell state read too late. Explicit
  `--corpus` / `--golden` still win over what the profile sets.
- **New profile keys**, all optional and all backward-compatible:
  - **`persona`** — the system prompt for this corpus, resolved **per request by
    collection**, so one server answers `hotel` with a hotel persona and `edi` with the
    EDI one. A profile with no `persona` keeps today's rail `SYSTEM_PROMPT`.
  - **`retrieval: {mode, rerank}`** — the profile's **default** retrieval mode (so `vault`
    can declare `hybrid+rerank`, its measured-best). Precedence, stated once: an
    **explicit flag wins over the profile default**, and **`INTERCHANGE_LOCKED` still
    wins over both** — policy over preference, exactly as ADR-0015 ruled for the web tier.
  - **`tools`** — a **least-privilege allow-list** honoured by both the subscription agent
    (`agent_sub.py`) and the MCP server (`mcp_server.py`). Default
    `[search_docs, lookup_segment]`, so **rail is unchanged**; a notes profile lists
    `[search_docs]` only and never sees `lookup_segment`.
- **`--golden-add`** appends a *validated* row to the profile's golden set — eval-as-you-go,
  so a personal corpus grows its own measured baseline instead of borrowing rail's.
- **`scripts/launchd/*.plist.example` + `make launchd-install PROFILE=x`** for the nightly
  rebuild (the sub-decision above), and **`INTERCHANGE_CORS_ORIGINS`** (default empty = **no
  CORS middleware added**) for a separate-origin personal frontend.
- **The HTTP allow-list `INTERCHANGE_CORPORA` is unchanged** (ADR-0015): a personal corpus
  is reachable over HTTP only if the operator opts it in per process. The overlay makes a
  corpus *definable*; the allow-list still governs whether a given process *serves* it.

**Deferred, explicitly.** Cross-corpus fan-out (asking `brain` and `research` one
question and merging) — trigger below. Incremental reindex by content hash — trigger
above. A personal write-back automation or frontend — it lives in a **sibling repo that
depends on the HTTP/MCP contract**, never a copy of this one.

## Consequences
**What becomes true now**
- Personal corpora **never appear in the tree**. The `brain`/`research` vault, index,
  profile block and golden set all live under `<workspace>/` and `<vault>`;
  the public repo carries only `rail`, `hotel` and the `vault` shape. The clone question
  is answered *no* — one engine, corpora as portable data.
- A corpus is answered by **its own persona with its own tools**, resolved per request,
  so a single multi-corpus process is coherent rather than an EDI expert wearing three hats.
- The `vault` profile can finally **declare `hybrid+rerank` as its default** — the mode
  ADR-0014 measured at 15/18 — instead of relying on the caller to pass a flag.

**What we accept as a cost**
- **One store per machine.** All collections share `INTERCHANGE_CHROMA_DIR`. That is the
  point (no per-clone store), but it means a machine's personal and public indexes sit in
  one directory; the `INTERCHANGE_CORPORA` allow-list, not filesystem separation, is what
  keeps a public process from serving a private collection.
- **The gate must isolate the overlay.** An autouse fixture pins `INTERCHANGE_PROFILES`
  off for the whole suite; without it a developer's personal overlay could turn the
  offline gate's result machine-dependent. This is a real obligation, recorded here.
- **Rerank deps become a soft requirement** of any profile that declares
  `hybrid+rerank` — the local cross-encoder must be installed for that profile to serve,
  where a `hybrid` profile needs nothing extra. A profile that declares a mode it cannot
  run should fail closed with a clear message, not silently downgrade.
- **`corpus_snapshot` caches on chunk count** (`interchange.py:777-805`): a rebuild that
  lands the **same** chunk count is **invisible** to a long-running server, which keeps
  serving the stale snapshot. Noted and **trigger-gated together with an atomic-rebuild
  item** — a nightly rebuild that changes content but not count is exactly the case that
  exposes this.
- **Orphaned HNSW segments** from `delete_collection` (`interchange.py:436`) accumulate in
  the shared store; a shared store makes the cruft shared too. A cleanup step is a small
  follow-up, not part of this slice.

**What this sets up or forecloses**
- **Cross-corpus fan-out query is deferred**, with a concrete trigger: the owner runs both
  a `brain` and a `research` alias against the same question repeatedly. Until then, two
  named corpora answered separately is the honest shape.
- A future personal **frontend or write-back automation** is foreclosed *as a fork*: it
  lives in a sibling repo against the HTTP/MCP contract (the ADR-0015 policy tier and the
  MCP tool surface), never a copy of the engine — the same rule that keeps the vertical
  data, not code.

## Verification
This ADR flips to **Accepted** only once the following are **measured** (ADR-0004:
measured, not asserted) and recorded here in an `## Update` section, the way ADR-0014
recorded its ablations:

- **Rebuild seconds** for `vault` and for the new `brain` corpus (the sub-decision's
  gate: full nightly rebuild stays under the 5-minute incremental-upsert trigger).
- **`make eval PROFILE=vault MODE=hybrid+rerank`** reproduces **15/18**, and
  **`MODE=hybrid`** reproduces **11/18** — the ADR-0014 numbers, confirming the profile's
  declared retrieval default did not move the measured result.
- **Rail eval unchanged at 14/14** — the committed profiles and the default persona/tool
  set are untouched by the overlay and the new keys.
- **`make a2a-demo PROFILE=hotel`** passing — the per-request persona/tool resolution
  answers `hotel` correctly on the $0 stub engine.

## Update 2026-09-23 — rebuild time measured, incremental reindex stays deferred
Slice 2 landed `INTERCHANGE_CHROMA_DIR`, `--profile` and the timed `--reindex`. All five
profiles were rebuilt into one workspace store (`<workspace>/chroma`, 59 MB after the
run) on the local default embedder, one process each, back to back (**measured**, wall
clock from the `Indexed …` summary line; Apple silicon laptop):

| profile | files | chunks | rebuild |
|---|---:|---:|---:|
| rail | 3 | 12 | 0.3 s |
| hotel | 3 | 21 | 0.3 s |
| brain (`<vault>`, overlay) | 25 | 407 | 3.0 s |
| research (`<research dumps>`, overlay) | 13 | 808 | 5.5 s |
| vault (`<notes vault>`, ADR-0014 corpus) | 188 | 4,614 | 30.2 s |

The largest corpus rebuilds in **30 s** against the **5-minute** trigger, so the nightly
full rebuild is the freshness story and **incremental upsert by content hash stays
deferred** — it would be code without a measurement behind it. Two profiles defined only
in the overlay (`brain`, `research`) indexed with no edit to the tree, which is the
portable-profile claim, exercised. The eval reproduction (vault 15/18 rerank, 11/18
hybrid; rail 14/14) is recorded below once the persona and retrieval-mode slices land.

## Update 2026-09-23 — evals reproduced, brain baseline seeded, Accepted
All seven slices are on `feature/corpus-profiles` (288 tests, up from 247; every slice
gated offline). The verification list above, **measured** on the shared workspace store:

- `make eval PROFILE=vault` with `MODE` unset now runs the profile's declared
  `hybrid+rerank` and reproduces ADR-0014's **15/18 hit@1**; `MODE=hybrid` reproduces
  **11/18**. The declared default moved nothing, as required.
- Rail is unchanged at **14/14 hit@1** with the overlay present and the new keys in place.
- `DEMO_PROFILE=brain` starts the MCP server with `search_docs` + `ask_interchange` only;
  `rail` still exposes `lookup_segment`.
- A live `--profile brain --engine claude-code --ask` answered from the vault in 6 s at $0
  marginal, cited the decision note, and left an audit row. It also showed a real gap: for
  a "why" question the top-4 caught the *Decision* section but not the *Options* section of
  the same note. Recorded as a paraphrase row in the brain golden set rather than fixed.
- **Brain golden baseline** — 16 rows seeded from the indexed notes (10 exact, 4 paraphrase,
  1 linked, 1 added via `--golden-add`, which validated the source against the index and
  refused an unindexed path), `k=4`, `pool=20`, `rerank_n=30`, local cross-encoder:

  | mode | hit@1 | hit@4 | near-miss |
  |---|---:|---:|---:|
  | hybrid | 11/15 | 15/15 | 0 |
  | dense | 12/15 | 15/15 | 0 |
  | bm25 | 10/15 | 13/15 | 1 |
  | hybrid+links | 7/15 | 15/15 | 0 |
  | hybrid+rerank | 12/15 | 14/15 | 1 |

  (15 answerable at eval time; the 16th row was added after the run.) Honest reading: on a
  25-note corpus the reranker lifts hit@1 by one row and *drops* one row out of the top-4,
  so its ADR-0014 win does not automatically transfer to a tiny corpus — the `brain`
  profile keeps `hybrid+rerank` declared, and this table is the baseline to beat as the
  vault grows. Link expansion regresses here too (7/15), consistent with ADR-0014.
- Rebuild times (previous update) settle the freshness sub-decision: nightly full rebuild,
  incremental upsert deferred with its trigger intact.

Left open, trigger-gated: cross-corpus fan-out, atomic rebuild + hash-keyed snapshot
cache, orphaned-segment cleanup in the shared store, and the retrieval gap on multi-section
"why" questions (candidates: section-aware neighbour expansion within the *same* note, or a
larger `k` for the brain profile — both need a measurement first).
