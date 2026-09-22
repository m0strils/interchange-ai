# Lesson 08 — A browser workbench that shows its scores honestly

Every earlier lesson answered a question and handed back an answer. This lesson
adds a surface where you watch the retrieval happen and see *why* a passage won
before you trust the answer. It is a browser workbench at `/ui`, over the same
guarded pipeline the CLI runs — no new engine, no lighter path, the same audit
row. The decision is [ADR-0015](../docs/adr/0015-browser-workbench-surface.md).
Here is the *why*.

## What we add

A same-origin page that asks a question, shows the retrieved evidence ranked with
its **real scores**, reveals the pipeline stage by stage as it runs, and streams
the grounded answer. Behind it: `retrieve_detail` (which keeps the scores instead
of discarding them), a policy tier that bounds what a web request may ask for, and
`POST /ask/stream` that sends the pipeline as Server-Sent Events. The CLI is
untouched; this is a fourth surface over the same core.

## Showing a score honestly

A retrieval score is only useful if you know what it is. The workbench never shows
a bare number. Each one carries its label from `score_legend`, and the labels are
deliberately different because the numbers are:

- **`dense_distance`** is `l2` — **squared** Euclidean distance over unit MiniLM
  embeddings. Lower is better, and only the chunks in the dense pool have one. The
  space is read live from the collection, never hard-coded, because a different
  collection could be `cosine` and the same number would then mean the opposite.
- **`bm25_score`** is raw Okapi BM25: `≥ 0` and **unbounded**. `0.0` means no
  query term overlapped, and then the rank shows as `—`, not as a made-up position.
- **`rrf_score`** is the reciprocal-rank-fusion sum, Σ 1/(60+rank), over exactly the
  rankings *this mode* fused. It is `null` for the single-ranking `dense` and `bm25`
  modes, because there was no fusion to score.
- **`rerank_score`** is the backend's own kind: a `logit` from the cross-encoder, a
  `score` from flashrank, a calibrated `probability` from TypeSafe's Jev. The first
  two are `measured` at $0; the last is `estimated`, because it is metered.

### Why bars would lie

The obvious way to draw scores is a bar chart, width proportional to value. For
BM25 and for a reranker logit that is a lie. A logit is unbounded and has no
meaningful zero, so "twice the bar" means nothing; normalising it to the max in
view makes the top row look certain and the bottom row look hopeless purely because
of who else happened to be on screen. So the workbench shows unbounded signals as
**the raw value plus an ordinal rank**, and it draws the one honest picture instead:
a **rank slopegraph**. Each passage's positions — dense rank, BM25 rank, fused rank,
reranked rank — are joined by a hairline. You see the passage BM25 loved and the
reranker demoted, as a line that falls. Rank is the thing every stage genuinely
shares, so a picture of ranks is a picture that is true. Jev's probability, being
calibrated to `0..1`, is the one signal that earns a fixed track.

This is the same honesty rule as ADR-0004: label measured versus estimated, and
never draw a number as if it means more than it does.

## The same guardrails on a new surface

The controls are a **layer**, not a feature of one pipeline shape (CLAUDE.md). The
input guardrail (OWASP LLM01) and the output grounding check run on every web
request exactly as they run on the CLI, because the web handler calls the same
`answer_detail`. A pinned re-ask is still guarded: an injection question with a
valid pin is blocked at the guard stage, and `fetch_chunks` never runs. There is no
web-only path around the guardrail, and the acceptance suite asserts it.

## Policy tier vs preference tier

A web request is the first Interchange request a stranger could send, so it is the
first that needs two tiers of authority. **The env is the policy tier. A request is
the preference tier. Policy wins.** The operator sets what corpora are reachable,
which knobs are locked, whether metered reranking is allowed, the rate limit and
the concurrency bound — in env. A request may express a *preference* within that.
When a preference exceeds policy, the answer is a **403 with a reason**, never a
silent downgrade to something the caller did not ask for. `GET /options` publishes
the whole policy document so the UI shows a locked knob as locked instead of
offering it and failing. Excessive agency (OWASP LLM Top 10, excessive-agency) is
contained by making authority live with the operator, not the caller.

## Pins as capabilities, and the oracle that wasn't shipped

The workbench lets you pick passages you trust and re-ask grounded only on them. The
naive way to send that back is `pin=<chunk id>`. That is a hole. With an
unrestricted corpus, `pin=<any id>` would let an unauthenticated caller read any
chunk of the private vault, one id at a time — a read-any-chunk **oracle**. So a
pin is not an id; it is a **capability token**. Every retrieved hit carries
`mint_pin(corpus, id)`, the first 16 hex of HMAC-SHA256 over `f"{corpus}|{id}"`, and
a re-ask must hand the token back. `fetch_chunks` verifies every token against the
corpus before it reads anything, by constant-time compare. A tampered token, or a
token minted for another corpus, is a 403. You can only pin a chunk the system
already showed you, in the corpus it showed you. The capability *is* the evidence of
prior authorised retrieval.

## The metered budget comes from the audit ledger

Metered reranking (TypeSafe Jev) is off by default and 403-gated. When an operator
turns it on, it is still bounded by a **daily budget**, and the budget is enforced
against the same honest ledger `--audit` reads: the spend so far today is the sum of
`cost_usd` over today's audit rows labelled `telemetry=="estimated"`. Over budget is
a 429, audited `blocked="budget"`. The run's rerank spend is folded into its own
`cost_usd` and the whole run is labelled `estimated`, so the metered path is never
free-looking or invisible. The cost control and the audit log are the same artefact,
which is the point.

## Two bugs worth teaching

**Contextvars do not cross into a new thread.** The audit `caller` is stored in a
`contextvars.ContextVar`. The stream runs the pipeline in a worker thread so the
async event loop stays free. The first cut set the caller in the request handler,
before starting the thread — and the audit rows came out with the wrong caller,
because a new thread does not inherit the parent's context var. The fix is one line
in the right place: set `enterprise.CALLER` **inside the worker function**, so the
`answer_detail` that writes the audit row sees it. A context var is thread-local by
design; crossing a thread boundary means re-establishing it on the far side.

**A `+` in a query string is a space.** The internal reranked mode is spelled
`hybrid+rerank`, and the links mode `hybrid+links`. Put either raw into a URL —
`?mode=hybrid+rerank` — and the query-string decoder turns the `+` into a space, so
the server receives `"hybrid rerank"`, which is not a mode. The fix is two parts:
the wire vocabulary splits `mode` and `rerank` into separate knobs so the reranked
mode never has to survive a URL at all, and a real `+` value like `hybrid+links`
must be percent-encoded as `hybrid%2Blinks`. The acceptance suite pins both: raw
`mode=hybrid+rerank` is a 422, and `mode=hybrid%2Blinks` is a 200. Two characters,
one of the oldest gotchas on the web, caught by a test rather than in the field.

## The mapping

**OWASP LLM Top 10**

| Clause | What covers it here |
|---|---|
| **LLM01 — prompt injection** | the input guardrail runs unchanged on every web request; a pinned re-ask is guarded before `fetch_chunks` |
| **Insecure output handling** | model and corpus text reach the page as DOM **text nodes**, never `innerHTML`; a `script-src 'self'` CSP with no CDN backs it, so an injected `<script>` in a chunk cannot execute |
| **Excessive agency** | the policy tier keeps authority with the operator — corpus allow-list, locked knobs, metered off by default, rate limit and concurrency bound — so a request cannot widen its own reach |
| **Vector / RAG poisoning** | retrieved chunk text is shown as evidence and rendered as text, never as HTML and never as instructions, so a poisoned passage can mislead a reader but cannot run in their browser or steer the model |

**NIST AI RMF**

- **GOVERN** — the policy tier is a governance boundary in code: who may ask what is
  an operator setting, refusals are audited, and every run writes the same audit row.
- **MEASURE** — the workbench surfaces per-stage timings and every retrieval score
  with an honest label, so retrieval quality and cost are observed, not asserted.

## Run it yourself

Serve the app on the stub engine (no API key, no metered call) against the local
index, and open the workbench:

```bash
INTERCHANGE_ENGINE=stub .venv/bin/python -m uvicorn app:app
# then open http://localhost:8000/ui/
```

Note: prefer `python -m uvicorn` over the `.venv/bin/uvicorn` shim. The shim's
shebang can carry a stale interpreter path (for example after the repo is moved),
and it then fails to launch; `python -m uvicorn` always uses the interpreter you
invoked it with.

See the policy document the UI renders from, and stream a run frame by frame:

```bash
curl -s localhost:8000/options | python -m json.tool
curl -sN -X POST localhost:8000/ask/stream \
  -H 'content-type: application/json' -d '{"q":"what is an 824?"}'
```

The stream sends the evidence on the `retrieve` frame *before* the answer arrives on
the `done` frame — you see the ranked chunks and their scores first, then the
grounded reply. Two more, to watch the policy tier and the `+` gotcha refuse a bad
request before the pipeline runs:

```bash
curl -si "localhost:8000/ask?q=x&corpus=vault"       | head -1   # 403 corpus_forbidden
curl -si "localhost:8000/ask?q=x&mode=hybrid+rerank" | head -1   # 422 (the '+' became a space)
```

## What this does not prove

This is a personal build, run against a single local process. The policy tier is
real code with real offline tests, but it has not seen production traffic; no public
deploy ships this sprint (the fail-closed public-auth rule is what would make one
safe to revisit). The UI's own JavaScript is verified in the browser, not by the
`pytest` gate — a JavaScript test runner is a follow-up, recorded honestly in
ADR-0015 rather than hidden. Token-level streaming, and a client-side cancel that
actually stops a mid-generate subprocess, are deferred: a Stop during generation
lets the model call finish server-side (bounded by the 180-second timeout) while the
browser stops listening.
