# Interchange

**A governed *knowledge runtime* for the rail / EDI domain — retrieval,
grounding, and audit as one integrated system.**

In EDI, the ISA/IEA envelope is literally called an *interchange*. In rail, an
interchange is where railroads exchange traffic. This project sits at both:
an assistant that answers questions about X12/EDI transaction sets and rail
trading-partner integration — built the way a regulated enterprise has to build
it, with guardrails, auditability, and cost governance from day one.

> Built by a rail-industry EDI platform architect as a working demonstration of
> production-minded agentic AI — not a naive demo.

## Positioning (2026): a knowledge runtime, not a RAG demo
"Naive RAG" — chunk-and-pray, retrieve-then-generate — is on its way out. The
durable 2026 pattern is the **knowledge runtime**: retrieval + verification +
reasoning + access-control + audit as *integrated operations*, with the judgment
to route between plain retrieval, long-context, and **agentic retrieval** (the
model inside the loop, deciding when it has enough context). Interchange is built
to that pattern — the MVP implements the grounded, audited core; agentic
retrieval, retrieval/long-context routing, and agentic memory are the roadmap
(and are marked honestly as such in the scorecard below).

## Why this exists
Most RAG demos stop at "retrieve → generate." Enterprises can't. This project
treats the hard parts as first-class:

- **Security** — input guardrail with prompt-injection heuristics + input limits
  (OWASP LLM01), and instruction/data separation in the prompt itself.
- **Groundedness** — an output guardrail: answers must cite retrieved sources or
  they are visibly flagged `⚠️ UNGROUNDED`. An honest "the context doesn't say"
  beats a confident hallucination.
- **Governance** — a JSONL audit log per request: question, model, sources,
  token usage, cost estimate, latency, blocked/grounded status.
- **Cost control** — per-request cost estimation and a running dashboard
  (`--audit`): requests, blocked, ungrounded, total spend, p50 latency.

The controls live in `enterprise.py`, deliberately stdlib-only and small enough
to read line-by-line.

## Quickstart

Prereqs: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

cp .env.example .env   # add your ANTHROPIC_API_KEY (console.anthropic.com)

python interchange.py --reindex                      # index docs/
python interchange.py --ask "What is an 824 and when is it used?"
python interchange.py                                # interactive
python interchange.py --audit                        # governance/cost summary
```

Embeddings run locally (Chroma's default model) — the only external call is
generation (Claude). Drop your own `.md`/`.txt` domain docs into `docs/` and
re-index; the included files are illustrative seed content.

### Engines (cost control)
Generation is pluggable — an enterprise pattern (model/provider routing) in miniature:

```bash
python interchange.py --ask "..."                      # default: Anthropic SDK (metered API)
python interchange.py --engine claude-code --ask "..." # headless Claude Code on a Pro/Max subscription ($0 marginal)
```

`--engine api` gives exact token/cost telemetry and is the standard production
pattern. `--engine claude-code` shells out to `claude -p`, billing nothing extra
if you have a Claude subscription (token counts are estimated; shares your
subscription's usage limits). The audit log records which engine served each
request. Set a default with `INTERCHANGE_ENGINE=claude-code` in `.env`.

## Architecture (MVP)

```
docs/*.md ──chunk──> Chroma (local vectors)
                         │  top-k retrieve
user ──input guardrail──> Claude (context = data, not instructions)
                         │
                 output guardrail (grounding/citation check)
                         │
                 audit log (tokens · cost · latency · grounded)
```

## Enterprise-readiness scorecard
✅ built · 🟡 partial · ⬜ roadmap

| Dimension | Control | Status |
|---|---|---|
| Security | input/output guardrails, injection defense, instruction/data separation | ✅ |
| Governance | per-request audit log w/ cost + grounding; secrets hygiene | ✅ |
| Evaluation | retrieval hit@k eval (`--eval`); answer-quality grade — refusal- & answer-correctness + faithfulness monitor (`--grade`, advisory) | 🟡 |
| Observability | always-on latency/cost in the audit log; opt-in OpenTelemetry tracing of the RAG + agent paths to a local Phoenix (`INTERCHANGE_TRACING=1`, ADR-0009) | 🟡 |
| Reliability | graceful refusal over hallucination; retries/fallback routing | 🟡 |
| Cost | per-request estimate + running total; model routing | 🟡 |
| Deployment | IaC, CI/CD, AWS Bedrock in-VPC | ⬜ |
| Context/Memory | agentic retrieval, retrieval/long-context routing, agentic memory | ⬜ |

## Roadmap
1. **Agentic retrieval:** LangGraph agent + an MCP tool server ("look up X12 segment definition"); hybrid retrieval; the model routes between retrieve / long-context / iterate-until-enough-context (the knowledge-runtime loop).
2. **Quality gate:** RAGAS eval harness on a golden set; block regressions.
3. **Observability:** Arize Phoenix tracing.
4. **Hardening:** classifier-grade guardrails (e.g., Bedrock Guardrails), model routing, caching.
5. **Cloud:** port generation to AWS Bedrock (data stays in-VPC).

## License / data
MIT. The `docs/` content is generic, public-knowledge EDI/rail reference
material — no proprietary partner specifications are included.
