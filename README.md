# Interchange

**An enterprise-grade agentic RAG assistant for the rail / EDI domain.**

In EDI, the ISA/IEA envelope is literally called an *interchange*. In rail, an
interchange is where railroads exchange traffic. This project sits at both:
a retrieval-augmented assistant that answers questions about X12/EDI transaction
sets and rail trading-partner integration — built the way a regulated enterprise
has to build it, with guardrails, auditability, and cost governance from day one.

> Built by a rail-industry EDI platform architect as a working demonstration of
> production-minded agentic AI — not a naive demo.

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
| Evaluation | golden dataset + faithfulness gate (RAGAS) | ⬜ |
| Observability | latency/cost in audit log; distributed tracing (Phoenix) | 🟡 |
| Reliability | graceful refusal over hallucination; retries/fallback routing | 🟡 |
| Cost | per-request estimate + running total; model routing | 🟡 |
| Deployment | IaC, CI/CD, AWS Bedrock in-VPC | ⬜ |

## Roadmap
1. **Agentic:** LangGraph agent + an MCP tool server ("look up X12 segment definition"); hybrid retrieval.
2. **Quality gate:** RAGAS eval harness on a golden set; block regressions.
3. **Observability:** Arize Phoenix tracing.
4. **Hardening:** classifier-grade guardrails (e.g., Bedrock Guardrails), model routing, caching.
5. **Cloud:** port generation to AWS Bedrock (data stays in-VPC).

## License / data
MIT. The `docs/` content is generic, public-knowledge EDI/rail reference
material — no proprietary partner specifications are included.
