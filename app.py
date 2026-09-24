"""Interchange over HTTP — the same governed pipeline, exposed as a service, plus
the browser workbench surface (ADR-0015).

Thin on purpose: the guardrails, grounding check and audit row live in
``enterprise.py`` / ``interchange.answer_detail`` and are reused verbatim, so every
HTTP caller gets exactly the governance the CLI gets. This module translates HTTP
to that call, adds the *policy tier* a shared/public surface needs, and streams the
pipeline stage-by-stage to a browser.

Routes:

    GET  /health                 -> liveness + active corpus/engine/ui/index
    GET  /options                -> the policy document the UI renders straight off
    GET  /ask?q=&mode=&k=&rerank= -> the answer_detail dict (+ corpus/request_id/audit_id)
    POST /ask   {q, corpus?, mode?, k?, rerank?, pin?}
    POST /ask/stream             -> Server-Sent Events: one `stage` frame per pipeline
                                    stage (hits ride the `retrieve` frame only), then
                                    a `done` frame with the answer, or an `error` frame
    /ui                          -> the vendored no-build Preact workbench (static)

Policy (``policy.py``): env is the policy tier and a request the preference tier, so
a query param can never override a locked knob or reach a disallowed corpus — the
answer is a 403 with a reason, never a silent downgrade. A per-host rate limit, a
generation concurrency bound and a daily budget for metered reranking all answer 429
and are audited. **No auth locally; fail-closed on a public deploy**: when
``A2A_PUBLIC_URL`` is not localhost, ``/ask*`` require ``X-API-Key`` (unset keys ⇒
403), matching the signed Agent Card the same host publishes. ``INTERCHANGE_CORS_ORIGINS``
(comma-separated; empty/unset ⇒ no CORS middleware) opts a separate-origin frontend in.

The app also carries the agent-to-agent surface (ADR-0013), mounted by
``a2a_agent.server.mount_a2a``: a signed Agent Card and an API-key-gated ``/a2a``.

Run:  uvicorn app:app --reload
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from enum import Enum
from pathlib import Path

from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import MutableHeaders

import a2a_agent.server as a2a_server
import enterprise
import interchange
import policy
from a2a_agent.profiles import profile_examples, profile_for_collection
from a2a_agent.server import mount_a2a

logger = logging.getLogger("interchange.web")

WEB_DIR = Path(__file__).parent / "web"
DENSE_POOL = interchange.DENSE_POOL

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)


def default_engine() -> str:
    """The generation engine unset requests use (same env knob as the CLI)."""
    return os.environ.get("INTERCHANGE_ENGINE", "api")


def cors_origins_from_env(env=None) -> list[str]:
    """Parse ``INTERCHANGE_CORS_ORIGINS`` into an allow-list of origins.

    Comma-separated, each origin whitespace-trimmed, empties dropped. Unset or
    empty yields ``[]`` — the same-origin default (no CORS middleware added), so a
    separate-origin personal frontend (ADR-0016) is opt-in per process and never on
    by accident. ``env`` defaults to ``os.environ``.
    """
    raw = (os.environ if env is None else env).get("INTERCHANGE_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# --- wire vocabulary (review #7) -------------------------------------------
# `mode` and `rerank` are separate knobs so `hybrid+rerank` never has to survive a
# query string (where `+` decodes to a space). `rerank != none` runs the internal
# `hybrid+rerank` mode and requires `mode == hybrid`.
class Mode(str, Enum):
    hybrid = "hybrid"
    dense = "dense"
    bm25 = "bm25"
    hybrid_links = "hybrid+links"


class Rerank(str, Enum):
    none = "none"
    cross_encoder = "cross-encoder"
    flashrank = "flashrank"
    typesafe = "typesafe"


# --- pydantic models (OpenAPI + a typed contract; handlers return JSONResponse) --
class PinRef(BaseModel):
    id: str
    token: str


class AskRequest(BaseModel):
    q: str = Field(..., max_length=8000, examples=["what is an 824?"])
    corpus: str | None = None
    mode: Mode | None = Field(None, examples=["hybrid"])
    k: int | None = Field(None, ge=1, le=DENSE_POOL, examples=[4])
    rerank: Rerank | None = Field(None, examples=["none"])
    pin: list[PinRef] | None = Field(None, max_length=DENSE_POOL)


class Hit(BaseModel):
    id: str
    pin: str | None = None
    corpus: str | None = None
    source: str | None = None
    chunk: int | None = None
    section: str | None = None
    title: str | None = None
    text: str | None = None
    meta: dict | None = None
    final_rank: int | None = None
    dense_rank: int | None = None
    dense_distance: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    rerank_backend: str | None = None
    pinned: bool = False


class Stage(BaseModel):
    stage: str
    ms: int
    telemetry: str
    detail: str
    data: dict


class LegendEntry(BaseModel):
    """One row of ``interchange.score_legend``: what a score means and how honest it is
    (``backend``/``telemetry`` are present on the rerank row only)."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    note: str
    backend: str | None = None
    telemetry: str | None = None


class Scoring(BaseModel):
    """The scoring legend (``interchange.score_legend``): the three fusion inputs are
    always present; ``rerank_score`` rides along only when a run reranked."""

    model_config = ConfigDict(extra="forbid")

    dense_distance: LegendEntry
    bm25_score: LegendEntry
    rrf_score: LegendEntry
    rerank_score: LegendEntry | None = None


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    answer_text: str
    grounded: bool
    sources: list[str]
    blocked: str | None
    engine: str
    model: str
    cost_usd: float
    telemetry: str
    hits: list[Hit]
    stages: list[Stage]
    scoring: Scoring
    mode: str
    mode_effective: str
    k: int
    pinned: bool
    corpus: str
    request_id: str
    audit_id: str | None


class DoneEvent(BaseModel):
    """The ``event: done`` SSE frame — the ``AskResponse`` shape minus ``hits`` (the
    evidence already rode the ``retrieve`` frame). Same ``extra="forbid"`` contract."""

    model_config = ConfigDict(extra="forbid")

    text: str
    answer_text: str
    grounded: bool
    sources: list[str]
    blocked: str | None
    engine: str
    model: str
    cost_usd: float
    telemetry: str
    stages: list[Stage]
    scoring: Scoring
    mode: str
    mode_effective: str
    k: int
    pinned: bool
    corpus: str
    request_id: str
    audit_id: str | None


class ErrorResponse(BaseModel):
    code: str
    message: str
    correlation_id: str


# --- /options envelope (typed policy document the UI renders straight off) --
class ChoiceKnob(BaseModel):
    """A knob offered as a fixed choice set (``corpora``/``mode``/``rerank``):
    ``reason`` is ``null`` unless ``locked`` is true."""

    model_config = ConfigDict(extra="forbid")

    allowed: list[str]
    default: str
    locked: bool
    reason: str | None = None


class RerankKnob(ChoiceKnob):
    """The rerank knob adds the honest ``unavailable`` map (backend -> why it can't run)."""

    unavailable: dict[str, str]


class RangeKnob(BaseModel):
    """A knob offered as a numeric range (``k``): ``reason`` is ``null`` unless locked."""

    model_config = ConfigDict(extra="forbid")

    min: int
    max: int
    default: int
    locked: bool
    reason: str | None = None


class MeteredInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    budget_usd: float
    spent_today_usd: float
    price_per_judgment_usd: float
    window: int


class IndexInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str | None
    chunks: int | None
    space: str | None


class OptionsResponse(BaseModel):
    """The policy document ``GET /options`` returns: every knob in one envelope so the
    UI renders it uniformly (``{allowed, default, locked, reason}`` for choices,
    ``{min, max, default, locked, reason}`` for ranges)."""

    model_config = ConfigDict(extra="forbid")

    corpora: ChoiceKnob
    mode: ChoiceKnob
    rerank: RerankKnob
    k: RangeKnob
    metered: MeteredInfo
    index: IndexInfo
    engine: str
    auth_required: bool
    ui: bool
    examples: list[str]


# --- policy resolution -----------------------------------------------------
class PolicyReject(Exception):
    """A preference the policy refuses — mapped to an ErrorResponse, never downgraded."""

    def __init__(self, code: str, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.retry_after = retry_after


def _resolve_request(corpus, mode, k, rerank) -> dict:
    """Apply the policy tier to a request's preferences; raise ``PolicyReject`` on any
    override the operator forbids (403), or an illegal combination (422). Returns the
    effective ``{corpus, mode, k, rerank_backend}``."""
    allowed = policy.corpora()
    corpus = corpus or policy.default_corpus()
    if corpus not in allowed:
        raise PolicyReject("corpus_forbidden", 403,
                           f"corpus {corpus!r} is not in the allow-list {allowed}")

    locked = policy.locked_knobs()
    if mode is not None and "mode" in locked:
        raise PolicyReject("knob_locked", 403, "Mode is locked by policy.")
    if rerank is not None and "rerank" in locked:
        raise PolicyReject("knob_locked", 403, "Rerank is locked by policy.")
    if k is not None and "k" in locked:
        raise PolicyReject("knob_locked", 403, "K is locked by policy.")

    mode_v = mode.value if mode else "hybrid"
    rerank_v = rerank.value if rerank else "none"
    k_v = k if k is not None else interchange.TOP_K

    if rerank_v != "none" and mode_v != "hybrid":
        raise PolicyReject("rerank_requires_hybrid", 422,
                           "rerank requires mode=hybrid")
    if rerank_v != "none":
        if rerank_v == "typesafe" and not policy.allow_metered():
            raise PolicyReject("metered_disabled", 403,
                               "Metered reranking is disabled by policy.")
        reason = policy.backend_reason(rerank_v)
        if reason:
            code = "metered_unavailable" if rerank_v == "typesafe" else "rerank_unavailable"
            raise PolicyReject(code, 403, reason)

    return {"corpus": corpus, "mode": mode_v, "k": k_v,
            "rerank_backend": None if rerank_v == "none" else rerank_v}


def _busy(correlation_id: str, caller: str) -> JSONResponse:
    """Audit a ``busy`` refusal (the generation semaphore was full) and return the 429.

    Sets the caller first: ``_preflight`` reset it in its ``finally`` before returning,
    so without this the audit row would name the wrong (or no) caller. The row is the
    same shape as the ``rate_limit`` / ``budget`` rows — no new audit keys (the A2A
    key-parity assertion holds)."""
    enterprise.CALLER.set(caller)
    enterprise.audit(question="", model=interchange.MODEL, sources=[], in_tokens=0,
                     out_tokens=0, latency_ms=0, grounded=False,
                     blocked="busy", engine=default_engine())
    return _error("busy", 429, correlation_id, "the server is busy", retry_after=5)


def _error(code, status, correlation_id, message, retry_after=None) -> JSONResponse:
    headers = {"X-Request-Id": correlation_id}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        {"code": code, "message": message, "correlation_id": correlation_id},
        status_code=status, headers=headers,
    )


def _audit_id(detail: dict) -> str | None:
    """The audit row id this run wrote, read back off the stage timeline."""
    for frame in detail.get("stages", []):
        aid = (frame.get("data") or {}).get("audit_id")
        if aid:
            return aid
    return None


def _response_body(detail: dict, corpus: str, request_id: str) -> dict:
    """The AskResponse dict: the answer_detail superset + corpus/request_id/audit_id."""
    body = dict(detail)
    body["corpus"] = corpus
    body["request_id"] = request_id
    body["audit_id"] = _audit_id(detail)
    for frame in body.get("stages", []):
        if frame.get("stage") == "done":
            frame.setdefault("data", {})["request_id"] = request_id
    return body


def _web_auth(request: Request, correlation_id: str) -> tuple[str, JSONResponse | None]:
    """The audit caller for this web request, or an error response if a public deploy
    refuses it (fail-closed). Local deploys are open; the caller is ``web/<sess8>``."""
    api_key = request.headers.get(a2a_server.api_key_header())
    ok, code = policy.web_key_ok(api_key)
    if not ok:
        msg = ("this host is public but no API keys are configured"
               if code == "web_disabled_public" else "a valid API key is required")
        return "", _error(code, 403, correlation_id, msg)
    session = request.headers.get("x-session")
    return policy.caller_for(session, api_key), None


def _preflight(request: Request, correlation_id: str, corpus, mode, k, rerank,
               cross_site_check: bool) -> tuple[dict | None, str | None, JSONResponse | None]:
    """Everything before the pipeline: cross-site refusal, fail-closed auth, policy
    resolution, rate limit and metered budget. Returns ``(resolved, caller, error)``;
    exactly one of ``resolved``/``error`` is set. Rate-limit and budget refusals are
    audited (they are governance events, not transport errors)."""
    if cross_site_check and request.headers.get("sec-fetch-site") == "cross-site":
        return None, None, _error("cross_site", 403, correlation_id,
                                   "cross-site requests are refused")
    caller, err = _web_auth(request, correlation_id)
    if err is not None:
        return None, None, err
    ctoken = enterprise.CALLER.set(caller)
    try:
        try:
            resolved = _resolve_request(corpus, mode, k, rerank)
        except PolicyReject as pr:
            return None, None, _error(pr.code, pr.status, correlation_id, pr.message,
                                      retry_after=pr.retry_after)

        host = request.client.host if request.client else "unknown"
        retry = policy.rate_check(host)
        if retry is not None:
            enterprise.audit(question="", model=interchange.MODEL, sources=[], in_tokens=0,
                             out_tokens=0, latency_ms=0, grounded=False,
                             blocked="rate_limit", engine=default_engine())
            return None, None, _error("rate_limited", 429, correlation_id,
                                      "rate limit exceeded", retry_after=retry)

        if resolved["rerank_backend"] == "typesafe" and policy.budget_exceeded():
            enterprise.audit(question="", model=interchange.MODEL, sources=[], in_tokens=0,
                             out_tokens=0, latency_ms=0, grounded=False,
                             blocked="budget", engine=default_engine())
            return None, None, _error("budget_exceeded", 429, correlation_id,
                                      "daily metered budget exceeded")
        return resolved, caller, None
    finally:
        enterprise.CALLER.reset(ctoken)


def _run_ask(request: Request, q, corpus, mode, k, rerank, pin, cross_site_check) -> JSONResponse:
    """The synchronous /ask path: policy pre-flight, semaphore, the governed pipeline,
    and the error catalogue on any failure (never the raw exception on the wire)."""
    correlation_id = uuid.uuid4().hex[:12]
    resolved, caller, err = _preflight(request, correlation_id, corpus, mode, k, rerank,
                                       cross_site_check)
    if err is not None:
        return err

    sema = policy.gen_semaphore()
    if not sema.acquire(blocking=False):
        return _busy(correlation_id, caller)
    ctoken = enterprise.CALLER.set(caller)
    try:
        detail = interchange.answer_detail(
            q, engine=default_engine(), collection=resolved["corpus"],
            mode=resolved["mode"], top_k=resolved["k"],
            rerank_backend=resolved["rerank_backend"], pin=pin,
        )
    except PermissionError:
        return _error("pin_invalid", 403, correlation_id, "one or more pins are invalid")
    except BaseException as e:  # SystemExit from a missing index, engine failures, …
        code = policy.classify_error(e)
        status, message = policy.ERROR_CATALOGUE[code]
        logger.error("ask failed [%s] %s: %r", correlation_id, code, e)
        return _error(code, status, correlation_id, message)
    finally:
        sema.release()
        enterprise.CALLER.reset(ctoken)

    body = _response_body(detail, resolved["corpus"], correlation_id)
    status = 400 if detail["blocked"] else 200
    return JSONResponse(body, status_code=status, headers={"X-Request-Id": correlation_id})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# --- security headers (raw ASGI: never buffers the SSE stream) -------------
class SecurityHeadersMiddleware:
    """Add CSP / nosniff / referrer-policy (and an X-Request-Id) to ``/ui`` and
    ``/ask*`` responses. Written as raw ASGI so the streaming response body is not
    buffered the way ``BaseHTTPMiddleware`` would buffer it (same reason A2A's key
    gate is raw ASGI)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not (path.startswith("/ui") or path.startswith("/ask")):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = CSP
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                if "x-request-id" not in headers:
                    headers["X-Request-Id"] = uuid.uuid4().hex[:12]
            await send(message)

        await self.app(scope, receive, send_wrapper)


# --- request body cap (raw ASGI: reject an oversized /ask* POST before routing) --
MAX_BODY_BYTES = 64 * 1024  # 64 KiB — an /ask body is a short question, never this big


class BodySizeLimitMiddleware:
    """Cap the request body on ``/ask*`` POSTs at ``MAX_BODY_BYTES`` and answer 413
    ``payload_too_large`` (an ``ErrorResponse``) before the handler runs. Raw ASGI so it
    sees the body as it arrives and never lets a giant upload reach pydantic; the small
    ``/ask`` body is buffered here and replayed to the app unchanged."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not (scope.get("type") == "http" and scope.get("method") == "POST"
                and scope.get("path", "").startswith("/ask")):
            await self.app(scope, receive, send)
            return

        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY_BYTES:
                await self._reject(send)
                return

        replayed = False

        async def replay():
            # Hand the app the buffered body once, then delegate to the real receive so
            # a genuine ``http.disconnect`` still reaches the streaming response's
            # disconnect watcher (never fabricate one, or SSE stops immediately).
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send) -> None:
        cid = uuid.uuid4().hex[:12]
        payload = json.dumps({
            "code": "payload_too_large",
            "message": f"request body exceeds the {MAX_BODY_BYTES}-byte limit",
            "correlation_id": cid,
        }).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            (b"x-request-id", cid.encode()),
        ]})
        await send({"type": "http.response.body", "body": payload})


def create_app() -> FastAPI:
    # Fail-fast on a mistyped engine: a typo in INTERCHANGE_ENGINE is a startup error
    # (SystemExit), not a 500 on the first request. /health and /options.engine still
    # echo the configured value verbatim.
    engine = default_engine()
    if engine not in interchange.ENGINES:
        raise SystemExit(
            f"INTERCHANGE_ENGINE={engine!r} is not one of {sorted(interchange.ENGINES)}")

    app = FastAPI(title="Interchange")

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError):
        """One 422 shape everywhere: pydantic/FastAPI validation failures become an
        ``ErrorResponse{code:"invalid_request", …}`` with a short human summary of the
        first error, instead of FastAPI's default ``{"detail": [...]}`` body (A1)."""
        cid = uuid.uuid4().hex[:12]
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
            msg = first.get("msg", "invalid request")
            message = f"{loc}: {msg}" if loc else msg
        else:
            message = "invalid request"
        return _error("invalid_request", 422, cid, message)

    @app.get("/health")
    def health() -> dict:
        corpus = interchange.active_collection()
        return {
            "status": "ok",
            "collection": corpus,
            "engine": default_engine(),
            "ui": policy.ui_enabled(),
            "index": interchange.index_meta(corpus)["chunks"] is not None,
        }

    @app.get("/options", response_model=OptionsResponse)
    def options() -> JSONResponse:
        """The policy document the workbench renders straight off: every knob in one
        envelope (choice knobs carry ``{allowed, default, locked, reason}``; the ``k``
        range carries ``{min, max, default, locked, reason}``; ``rerank`` adds an
        ``unavailable`` backend->reason map). ``reason`` is ``null`` unless the knob is
        locked. Env is read live, so a policy change shows up on the next request."""
        locked = policy.locked_knobs()
        rerank_allowed, rerank_unavailable = policy.rerank_availability()
        corpus = policy.default_corpus()
        idx = interchange.index_meta(corpus)
        # Examples follow the default corpus, not $DEMO_PROFILE (ADR-0016): one server
        # mounting several corpora must show the default corpus's cold-start prompts.
        _corpus_profile = profile_for_collection(corpus)
        examples = (profile_examples(_corpus_profile) if _corpus_profile is not None
                    else profile_examples())

        def _reason(knob: str) -> str | None:
            return f"{knob.capitalize()} is locked by policy." if knob in locked else None

        doc = {
            "corpora": {"allowed": policy.corpora(), "default": corpus,
                        "locked": False, "reason": None},
            "mode": {"allowed": [m.value for m in Mode], "default": "hybrid",
                     "locked": "mode" in locked, "reason": _reason("mode")},
            "rerank": {"allowed": rerank_allowed, "default": "none",
                       "locked": "rerank" in locked, "reason": _reason("rerank"),
                       "unavailable": rerank_unavailable},
            "k": {"min": 1, "max": DENSE_POOL, "default": interchange.TOP_K,
                  "locked": "k" in locked, "reason": _reason("k")},
            "metered": {"allowed": policy.allow_metered(),
                        "budget_usd": policy.metered_budget_usd(),
                        "spent_today_usd": round(policy.estimated_spend_today(), 6),
                        "price_per_judgment_usd": interchange.PRICE_TYPESAFE_JUDGMENT_USD,
                        "window": interchange.RERANK_N},
            "index": {"collection": idx["collection"], "chunks": idx["chunks"],
                      "space": idx["space"]},
            "engine": default_engine(),
            "auth_required": policy.auth_required(),
            "ui": policy.ui_enabled(),
            "examples": examples,
        }
        return JSONResponse(doc, headers={"X-Request-Id": uuid.uuid4().hex[:12]})

    @app.get("/ask", response_model=AskResponse,
             responses={400: {"model": AskResponse}, 403: {"model": ErrorResponse},
                        422: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
                        500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def ask_get(request: Request, q: str = Query(..., max_length=8000,
                                                 examples=["what is an 824?"]),
                corpus: str | None = Query(None),
                mode: Mode | None = Query(
                    None,
                    description="Retrieval mode. A `+` in a value (e.g. `hybrid+links`) "
                                "must be percent-encoded as `hybrid%2Blinks`, since a raw "
                                "`+` in a query string decodes to a space."),
                k: int | None = Query(None, ge=1, le=DENSE_POOL),
                rerank: Rerank | None = Query(None)) -> JSONResponse:
        return _run_ask(request, q, corpus, mode, k, rerank, None, cross_site_check=True)

    @app.post("/ask", response_model=AskResponse,
              responses={400: {"model": AskResponse}, 403: {"model": ErrorResponse},
                         422: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
                         500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def ask_post(request: Request, body: AskRequest = Body(...)) -> JSONResponse:
        pin = [p.model_dump() for p in body.pin] if body.pin else None
        return _run_ask(request, body.q, body.corpus, body.mode, body.k, body.rerank,
                        pin, cross_site_check=True)

    @app.post("/ask/stream", response_class=StreamingResponse, responses={
        200: {"content": {"text/event-stream": {}},
              "description": "Server-Sent Events: the governed pipeline streamed frame by "
                             "frame (see the endpoint description)."},
        403: {"model": ErrorResponse}, 413: {"model": ErrorResponse},
        422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
    async def ask_stream(request: Request, body: AskRequest = Body(...)):
        r"""Stream the governed pipeline as Server-Sent Events (`text/event-stream`).

        Five frame kinds ride one connection; the `event:` field disambiguates them:

        * **`event: stage`** (one per pipeline stage — `guard`, `retrieve`, `generate`,
          `ground`, `done`, plus `rerank` when a run reranked). `hits` and `scoring` are
          attached to the **`retrieve`** frame only; every other stage frame omits them.
          The `stage: done` frame's `data.request_id` is the correlation id (injected here
          so it agrees with the final `done` frame below).

              event: stage
              data: {"stage": "retrieve", "ms": 3, "telemetry": "measured",
                     "detail": "2 chunk(s)", "data": {"mode": "hybrid", "k": 4, ...},
                     "hits": [{"id": "x12-overview.md:0", "final_rank": 1, ...}],
                     "scoring": {"dense_distance": {"kind": "l2", "note": "..."}, ...}}

        * **`event: done`** — the answer once, as the `AskResponse` shape **minus `hits`**
          (see `DoneEvent`; the evidence already rode the `retrieve` frame). Both this and
          the `stage: done` frame are sent, on purpose, and carry the same `request_id`.

              event: done
              data: {"answer_text": "An 824 reports ...", "grounded": true,
                     "sources": ["x12-overview.md"], "blocked": null, "request_id": "ab12cd34ef56",
                     "audit_id": "…", "scoring": {...}, "stages": [...]}

        * **`event: error`** — a catalogue code and safe message; the raw exception never
          reaches the wire.

              event: error
              data: {"code": "index_missing", "message": "The index is empty. Run --reindex.",
                     "correlation_id": "ab12cd34ef56"}

        * **`: keepalive`** — an SSE comment sent every ~15 s of silence to hold the
          connection open (and to poll for client disconnect).

              : keepalive
        """
        correlation_id = uuid.uuid4().hex[:12]
        pin = [p.model_dump() for p in body.pin] if body.pin else None
        resolved, caller, err = _preflight(request, correlation_id, body.corpus, body.mode,
                                           body.k, body.rerank, cross_site_check=True)
        if err is not None:
            return err

        sema = policy.gen_semaphore()
        if not sema.acquire(blocking=False):
            return _busy(correlation_id, caller)

        loop = asyncio.get_running_loop()
        aq: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()
        engine = default_engine()

        def _put(item) -> None:
            # The event loop may already be gone (client disconnected while the worker
            # was still running); dropping the frame is fine — the generator is done.
            try:
                loop.call_soon_threadsafe(aq.put_nowait, item)
            except RuntimeError:
                pass

        def on_event(frame: dict) -> None:
            # A5: the `stage: done` frame carries `request_id: null` from answer_detail;
            # stamp it with the correlation id so it agrees with the final `done` frame.
            if frame.get("stage") == "done":
                frame.setdefault("data", {})["request_id"] = correlation_id
            _put(("stage", frame))

        def worker() -> None:
            # contextvars do NOT cross into a new thread — set the caller HERE so the
            # audit row names it (the "contextvars across threads" bug this teaches).
            enterprise.CALLER.set(caller)
            try:
                detail = interchange.answer_detail(
                    body.q, engine=engine, collection=resolved["corpus"],
                    mode=resolved["mode"], top_k=resolved["k"],
                    rerank_backend=resolved["rerank_backend"], pin=pin,
                    on_event=on_event, cancel=cancel,
                )
                _put(("result", detail))
            except PermissionError:
                _put(("error", "pin_invalid"))
            except BaseException as e:  # SystemExit in a worker thread is swallowed silently
                code = policy.classify_error(e)
                logger.error("stream failed [%s] %s: %r", correlation_id, code, e)
                _put(("error", code))
            finally:
                # S1: release the generation slot ONLY when the worker (and its
                # `claude -p` subprocess) has actually finished — never in the response
                # generator, which fires on client disconnect while this thread runs on.
                _put(("sentinel", None))
                sema.release()

        # Pair acquire ⇄ worker: once the slot is taken a worker is guaranteed to run and
        # release it, so a disconnect can never leak the semaphore (S1).
        threading.Thread(target=worker, daemon=True).start()

        async def frames():
            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(aq.get(), 15)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            cancel.set()
                        yield ": keepalive\n\n"
                        continue
                    if kind == "stage":
                        yield _sse("stage", payload)
                    elif kind == "result":
                        body_out = _response_body(payload, resolved["corpus"], correlation_id)
                        body_out.pop("hits", None)
                        yield _sse("done", body_out)
                    elif kind == "error":
                        status, message = policy.ERROR_CATALOGUE.get(
                            payload, (503, "error"))
                        yield _sse("error", {"code": payload, "message": message,
                                             "correlation_id": correlation_id})
                    elif kind == "sentinel":
                        break
            finally:
                # Signal the worker to stop at the next stage boundary; the worker owns
                # the semaphore release (S1), so we do NOT release it here.
                cancel.set()

        return StreamingResponse(
            frames(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                     "X-Request-Id": correlation_id},
        )

    # Order: SecurityHeaders is added last so it is outermost and stamps CSP /
    # X-Request-Id onto the body-cap 413 too. BodySizeLimit runs closer to the app,
    # reading and replaying the request body before routing.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS for a separate-origin personal frontend (ADR-0016). Empty/unset =>
    # add nothing (same-origin only, today's behaviour). Credentials are off: this
    # is an origin allow-list for a read/ask surface, not a cookie-authenticated one.
    cors_origins = cors_origins_from_env()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    # Agent-to-agent surface (ADR-0013). The card advertises this base URL, so it
    # has to be the URL peers actually reach us on — Render sets A2A_PUBLIC_URL.
    mount_a2a(app, base_url=os.environ.get("A2A_PUBLIC_URL", "http://localhost:8000"))

    # The workbench is served same-origin from vendored static files. Guarded: a
    # fresh clone (or INTERCHANGE_UI=0) has no `web/`, and StaticFiles raises at
    # import when the directory is absent (review #22).
    if WEB_DIR.is_dir() and os.environ.get("INTERCHANGE_UI", "1") != "0":
        app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    return app


app = create_app()
