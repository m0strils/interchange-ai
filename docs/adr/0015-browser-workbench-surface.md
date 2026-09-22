# ADR-0015: A browser workbench over the same governed pipeline

- **Status:** Accepted
- **Date:** 2026-09-22
- **Deciders:** Jeff Lynch

## Context
Interchange answers questions from four surfaces — the CLI, the REST `/ask`, the
MCP tool server, and the A2A task path (ADR-0013) — and all four end in the same
call: `interchange.answer_detail` plus the guardrails and audit row in
`enterprise.py`. A person who wants to judge *why* a passage won had nothing to
look at. Every retrieval score was computed and then discarded: the dense query
read only Chroma ids, `bm25_rank` returned indices, `reciprocal_rank_fusion`
returned keys, and the reranker returned ids. `/ask` returned deduped filenames.
`--explain` narrated to stderr. There was no browser surface at all: no static
files, no streaming on `/ask`, no scored evidence anywhere.

The gap is a teaching gap as much as a product one. The 2026 headline claim of
this repo is that retrieval is *inspectable* — that groundedness is a control you
can watch work, not a promise. That claim needs a surface where a reader sees the
ranked evidence with its real numbers before trusting the answer.

Constraints, all carried from earlier ADRs, all binding here:

- **$0 marginal.** No metered call by default (CLAUDE.md; ADR-0003/0004). A web
  surface must not open a cheap path to paid inference.
- **No hosted CI.** The gate is a local `pre-push` hook (ADR-0006). Whatever ships
  has to be testable offline and free, under the existing `pytest` gate.
- **Offline tests.** The model boundary is stubbed (ADR-0005). New behaviour needs
  acceptance criteria that run with no network and no key.
- **Single deploy.** One process, one origin. There is no second service to run,
  no separate build pipeline to keep alive, and no budget for one.

The outcome is a same-origin browser workbench at `/ui`, over the *same* governed
pipeline, plus the scored-retrieval, policy, and stage-event contract it needs.
The CLI is untouched. This is recorded here and taught as Lesson 08.

## Options considered
1. **A separate Next.js app on Vercel.** The familiar shape: a React front end
   deployed on its own, calling Interchange as a JSON API over CORS. Best-in-class
   developer experience and a real build. But it is a second service with its own
   deploy, its own origin (so CORS, and a public API surface to secure), and a
   Node build pipeline — none of which the $0 / single-deploy / no-hosted-CI
   constraints have room for. It also splits the audit story across two systems.
2. **Server-rendered Jinja templates**, the way `workflow-engine` renders its
   dashboard. One process, no Node, no build. But the workbench is not a document;
   it is a live instrument — a stage timeline that fills as events land, evidence
   that arrives in rank order, runs that stack and compare. That is client state,
   and hand-rolling it on server-rendered HTML plus sprinkled JavaScript trades one
   kind of complexity for a worse one.
3. **Vendored, no-build Preact + htm + `@preact/signals`, served by FastAPI from
   `web/` — chosen.** Five pinned ES-module files under `web/vendor/`, fetched once
   with `curl` and committed, with bare specifiers rewritten to relative paths so no
   import map is needed and `script-src 'self'` holds. Reactivity (signals) without
   a build step, a real component model, one process, one origin, and every byte the
   browser runs is in the repo and hashed. The cost is that the vendored files are
   pinned by hand and the UI's own JavaScript is not exercised by the Python gate.
4. **A Vite build committed to the repo.** Same Preact, but with a proper bundler
   and the built artefact checked in. Cleaner authoring, tree-shaking, a dependency
   graph a tool understands. But it reintroduces Node and a build step as the source
   of truth, and a committed `dist/` that can silently drift from its inputs — the
   exact "did the build match the source?" problem the no-build route sidesteps by
   having no build.

## Decision
Add the workbench as a fourth-and-a-half surface: a new front end and the backend
contract it needs, with the guardrails, audit, and honest telemetry reused
verbatim. Three parts.

### (a) The contract — scored retrieval and a streamed pipeline
`retrieve_detail(question, *, mode, top_k, pool, rerank_n, rerank_backend)` returns
a `Retrieval` record `{hits, scoring, timings, space, corpus}`, so the scores exist
as data even when the retriever is faked in a test. Each `Hit` keeps every signal
it has and `null` for every signal it does not: `dense_rank`/`dense_distance` only
for ids in the dense pool, `bm25_rank` `null` when the BM25 score is `0.0`,
`rrf_score` `null` for the `dense`/`bm25` single-ranking modes and for pinned
chunks, `rerank_score` only inside the rerank window. `retrieve()` becomes a thin
wrapper over `retrieve_detail(...).hits`, so its signature and every existing caller
are unchanged.

`score_legend(space, rerank_backend)` labels the numbers honestly, because a number
with no unit is a lie waiting to happen:

- `dense_distance.kind` is the collection's HNSW `space` read live (`l2` here =
  **squared** Euclidean over unit MiniLM embeddings; lower is better). Never
  hard-coded.
- `bm25_score.kind` is `bm25_okapi`: a raw Okapi BM25 value, `≥ 0` and **unbounded**;
  `0.0` means no query-term overlap and the rank shows as `—`.
- `rrf_score.kind` is `rrf`: the Σ 1/(60+rank) sum over the rankings *this mode*
  fused.
- `rerank_score` carries the backend's own `kind` — `logit` (cross-encoder),
  `score` (flashrank), or `probability` (typesafe) — and its telemetry honesty:
  `measured` at $0 for the local backends, `estimated` for the metered one.

`answer_detail` gains an `on_event(frame)` callback that fires once per pipeline
stage — `guard → retrieve → [rerank] → generate → ground → done` — and a `cancel`
event checked between stages. The `hits` and `scoring` ride the `retrieve` frame
only; they never sit inside the `stages` list. `POST /ask/stream` turns those
frames into Server-Sent Events. It is **`fetch` + `ReadableStream`**, deliberately
**not `EventSource`**: `EventSource` auto-reconnects on every drop, which from one
idle browser tab would respawn a fresh `claude -p` subprocess every few seconds.
The stream sends `: keepalive` comments on silence, and — the part that matters —
the generation **semaphore is released inside the worker thread**, in its `finally`,
never in the response generator. A client disconnect fires the generator's cleanup;
if the slot were released there, a still-running subprocess would keep a freed slot.
`GET /options` publishes the whole policy document (below) so the UI renders straight
off it and hard-codes no option list.

### (b) The policy tier — env is policy, a request is preference, policy wins
The web surface is the first Interchange surface a stranger could reach, so it is
the first that needs a policy tier distinct from the caller's preferences
(`policy.py`). The rule is one sentence: **the env is the policy tier, a request is
the preference tier, and policy wins** — a refused preference is a **403 with a
reason**, never a silent downgrade to something the caller did not ask for.

- **Corpus allow-list** (`INTERCHANGE_CORPORA`, default `edi,hotel`). The private
  `vault` is reachable only if an operator lists it.
- **Pins are HMAC capability tokens.** A retrieved hit carries `mint_pin(corpus,
  id)` = the first 16 hex of HMAC-SHA256 over `f"{corpus}|{id}"`. A re-ask that
  pins chunks must hand every token back, and `fetch_chunks` verifies each before
  reading anything. Without this, `pin=<any id>` plus an unrestricted corpus is an
  unauthenticated read-any-chunk oracle over the personal vault. The pin is a
  *capability*, not a lookup key.
- **Metered reranking is off by default.** `rerank=typesafe` is a 403 unless
  `INTERCHANGE_ALLOW_METERED=1`. When on, a **daily budget** read from the audit
  ledger (the sum of today's `cost_usd` over rows labelled `telemetry=="estimated"`)
  caps it; over budget is a 429, audited `blocked="budget"`. The rerank spend is
  folded into the run's `cost_usd` and the whole run is labelled
  `telemetry=estimated`, so the metered path is never invisible in the cost total.
- **A per-host token bucket and a generation semaphore.** The bucket
  (`INTERCHANGE_RATE_PER_MIN`) rate-limits per client; the semaphore
  (`INTERCHANGE_MAX_CONCURRENT`) bounds how many 180-second subprocesses run at
  once. Both answer 429 and audit the refusal.
- **An error catalogue with correlation ids.** A `SystemExit` from a missing index,
  or an engine failure, is mapped by cause to a fixed code
  (`index_missing`/`rerank_unavailable`/…) and a safe message; the real text and a
  `correlation_id` go to the server log only. `str(e)` never reaches the wire — it
  leaks filesystem paths and stderr.
- **Security headers.** `Content-Security-Policy` (`script-src 'self'`, no CDN),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, added by raw
  ASGI middleware so the SSE body is never buffered.
- **Fail-closed on a public deploy.** When `A2A_PUBLIC_URL`'s host is not localhost
  — i.e. the host is publishing a discoverable signed Agent Card — `/ask*` require
  `X-API-Key` from `A2A_API_KEYS`, and unset keys are a 403, not an open door.
  Locally (the default) the routes stay open for the demo.

### (c) The UI stack
The vendored no-build Preact stack (Option 3). `web/index.html` links one stylesheet
and one ES module; `web/vendor/` holds the five pinned files with a `SHA256SUMS`
manifest and a `VERSIONS.md` recording the exact `curl`/`sed`/`shasum` commands. No
Node, no import map, no runtime CDN. `tests/test_web_assets.py` checks the hashes
match, that no vendored file carries a bare `preact`/`@preact` specifier or an
`http(s)` URL (bar the three w3.org XML-namespace constants Preact passes to
`createElementNS`), and that `web/` contains exactly the manifest. The `/ui` mount
is guarded: it is skipped when `INTERCHANGE_UI=0` or when `web/` is absent, because
`StaticFiles` raises at import when its directory is missing.

**Origin of the P0 changes.** Before any of this was built, the design went through
a six-lens review — security, correctness, cost, governance, accessibility, UX.
That review is why the pins are capability tokens and not lookup keys, why the
stream is `fetch` and not `EventSource`, why metered reranking is budgeted from the
ledger and 403-gated, why `/options` publishes precedence so a query param can never
override an operator's env, and why the muted text token was darkened so the numerals
it carries pass AA contrast. The controls in this ADR are not afterthoughts bolted
on; several are the review's P0 findings, folded in before the first line of the
surface shipped.

## Consequences
**What becomes true now**
- Retrieval is inspectable from a browser, on the same governed pipeline, with the
  same audit row the CLI writes. The scores that were computed and thrown away are
  now first-class data with honest labels.
- The policy tier gives the surface a safe public story *without* being deployed
  publicly: the fail-closed rule is what will make the go-public decision reversible
  and cheap to revisit.
- `on_event` is a clean seam. Token-level streaming, when it lands, reuses it —
  forward `claude -p`'s partial-message deltas as a `token` stage through the same
  callback — with no new transport.

**What we accept as a cost**
- **`web/<sess8>` is correlation, not identity.** The caller label on a local run is
  the first 8 chars of a browser-kept session uuid. It ties a run to a tab so the
  audit trail is followable; it does not authenticate a person. On a public deploy
  the label is the API-key label instead.
- **`/options` and `/ui` stay open on a public deploy.** Only `/ask*` are
  key-gated. A public host therefore discloses its policy document and serves the
  static UI to anyone. This is accepted: it is information disclosure only, no
  inference and no corpus content, and discovery has to work before a caller has a
  key (the same reasoning as the open Agent Card endpoint in ADR-0013).
- **The rate-limit bucket keys on the socket peer.** Behind a reverse proxy every
  client shares the proxy's IP and collapses into one bucket — deliberately
  conservative (fail toward over-limiting). `X-Forwarded-For` is *not* trusted; it
  is client-spoofable and would let a forged IP mint a fresh bucket per request. A
  `TRUSTED_PROXY` parse is a follow-up, to land before any behind-a-proxy deploy.
- **The UI's JavaScript is not under the pytest gate.** The Python contract (routes,
  policy, stream framing, vendored-asset integrity) is covered offline; the
  rendered behaviour was verified in-browser by the accessibility and UI/UX agents.
  A JavaScript test runner is a follow-up, recorded here as a real gap, not hidden.
- **The `--agent` path is not in the UI.** It returns a plain string with no `hits`
  and no scored evidence, so it has nothing for the workbench to show. It stays a
  CLI/API capability.
- **A client disconnect cannot kill a mid-generate subprocess.** `claude -p` has no
  cancel signal we honour mid-call; `cancel` is checked between stages, so a Stop
  during generation lets the current model call finish server-side (bounded by the
  180-second subprocess timeout) while the browser stops listening. The UI says so
  in plain words rather than pretending the work stopped.
- **The vendored JavaScript is pinned by hand.** Its integrity rests on
  `SHA256SUMS` plus the `pytest` manifest check, not on a lockfile a tool resolves.
  Updating a version is a manual re-vendor with the recorded commands.

## Honest limits
This is a personal learning build, not a fielded multi-tenant service. The policy
tier is real code with real tests, but it has been exercised by the offline suite
and by hand, not by production traffic. No public deploy ships this sprint; the
fail-closed rule is what would make one safe to revisit, gated on the separate
go-public decision. Token streaming, a JavaScript test runner, the `TRUSTED_PROXY`
parse, and the `--agent` path in the UI are all deferred, explicitly.
