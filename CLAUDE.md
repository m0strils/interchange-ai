# CLAUDE.md — Interchange

A governed **knowledge runtime** for the X12/EDI + rail domain: retrieval,
grounding, and audit as one system — built the way a regulated enterprise has to.
A personal learning-by-building project; present it as such, with no proprietary data.

## Commands
```bash
python -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
pip install -r requirements.txt                     # runtime deps
pip install -r requirements-dev.txt                 # test deps (pytest, pytest-bdd)

python interchange.py --reindex                     # build the local Chroma index
python interchange.py --ask "what is an 824?"       # one-shot RAG
python interchange.py --agent --explain --ask "…"   # agentic loop on your Claude subscription
python interchange.py --audit                       # governance / cost dashboard
python -m pytest -q                                 # the test gate (offline, free)
```

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

## Honest-claim rule
Personal portfolio/learning project. Scorecards tell the truth (built / partial /
roadmap). No demo dressed up as shipped; no proprietary partner specs; `docs/` is
public-knowledge seed content only.
