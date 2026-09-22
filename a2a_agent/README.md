# a2a_agent

The Agent-to-Agent (A2A) protocol surface for Interchange (ADR-0013): a
signed Agent Card, an API-keyed JSON-RPC task path, and a `requester` client
that verifies the card before sending anything. Same guarded core as the CLI
and `/ask` — the input guardrail and grounding check run unchanged on this
path.

## Run mode 1 — one command, offline, $0

```bash
make a2a-demo PROFILE=hotel      # or PROFILE=rail (default)
make test                        # offline suite, includes tests/test_a2a.py
INTERCHANGE_ENGINE=claude-code make a2a-accept   # acceptance gate; P1 costs $0 with this set
make a2a-keygen                  # prints a PRIVATE KEY block, then a PUBLIC KEY block (PEM)
```

`a2a_agent/demo.sh` mints an ephemeral ES256 key pair for the run, starts
`uvicorn app:app` on port `A2A_DEMO_PORT` (default 8765), runs the requester
against it, and stops the server. Engine is always `stub` — the point of the
demo is the governed handoff, not the model.

## Run mode 2 — manual, two terminals, a real model

Terminal 1 (server):

```bash
export A2A_SIGNING_KEY_PEM="$(cat path/to/private.pem)"
export A2A_API_KEYS="demo-key:requester"
export INTERCHANGE_ENGINE=claude-code   # or: api
# optional: point at a non-default corpus
export INTERCHANGE_COLLECTION=hotel
export INTERCHANGE_DOCS_DIR=hotel-demo
# optional: the URL peers actually reach you on (default http://localhost:8000)
export A2A_PUBLIC_URL=http://localhost:8000

.venv/bin/python -m uvicorn app:app --port 8000
```

Terminal 2 (requester):

```bash
export A2A_PINNED_PUBLIC_KEY_PEM="$(cat path/to/public.pem)"
# optional if the server used a non-default kid:
export A2A_PINNED_KID=interchange-2026-09

.venv/bin/python -m a2a_agent.requester \
  --url http://localhost:8000 --api-key demo-key --live \
  --question "what is an 824?"
```

`--profile rail|hotel` supplies the sample question instead of `--question`.
`--live` only warns if the far side answered from the stub engine — the
engine is the server's choice, not something this flag can change.

## Run mode 3 — plain HTTP once a server is up

```bash
curl -s localhost:8000/health
curl -s "localhost:8000/ask?q=what+is+an+824"
curl -s "localhost:8000/ask?q=late+checkout&corpus=hotel"
curl -s localhost:8000/.well-known/agent-card.json   # open, no key; signatures[], interfaces 1.0 + 0.3
```

The JSON-RPC task path at `/a2a` requires the API key header. The original
CLI is unchanged: `python interchange.py --ask "..." --engine claude-code`.

## Environment variables

| Variable | Side | Default | Purpose |
|---|---|---|---|
| `A2A_SIGNING_KEY_PEM` | server | unset (unsigned card) | Private ES256 key PEM the card is signed with. Env only, never on disk. |
| `A2A_PINNED_PUBLIC_KEY_PEM` | requester | unset (uses committed pin) | Public key PEM the requester trusts for this run — overrides the committed pin, for the demo's ephemeral key. |
| `A2A_PINNED_KID` | requester | `interchange-2026-09` | The `kid` the pinned public key applies to. |
| `A2A_API_KEYS` | server | unset (no key valid) | `key:label,key2:label2` — valid API keys and the caller label each writes to the audit log. |
| `A2A_API_KEY_HEADER` | both | `X-API-Key` | Header name the API key is presented in. |
| `A2A_PUBLIC_URL` | server | `http://localhost:8000` | The base URL the Agent Card advertises — must be the URL peers actually reach. |
| `A2A_DEMO_PORT` | demo | `8765` | Port `make a2a-demo` binds its ephemeral server to. |
| `INTERCHANGE_ENGINE` | server | `api` | Generation engine: `api`, `claude-code` (Max subscription, $0), or `stub`. |
| `INTERCHANGE_COLLECTION` | server | repo default | Chroma collection to answer from, when not using a profile's default. |
| `INTERCHANGE_DOCS_DIR` | server | repo default | Docs directory backing that collection, for `--reindex`. |

## What the demo output means

- `card verified kid=interchange-2026-09 interfaces=1.0,0.3` — the requester
  checked the Agent Card's signature against a pinned key before sending
  anything; the interfaces line shows both JSON-RPC versions the card offers.
- `status: WORKING` / `status: COMPLETED` (or `FAILED`) — task lifecycle
  events as the knowledge agent works the request.
- `grounded: true` — the answer passed the output grounding check (cited
  retrieved sources), same check the CLI and `/ask` enforce.
- `audit: caller=a2a:requester engine=... model=... cost_usd=... marginal_usd=... blocked=...` —
  the server's own audit row for the request, read back from the JSONL log,
  not a value the client reported about itself.

## Key handling

- The private key lives only in `A2A_SIGNING_KEY_PEM`, never in the tree.
- `.gitignore` excludes `*.pem` except `*.pub.pem`.
- The committed `a2a_agent/keys/interchange-2026-09.pub.pem` is the pin for
  the deployed agent.
- The offline demo mints its own ephemeral pair per run and overrides the
  pin via `A2A_PINNED_PUBLIC_KEY_PEM` — a fresh clone has no private key and
  needs none to run the demo.

## More

- [ADR-0013: agent-to-agent interop over A2A](../docs/adr/0013-a2a-agent-interop.md)
- [Lesson 07 — handing off to another agent over A2A](../lessons/07-a2a-handoff.md)
- [orchestrate/README.md](orchestrate/README.md) — watsonx Orchestrate registration
