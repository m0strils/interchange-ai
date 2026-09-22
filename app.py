"""
Interchange over HTTP — the same governed pipeline, exposed as a service.

Thin on purpose: the guardrails, grounding check and audit row live in
``enterprise.py`` / ``interchange.answer_detail`` and are reused verbatim, so an
HTTP caller gets exactly the governance the CLI gets (the controls are a layer,
not a feature of one pipeline shape). This module only translates HTTP to that
call and the governance verdict back to a status code:

    GET  /health                      -> liveness + the active corpus/engine
    GET  /ask?q=...&corpus=...        -> the answer_detail dict (+ "corpus")
    POST /ask  {"q": ..., "corpus": ...}

A blocked question is a *successful* guardrail, so it answers 400 with the same
detail dict (blocked reason included) rather than a bare error.

The same app also carries the agent-to-agent surface (ADR-0013), mounted by
``a2a_agent.server.mount_a2a``: a signed Agent Card at
``/.well-known/agent-card.json`` and an API-key-gated JSON-RPC task endpoint at
``/a2a``. One deploy, two integration shapes — REST for a human-built client,
A2A for a peer agent — over one governed core.

No auth and no rate limit on ``/ask`` yet — deliberately scheduled, not
forgotten; that surface is local/demo-only until they land. ``/a2a`` does
require a key.

Run:  uvicorn app:app --reload
"""
from __future__ import annotations

import os

from fastapi import Body, FastAPI, Query
from fastapi.responses import JSONResponse

import interchange
from a2a_agent.server import mount_a2a


def default_engine() -> str:
    """The generation engine unset requests use (same env knob as the CLI)."""
    return os.environ.get("INTERCHANGE_ENGINE", "api")


def _ask(question: str, corpus: str | None) -> JSONResponse:
    """Run the governed pipeline and map the verdict onto a status code."""
    detail = interchange.answer_detail(
        question, engine=default_engine(), collection=corpus
    )
    detail["corpus"] = corpus or interchange.COLLECTION
    return JSONResponse(detail, status_code=400 if detail["blocked"] else 200)


def create_app() -> FastAPI:
    app = FastAPI(title="Interchange")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "collection": interchange.active_collection(),
            "engine": default_engine(),
        }

    @app.get("/ask")
    def ask_get(q: str = Query(...), corpus: str | None = Query(None)) -> JSONResponse:
        return _ask(q, corpus)

    @app.post("/ask")
    def ask_post(q: str = Body(...), corpus: str | None = Body(None)) -> JSONResponse:
        return _ask(q, corpus)

    # Agent-to-agent surface (ADR-0013). The card advertises this base URL, so it
    # has to be the URL peers actually reach us on — Render sets A2A_PUBLIC_URL.
    mount_a2a(app, base_url=os.environ.get("A2A_PUBLIC_URL", "http://localhost:8000"))
    return app


app = create_app()
