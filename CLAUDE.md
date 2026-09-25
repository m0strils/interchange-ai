# CLAUDE.md — Interchange

A governed **knowledge runtime** for the X12/EDI + rail domain: retrieval,
grounding, and audit as one system — built the way a regulated enterprise has to.
A personal learning-by-building project; present it as such, with no proprietary data.

## Commands
```bash
python -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
pip install -r requirements.txt                     # runtime deps
pip install -r requirements-dev.txt                 # test deps (pytest, pytest-bdd)

python interchange.py --reindex                     # build the local Chroma index (.md/.txt/.pdf; PDF via pypdf, flat text — ADR-0010)
python interchange.py --ask "what is an 824?"       # one-shot RAG
python interchange.py --agent --explain --ask "…"   # agentic loop on your Claude subscription
python interchange.py --audit                       # governance / cost dashboard
python -m pytest -q                                 # the test gate (offline, free)
uvicorn app:app                                     # HTTP: /health, /ask, signed A2A card + /a2a (ADR-0013)
INTERCHANGE_ENGINE=stub python -m uvicorn app:app   # browser workbench at /ui + POST /ask/stream (SSE) + GET /options (ADR-0015); $0 stub
# ^ prefer `python -m uvicorn`; the `.venv/bin/uvicorn` shim can carry a stale shebang.
#   Policy env vars for the web surface: see .env.example ("Browser workbench + HTTP policy tier").
make a2a-demo PROFILE=hotel                         # two-agent A2A demo, $0 on the stub engine (rail|hotel)
scripts/a2a-accept.sh                               # A2A Goal A acceptance gate (run with INTERCHANGE_ENGINE=claude-code)
make workbench-accept                               # real-engine acceptance gate (ADR-0015): 5 claude -p calls on the subscription, $0 marginal; WB_ENGINE=stub self-tests at $0
make reindex PROFILE=vault                          # index a profile's corpus in-process via --profile (ADR-0016); vault still needs INTERCHANGE_VAULT_DIR unless an overlay sets docs_dir
make eval PROFILE=vault MODE=all K=4                # measured retrieval ablations over the profile's golden set (ADR-0014); MODE unset = the profile's declared default
python interchange.py --profile brain --ask "…"     # any profile, including ones defined only in the private overlay (~/.interchange/profiles.yaml, ADR-0016)
python interchange.py --profile brain --golden-add --question "…" --expected "path/in/corpus.md"   # eval-as-you-go: append a validated golden row
scripts/launchd/install.sh brain                    # nightly 03:30 full reindex for one profile (read-only, $0); measured 30 s for 4,614 chunks
# ^ INTERCHANGE_CHROMA_DIR relocates the store (one per machine, N collections); INTERCHANGE_PROFILES="" disables the overlay (the test gate pins it off)
```

**Status:** ADR-0016 in progress on `feature/corpus-profiles` — **corpus profiles as
portable data**: a private overlay (`INTERCHANGE_PROFILES`) adds or extends profiles outside
the tree, `INTERCHANGE_CHROMA_DIR` relocates the store, `--profile` applies a profile
in-process (retiring the export-before-`.env` edge), and `persona` / `retrieval` / `tools`
are profile keys resolved per request by collection. The owner's second brain (a new
Obsidian vault) and a `research` corpus over saved last30days dumps are overlay-only
profiles; nothing personal enters the repo. Rebuild times are **measured** (vault 30 s,
brain 3 s); incremental reindex stays trigger-gated. Before it, ADR-0015 shipped — a same-origin **browser workbench** at `/ui` over the
same governed pipeline: scored retrieval (`retrieve_detail`, honest score labels), a
policy tier (`policy.py`: env is policy, request is preference, policy wins), pins as
HMAC capability tokens, a ledger-enforced metered budget, a per-host rate limit +
generation semaphore, and `POST /ask/stream` (SSE, `fetch`/`ReadableStream`). The CLI
is untouched; the JS is verified in-browser, not by the pytest gate (a noted gap).
Before it, ADR-0014 shipped — the vault corpus (188 notes, 4,614 chunks) is ingested
read-only and its retrieval ablations are **measured** (`eval/eval-runs.jsonl`):
ADR-0007's reranker trigger fired and paid off (hit@1 11→15/18, local cross-encoder, $0),
while naive link-aware expansion regressed and stays deferred.

## Architecture & conventions
- **Guardrails + audit are the spine** (`enterprise.py`): input guardrail
  (OWASP LLM01), output grounding check, JSONL audit with honest telemetry. Reuse
  them on every path — the controls are a *layer*, not a feature of one pipeline shape.
- **Engines return a dict** `{text, in, out, cost, telemetry, model}`. The `claude -p`
  JSON parse lives in exactly one place: `interchange.parse_claude_usage`.
- **Telemetry is honest** (ADR-0004): `telemetry` is `measured` or `estimated`; cost
  is a *shadow* (API-equivalent) value with `marginal_usd` ($0 on a subscription);
  record the model that **actually ran**, not the configured one.
- **`--agent` runs on your Claude subscription** (ADR-0003): headless `claude -p`
  driving an MCP tool server (`mcp_server.py`), least-privilege tool allow-list, no
  API key. The hand-rolled API loop (`agent.py`) is kept as the Lesson 02 reference.
- **Decisions live in `docs/adr/`.** Read them before changing orchestration, auth,
  telemetry, or tooling; a new significant decision gets a new ADR.
- **Teaching layer:** `lessons/` (how) + `docs/adr/` (why) + `TEACHING.md` (index).

## Testing (ADR-0005)
`pytest` + `pytest-bdd`. Acceptance criteria in `features/*.feature`, units in
`tests/`. Tests run **offline and free** — stub the model boundary (patch the engine
/ `subprocess.run` / `retrieve`) and redirect `enterprise.AUDIT_PATH` to a temp file.
Add or adjust a scenario for new behavior *before* implementing it.

**Gate (ADR-0006):** a `pre-push` hook runs the suite before every push — no hosted
CI (out of GitHub Actions minutes / $0). Install once per clone:
`git config core.hooksPath .githooks`. A failing suite blocks the push
(`git push --no-verify` bypasses in a pinch).

## Honest-claim rule
Personal portfolio/learning project. Scorecards tell the truth (built / partial /
roadmap). No demo dressed up as shipped; no proprietary partner specs; `docs/` is
public-knowledge seed content only.
