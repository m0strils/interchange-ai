# ADR-0007: Retrieval strategy — hybrid, structure-aware, measured

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
`retrieve()` today is naive: top-k (k=4) **dense-only** vector search over Chroma's
default local embeddings, with blind 1200/150-char chunking. It backs both the RAG
path and the agent's `search_docs` tool.

The 2026 baseline is **hybrid retrieval (BM25 + dense) + reranking**, with routing
between plain retrieval, long-context, and agentic multi-hop (the knowledge-runtime
idea; enterprise-readiness dimension 8). Domain fit makes this sharper here: EDI/X12
is full of **exact codes** (824, N1, ISA, GS…) that dense embeddings blur but BM25
nails — so hybrid is unusually valuable for this corpus.

**The honest trap:** the corpus is *two tiny seed docs* and there is **no eval set**.
You cannot measure a retrieval improvement today — every "upgrade" would be
faith-based, and stacking rerankers/routers on a toy corpus is cargo-culting. So the
real decision is as much about **sequencing** as technique.

$0/offline holds throughout: BM25, local embeddings, and a local cross-encoder
reranker are all free and offline; model-assisted steps run on the subscription.

## Options (the menu)
1. **Chunking:** blind char windows → **structure-aware** (split on segment/heading
   boundaries). Cheap, big win for these docs.
2. **Retrieval:** dense-only → **hybrid BM25 + dense, fused with RRF.** The core 2026
   upgrade; catches exact codes dense search misses.
3. **Reranking:** none → a **local cross-encoder** over fused candidates. Precision
   boost; adds a dep + latency.
4. **Query handling:** none → rewriting / HyDE (model-assisted). Marginal here.
5. **Router:** none → retrieve-vs-long-context (+ agentic multi-hop). *Premature* —
   the whole corpus fits in context now, so there's no tradeoff to route yet.
6. **Evaluation:** none → a **small golden Q&A set** so any change is measured. The
   prerequisite for claiming improvement (pairs with the RAGAS backlog item).

## Decision (proposed)
Sequence it so every upgrade is *measured*, and don't over-build:

- **Now — the domain-right upgrade, measured:** structure-aware chunking + **hybrid
  (BM25 + dense, RRF)**, paired with a **small golden eval set** (question → expected
  source). Hybrid demonstrably helps exact-code queries even on the seed corpus, and
  the tiny eval set makes the gain visible instead of assumed. Test-gated; `retrieve()`
  stays the single seam both paths call.
- **Deferred, with explicit triggers:**
  - **Reranking** — when the eval shows precision headroom.
  - **The retrieve-vs-long-context router + agentic multi-hop** — when the corpus
    outgrows the context window (until then, long-context trivially wins).
- **Encouraged in parallel:** grow the corpus toward real EDI/rail reference docs —
  it's what will eventually make reranking and the router *matter*.

## Consequences
- Avoids fancy retrieval on a toy corpus; the Evaluation dimension is applied
  honestly — improvements are shown, not claimed.
- Pulls the eval-harness decision forward (retrieval and eval are inseparable).
- Concrete first build: hybrid + structure-aware chunking + a golden set, all
  local/$0, behind the `pre-push` gate (ADR-0006).
- New deps when this lands: a BM25 implementation (e.g. `rank-bm25`) — or Chroma's
  hybrid if it fits — and later a `sentence-transformers` cross-encoder.
- The router is parked as a *choice with a trigger*, not an omission.

## Update — built and measured (2026-08-19)
Shipped the "Now" slice: structure-aware chunking, hybrid BM25+dense retrieval fused
with RRF (`interchange.retrieve`, the single seam both the RAG path and the agent's
`search_docs` call), and an offline hit@k eval (`eval/golden.jsonl` + `--eval`). New
dep: `rank-bm25` (local, $0). Test-gated: the `pytest` suite grew from 14 → 36, all
offline/free (pure functions only — the fused `retrieve()` that touches embeddings is
exercised by the manual `--eval` runner, not the gate).

**The measured gain (honest, small-sample):** on a 14-question golden set over the
two seed docs, dense-only scored **hit@1 = 13/14 (93%)**; hybrid scored **14/14
(100%)**. The single question hybrid rescued is the ambiguous exact-code case — *"What
is the 824 Application Advice transaction set?"* — where dense retrieval put the rail
notes on top and BM25's exact-token signal tipped it back to the canonical X12
reference. That is precisely the failure mode this ADR predicted BM25 would fix. It is
**one question on a toy corpus** — a directional signal, not a benchmark; the value is
that the harness now makes such gains (and regressions) *visible* as the corpus grows.
(Contract note: `008010` turned out to appear in both docs' version matrices, so it is
not a discriminator — the golden set avoids it.)

## Update — 2026-09-24 (go-public: golden row 12 privacy edit)
`eval/golden.jsonl` row 12 — the one question naming a specific cloud provider's
services from the private platform notes — was rewritten for the go-public pass to
match the now-generalised `docs/rail-edi-notes.md` platform section (question and
`expected_facts`); every other row is byte-identical. This is a deliberate,
recorded edit to the otherwise-protected golden file, made for privacy. Re-measured
after the edit (hybrid, k=4, over the 3-doc seed corpus): **hit@1 = 13/14, hit@4 =
14/14** — the rewritten row hits at rank 1, so the retrieval baseline is unchanged.
