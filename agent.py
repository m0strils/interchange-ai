"""
Interchange — agentic runtime (iteration 1 of the knowledge-runtime evolution).

Where interchange.py does one shot (retrieve -> generate), this runs the loop a
production agent runs: the model decides *whether* to search, can look up a
domain fact, and *iterates* — search, reason, "do I have enough?", answer or
search again.

Per ADR-0002 (docs/adr/0002-orchestration-framework.md) the loop is hand-rolled
on the Anthropic SDK — no framework — so every step is visible and teachable.
LangGraph comes later, in a superseding ADR, when branching state earns it.

The loop, in one breath:
    while the model asks for a tool:
        run the tool -> hand the result back -> let it think again
    stop when it answers (or we hit the step cap — a reliability guard).

Reuses the MVP's controls unchanged: input guardrail (OWASP LLM01), grounding
check, and the audit/cost log. Only the API engine supports tool use, so this
path needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import os
import sys
import time

from enterprise import GuardrailViolation, audit, guard_input, guard_output
from interchange import MODEL, TOP_K, _explain, retrieve

# A step cap is a reliability control, not a nicety: a wrong tool result can send
# an agent into a retrieve/reason loop that never converges. Bound it. (Maps to
# the enterprise-readiness Reliability dimension — fail closed, not forever.)
MAX_STEPS = 6
MAX_TOKENS = 1024


# --- the domain tool -------------------------------------------------------
# A tiny, public-knowledge X12 segment dictionary — illustrative seed content,
# the same spirit as docs/. Swap in your own segment guide. This is the "look up
# an X12 segment" tool the roadmap calls for, in miniature.
_SEGMENTS = {
    "ISA": "Interchange Control Header — opens the interchange envelope; carries sender/receiver IDs, control number, and version.",
    "IEA": "Interchange Control Trailer — closes the ISA envelope; counts the functional groups inside.",
    "GS":  "Functional Group Header — groups transaction sets of one type; carries the functional identifier code.",
    "GE":  "Functional Group Trailer — closes the GS group; counts the transaction sets inside.",
    "ST":  "Transaction Set Header — starts one transaction set; carries the 3-digit set ID (e.g. 214, 404).",
    "SE":  "Transaction Set Trailer — closes the ST set; counts the segments inside.",
    "B10": "Beginning Segment for Transportation Carrier Shipment Status (214) — reference and shipment identifiers.",
    "N1":  "Party Identification — names a party (shipper, consignee, carrier) by role and ID.",
    "REF": "Reference Information — a qualified reference number (e.g. bill of lading, PO number).",
    "DTM": "Date/Time Reference — a qualified date or time (e.g. estimated arrival, ship date).",
}


def _lookup_segment(segment_id: str) -> str:
    seg = (segment_id or "").strip().upper()
    if seg in _SEGMENTS:
        return f"{seg}: {_SEGMENTS[seg]}"
    known = ", ".join(sorted(_SEGMENTS))
    return f"No definition for segment '{seg}'. Known segments: {known}."


# --- tool schemas (what the model sees) ------------------------------------
TOOLS = [
    {
        "name": "search_docs",
        "description": (
            "Search the indexed EDI/rail knowledge base for passages relevant to a "
            "query. Use this to ground answers in the documents. Returns the top "
            "matching chunks with their source filenames."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_segment",
        "description": (
            "Look up the definition of an X12 EDI segment by its identifier "
            "(e.g. ISA, GS, ST, N1). Use for precise segment questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "segment_id": {"type": "string", "description": "Segment ID, e.g. 'ISA'."}
            },
            "required": ["segment_id"],
        },
    },
]

SYSTEM_PROMPT = (
    "You are Interchange, an assistant for X12/EDI and rail trading-partner "
    "integration. Use the tools to gather information before answering — call "
    "search_docs for document-grounded questions and lookup_segment for segment "
    "definitions. You may call tools multiple times. Answer ONLY from tool "
    "results; cite the source filename in [brackets] for retrieved facts. If the "
    "tools do not contain the answer, say so plainly — do not invent details."
)


def _run_tool(name: str, tool_input: dict, sources: set[str], explain: bool) -> str:
    """Dispatch a single tool call. Records which sources were used so the
    grounding check downstream sees the same [filenames] the model can cite."""
    if name == "search_docs":
        hits = retrieve(tool_input.get("query", ""))
        for _, meta in hits:
            sources.add(meta["source"])
        if explain:
            got = sorted({m["source"] for _, m in hits})
            _explain(f"  tool search_docs('{tool_input.get('query','')}') -> {len(hits)} chunk(s) from {got}")
        # instruction/data separation: tool output is DATA, labeled as such
        return "\n\n".join(f"[{m['source']}]\n{d}" for d, m in hits) or "No matching passages."
    if name == "lookup_segment":
        out = _lookup_segment(tool_input.get("segment_id", ""))
        if explain:
            _explain(f"  tool lookup_segment('{tool_input.get('segment_id','')}') -> {out[:60]}...")
        return out
    return f"Unknown tool: {name}"


def answer_agentic(question: str, explain: bool = False) -> str:
    """Answer via the agentic tool-use loop. Same guardrails + audit as the MVP,
    but the model drives retrieval instead of a fixed one-shot pipeline."""
    import anthropic

    # -- enterprise: input guardrail (unchanged from the MVP) --
    if explain:
        _explain("stage 1 input guardrail — checking for injection / limits (OWASP LLM01)")
    try:
        question = guard_input(question)
    except GuardrailViolation as e:
        if explain:
            _explain(f"  blocked: {e}")
        audit(question=question, model=MODEL, sources=[], in_tokens=0, out_tokens=0,
              latency_ms=0, grounded=False, blocked=str(e), engine="api")
        return f"🛑 Request blocked by input guardrail: {e}"
    if explain:
        _explain("  passed")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("The agentic loop needs the API engine — set ANTHROPIC_API_KEY "
                 "(copy .env.example to .env). Tool use is not available via --engine claude-code.")

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    sources: set[str] = set()
    in_tokens = out_tokens = 0
    t0 = time.monotonic()

    resp = None
    for step in range(MAX_STEPS):
        if explain:
            _explain(f"stage 2 loop step {step + 1}/{MAX_STEPS} — asking the model (tools available)")
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
            tools=TOOLS, messages=messages,
        )
        in_tokens += resp.usage.input_tokens
        out_tokens += resp.usage.output_tokens

        if resp.stop_reason != "tool_use":
            if explain:
                _explain(f"  model answered (stop_reason={resp.stop_reason}) — leaving the loop")
            break

        # The model wants tools. Append its turn verbatim (tool_use blocks and
        # all — the API needs them), run each tool, hand results back together.
        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = _run_tool(block.name, block.input, sources, explain)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        messages.append({"role": "user", "content": tool_results})
    else:
        if explain:
            _explain(f"  hit the {MAX_STEPS}-step cap — stopping (reliability guard)")

    latency_ms = int((time.monotonic() - t0) * 1000)
    text = next((b.text for b in resp.content if b.type == "text"), "") if resp else ""

    # -- enterprise: output grounding + audit (unchanged controls) --
    text, grounded = guard_output(text, sorted(sources))
    if explain:
        verdict = "grounded ✅" if grounded else "⚠️ UNGROUNDED"
        _explain(f"stage 3 output guardrail — {verdict}; sources touched: {sorted(sources)}")
        _explain(f"  audit: {in_tokens} in / {out_tokens} out tok, {latency_ms}ms -> audit.jsonl")
    audit(question=question, model=MODEL, sources=sorted(sources),
          in_tokens=in_tokens, out_tokens=out_tokens,
          latency_ms=latency_ms, grounded=grounded, engine="api")
    return text
