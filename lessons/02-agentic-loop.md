# Lesson 02 — From one-shot RAG to an agentic loop

Lesson 01 built a pipeline that always does the same thing: retrieve once, then
answer. That's fine until the question needs *judgment* — "should I even search?",
"I got nothing useful, let me try a different query", "I need the definition of
that segment before I can answer". A fixed pipeline can't make those calls. An
**agent** can.

This lesson adds `agent.py`: the model drives retrieval and a domain tool,
iterating until it has enough to answer. The decision to build the loop by hand
(rather than adopt a framework yet) is recorded in
[ADR-0002](../docs/adr/0002-orchestration-framework.md) — read it for the *why*.

## The whole idea in five lines

```
messages = [the question]
loop (up to a step cap):
    ask the model, with tools available
    if it answered  -> done
    if it wants tools -> run them, hand results back, ask again
```

That's the entire agent loop. Everything else — the tool schemas, the guardrails,
the audit — is the production scaffolding around it.

## The tool-use protocol (what actually happens on the wire)

1. You send the question **plus a list of tools** (name, description, JSON schema).
2. The model replies with `stop_reason: "tool_use"` and one or more `tool_use`
   blocks: *"call `search_docs` with `{query: ...}`"*.
3. You **append the model's turn verbatim** (the `tool_use` blocks and all — the
   API needs them to stay in the transcript), run each tool, and send the outputs
   back as `tool_result` blocks, matched by `tool_use_id`.
4. The model reads the results and either answers, or asks for more tools. You
   loop until it stops asking.

The two tools here:
- **`search_docs`** — wraps the same retrieval from Lesson 01.
- **`lookup_segment`** — a tiny X12 segment dictionary (the "look up a segment
  definition" tool, in miniature). It's a pure in-process function; no MCP yet
  (that's a later ADR).

## What carries over from Lesson 01 — and why that matters

The agent path reuses the MVP's controls *unchanged*:

- **Input guardrail (OWASP LLM01)** still runs first — injection never reaches the loop.
- **Instruction/data separation** still holds: tool results are labeled DATA
  (`[filename]` blocks), never instructions. This is the defense against
  *indirect* injection — a poisoned document can't hijack the agent just because
  the agent read it.
- **Grounding check** still runs on the final answer, against the sources the
  tools actually touched.
- **Audit log** still records tokens, latency, and grounded/blocked status — now
  summed across every step of the loop.

That reuse is the point: *the controls are a layer, not a feature of one pipeline
shape.* Change the orchestration, keep the governance.

## The new control this lesson introduces: a step cap

An agent with a bad tool result can loop forever — search, get nothing, reason,
search again, never converge. `MAX_STEPS` bounds it. That's not a nicety; it's the
enterprise-readiness **Reliability** dimension applied to the loop: *fail closed,
not forever.* A production agent also wants per-step timeouts and a token budget —
noted as roadmap, not built here.

## Map to the framework

| Dimension | What this lesson adds |
|---|---|
| Context & Memory | agentic retrieval — the model decides when/what to retrieve (dimension 8) |
| Reliability | a step cap so the loop always terminates |
| Security | instruction/data separation now defends the *tool-result* channel too |
| Governance | the audit log spans a multi-step loop, not a single call |

## Try it yourself

```bash
python interchange.py --reindex                     # build the index (no API key needed)
python interchange.py --agent --explain --ask "What is a 214 and which segment starts it?"
```

With `--explain` you'll watch the loop narrate itself: each step, each tool call,
and the final grounding verdict. Generation needs `ANTHROPIC_API_KEY` (tool use is
API-only) — retrieval and the guardrails run without it.

## What's honest about this

This is iteration 1. The loop is real and legible, but it's a *single* agent with
*two* tools and *linear* iteration. No planning, no memory across turns, no
parallel tool calls. Those arrive when they earn their complexity — and each will
get its own ADR and lesson. That progression *is* the curriculum.
