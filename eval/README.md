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

- `expected_source` is exactly one real corpus filename: `x12-overview.md` or
  `rail-edi-notes.md`.
- The scorer (`hit_at_k`) also accepts a list of acceptable sources, but this file
  uses the single-string form throughout.

## How it's run

```bash
python interchange.py --eval
```

`run_eval()` loads this JSONL, calls `retrieve()` per question, maps the retrieved
chunks back to their source filenames, and computes `hit_at_k` at the default
`TOP_K`. It prints a per-question table plus the aggregate and returns
`{"n", "hits", "hit_at_k", "k"}`.

Note: `--eval` touches embeddings (it runs the full fused `retrieve()`), so it is a
**manual runner, not the offline test gate**. The `pytest` suite stays offline and
$0 by exercising only the pure functions (`chunk`, `tokenize`, `bm25_rank`,
`reciprocal_rank_fusion`, `hit_at_k`).

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
