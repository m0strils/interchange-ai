# ADR-0008: Answer-quality evaluation — refusal- and answer-correctness, advisory

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
ADR-0007 made retrieval *measured* — a golden set and a hit@k eval, "measure, don't
claim." Answer quality has no such check. The only grounding on the generated answer
is **syntactic**: `enterprise.guard_output` flags an answer as ungrounded solely when
it lacks a `[filename]` citation. Nothing checks whether the answer is *correct*, or
whether the system *correctly declines* when the two seed docs can't answer. Closing
that is roadmap #2.

The honest constraints from ADR-0003/0004/0006 still hold: **$0 subscription** for any
LLM call (`claude -p`, no API key), telemetry labeled `measured` vs `estimated`, and
the `pre-push` gate stays **offline and instant** — an LLM eval cannot live in it.

## Options (the menu)
1. **Faithfulness as the gate** — decompose the answer into claims, check each against
   retrieved context, gate on the ratio. The obvious RAG metric — **and it loses here.**
   Interchange generates the answer *from* the retrieved context under a prompt that
   says *"Answer ONLY from the provided context… do not invent details"*
   (`interchange.py:35-40`). By construction a well-behaved model's claims are in the
   context → faithfulness ≈ 1.0 on nearly every run → a gate that structurally never
   fires. Shipping it as a gate would be exactly the overclaim the honest-claim rule
   forbids. It survives only as a *secondary monitor*.
2. **Refusal-correctness** — add out-of-corpus / unanswerable questions and score
   whether the system avoids fabricating an answer. This is *where a from-context RAG
   actually fails*, so it can genuinely fail — a real headline signal. (First tried as
   a decline-phrase regex; **verification against real output killed that** — see the
   correction note below — and it's now defined via faithfulness on these rows.)
3. **Answer-correctness via gold `expected_facts`** — light keyword/substring facts per
   answerable golden question; score = fraction present. **Deterministic — no LLM to
   score**, only generation costs a $0 call. The other headline signal.
4. **RAGAS library vs hand-rolled** — RAGAS is the standard toolkit but a heavy dep and
   less legible; hand-rolled, RAGAS-*style* metrics match the spirit of `enterprise.py`
   and stay readable.
5. **Metered-API judge vs $0 subscription judge** — an API judge buys temperature
   control (repeatability) at the cost of the $0 ethos; the subscription judge is free
   but non-deterministic.
6. **Gate vs advisory** — wire it into `pre-push` (impossible — not offline/$0) vs a
   manual pre-release report.

## Decision
Add a `--grade` command: a **hand-rolled, RAGAS-style**, **$0 subscription**,
**advisory** eval (generation *and* judge via `claude -p`, telemetry `estimated`).
Generation is forced to `engine="claude-code"` — `answer()` defaults to `engine="api"`,
which `sys.exit`s without `ANTHROPIC_API_KEY` (`interchange.py:101-103, :201`). It
scores three signals:

- **Refusal-correctness (headline).** New `unanswerable: true` golden rows (a non-EDI
  question; an in-domain code — 850, 856 — or adjacent standard/protocol — EDIFACT,
  AS2 — all absent from both seed docs).
  Scored as **faithfulness == 1.0 on those rows** (no unsupported claim). Faithfulness
  is *not* circular here: the answer is no longer built purely from context — the model
  can reach for ungrounded world knowledge, and that is exactly what this catches.
- **Answer-correctness (headline).** Gold `expected_facts` on answerable rows; score =
  fraction present, case-insensitive. Deterministic — no LLM needed to score.
- **Faithfulness (secondary — hallucination monitor).** The $0 judge decomposes the
  answer into claims and checks each against context; score = supported/total, with
  **zero-claim (a refusal) → 1.0**. Labeled a monitor, **never** a pass/fail gate.

Advisory means it prints a report and returns a summary; an optional `--fail-under`
gives a nonzero exit for anyone who wants one. It is **not** wired into `pre-push`
(ADR-0006 keeps that hook offline/$0). `--grade` writes its own log,
`eval/grade-runs.jsonl` — **not** `audit.jsonl`, whose per-request dashboard
(`enterprise.py:139-155`) stays clean.

## Consequences
- **Two grounding layers, taught explicitly:** a cheap *runtime* guardrail
  (`guard_output`, every request, syntactic) vs *eval-time* answer quality (`--grade`,
  pre-release, $0). The distinction is the lesson.
- The eval measures signals that **can actually fail** on a from-context RAG — the
  unanswerable rows are the ones that expose a fabricated answer (refusal-correct =
  false, faithfulness < 1). Faithfulness alone would have been near-vacuous.
- The judge is non-deterministic (Opus via `claude -p`, no temperature control), so
  **v1 is advisory with no committed regression baseline** — a flaky baseline is worse
  than none.
- Small corpus ⇒ few golden questions; the **harness/pattern is the deliverable**,
  stated honestly, the same way ADR-0007's hit@k gain was a directional signal.
- **Deferred, with triggers:** a real regression baseline once the judge is made
  *repeatable*; and observability tracing of eval runs — planned as **ADR-0009** in a
  fresh cycle, so designing the trace surface doesn't pre-commit before the eval exists.

## Correction (found during verification — 2026-08-19)
Refusal-correctness was first implemented as a deterministic decline-phrase regex plus
a "cite nothing" rule. The **first live `--grade` run refuted it.** For *"what is the
850?"* the model gave a model refusal — *"the provided context doesn't cover the 850…
none of which is the 850… I can't describe it without inventing details"* — while
citing what the docs *do* cover; the regex scored that a **failure** (it says "doesn't
cover", not "context does not", and it cites sources). Meanwhile *"boiling point of
water?"* was answered *"100 °C"* from world knowledge (faithfulness 0.33). A regex
can't separate the two — the wrong answer also contains decline-ish phrasing. So
refusal-correctness was redefined as **faithfulness == 1.0 on the unanswerable rows**,
which scores the good refusal 1.0 and the hallucinated answer < 1.0. This is the
honest-telemetry rule in action: a metric that mis-scored real output was corrected
before it shipped, and the record keeps the road not taken.
