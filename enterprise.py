"""
Enterprise controls for Interchange — the showcase differentiator.

Adds to the MVP (see enterprise-readiness.md, dimensions 1/2/4/6):
  - input guardrail:  prompt-injection heuristics + input limits (OWASP LLM01)
  - output guardrail: grounding check — answers must cite retrieved sources
  - audit log:        JSONL record of every request (who/what/model/latency/cost)
  - cost tracking:    token usage -> $ estimate per request, running total

Deliberately dependency-free (stdlib only) so the controls are legible in an
interview: each function is small enough to read aloud and defend.

Usage (wired into interchange.py):
    from enterprise import guard_input, guard_output, audit
"""
from __future__ import annotations

import contextvars
import json
import pathlib
import re
import time
import uuid

AUDIT_PATH = pathlib.Path(__file__).parent / "audit.jsonl"

# Who is asking. Set by a calling surface (the HTTP API / an A2A peer) so the
# audit row records the caller identity; None on the CLI path. A ContextVar
# keeps it request-scoped without threading an argument through the pipeline.
CALLER: contextvars.ContextVar[str | None] = contextvars.ContextVar("caller", default=None)

# --- 1) input guardrail (OWASP LLM01: prompt injection) --------------------
# Heuristic first line of defense. Enterprise stack layers this with a
# classifier (e.g., Bedrock Guardrails / Llama Guard) — documented in README.
MAX_INPUT_CHARS = 2000
_INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior|above) (instructions|context|rules)",
    r"disregard (your|the) (system prompt|instructions|rules)",
    r"you are now\b",
    r"\bnew (persona|identity|instructions)\b",
    r"reveal (your|the) (system prompt|instructions|secrets?|api key)",
    r"\bjailbreak\b",
    r"\bDAN mode\b",
    r"pretend (you are|to be)\b",
    r"output (your|the) (system|hidden) prompt",
]
_injection_re = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


class GuardrailViolation(Exception):
    """Raised when a guardrail blocks the request/response."""


def guard_input(question: str) -> str:
    """Validate the user question before it reaches the model."""
    q = question.strip()
    if not q:
        raise GuardrailViolation("empty input")
    if len(q) > MAX_INPUT_CHARS:
        raise GuardrailViolation(
            f"input too long ({len(q)} chars > {MAX_INPUT_CHARS}); possible stuffing attack"
        )
    m = _injection_re.search(q)
    if m:
        raise GuardrailViolation(f"possible prompt-injection pattern: {m.group(0)!r}")
    return q


# --- 2) output guardrail (grounding / citation check) ----------------------
def guard_output(answer: str, source_names: list[str]) -> tuple[str, bool]:
    """
    Grounding check: the system prompt requires [filename] citations from the
    retrieved context. If none are present, flag the answer as ungrounded —
    return it with a visible warning instead of silently passing it through.
    Returns (possibly annotated answer, grounded: bool).
    """
    cited = any(f"[{name}]" in answer for name in source_names)
    # "don't know" responses are legitimately citation-free
    refusal = re.search(r"(context does not|don't have|no information|cannot find)", answer, re.I)
    if cited or refusal:
        return answer, True
    return (
        "⚠️ UNGROUNDED (no source citations — treat as unverified):\n\n" + answer,
        False,
    )


# --- 3+4) audit log + cost tracking ---------------------------------------
# Prices per million tokens (update as pricing changes; illustrative defaults).
_PRICES = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    pin, pout = _PRICES.get(model, (3.00, 15.00))
    return (in_tokens * pin + out_tokens * pout) / 1_000_000


def audit(
    *,
    question: str,
    model: str,
    sources: list[str],
    in_tokens: int,
    out_tokens: int,
    latency_ms: int,
    grounded: bool,
    blocked: str | None = None,
    engine: str = "api",
    telemetry: str = "measured",
    cost_usd: float | None = None,
    context: dict | None = None,
    hit_sources: list[str] | None = None,
) -> dict:
    """Append a governance record for this request; return it (ADR-0004).

    telemetry: "measured" (real token/cost data) or "estimated" (a labeled guess).
    cost_usd:  the API-equivalent cost when known (e.g. `claude -p` total_cost_usd);
               if None it's computed from the token counts. On subscription engines
               this is the *shadow* cost — real resource use, but $0 marginal to you.
    context:   the mode-independent context-assembly block (ADR-0018:
               {mode, chunks_in, chunks_out, chars, budget_hit, fallbacks,
               dropped_hits, secret_drops, assemble_ms}); None for callers that
               assemble no context (guardrail blocks, rate-limit/budget refusals).
    hit_sources: the retrieved hits' sources, separate from ``sources`` (which follows
               the INCLUDED set once assembly can drop a ranked note — review finding #2).
    Both keys are always written (default None) so every row shares one shape.
    """
    shadow = cost_usd if cost_usd is not None else estimate_cost(model, in_tokens, out_tokens)
    marginal = shadow if engine == "api" else 0.0
    rec = {
        "id": str(uuid.uuid4())[:8],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": question[:300],
        "model": model,
        "engine": engine,
        "telemetry": telemetry,
        "sources": sources,
        "hit_sources": hit_sources,
        "context": context,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "cost_usd": round(shadow, 6),        # API-equivalent (shadow) cost
        "marginal_usd": round(marginal, 6),  # what you actually paid ($0 on a subscription)
        "latency_ms": latency_ms,
        "grounded": grounded,
        "blocked": blocked,
        "caller": CALLER.get(),
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def audit_summary() -> str:
    """Running totals for the cost/quality dashboard (CLI `--audit`)."""
    if not AUDIT_PATH.exists():
        return "no audit records yet"
    recs = [json.loads(line) for line in AUDIT_PATH.read_text().splitlines() if line.strip()]
    shadow = sum(r.get("cost_usd", 0) for r in recs)
    billed = sum(r.get("marginal_usd", r.get("cost_usd", 0)) for r in recs)
    estimated = sum(1 for r in recs if r.get("telemetry") == "estimated")
    blocked = sum(1 for r in recs if r.get("blocked"))
    ungrounded = sum(1 for r in recs if r.get("grounded") is False)
    lat = [r["latency_ms"] for r in recs if r.get("latency_ms")]
    p50 = sorted(lat)[len(lat) // 2] if lat else 0
    return (
        f"requests={len(recs)}  blocked={blocked}  ungrounded={ungrounded}  "
        f"estimated_rows={estimated}  shadow_cost=${shadow:.4f}  billed=${billed:.4f}  "
        f"p50_latency={p50}ms"
    )
