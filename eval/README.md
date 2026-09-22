# Golden evaluation set

A small, hand-authored retrieval eval for Interchange's hybrid (BM25 + dense)
retriever. It is a **seed** set over a **two-doc seed corpus**
(`docs/x12-overview.md`, `docs/rail-edi-notes.md`) — deliberately small and honest,
not a benchmark. As the corpus grows, this set should grow with it.

## What it measures

Each question has exactly one document where the answer lives. The eval asks:
does the retriever surface that document in its top-`k` results? That's **hit@k** —
a retrieval-quality signal, upstream of any generation. It says nothing about answer
quality; it only checks that grounding material was retrieved at all.

## Format — `golden.jsonl`

One JSON object per line:

```json
{"question": "What is the 997 Functional Acknowledgment used for?", "expected_source": "x12-overview.md"}
```

- `expected_source` is a source **as recorded in the index** — the basename for a
  flat corpus (`x12-overview.md`, `rail-edi-notes.md`), the relative POSIX path for a
  nested one (see the Vault set below). It equals the basename on a flat corpus, so
  this file is unchanged (ADR-0014).
- The scorer (`hit_at_k`) also accepts a list of acceptable sources, but this file
  uses the single-string form throughout.
- Rows with **no** expected source (the `unanswerable` rows below) are **skipped** by
  `--eval` and counted as `skipped` — they have no retrieval ground truth. They belong
  to the answer-quality grade (`--grade`, ADR-0008), which measures whether the system
  *declines* them without fabricating.

## How it's run

```bash
python interchange.py --eval                       # hybrid, hit@TOP_K over golden.jsonl
python interchange.py --eval --k 1                 # tighten the cutoff to hit@1
python interchange.py --eval --mode dense          # ablation: dense-only (bypasses fusion)
python interchange.py --eval --mode bm25           # ablation: BM25-only
python interchange.py --eval --mode all            # run every mode, print a comparison table
python interchange.py --eval --golden eval/golden-vault.jsonl --corpus vault  # a named corpus
python interchange.py --eval --depth 20 --pool 40  # widen the rank/near-miss window and the pool
python interchange.py --eval --mode hybrid+rerank --rerank-n 30  # rerank the top-30 fused candidates
```

`run_eval()` loads a golden JSONL, calls `retrieve()` per question **to `--depth`**,
maps the retrieved chunks back to their sources, and records — per question — whether
it was a `hit@k`, the **rank** of the expected source, and its class. It prints a
per-question table plus the aggregate.

### Flags (ADR-0014)

| flag | default | meaning |
| --- | --- | --- |
| `--k N` | `TOP_K` (4) | the hit@k cutoff |
| `--golden PATH` | `eval/golden.jsonl` | which golden set to score |
| `--corpus NAME` | module collection | the Chroma collection to read; scoped to the run, never mutates module state |
| `--mode {hybrid,dense,bm25,hybrid+links,hybrid+rerank,all}` | `hybrid` | retrieval mode; `hybrid+links` re-fuses the one-hop wikilink neighbours of the top-3 fused notes as a third RRF ranking (identical to `hybrid` when no links resolve); `hybrid+rerank` reorders the top `--rerank-n` fused candidates by a relevance scorer; `all` runs each and prints a comparison table |
| `--depth N` | 10 | how deep to look for the expected source (for rank + near-miss) |
| `--pool N` | 20 | dense candidate-pool size fed to fusion |
| `--rerank-n N` | 30 | fused-candidate window `hybrid+rerank` reorders (backend from `INTERCHANGE_RERANK`) |

### What it reports

- **hit@1 and hit@k** — the headline retrieval-quality signals.
- A **rank histogram** over `@1`, `@2-k`, `@{k+1}-depth`, `absent` (the buckets sum to
  the number of scored questions).
- The **near-miss line** — `near-miss (expected within top-{depth} but outside top-{k})
  = N`. This is **ADR-0007's "precision headroom" reranker trigger, expressed as a
  number**: build the deferred reranker when it is `> 0` on the hybrid run, and keep it
  deferred (for a measured reason, not an assumed one) while it is `0`.
- **skipped** — the count of unanswerable rows that carry no retrieval ground truth.
- With `--mode all`, a comparison table: `mode | hit@1 | hit@k | near-miss | absent`.
  On the seed corpus this reproduces ADR-0007's measured numbers — hybrid `14/14`,
  dense-only `13/14` — so the ablation is verifiable, not asserted.

### The run log — `eval-runs.jsonl`

Every `--eval` run **appends one JSON line** to `eval/eval-runs.jsonl` (gitignored,
alongside `grade-runs.jsonl`): the aggregate plus `mode`, `corpus`, `depth`, `pool`,
`near_miss`, the histogram, and a `results` array carrying each question's expected
source, rank, class, and the top-`depth` retrieved sources — so a run is reproducible
and comparable against another run *with the same pool and depth*.

The return value keeps its legacy keys `{"n", "hits", "hit_at_k", "k"}` and adds
`hit_at_1`, `histogram`, `near_miss`, `absent`, `mode`, `corpus`, `golden`, `depth`,
`pool`, `rerank`, `skipped`, and `results`. `rerank` is `null` unless the run used
`hybrid+rerank`, in which case it records `{backend, window, calls, telemetry}`.

### Reranking — `hybrid+rerank` (ADR-0007 trigger, ADR-0014)

Once the hybrid run shows `near-miss > 0` — precision headroom — the reranker
ADR-0007 deferred is warranted. `--mode hybrid+rerank` takes the plain hybrid
fusion, reorders its top `--rerank-n` candidates (default 30) by a relevance
scorer, and returns the top-`k`. The backend is chosen by `INTERCHANGE_RERANK`:
`cross-encoder` (the default — a local sentence-transformers `ms-marco-MiniLM-L-6-v2`
cross-encoder, `$0` and offline, telemetry **measured**), `flashrank` (the same
model family via ONNX with no torch, the torch-less local fallback), or `typesafe`
(TypeSafe System One scoring one calibrated Noul per candidate — **metered**, its
per-pair calls counted in the log's `rerank.calls`, and labelled **estimated** per
ADR-0004). Install a backend with `pip install -r requirements-rerank.txt`. To run the
`typesafe` backend without ever writing the key to a file, pull it from the macOS
keychain into the process env on the command line:

```bash
TYPESAFE_API_KEY="$(security find-generic-password -s typesafe -w)" INTERCHANGE_RERANK=typesafe make eval PROFILE=vault MODE=hybrid+rerank K=4
```

The key then lives only in the keychain and the transient env of that one process —
it never lands in `.env` or the shell config. Reranking **never runs in the offline
pytest gate** — the scorers import their
backend lazily, so `pytest` never pulls torch/onnx/typesafe — and `--mode all`
skips the `hybrid+rerank` row (printing one honest line) when the selected backend
is not installed. The window is 30 because, measured on the vault golden set, the
hybrid misses sit at fused ranks up to 16; a narrower window could not lift them.

Note: `--eval` touches embeddings (it runs the full fused `retrieve()`), so it is a
**manual runner, not the offline test gate**. The `pytest` suite stays offline and
$0 by exercising only the pure functions (`chunk`, `tokenize`, `bm25_rank`,
`reciprocal_rank_fusion`, `hit_at_k`, `fuse_rankings`, `rank_of_expected`, `classify`,
`rank_histogram`, `unknown_expected`) and the runner with `retrieve()`/`_known_sources()`
stubbed.

## Vault set — `golden-vault.jsonl`

A second golden set scores retrieval over the nested Obsidian **vault** corpus
(ADR-0014), read with `--golden eval/golden-vault.jsonl --corpus vault`. The **format
is identical** to `golden.jsonl`, with two differences a nested corpus brings:

- `expected_source` is the **relative POSIX path recorded in the index** (e.g.
  `Projects/Interchange.md`), not just a basename — the vault has duplicate basenames,
  so the folder-qualified path is what disambiguates them.
- `expected_sources` (a **list**) is allowed for a question whose answer could
  legitimately live in more than one note; `hit_at_k` counts a hit on *any* of them.
- Optional `kind` and `note` fields annotate a row (e.g. the retrieval facet it probes,
  or why a source was chosen). `kind` is echoed in the per-question table and stored in
  the log; `note` is documentation for the reader. Neither affects scoring.

Before its first scored run the vault set is **drafted from the indexed notes and
vetted by the user** — an unvetted expected path is flagged (`WARN: … not in the
index`) before any number is trusted (`unknown_expected`).

## Measured, not claimed (ADR-0007)

This is an honest-telemetry project. We do **not** assert a hit@k number here — the
score is whatever `--eval` measures on your machine against the current index. Report
the observed number with its `k` and corpus state; never hard-code an aspirational
figure. The point of the mixed question set below is to make the number *diagnostic*:
if dense retrieval regresses, the paraphrase questions fall first; if the code
tokenizer regresses, the exact-code questions fall first.

## The deliberate question mix (14 questions)

**Exact-code / exact-term queries where the term is UNIQUE to one doc** — these
should be BM25 wins, because the code survives tokenization as a single token and
appears in only one document:

- `997`, `214`, `ISA/IEA`, `GS/GE`, `ST/SE` -> `x12-overview.md`
- `161`, `404`, `417`, `990`, `AAR`, AWS/Aurora platform -> `rail-edi-notes.md`

**Natural-language / paraphrase queries where dense retrieval should shine** — no
discriminating code is present, so the retriever has to match on meaning:

- "Which X12 message confirms that a received functional group was syntactically
  received?" -> `x12-overview.md` (paraphrases the 997 definition without naming 997).
- "How does a railroad tell a trading partner that a received document failed
  validation?" -> `rail-edi-notes.md` (see the judgment call below).

## Judgment calls

**824 is in BOTH docs** (it is explicitly listed as non-discriminating in the frozen
contract). We use it twice, deliberately, and split the expected source by framing:

- *"What is the 824 Application Advice transaction set?"* -> **`x12-overview.md`**.
  This is a generic definitional question, and `x12-overview.md` is the canonical
  X12 reference where 824 is defined as a general-purpose Application Advice. That is
  the document we'd want a reader to land on for the base concept.
- *"How does a railroad tell a trading partner that a received document failed
  validation?"* -> **`rail-edi-notes.md`**. This is rail-framed and specifically
  about signaling validation failures — the rail notes describe 824 as "widely used
  to signal validation failures" in the railroad interchange context, which matches
  the intent more tightly than the generic X12 definition.

These two are the genuinely hard/ambiguous cases: both could plausibly retrieve
either doc, so they're the ones most likely to move the hit@k number. That's
intended — they're where the retriever's semantics (not just keyword overlap) get
tested. If a future retrieval change makes the 824 cases fragile, that's a signal to
revisit whether single-source ground truth is still the right model, or whether these
should switch to the list form that `hit_at_k` supports.
