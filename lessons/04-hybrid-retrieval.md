# Lesson 04 — Hybrid retrieval, and how to *prove* it helped

Lesson 01 built a grounded, audited RAG loop — but its retrieval was the naive
default: dense-only vector search (top-k = 4) over blind 1200-character chunks.
That's exactly the "chunk-and-pray RAG" [TEACHING.md](../TEACHING.md) warns is
dead. This lesson upgrades the *retrieval* half of the knowledge runtime — and,
just as importantly, builds the eval that **proves** the upgrade helped instead of
just sounding modern.

The decision is [ADR-0007](../docs/adr/0007-retrieval-strategy.md); read it for the
full options menu and the sequencing argument (why hybrid + eval *now*, reranking
and routing *later, with triggers*). Here's the short version and the *why*.

## The problem: dense embeddings blur exact codes

EDI is a domain of exact identifiers — `824`, `997`, `ISA`, `008010`. Dense
embeddings map text to vectors by *meaning*, and a bare 3-digit code carries almost
no semantic signal, so `214` and `417` land as near-identical vectors. Ask *"what is
an 824?"* and dense search can hand you the wrong document because two codes simply
*felt* similar.

Lexical search (BM25) has the mirror-image strength: it matches exact tokens. `824`
is `824`, full stop. The 2026 baseline — and the sharp call for *this* corpus — is
**hybrid**: run both and fuse them.

## Four moving parts

**1. Structure-aware chunking** — `chunk()`. Instead of cutting every 1200
characters (which slices mid-sentence and blends unrelated topics), split on
Markdown headings and tag each chunk with the section it came from:

```
section='What X12 is'              text='## What X12 is\nANSI ASC X12 is the domi…'
section='Common transaction sets'  text='## Common transaction sets\n- **997 — Func…'
section='Envelopes (structure)'    text='## Envelopes (structure)\n- **ISA/IEA** — in…'
```

Each chunk is now a coherent unit, and the `section` label rides along in metadata.

**2. BM25 lexical ranking** — `bm25_rank()`, `tokenize()`. The tokenizer keeps
digit runs intact on purpose, so codes survive as single tokens:

```python
tokenize("An 824 Application Advice; version 008010, ISA/GS envelopes.")
# -> ['an', '824', 'application', 'advice', 'version', '008010', 'isa', 'gs', 'envelopes']
```

`824` and `008010` stay whole — that's the exact-match signal dense loses.

**3. Dense ranking** — Chroma's local embeddings. Still here, because it catches
paraphrases with *zero* keyword overlap: *"which message confirms a group was
syntactically received?"* retrieves the 997 doc without the string "997" appearing.

**4. Reciprocal Rank Fusion** — `reciprocal_rank_fusion()`. You can't just add a
BM25 score to a cosine similarity — they're on different scales. RRF ignores raw
scores and fuses by **rank**: each chunk scores `Σ 1/(k + rank)` over every list it
appears in (`k = 60`), and the fused order is by that sum.

All four sit behind **one function, `retrieve()`** — so both the RAG path
(`answer`) and the subscription agent's `search_docs` tool (Lesson 03) get hybrid
retrieval through the single seam, unchanged callers.

## The insight RRF actually teaches

Building this, the first fusion example we tried *tied* — and that tie is the real
lesson. Give RRF a single swapped pair (chunk A is 1st in one list, 2nd in the
other; chunk B is the reverse) and the scores are **identical**, because
`1/(k+1) + 1/(k+2)` is the same either way. RRF does **not** reward "whoever won a
list." It rewards **consensus** — a chunk both lists agree on:

```python
dense = ["P", "Q"]     # P is dense's #1
bm25  = ["P", "R"]     # P is ALSO bm25's #1  -> consensus
reciprocal_rank_fusion([dense, bm25])   # -> ['P', 'Q', 'R']
#   P: in 2 lists  score=0.03279   <- appearing in BOTH beats topping only one
#   Q: in 1 list   score=0.01613
#   R: in 1 list   score=0.01613
```

That's the whole point of fusing: agreement between a lexical and a semantic view
is a stronger signal than either view's top pick alone.

## Measure it, don't claim it

The honest trap ADR-0007 names: on a two-doc seed corpus, *any* retrieval "upgrade"
is faith-based unless you can measure it. So the eval is part of the build, not a
follow-up. `eval/golden.jsonl` holds 14 hand-authored `question → expected_source`
pairs (a deliberate mix of exact-code and paraphrase questions), and `--eval` scores
**hit@k** — did the right document surface in the top *k*?

```
$ python interchange.py --eval --k 1
  hit@1 = 14/14 = 100.0%
```

The number that matters is the **comparison**, run head-to-head on the same set:

| retriever | hit@1 |
|---|---|
| dense-only (Lesson 01) | 13/14 = **93%** |
| hybrid (this lesson) | 14/14 = **100%** |

The single question hybrid rescued is *"What is the 824 Application Advice
transaction set?"* — `824` appears in **both** docs, dense put the rail notes on
top, and BM25's exact-token signal tipped it back to the canonical X12 reference.
That is precisely the failure mode the ADR predicted BM25 would fix. It's **one
question on a toy corpus** — directional, not a benchmark. The value isn't the
100%; it's that the harness now makes gains *and regressions* **visible** as the
corpus grows.

## The offline discipline (why the eval isn't in the gate)

The `pytest` gate must stay offline and free (ADR-0005/0006) — but Chroma's default
embeddings download a model on first use. So the line we drew:

- **In the gate:** the *pure* functions only — `chunk`, `tokenize`, `bm25_rank`,
  `reciprocal_rank_fusion`, `hit_at_k`. No network, no embeddings. (The suite grew
  14 → 36 tests, still ~0.05s.)
- **A manual runner:** the embedding-touching full `retrieve()` and `--eval`.

Knowing *which* of your checks can run for free — and keeping the expensive ones out
of the fast loop — is itself part of building for an enterprise.

## Map to the framework

| Dimension | What this lesson adds |
|---|---|
| **Evaluation & Quality Gates** | a golden set + offline hit@k — retrieval changes are *measured*, not asserted (the RAGAS/faithfulness gate is still ahead) |
| **Context & Memory** | hybrid (lexical + semantic) retrieval as the reusable `retrieve()` seam; the retrieve-vs-long-context router is deferred until the corpus outgrows the window |
| **Cost & Efficiency** | BM25 + local embeddings are $0/offline; the fast test gate stays free by design |
| **Governance** | improvements shown with numbers, boundaries stated — honest telemetry applied to retrieval |

## Try it yourself

```bash
python interchange.py --reindex        # rebuild with structure-aware chunks
python interchange.py --eval           # hit@k over eval/golden.jsonl (offline, $0)
python interchange.py --eval --k 1     # the stricter top-chunk metric
```

Want to see it drive a real answer? `--ask` runs the same hybrid `retrieve()` into
the grounded, cited RAG loop from Lesson 01:

```bash
python interchange.py --explain --ask "what is an 824?"   # needs a generation engine
```

## What's honest about this

This is a **seed** eval on a **two-doc** corpus: a 93% → 100% move is a single
question flipping, so treat it as a directional signal, not proof of a universal
win. Two things were deliberately *not* built yet, each parked with a trigger in
ADR-0007: a **cross-encoder reranker** (add it when the eval shows precision
headroom) and a **retrieve-vs-long-context router** (add it when the corpus stops
fitting in the context window — until then, long-context trivially wins). The
fastest way to make *both* of those matter is the least glamorous task: grow the
corpus toward real EDI/rail reference docs. The harness is now here to tell us,
honestly, when they start to pay off.
```
