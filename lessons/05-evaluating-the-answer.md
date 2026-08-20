# Lesson 05 — Evaluating the answer, and the metric that lied

Lesson 04 measured *retrieval* — did the right document surface? This lesson measures
the *answer* — is it correct, and does the system decline when the corpus can't help?
It's roadmap #2, and it comes with two lessons for the price of one: the obvious
answer-metric is **circular** here, and even the metric that replaced it got **caught
lying by verification** before it shipped.

The decision is [ADR-0008](../docs/adr/0008-evaluation-gate.md). Here's the *why*.

## The trap: faithfulness is circular on a from-context RAG

The industry-standard RAG answer-metric is **faithfulness**: decompose the answer into
claims, check each against the retrieved context, score = supported / total. It sounds
right. It's nearly useless *here* — and understanding why is the lesson.

Interchange generates its answer *from* the retrieved context, under a system prompt
that says *"Answer ONLY from the provided context… do not invent details"*
([`interchange.py`](../interchange.py) SYSTEM_PROMPT). So a well-behaved model's claims
are in the context **by construction** → faithfulness ≈ 1.0 on nearly every run → a
"gate" that structurally never fires. Shipping that as your headline eval would be
decorative — a green light wired to nothing. (This project's honest-claim rule forbids
exactly that kind of number.)

## The fix: measure what can actually fail

Two signals *can* fail on this system, so those become the headline:

**1. Refusal-correctness.** Add out-of-corpus questions — an EDI code the seed docs
don't cover (850, 856), an adjacent standard (EDIFACT, AS2), a pure off-domain
question ("boiling point of water?"). The *correct* behavior is to decline. This is
where a from-context RAG genuinely breaks — by reaching past the context into its
parametric memory.

**2. Answer-correctness.** Attach light gold `expected_facts` (keywords) to each
answerable golden question; score = fraction present. **Deterministic — no LLM needed
to score it**, only a $0 call to generate the answer.

Faithfulness stays, demoted to a *secondary hallucination monitor* — you watch it for
drops, not levels.

## The metric that lied (and how we caught it)

Refusal-correctness was first built the obvious way: a regex for decline phrases
("context does not…") plus a rule that a refusal should cite nothing. Clean, fast,
deterministic. **The first live `--grade` run refuted it.**

Asked *"what is the 850 Purchase Order?"*, the model produced a model refusal:

> *"The provided context doesn't cover the 850 Purchase Order… the transaction sets
> documented here are the 997, 824, and 214 [x12-overview.md], plus the rail-specific
> 161, 404, 417, and 990 [rail-edi-notes.md] — none of which is the 850. So I can't
> describe the 850 without inventing details."*

The regex scored that a **failure** — it says "doesn't cover," not "context does not,"
and it *cites* the docs (to explain the gap). Meanwhile *"boiling point of water?"* was
answered *"100 degrees Celsius"* from world knowledge — an actual failure. A regex
**can't separate the two**: the wrong answer also contains decline-ish phrasing.

What *did* separate them: **faithfulness**. The good refusal's claims ("the docs cover
997, 824…") are all supported → 1.0. The boiling-point answer's "100 °C" is not in an
EDI doc → below 1.0. So refusal-correctness was redefined as **faithfulness == 1.0 on
the unanswerable rows.** And here's the twist that resolves the circularity: for an
*out-of-corpus* question the answer is **no longer built purely from context** — the
model can reach for ungrounded knowledge — so faithfulness stops being circular and
starts being exactly the right detector.

The measured result, corrected:

| signal | score | meaning |
|---|---|---|
| answer-correctness | 100% | answerable questions surface the expected facts |
| refusal-correctness | 50% | passes the 850 refusal; flags the boiling-point hallucination |
| faithfulness (monitor) | ~90% | wobbles run-to-run (0.33 → 0.80 on the same item) |

That wobble is why **v1 is advisory, not a hard gate**: the judge runs on `claude -p`
(Opus, no temperature control), so it's non-deterministic. A gate that flips on noise
is worse than no gate. Threshold on `== 1.0` (any unsupported claim fails), report the
number labeled `estimated`, and don't commit a baseline until the judge is repeatable.

## Two grounding layers

It's worth seeing these side by side — they're different tools:

| | runtime guardrail (`guard_output`) | eval-time judge (`--grade`) |
|---|---|---|
| When | every request | pre-release, manual |
| Checks | *syntactic* — is a `[source]` cited? | *semantic* — correct? hallucinated? |
| Cost | free, instant | $0 subscription, slow-ish |
| In the gate? | yes (runtime) | **no** — an LLM can't live in the offline `pre-push` hook (ADR-0006) |

## Map to the framework

| Dimension | What this lesson adds |
|---|---|
| **Evaluation & Quality Gates** | answer-quality eval — refusal-/answer-correctness that can genuinely fail; faithfulness as a monitor, honestly framed |
| **Governance** | a metric that mis-scored real output was corrected *before shipping*, and the road-not-taken is recorded in the ADR |
| **Cost & Efficiency** | generation + judge on the subscription — $0 marginal; deterministic scoring where possible to avoid LLM calls |

## Try it yourself

```bash
python interchange.py --reindex        # build the index
python interchange.py --grade          # advisory answer-quality report ($0, needs the claude CLI)
python interchange.py --grade --fail-under 0.8   # optional: nonzero exit if a headline signal drops
```

The unanswerable rows are the interesting ones — watch whether the model declines or
reaches for world knowledge.

## What's honest about this

Two seed docs ⇒ a handful of golden questions; the numbers are directional and labeled
`estimated`, never asserted. The judge is non-deterministic, so refusal-correctness can
wobble — that's *why* it's advisory with no committed baseline (deferred until the judge
is made repeatable). And the sharpest honesty here isn't a number at all: it's that
**verifying against real output, not just green tests, is what caught a metric that
would otherwise have shipped a comfortable lie.**
